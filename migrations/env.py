"""Alembic environment.

The database URL and the target metadata are taken from the application's own settings and
models, so a migration can never be generated against a different schema than the one the
app uses. ``render_as_batch`` is required for SQLite, which cannot ALTER a column in place.
"""

from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# Alembic connects with its own engine, bypassing app.db.base.build_engine, which is what
# normally creates var/. Without this, `alembic upgrade head` on a fresh checkout fails
# with "unable to open database file" because the SQLite parent directory is missing.
settings.ensure_directories()

config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _restrict_sqlite_permissions() -> None:
    """Make a freshly migrated SQLite file owner-only.

    Alembic builds its own engine with engine_from_config, bypassing
    app.db.base.build_engine and therefore its permission hook. The documented first-run
    sequence is `alembic upgrade head` *before* the API starts, so without this the
    database holding resumes and application answers sits at the process umask (0644)
    until the app first connects — and stays there in a migrate-only deployment.
    """
    url = settings.database_url
    if not url.startswith("sqlite") or ":memory:" in url:
        return
    database = Path(url.split("///", 1)[-1])
    try:
        if database.exists():
            database.chmod(0o600)
    except OSError:
        pass


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    _restrict_sqlite_permissions()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
