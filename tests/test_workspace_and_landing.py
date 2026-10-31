"""Landing page, workspace navigation, platform assistants and demo write boundaries.

The navigation tests read ``ui.streamlit_app`` as data rather than rendering it: importing
that module executes ``st.navigation(...).run()``, which needs a live Streamlit session.
Asserting on the declared page objects still catches the failure that matters — a page
dropped or renamed during a restructure — without pretending to exercise the router.
"""

from __future__ import annotations

import ast
import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from app.api.deps import DEMO_SESSION_HEADER
from app.config import reset_settings_cache
from app.services.demo_sessions import new_session_key
from app.services.platforms import PLATFORMS, PLATFORMS_BY_KEY, get_platform

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = PROJECT_ROOT / "ui" / "streamlit_app.py"
LANDING = PROJECT_ROOT / "ui" / "landing.py"

#: Titles the workspace must keep offering. The original eleven views plus the five
#: platform assistants and the landing link.
EXPECTED_TITLES: set[str] = {
    "JobOrbit",
    "Overview",
    "Resume and profile",
    "Job discovery",
    "Job feed",
    "Job detail",
    "Saved searches",
    "Naukri",
    "LinkedIn",
    "Indeed",
    "Wellfound",
    "ATS & other platforms",
    "Bulk preparation",
    "Action inbox",
    "Review queue",
    "Application tracker",
    "Settings and sources",
    "Logs and diagnostics",
}


def _entrypoint_source() -> str:
    return ENTRYPOINT.read_text(encoding="utf-8")


def _declared_pages() -> list[dict[str, str]]:
    """Every ``st.Page(...)`` in the entrypoint, as its keyword arguments."""
    pages: list[dict[str, str]] = []
    for node in ast.walk(ast.parse(_entrypoint_source())):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "Page"):
            continue
        entry = {
            keyword.arg: keyword.value.value
            for keyword in node.keywords
            if keyword.arg and isinstance(keyword.value, ast.Constant)
        }
        pages.append({key: str(value) for key, value in entry.items()})
    return pages


# --------------------------------------------------------------------------------------
# Navigation structure
# --------------------------------------------------------------------------------------


def test_every_page_survives_the_restructure() -> None:
    titles = {page["title"] for page in _declared_pages() if "title" in page}
    missing = EXPECTED_TITLES - titles
    assert not missing, f"these pages disappeared from navigation: {sorted(missing)}"


def test_every_page_has_a_stable_url_for_bookmarks_and_refresh() -> None:
    pages = _declared_pages()
    paths = [page.get("url_path", "") for page in pages]
    assert all(paths), "a page without url_path gets a generated URL that can change"
    assert len(set(paths)) == len(paths), f"duplicate url_path values: {paths}"


def test_the_landing_page_is_the_default_route() -> None:
    defaults = [page for page in _declared_pages() if page.get("default") == "True"]
    assert len(defaults) == 1, "exactly one page may be the root route"
    assert defaults[0]["title"] == "JobOrbit"


def test_navigation_is_grouped_into_the_four_workspace_sections() -> None:
    source = _entrypoint_source()
    for section in ("Main", "Platform assistants", "Applications", "System"):
        assert f'"{section}"' in source, f"missing navigation section: {section}"


def test_only_the_workspace_wrapper_starts_the_api() -> None:
    """One start site keeps the landing page inert; more than one reintroduces the cost."""
    source = _entrypoint_source()
    assert source.count("ensure_api_running()") == 1


# --------------------------------------------------------------------------------------
# The landing page touches nothing
# --------------------------------------------------------------------------------------


def test_the_landing_page_never_starts_the_api_or_seeds_the_database() -> None:
    """Arriving at the root URL must cost a template render, not a migration and a scoring pass."""
    called: set[str] = set()
    for node in ast.walk(ast.parse(LANDING.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            func = node.func
            called.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))
    banned = {
        "ensure_api_running",
        "require_api",
        "get_client",
        "seed_demo_data",
        "build_engine",
        "get_session_factory",
    }
    assert not (banned & called), f"the landing page calls {sorted(banned & called)}"


