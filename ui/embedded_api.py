"""Start the API inside the Streamlit process, for single-process hosts.

Locally the two processes are separate, which is what the architecture assumes: the UI
talks to the backend only over HTTP. Streamlit Community Cloud runs exactly one process
(``streamlit run``), so there is nowhere for a second one to live and every page would
report "Cannot reach the API".

This module closes that gap without weakening the boundary. It *starts* uvicorn on
loopback inside the same container and nothing more — it never reads a model, a repository
or the database, so the UI still reaches its data only over HTTP and a React frontend could
still replace it unchanged.

Two behaviours matter and are easy to get wrong:

* **It must run once, not once per interaction.** Streamlit re-executes the whole script on
  every widget change, so a plain function call would try to bind port 8000 repeatedly.
  ``st.cache_resource`` gives one shared instance for the life of the process.
* **It must not hijack a real deployment.** If ``JA_API_BASE_URL`` names an API, or
  something is already listening locally, this does nothing and the configured API wins.
"""

from __future__ import annotations

import os
import socket
import threading
import time

import streamlit as st

_STARTUP_TIMEOUT_SECONDS = 45.0
_POLL_INTERVAL_SECONDS = 0.25


def _port_is_open(host: str, port: int, timeout: float = 0.4) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)
        return probe.connect_ex((host, port)) == 0


def _serve(host: str, port: int) -> None:
    import uvicorn

    from app.main import app

    uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning")).run()


def _prepare_database() -> None:
    """Create the schema and, in demo mode, the sample data and the per-visitor store.

    Streamlit Cloud never runs ``alembic upgrade head``, and its filesystem is wiped on
    redeploy, so the schema has to be created at boot. Alembic is used rather than
    ``create_all`` so the deployed schema is the same one the migrations produce.

    In demo mode the seeded database becomes a *template*: every visitor gets a copy of it
    so one visitor's shortlist never reaches the next. The template itself is only ever
    read after this point.
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "head")

    from app.config import get_settings

    settings = get_settings()
    if not settings.demo_mode:
        return

    from sqlalchemy.orm import Session

    from app.db.base import build_engine
    from app.services.demo import seed_demo_data
    from app.services.demo_sessions import configure_store

    with Session(build_engine()) as session:
        seed_demo_data(session)

    template = Path(settings.database_url.split("///", 1)[-1])
    if template.exists():
        configure_store(settings, template)


@st.cache_resource(show_spinner="Starting the local API…")
def ensure_api_running() -> str:
    """Return a human-readable status for the API the dashboard will talk to."""
    if os.environ.get("JA_API_BASE_URL"):
        return f"external: {os.environ['JA_API_BASE_URL']}"

    host = os.environ.get("JA_API_HOST", "127.0.0.1")
    port = int(os.environ.get("JA_API_PORT", "8000"))

    if _port_is_open(host, port):
        return f"already running on {host}:{port}"

    _prepare_database()
    threading.Thread(target=_serve, args=(host, port), daemon=True, name="embedded-api").start()

    deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _port_is_open(host, port):
            return f"embedded on {host}:{port}"
        time.sleep(_POLL_INTERVAL_SECONDS)
    return f"failed to start on {host}:{port}"
