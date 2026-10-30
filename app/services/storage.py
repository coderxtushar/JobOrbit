"""Private file storage for uploads and generated artifacts.

Three properties are enforced here:

* Filenames are rebuilt from scratch, never taken from the client, so a name like
  ``../../.ssh/authorized_keys`` cannot escape the data directory.
* The declared extension must agree with the file's magic bytes, so a renamed executable
  is rejected before any parser touches it.
* Nothing is written outside ``settings.data_dir``, which is created with mode 700 and is
  never mounted as a static route.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings

ALLOWED_RESUME_EXTENSIONS = frozenset({".pdf", ".docx"})
_SAFE_STEM = re.compile(r"[^A-Za-z0-9._-]+")

_MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    # DOCX is a ZIP container; both the plain and empty-archive signatures appear in practice.
    ".docx": (b"PK\x03\x04", b"PK\x05\x06"),
}


class UnsupportedFileType(ValueError):
    pass


class FileTooLarge(ValueError):
    pass


class CorruptUpload(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredFile:
    path: Path
    original_filename: str
    extension: str
    size_bytes: int
    sha256: str
    content_type: str


def safe_stem(filename: str) -> str:
    """Reduce a client-supplied filename to a harmless stem."""
    stem = Path(filename or "").name
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    cleaned = _SAFE_STEM.sub("_", stem).strip("._-")
    return (cleaned or "upload")[:80]


def _validate(filename: str, payload: bytes, settings: Settings) -> str:
    extension = Path(filename or "").suffix.lower()
    if extension not in ALLOWED_RESUME_EXTENSIONS:
        raise UnsupportedFileType(
            f"'{extension or 'no extension'}' is not supported; upload a .pdf or .docx file"
        )
    if not payload:
        raise CorruptUpload("the uploaded file is empty")
    if len(payload) > settings.max_upload_bytes:
        raise FileTooLarge(
            f"file is {len(payload) // 1024} KB; the limit is {settings.max_upload_mb} MB"
        )
    expected = _MAGIC_PREFIXES[extension]
    if not payload.startswith(expected):
        raise CorruptUpload(
            f"file content does not look like a {extension} file; it may be renamed or corrupt"
        )
    return extension


def store_resume(filename: str, payload: bytes, settings: Settings | None = None) -> StoredFile:
    """Validate and write an uploaded resume into the private resume directory."""
    settings = settings or get_settings()
    settings.ensure_directories()
    extension = _validate(filename, payload, settings)

    digest = hashlib.sha256(payload).hexdigest()
    target = settings.resume_dir / f"{safe_stem(filename)}-{digest[:12]}{extension}"
    target.write_bytes(payload)
    try:
        target.chmod(0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass

    content_type = (
        "application/pdf"
        if extension == ".pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return StoredFile(
        path=target,
        original_filename=Path(filename).name,
        extension=extension,
        size_bytes=len(payload),
        sha256=digest,
        content_type=content_type,
    )


def store_artifact(
    name: str, content: str, settings: Settings | None = None, subdir: str = ""
) -> Path:
    """Write a generated artifact (cover letter, resume variant) to private storage."""
    settings = settings or get_settings()
    settings.ensure_directories()
    directory = settings.artifact_dir / subdir if subdir else settings.artifact_dir
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{safe_stem(name)}-{secrets.token_hex(4)}.md"
    target.write_text(content, encoding="utf-8")
    return target


def store_import_payload(name: str, payload: bytes, settings: Settings | None = None) -> Path:
    """Keep a copy of an imported file so an import run can be audited later."""
    settings = settings or get_settings()
    settings.ensure_directories()
    target = settings.import_dir / f"{safe_stem(name)}-{secrets.token_hex(4)}.bin"
    target.write_bytes(payload)
    return target


def delete_quietly(path: str | Path | None) -> bool:
    """Remove a stored file, reporting whether it existed. Never raises."""
    if not path:
        return False
    candidate = Path(path)
    try:
        candidate.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
