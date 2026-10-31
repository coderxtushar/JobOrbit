"""Per-visitor database isolation for the public demo.

A shared deployment has one database and no login, so every write a visitor makes is
visible to the next one. Shortlisting a job, answering an inbox question or preparing an
application are the whole point of the demo, but with one shared database the second
visitor inherits the first visitor's half-finished state.

This module gives each browser session its own SQLite file, copied from a template that
was seeded and scored once. Reads and writes for that session go to that copy, so the
repository layer, the services and the routes are untouched — the isolation is entirely in
which engine :func:`app.api.deps.get_db` binds to.

**This is isolation, not authorization.** The session key is an unguessable capability
token carried in a request header; it keeps two honest visitors apart. It does not
authenticate anybody, and a visitor who obtains another visitor's key would see that
session's data. That is acceptable only because every row in it is fictional, which is why
resume upload and real job import stay refused outright. Real per-user data needs the four
prerequisites documented in :mod:`app.auth`.
"""

from __future__ import annotations

import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.base import build_engine
from app.logging_conf import get_logger

logger = get_logger(__name__)

#: Length of the generated session key. 32 bytes of ``token_urlsafe`` entropy makes the
#: key unguessable, which is what keeps one visitor out of another's copy.
_KEY_BYTES = 32

#: Bounds on the per-session store. Streamlit Community Cloud gives an ephemeral container
#: with limited disk, so the number of live copies is capped and the oldest is evicted
#: rather than letting a popular demo fill the filesystem. A copy of the seeded template is
#: roughly 400 KB, so the cap is a few megabytes in total.
MAX_SESSIONS = 24
SESSION_TTL_SECONDS = 2 * 60 * 60


def new_session_key() -> str:
    """Mint an unguessable key for a new demo visitor."""
    return secrets.token_urlsafe(_KEY_BYTES)


@dataclass
class _DemoSession:
    key: str
    path: Path
    engine: Engine
    factory: sessionmaker[Session]
    last_used: float = field(default_factory=time.monotonic)


class DemoSessionStore:
    """Hands out one isolated database per demo session key.

    The template is built once: migrations plus the demo seed run against it, and every
    session is a file copy. Copying is far cheaper than re-running the seed (which scores
    the whole feed), and it guarantees every visitor starts from byte-identical state.
    """

    def __init__(self, settings: Settings, template_path: Path) -> None:
        self._settings = settings
        self._template_path = template_path
        self._directory = template_path.parent / "demo-sessions"
        self._sessions: dict[str, _DemoSession] = {}
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------------------

    def factory_for(self, key: str) -> sessionmaker[Session]:
        """Return the session factory for ``key``, creating its database on first use."""
        with self._lock:
            self._evict_expired_locked()
            existing = self._sessions.get(key)
            if existing is not None:
                existing.last_used = time.monotonic()
                return existing.factory
            self._evict_to_capacity_locked()
            created = self._create_locked(key)
            return created.factory

    def _create_locked(self, key: str) -> _DemoSession:
        self._directory.mkdir(parents=True, exist_ok=True)
        try:
            self._directory.chmod(0o700)
        except OSError:  # pragma: no cover - platform dependent
            pass
        path = self._directory / f"{_safe_filename(key)}.db"
        shutil.copyfile(self._template_path, path)
        try:
            path.chmod(0o600)
        except OSError:  # pragma: no cover - platform dependent
            pass

        engine = build_engine(self._settings.model_copy(update={"database_url": _url_for(path)}))
        factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
        record = _DemoSession(key=key, path=path, engine=engine, factory=factory)
        self._sessions[key] = record
        logger.info("demo session created", extra={"demo_sessions_live": len(self._sessions)})
        return record

    # -- eviction ----------------------------------------------------------------------

    def _evict_expired_locked(self) -> None:
        cutoff = time.monotonic() - SESSION_TTL_SECONDS
        for key in [k for k, s in self._sessions.items() if s.last_used < cutoff]:
            self._drop_locked(key)

    def _evict_to_capacity_locked(self) -> None:
        while len(self._sessions) >= MAX_SESSIONS:
            oldest = min(self._sessions.values(), key=lambda s: s.last_used)
            self._drop_locked(oldest.key)

    def _drop_locked(self, key: str) -> None:
        record = self._sessions.pop(key, None)
        if record is None:  # pragma: no cover - defensive
            return
        record.engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(record.path) + suffix)
            try:
                candidate.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - platform dependent
                pass
        logger.info("demo session evicted", extra={"demo_sessions_live": len(self._sessions)})

    # -- introspection, for the diagnostics page ---------------------------------------

    @property
    def live_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def reset(self) -> None:
        """Drop every session. Used by tests and on process shutdown."""
        with self._lock:
            for key in list(self._sessions):
                self._drop_locked(key)


def _safe_filename(key: str) -> str:
    """Keep only characters that cannot escape the sessions directory.

    ``token_urlsafe`` emits ``-`` and ``_``, which are safe, but the key arrives in a
    client-controlled header so it is filtered rather than trusted: a key containing
    ``../`` must not be able to name a file outside the directory.
    """
    return "".join(character for character in key if character.isalnum() or character in "-_")[:96]


def _url_for(path: Path) -> str:
    return f"sqlite+pysqlite:///{path}"


_store: DemoSessionStore | None = None
_store_lock = threading.Lock()


def configure_store(settings: Settings, template_path: Path) -> DemoSessionStore:
    """Install the process-wide store. Called once, when the demo API boots."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.reset()
        _store = DemoSessionStore(settings, template_path)
        return _store


def get_store() -> DemoSessionStore | None:
    return _store


def reset_store() -> None:
    """Tear the store down. Used by tests so one test's sessions cannot leak into another."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.reset()
        _store = None