def test_the_landing_page_renders_the_required_copy() -> None:
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r})\n"
        "import streamlit as st\n"
        "from ui import landing\n"
        "landing.render(None)\n"
    )
    app = AppTest.from_string(script)
    app.run(timeout=40)
    assert not app.exception

    text = " ".join(str(block.value) for block in app.markdown)
    assert "Your job search," in text and "in orbit." in text
    assert "Discover relevant opportunities" in text
    assert "Stay in control of every submission" in text
    assert "Job<span" in text, "the wordmark must render"
    assert 'id="how-it-works"' in text, "the secondary CTA needs a real target"
    assert 'id="features"' in text and 'id="platforms"' in text

    labels = {button.label for button in app.button}
    assert "Explore JobOrbit" in labels
    # Streamlit 1.41's AppTest exposes no link_button accessor, so the secondary CTA is
    # asserted at its source plus its anchor target, which is what has to stay in sync.
    source = LANDING.read_text(encoding="utf-8")
    assert 'link_button("How it works", "#how-it-works"' in source


def test_the_landing_page_hides_the_operational_sidebar() -> None:
    from ui.theme import _LANDING_CSS

    assert 'section[data-testid="stSidebar"]' in _LANDING_CSS
    assert "display: none" in _LANDING_CSS


def test_the_landing_page_shows_the_demo_badge_only_in_demo_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ui import landing

    monkeypatch.setenv("JA_DEMO_MODE", "true")
    reset_settings_cache()
    assert landing.DEMO_BADGE == "Free demo · No account required · Fictional data"
    assert "No account required" in landing.DEMO_BADGE
    reset_settings_cache()


def test_the_landing_page_offers_no_working_sign_in() -> None:
    """Identity is designed for but not enabled, so there must be no OAuth control yet."""
    source = LANDING.read_text(encoding="utf-8")
    assert "coming soon" in source
    for forbidden in ("accounts.google.com", "oauth2", "client_id", "id_token"):
        assert forbidden not in source, f"landing page references {forbidden}"


# --------------------------------------------------------------------------------------
# Platform registry and endpoints
# --------------------------------------------------------------------------------------


def test_the_registry_covers_every_source_exactly_once() -> None:
    from app.db.models import SourceName

    seen: list[SourceName] = [source for platform in PLATFORMS for source in platform.sources]
    assert len(seen) == len(set(seen)), "a source appears in two platform sections"
    assert set(seen) == set(SourceName), "a source would be invisible in the platform view"


def test_the_five_platform_sections_exist() -> None:
    assert set(PLATFORMS_BY_KEY) == {"naukri", "linkedin", "indeed", "wellfound", "ats"}


def test_an_unknown_platform_is_a_404(client: TestClient) -> None:
    assert get_platform("monster") is None
    assert client.get("/api/platforms/monster").status_code == 404


def test_the_platform_list_reports_zero_rather_than_a_placeholder(client: TestClient) -> None:
    payload = client.get("/api/platforms").json()
    assert len(payload) == 5
    for platform in payload:
        assert platform["jobs_stored"] == 0
        assert platform["applications"] == 0
        assert platform["supports_automated_submission"] is False


def test_only_the_ats_section_reports_automated_discovery(client: TestClient) -> None:
    """The compliance claim, asserted through the API rather than trusted from the docs."""
    payload = {item["key"]: item for item in client.get("/api/platforms").json()}
    assert payload["ats"]["discovery_source_count"] > 0
    for key in ("naukri", "linkedin", "indeed", "wellfound"):
        assert payload[key]["discovery_source_count"] == 0
        assert payload[key]["supports_automated_discovery"] is False


def test_a_platform_labels_submission_as_permanently_unavailable(client: TestClient) -> None:
    for key in PLATFORMS_BY_KEY:
        detail = client.get(f"/api/platforms/{key}").json()
        actions = {action["key"]: action for action in detail["actions"]}
        assert actions["automated_submission"]["available"] is False
        assert "Never available" in actions["automated_submission"]["description"]
        for source in detail["sources"]:
            assert source["effective_capabilities"]["automated_submission_enabled"] is False


def test_an_import_only_platform_explains_why_discovery_is_unavailable(
    client: TestClient,
) -> None:
    detail = client.get("/api/platforms/linkedin").json()
    actions = {action["key"]: action for action in detail["actions"]}
    assert actions["automated_discovery"]["available"] is False
    assert "terms prohibit" in actions["automated_discovery"]["description"]
    assert "8.2" in detail["how_jobs_arrive"]


