"""The per-visitor demo store copies what a reader of the template sees."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.base import build_engine
from app.db.models import Base, Job
from app.services.demo import seed_demo_data
from app.services.demo_sessions import DemoSessionStore


def test_a_visitor_copy_includes_rows_still_in_the_write_ahead_log(tmp_path: Path) -> None:
    template = tmp_path / "template.db"
    settings = get_settings().model_copy(update={"database_url": f"sqlite+pysqlite:///{template}"})
    engine = build_engine(settings)  # WAL mode, as in production
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        seed_demo_data(session)
        seeded = session.scalar(select(func.count()).select_from(Job))

    # The template engine stays open, as it does inside the running API, so the seed may
    # still be in template.db-wal rather than in template.db itself.
    try:
        store = DemoSessionStore(settings, template)
        with store.factory_for("visitor-key")() as visitor:
            copied = visitor.scalar(select(func.count()).select_from(Job))
        store.reset()
    finally:
        engine.dispose()

    assert seeded and seeded > 0
    assert copied == seeded
