"""The secret store: owner-only files, and a keychain backend that keeps values out of argv.

The real macOS keychain is never touched here: the keychain backend is exercised against a
mocked ``subprocess.run``.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from app.config import get_settings
from app.services import secrets as secrets_module
from app.services.secrets import SecretStore, SecretStoreError


def test_file_backend_writes_owner_only_files() -> None:
    settings = get_settings()
    store = SecretStore(settings, backend="file")
    store.set("gmail-refresh-token-1", "1//secret-value")

    path = settings.secrets_dir / "gmail-refresh-token-1.secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(settings.secrets_dir.stat().st_mode) == 0o700
    assert store.get("gmail-refresh-token-1") == "1//secret-value"
    assert not [p for p in settings.secrets_dir.iterdir() if p.name.startswith(".tmp-")]

    store.set("gmail-refresh-token-1", "1//rotated")
    assert store.get("gmail-refresh-token-1") == "1//rotated"
    assert store.delete("gmail-refresh-token-1") is True
    assert store.get("gmail-refresh-token-1") is None
    assert store.delete("gmail-refresh-token-1") is False


def test_conftest_forces_the_file_backend() -> None:
    assert SecretStore(get_settings()).backend == "file"


@pytest.mark.parametrize("name", ["../escape", "a/b", "", "x" * 200, "white space"])
def test_unsafe_names_are_refused(name: str) -> None:
    with pytest.raises(SecretStoreError):
        SecretStore(get_settings(), backend="file").set(name, "value")


def test_empty_values_are_refused() -> None:
    with pytest.raises(SecretStoreError):
        SecretStore(get_settings(), backend="file").set("token", "")


class FakeSecurity:
    """Records ``security`` invocations and emulates a one-item keychain."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.items: dict[str, str] = {}

    def run(self, args: list[str], input: str | None = None, **_: object):  # noqa: A002
        self.calls.append((list(args), input))
        verb = args[1]
        if verb == "-i":
            parts = (input or "").split()
            account = parts[parts.index("-a") + 1]
            self.items[account] = bytes.fromhex(parts[parts.index("-X") + 1]).decode()
            return subprocess.CompletedProcess(args, 0, "", "")
        account = args[args.index("-a") + 1]
        if verb == "find-generic-password":
            if account not in self.items:
                return subprocess.CompletedProcess(args, 44, "", "not found")
            return subprocess.CompletedProcess(args, 0, self.items[account] + "\n", "")
        if verb == "delete-generic-password":
            if self.items.pop(account, None) is None:
                return subprocess.CompletedProcess(args, 44, "", "not found")
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"unexpected security verb {verb}")


def test_keychain_backend_never_puts_the_value_in_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSecurity()
    monkeypatch.setattr(secrets_module.subprocess, "run", fake.run)
    store = SecretStore(get_settings(), backend="keychain")

    store.set("gmail-refresh-token-7", "1//top secret value")
    assert store.get("gmail-refresh-token-7") == "1//top secret value"
    assert store.delete("gmail-refresh-token-7") is True
    assert store.get("gmail-refresh-token-7") is None
    assert store.delete("gmail-refresh-token-7") is False

    for args, _stdin in fake.calls:
        assert args[0] == str(secrets_module.SECURITY_CLI)
        assert not any("top secret" in arg for arg in args)
    assert all(
        "JobOrbit" in " ".join(args) or "JobOrbit" in (stdin or "") for args, stdin in fake.calls
    )


def test_forced_keychain_without_a_keychain_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_SECRET_BACKEND", "keychain")
    from app.config import reset_settings_cache

    reset_settings_cache()
    monkeypatch.setattr(secrets_module, "_load_keyring", lambda: None)
    monkeypatch.setattr(secrets_module, "_keychain_cli_available", lambda: False)
    with pytest.raises(SecretStoreError, match="keychain"):
        SecretStore(get_settings())


def test_auto_prefers_keyring_when_importable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("JA_SECRET_BACKEND", "auto")
    from app.config import reset_settings_cache

    reset_settings_cache()

    class FakeKeyring:
        store: dict[tuple[str, str], str] = {}

        @classmethod
        def get_password(cls, service: str, name: str) -> str | None:
            return cls.store.get((service, name))

        @classmethod
        def set_password(cls, service: str, name: str, value: str) -> None:
            cls.store[(service, name)] = value

        @classmethod
        def delete_password(cls, service: str, name: str) -> None:
            del cls.store[(service, name)]

    monkeypatch.setattr(secrets_module, "_load_keyring", lambda: FakeKeyring)  # type: ignore[arg-type,return-value]
    store = SecretStore(get_settings())
    assert store.backend == "keyring"
    store.set("t", "v")
    assert FakeKeyring.store == {("JobOrbit", "t"): "v"}
    assert store.get("t") == "v"
    assert store.delete("t") is True