def test_platform_counts_follow_stored_jobs(client: TestClient) -> None:
    client.post(
        "/api/jobs/import",
        json={
            "records": [
                {
                    "source": "linkedin",
                    "external_id": "PLAT-1",
                    "title": "Backend Developer",
                    "company": "Northwind Systems",
                    "location": "Bengaluru, India",
                    "url": "https://jobs.example.com/plat/1",
                    "description": "Requirements\n- Python\n- FastAPI\n",
                }
            ]
        },
    )
    detail = client.get("/api/platforms/linkedin").json()
    assert detail["jobs_stored"] == 1
    assert sum(detail["jobs_by_status"].values()) == 1
    assert client.get("/api/platforms/indeed").json()["jobs_stored"] == 0


# --------------------------------------------------------------------------------------
# Demo-mode write boundaries
# --------------------------------------------------------------------------------------


@pytest.fixture
def demo_api(engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("JA_DEMO_MODE", "true")
    reset_settings_cache()
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
    reset_settings_cache()


@pytest.fixture
def demo_store_api(engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A demo API with a real per-session store backed by a seeded template database."""
    from sqlalchemy import create_engine as make_engine
    from sqlalchemy.orm import sessionmaker

    from app.config import get_settings
    from app.db.models import Base
    from app.services.demo import seed_demo_data
    from app.services.demo_sessions import configure_store, reset_store

    monkeypatch.setenv("JA_DEMO_MODE", "true")
    reset_settings_cache()

    template = tmp_path / "demo-template.db"
    template_engine = make_engine(f"sqlite+pysqlite:///{template}")
    Base.metadata.create_all(template_engine)
    with sessionmaker(bind=template_engine)() as seeding_session:
        seed_demo_data(seeding_session)
    template_engine.dispose()

    configure_store(get_settings(), template)
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
    reset_store()
    reset_settings_cache()


@pytest.mark.parametrize(
    ("method", "path", "kwargs", "code"),
    [
        ("POST", "/api/jobs/discover", {"json": {"sources": ["greenhouse"]}}, "discovery"),
        (
            "POST",
            "/api/jobs/import",
            {
                "json": {
                    "records": [
                        {
                            "source": "linkedin",
                            "title": "Backend Developer",
                            "company": "Northwind Systems",
                            "url": "https://jobs.example.com/demo/1",
                        }
                    ]
                }
            },
            "job_import",
        ),
        ("POST", "/api/batches", {"json": {"bands": ["high"]}}, "batch_run"),
        ("PATCH", "/api/sources/linkedin", {"json": {"enabled": False}}, "source_config"),
    ],
)
def test_demo_mode_refuses_the_writes_that_cost_somebody_else(
    demo_api: TestClient, method: str, path: str, kwargs: dict, code: str
) -> None:
    response = demo_api.request(method, path, **kwargs)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == f"demo_mode_{code}_blocked"


def test_demo_mode_refuses_a_csv_import(demo_api: TestClient) -> None:
    response = demo_api.post(
        "/api/jobs/import-csv",
        files={"file": ("jobs.csv", io.BytesIO(b"title,company\nx,y\n"), "text/csv")},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "demo_mode_job_import_blocked"


def test_every_blocked_operation_explains_itself_and_offers_a_way_forward() -> None:
    from app.api.deps import DEMO_BLOCKED_REASONS

    assert set(DEMO_BLOCKED_REASONS) == {
        "discovery",
        "job_import",
        "batch_run",
        "source_config",
        "resume_upload",
    }
    for operation, reason in DEMO_BLOCKED_REASONS.items():
        assert "disabled" in reason or "cannot" in reason or "too" in reason, operation
        assert len(reason) > 80, f"{operation} needs a real explanation, not a label"


def test_a_session_scoped_write_is_refused_without_an_isolated_database(
    demo_api: TestClient,
) -> None:
    """A write with nowhere private to go must be refused, not sent to the shared copy."""
    for path in ("/api/jobs/score", "/api/batches/preview"):
        response = demo_api.post(path, json={})
        assert response.status_code == 403, f"{path} must require an isolated session"
        assert response.json()["error"]["code"] == "demo_mode_write_disabled"


def test_the_light_writes_work_once_the_visitor_has_a_session(
    demo_store_api: TestClient,
) -> None:
    """Shortlisting, skipping and scoring are the demo's point, against the visitor's copy."""
    headers = {DEMO_SESSION_HEADER: new_session_key()}
    for path in ("/api/jobs/score", "/api/batches/preview"):
        response = demo_store_api.post(path, json={}, headers=headers)
        assert response.status_code != 403, f"{path} should work with a session: {response.text}"


def test_two_demo_sessions_cannot_see_each_others_writes(demo_store_api: TestClient) -> None:
    """The acceptance criterion: one visitor's shortlist must not reach another visitor."""
    first = {DEMO_SESSION_HEADER: new_session_key()}
    second = {DEMO_SESSION_HEADER: new_session_key()}

    job_id = demo_store_api.get("/api/jobs", headers=first).json()["items"][0]["id"]
    shortlisted = demo_store_api.post(f"/api/jobs/{job_id}/shortlist", headers=first)
    assert shortlisted.status_code == 200, shortlisted.text

    mine = demo_store_api.get(f"/api/jobs/{job_id}", headers=first).json()
    theirs = demo_store_api.get(f"/api/jobs/{job_id}", headers=second).json()
    assert mine["status"] != theirs["status"], (
        "the second visitor is reading the first visitor's shortlist"
    )


def test_a_demo_session_key_cannot_escape_the_sessions_directory() -> None:
    """The key arrives in a client-controlled header, so it is filtered, not trusted."""
    from app.services.demo_sessions import _safe_filename

    assert "/" not in _safe_filename("../../etc/passwd")
    assert ".." not in _safe_filename("../../etc/passwd")


def test_mutating_endpoints_are_either_blocked_or_session_scoped() -> None:
    """Audit gate: a new mutating route must be classified, not silently exposed.

    Keyed on the endpoint function name rather than the URL path, because the path is what
    changes when a route is moved while its demo-safety classification does not.
    """
    from app.api.deps import DEMO_SESSION_SCOPED
    from app.main import create_app

    blocked_endpoints = {
        "discover_jobs",
        "import_jobs",
        "import_jobs_csv",
        "start_batch",
        "update_source",
        "upload_resume",
    }
    app = create_app()
    mutating = {
        getattr(route.endpoint, "__name__", "")
        for route in app.routes
        if getattr(route, "methods", set()) & {"POST", "PUT", "PATCH", "DELETE"}
    }
    unclassified = mutating - blocked_endpoints - set(DEMO_SESSION_SCOPED)
    assert not unclassified, (
        f"these mutating routes are unclassified for demo mode: {sorted(unclassified)}"
    )
    assert not (blocked_endpoints & set(DEMO_SESSION_SCOPED)), (
        "an operation cannot be both blocked and session-scoped"
    )

    routes_dir = PROJECT_ROOT / "app" / "api" / "routes"
    guarded_sources = "".join(
        path.read_text(encoding="utf-8") for path in sorted(routes_dir.glob("*.py"))
    )
    assert guarded_sources.count("refuse_in_demo_mode(settings,") == 6


# --------------------------------------------------------------------------------------
# Auth abstractions exist but authenticate nothing
# --------------------------------------------------------------------------------------


def test_the_local_provider_is_not_treated_as_authenticated() -> None:
    from app.auth import LOCAL_OWNER_ID, CurrentUser, get_auth_provider

    provider = get_auth_provider()
    user = provider.current_user()
    assert isinstance(user, CurrentUser)
    assert user.subject == LOCAL_OWNER_ID
    assert user.is_local_owner is True
    assert user.is_authenticated is False, (
        "a principal nobody verified must never report as authenticated"
    )
    assert provider.login_url() == "", "sign-in does not exist yet and must not be implied"


def test_the_auth_module_documents_what_real_sign_in_requires() -> None:
    import app.auth as auth

    doc = auth.__doc__ or ""
    for requirement in ("user_id", "OIDC", "repository", "demo mode"):
        assert requirement in doc, f"the migration note omits {requirement}"
