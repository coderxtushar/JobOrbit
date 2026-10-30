"""Database engine and session management.

The only dialect-specific code in the project lives here: SQLite needs an explicit
``PRAGMA foreign_keys=ON`` per connection, because it ignores foreign keys by default and
would silently accept the orphan rows the schema is designed to prevent.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # Batch preparation runs several worker threads, each with its own connection.
        # Without WAL a reader blocks the writer outright, and without busy_timeout a
        # concurrent write fails instantly with "database is locked" instead of waiting.
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def _restrict_sqlite_file_permissions(engine: Engine, db_path: Path) -> None:
    """Make the database file owner-only once SQLite has created it.

    SQLite creates the file with the process umask, typically 0644. The database holds
    resume text, contact details and application answers, so it must not be world-readable
    even though its parent directory is 0700 — that would make the only protection a
    directory mode that a later move or copy of the data directory would silently drop.
    """
    tightened = False

    @event.listens_for(engine, "connect")
    def _chmod(_dbapi_connection: Any, _record: Any) -> None:
        nonlocal tightened
        if tightened:
            return
        tightened = True
        try:
            if db_path.exists():
                db_path.chmod(0o600)
        except OSError:  # pragma: no cover - platform dependent (e.g. Windows)
            pass


def build_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    url = settings.database_url
    kwargs: dict[str, Any] = {"echo": False, "future": True, "pool_pre_ping": True}
    sqlite_path: Path | None = None

    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" not in url:
            sqlite_path = Path(url.split("///", 1)[-1])
            sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        _enable_sqlite_foreign_keys(engine)
        if sqlite_path is not None:
            _restrict_sqlite_file_permissions(engine, sqlite_path)
    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)
    return _session_factory


def configure(engine: Engine) -> None:
    """Point the module at a specific engine. Used by tests and by the Streamlit process."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def create_all(engine: Engine | None = None) -> None:
    Base.metadata.create_all(bind=engine or get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
