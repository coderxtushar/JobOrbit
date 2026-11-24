"""A small secret store for OAuth refresh tokens.

Tokens are deliberately kept out of the database: a database file is copied into backups,
attached to bug reports and opened in viewers, and a refresh token in it would grant
mailbox access to whoever ends up holding the copy. Three backends, chosen in order:

1. The ``keyring`` package, when it happens to be installed. It is optional and not a
   dependency of this project, so it is imported lazily.
2. On macOS, the login keychain through ``/usr/bin/security``. The value is passed on
   stdin as hex (``security -i`` with ``-X``), never as a command-line argument, because
   argv is visible to every local process through ``ps``.
3. A file per secret under ``settings.secrets_dir``: directory mode 0700, file mode 0600.

``JA_SECRET_BACKEND`` forces one: ``keychain`` (keyring or the macOS keychain, failing
rather than silently falling back to a file) or ``file``. Values are never logged.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Literal

from app.config import Settings, get_settings
from app.logging_conf import get_logger

logger = get_logger(__name__)

SERVICE_NAME = "JobOrbit"
SECURITY_CLI = Path("/usr/bin/security")
#: ``security`` exits with this code when the item does not exist.
_SECURITY_NOT_FOUND = 44
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")

BackendName = Literal["keyring", "keychain", "file"]


class SecretStoreError(RuntimeError):
    """The secret backend failed. The message never contains the secret value."""


def _load_keyring() -> ModuleType | None:
    try:
        return importlib.import_module("keyring")
    except Exception:  # noqa: BLE001 - any import failure means "not available"
        return None


def _keychain_cli_available() -> bool:
    return sys.platform == "darwin" and SECURITY_CLI.exists()


class SecretStore:
    """Get, set and delete named secrets in the best available backend."""

    def __init__(self, settings: Settings | None = None, backend: BackendName | None = None):
        self._settings = settings or get_settings()
        self._keyring: ModuleType | None = None
        self.backend: BackendName = backend or self._choose_backend()

    def _choose_backend(self) -> BackendName:
        preference = self._settings.secret_backend
        if preference == "file":
            return "file"
        self._keyring = _load_keyring()
        if self._keyring is not None:
            return "keyring"
        if _keychain_cli_available():
            return "keychain"
        if preference == "keychain":
            raise SecretStoreError(
                "JA_SECRET_BACKEND=keychain, but neither the keyring package nor the macOS "
                "keychain is available. Use JA_SECRET_BACKEND=file or auto."
            )
        return "file"

    # ------------------------------------------------------------------ public API

    def get(self, name: str) -> str | None:
        name = self._check_name(name)
        if self.backend == "keyring":
            value = self._keyring_module().get_password(SERVICE_NAME, name)
            return value if isinstance(value, str) else None
        if self.backend == "keychain":
            return self._keychain_get(name)
        return self._file_get(name)

    def set(self, name: str, value: str) -> None:
        name = self._check_name(name)
        if not value:
            raise SecretStoreError("refusing to store an empty secret")
        if self.backend == "keyring":
            self._keyring_module().set_password(SERVICE_NAME, name, value)
        elif self.backend == "keychain":
            self._keychain_set(name, value)
        else:
            self._file_set(name, value)
        logger.info("secret stored", extra={"detail": f"{name} in {self.backend}"})

    def delete(self, name: str) -> bool:
        """Remove a secret. Returns whether one existed; a missing secret is not an error."""
        name = self._check_name(name)
        if self.backend == "keyring":
            module = self._keyring_module()
            try:
                module.delete_password(SERVICE_NAME, name)
            except Exception:  # noqa: BLE001 - keyring raises PasswordDeleteError if absent
                return False
            return True
        if self.backend == "keychain":
            return self._keychain_delete(name)
        return self._file_delete(name)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _check_name(name: str) -> str:
        # Names become file names and CLI arguments, so only a conservative alphabet.
        if not _SAFE_NAME.match(name or ""):
            raise SecretStoreError("secret names may contain only letters, digits, '.', '_', '-'")
        return name

    def _keyring_module(self) -> ModuleType:
        if self._keyring is None:
            self._keyring = _load_keyring()
        if self._keyring is None:
            raise SecretStoreError("the keyring package is not installed")
        return self._keyring

    # --- macOS keychain via /usr/bin/security

    def _security(self, args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(  # noqa: S603 - fixed binary, no shell
                [str(SECURITY_CLI), *args],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SecretStoreError(f"the macOS keychain could not be used: {error}") from error

    def _keychain_get(self, name: str) -> str | None:
        result = self._security(["find-generic-password", "-s", SERVICE_NAME, "-a", name, "-w"])
        if result.returncode == _SECURITY_NOT_FOUND:
            return None
        if result.returncode != 0:
            raise SecretStoreError(f"keychain read failed (exit {result.returncode})")
        value = result.stdout.rstrip("\n")
        return value or None

    def _keychain_set(self, name: str, value: str) -> None:
        command = (
            f"add-generic-password -U -s {SERVICE_NAME} -a {name} "
            f"-X {value.encode('utf-8').hex()}\n"
        )
        result = self._security(["-i"], stdin=command)
        if result.returncode != 0 or "error" in (result.stderr or "").lower():
            raise SecretStoreError(f"keychain write failed (exit {result.returncode})")

    def _keychain_delete(self, name: str) -> bool:
        result = self._security(["delete-generic-password", "-s", SERVICE_NAME, "-a", name])
        if result.returncode == _SECURITY_NOT_FOUND:
            return False
        if result.returncode != 0:
            raise SecretStoreError(f"keychain delete failed (exit {result.returncode})")
        return True

    # --- owner-only files

    @property
    def _directory(self) -> Path:
        return self._settings.secrets_dir

    def _path(self, name: str) -> Path:
        return self._directory / f"{name}.secret"

    def _ensure_directory(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self._directory.chmod(0o700)
        except OSError:  # pragma: no cover - platform dependent (e.g. Windows)
            pass

    def _file_get(self, name: str) -> str | None:
        path = self._path(name)
        if not path.is_file():
            return None
        value = path.read_text(encoding="utf-8").strip()
        return value or None

    def _file_set(self, name: str, value: str) -> None:
        self._ensure_directory()
        # Written to a 0600 temporary file and renamed over the target, so the secret is
        # never readable by others even for an instant and a crash leaves no half-file.
        descriptor, temporary = tempfile.mkstemp(dir=self._directory, prefix=".tmp-")
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(value)
            os.replace(temporary, self._path(name))
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        self._path(name).chmod(0o600)

    def _file_delete(self, name: str) -> bool:
        path = self._path(name)
        if not path.exists():
            return False
        path.unlink()
        return True


__all__ = ["SERVICE_NAME", "SecretStore", "SecretStoreError"]
