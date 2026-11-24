"""User-initiated job capture: the API, the extension manifest, and the page extractor.

The extractor tests run ``extension/extractor.js`` in a real headless Chrome against
synthetic pages in ``tests/fixtures/capture/``, served under the platform's own URL by
Playwright request routing so the site heuristics see the host they key on. No request
leaves the machine. These pages imitate the structure of LinkedIn, Naukri and Indeed job
views as of writing; they are not those sites, and passing here says nothing about the
live markup, which changes without notice.

Browser tests are skipped when Chrome (or, for the unpacked-extension test, Playwright's
bundled Chromium) cannot be started.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import reset_settings_cache
from app.db.models import AuditLog, CandidateProfile, Job, JobSourceReference, SourceName
from app.services.capture import infer_external_id, infer_source, map_employment_type

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = PROJECT_ROOT / "extension"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "capture"


def _listing(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Backend Engineer (Python)",
        "company": "Acme Robotics",
        "location": "Bengaluru, Karnataka, IN",
        "url": "https://careers.acme-robotics.example/jobs/backend-engineer-python?gh_jid=4412",
        "page_url": "https://careers.acme-robotics.example/jobs/backend-engineer-python",
        "description": (
            "Build REST APIs with Python and FastAPI on PostgreSQL. Docker and AWS. "
            "0-2 years of experience. Bengaluru, hybrid."
        ),
        "posted_at": "2026-11-14",
        "employment_type": "FULL_TIME",
        "source_hint": "",
        "extension_version": "0.1.0",
        "captured_at": "2026-11-21T10:00:00Z",
        "extraction": {
            "method": "json-ld",
            "confidence": 0.9,
            "missing": [],
            "field_sources": {"title": "json-ld"},
        },
    }
    payload.update(overrides)
    return payload


def _job_count(session: Session) -> int:
    session.expire_all()
    return int(session.scalar(select(func.count(Job.id))) or 0)


# --------------------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------------------


def test_capture_creates_a_scored_job_with_provenance(
    client: TestClient, session: Session, profile: CandidateProfile
) -> None:
    response = client.post("/api/capture/job", json=_listing())
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["created"] is True
    assert body["duplicate_of"] is None
    assert body["source"] == "company_site"
    assert isinstance(body["score"], float)
    assert body["band"] in {"high", "review", "low"}
    assert body["confidence"]
    assert 0 < len(body["explanation"]) <= 5
    assert body["dashboard_path"] == f"/job?job_id={body['job_id']}"

    session.expire_all()
    job = session.get(Job, body["job_id"])
    assert job is not None
    assert job.title == "Backend Engineer (Python)"
    assert job.company == "Acme Robotics"
    assert job.employment_type.value == "full_time"
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-11-14"

    (reference,) = job.source_references
    assert reference.source is SourceName.COMPANY_SITE
    assert reference.retrieval_method == "user_capture"
    metadata = reference.source_metadata
    assert metadata["extension_version"] == "0.1.0"
    assert metadata["extraction_method"] == "json-ld"
    assert metadata["page_url"].startswith("https://careers.acme-robotics.example/")
    assert metadata["captured_at"].startswith("2026-11-21T10:00:00")

    audit = session.scalars(select(AuditLog).where(AuditLog.action == "jobs.captured")).one()
    assert audit.entity_id == job.id


def test_platform_and_posting_id_are_inferred_from_the_url(
    client: TestClient, session: Session, profile: CandidateProfile
) -> None:
    response = client.post(
        "/api/capture/job",
        json=_listing(
            url="https://in.linkedin.com/jobs/view/backend-developer-at-initech-3912345678/"
        ),
    )
    assert response.status_code == 201, response.text
    assert response.json()["source"] == "linkedin"

    session.expire_all()
    reference = session.scalars(select(JobSourceReference)).one()
    assert reference.source is SourceName.LINKEDIN
    assert reference.external_id == "3912345678"


def test_the_same_listing_captured_twice_is_one_job(
    client: TestClient, session: Session, profile: CandidateProfile
) -> None:
    first = client.post("/api/capture/job", json=_listing())
    assert first.status_code == 201
    job_id = first.json()["job_id"]

    # Same posting, reached through a link with campaign tags and a fragment.
    again = client.post(
        "/api/capture/job",
        json=_listing(
            url=(
                "https://careers.acme-robotics.example/jobs/backend-engineer-python"
                "?utm_source=newsletter&gh_jid=4412#apply"
            )
        ),
    )
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["created"] is False
    assert body["duplicate_of"] == job_id
    assert body["job_id"] == job_id
    assert "Already in JobOrbit" in body["message"]
    assert _job_count(session) == 1


def test_a_capture_matches_a_job_that_was_imported_from_a_file(
    client: TestClient, session: Session, profile: CandidateProfile
) -> None:
    imported = client.post(
        "/api/jobs/import",
        json={
            "records": [
                {
                    "source": "manual",
                    "title": "Backend Engineer (Python)",
                    "company": "Acme Robotics",
                    "url": "https://careers.acme-robotics.example/jobs/backend-engineer-python?gh_jid=4412",
                }
            ]
        },
    )
    assert imported.status_code == 201

    captured = client.post("/api/capture/job", json=_listing())
    assert captured.status_code == 200
    assert captured.json()["created"] is False
    assert _job_count(session) == 1

    session.expire_all()
    job = session.scalars(select(Job)).one()
    # The capture enriched the imported row with the description it lacked, and the job
    # now carries both sightings as provenance.
    assert "FastAPI" in job.description
    assert {ref.retrieval_method for ref in job.source_references} == {
        "manual_import",
        "user_capture",
    }


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(document.cookie)",
        "file:///etc/passwd",
        "data:text/html,<script>alert(1)</script>",
        "ftp://jobs.example.com/1",
        "http://127.0.0.1:8000/api/jobs",
        "https://user:pass@jobs.example.com/1",
        "",
    ],
)
def test_unsafe_urls_are_rejected(
    client: TestClient, session: Session, profile: CandidateProfile, url: str
) -> None:
    response = client.post("/api/capture/job", json=_listing(url=url))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    assert "url" in response.json()["error"]["field_errors"]
    assert _job_count(session) == 0


def test_an_unsafe_page_url_is_dropped_not_stored(
    client: TestClient, session: Session, profile: CandidateProfile
) -> None:
    response = client.post(
        "/api/capture/job", json=_listing(page_url="javascript:alert(1)", url=_listing()["url"])
    )
    assert response.status_code == 201
    session.expire_all()
    reference = session.scalars(select(JobSourceReference)).one()
    assert reference.source_metadata["page_url"] == _listing()["url"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"unexpected": "field"},
        {"title": ""},
        {"company": "   "},
        {"description": "x" * 20_001},
        {"title": "t" * 401},
        {"extraction": {"method": "json-ld", "cookies": "nope"}},
        {"extraction": {"method": "json-ld", "confidence": 3}},
    ],
)
def test_malformed_bodies_are_refused(
    client: TestClient, session: Session, profile: CandidateProfile, overrides: dict[str, Any]
) -> None:
    response = client.post("/api/capture/job", json=_listing(**overrides))
    assert response.status_code == 422, response.text
    assert _job_count(session) == 0


def test_status_is_a_cheap_reachability_check(client: TestClient) -> None:
    response = client.get("/api/capture/status")
    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "JobOrbit"
    assert body["version"]
    assert body["token_required"] is False
    assert body["capture_enabled"] is True


def test_demo_mode_refuses_capture(engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_DEMO_MODE", "true")
    reset_settings_cache()
    from app.main import create_app

    with TestClient(create_app()) as demo:
        response = demo.post("/api/capture/job", json=_listing())
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "demo_mode_job_capture_blocked"
        status = demo.get("/api/capture/status").json()
        assert status["demo_mode"] is True
        assert status["capture_enabled"] is False
    reset_settings_cache()


def test_a_bearer_token_is_required_when_configured(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JA_API_TOKEN", "capture-test-token-0123456789")
    reset_settings_cache()
    from app.main import create_app

    with TestClient(create_app()) as api:
        assert api.post("/api/capture/job", json=_listing()).status_code == 401
        assert api.get("/api/capture/status").status_code == 401
        wrong = {"Authorization": "Bearer not-the-token"}
        assert api.post("/api/capture/job", json=_listing(), headers=wrong).status_code == 401

        good = {"Authorization": "Bearer capture-test-token-0123456789"}
        status = api.get("/api/capture/status", headers=good)
        assert status.status_code == 200
        assert status.json()["token_required"] is True
        assert api.post("/api/capture/job", json=_listing(), headers=good).status_code == 201
    reset_settings_cache()


@pytest.mark.parametrize(
    ("url", "source"),
    [
        ("https://www.linkedin.com/jobs/view/123456789/", SourceName.LINKEDIN),
        ("https://www.naukri.com/job-listings-python-developer-151124012345", SourceName.NAUKRI),
        ("https://in.indeed.com/viewjob?jk=0123456789abcdef", SourceName.INDEED),
        ("https://uk.indeed.co.uk/viewjob?jk=0123456789abcdef", SourceName.INDEED),
        ("https://wellfound.com/jobs/123-backend", SourceName.WELLFOUND),
        ("https://boards.greenhouse.io/acme/jobs/4412", SourceName.GREENHOUSE),
        ("https://careers.acme.example/jobs/1", SourceName.COMPANY_SITE),
        ("https://notlinkedin.com/jobs/view/123456789", SourceName.COMPANY_SITE),
    ],
)
def test_source_inference(url: str, source: SourceName) -> None:
    assert infer_source(url) is source


def test_external_id_and_employment_type_mapping() -> None:
    assert (
        infer_external_id(
            SourceName.LINKEDIN, "https://www.linkedin.com/jobs/search/?currentJobId=3912345678"
        )
        == "3912345678"
    )
    assert (
        infer_external_id(SourceName.INDEED, "https://in.indeed.com/viewjob?jk=0123456789abcdef")
        == "0123456789abcdef"
    )
    assert infer_external_id(SourceName.COMPANY_SITE, "https://acme.example/jobs/99") is None
    assert map_employment_type("FULL_TIME") == "full_time"
    assert map_employment_type("INTERN, PART_TIME") == "internship"
    assert map_employment_type("Full Time, Permanent") == "full_time"
    assert map_employment_type("Contractor") == "contract"
    assert map_employment_type("whenever") is None


# --------------------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------------------


def _manifest() -> dict[str, Any]:
    return json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_requests_only_the_minimal_permissions() -> None:
    manifest = _manifest()
    assert manifest["manifest_version"] == 3
    assert sorted(manifest["permissions"]) == ["activeTab", "scripting", "storage"]
    assert sorted(manifest["host_permissions"]) == ["http://127.0.0.1/*", "http://localhost/*"]
    for forbidden in (
        "content_scripts",
        "background",
        "optional_permissions",
        "optional_host_permissions",
        "externally_connectable",
        "web_accessible_resources",
        "declarative_net_request",
    ):
        assert forbidden not in manifest, forbidden
    assert manifest["action"]["default_popup"] == "popup.html"


def test_extension_code_never_touches_private_browser_data() -> None:
    """A static backstop for the runtime traps below: none of these APIs appear at all."""
    forbidden = (
        "document.cookie",
        "chrome.cookies",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "chrome.history",
        "chrome.webRequest",
        ".innerHTML",
        "eval(",
        "<all_urls>",
    )
    for path in sorted(EXTENSION_DIR.glob("*.js")):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path.name} uses {token}"
    for page in ("popup.html", "options.html"):
        html = (EXTENSION_DIR / page).read_text(encoding="utf-8")
        assert "<script>" not in html, "MV3 forbids inline scripts"


def test_every_file_the_extension_references_exists() -> None:
    manifest = _manifest()
    referenced = {manifest["action"]["default_popup"], manifest["options_ui"]["page"]}
    for page in list(referenced):
        html = (EXTENSION_DIR / page).read_text(encoding="utf-8")
        for marker in ('src="', 'href="'):
            for chunk in html.split(marker)[1:]:
                target = chunk.split('"', 1)[0]
                if target and not target.startswith(("#", "http")):
                    referenced.add(target)
    referenced.add("extractor.js")
    for name in referenced:
        assert (EXTENSION_DIR / name).is_file(), name


# --------------------------------------------------------------------------------------
# Extractor, in a real Chrome
# --------------------------------------------------------------------------------------

#: Installed before any page script runs. Each private surface records the access and then
#: throws, so an extractor that touched one would both fail and be caught in the record.
TRAPS = """
(() => {
  window.__joborbitTouched = [];
  const note = (what) => { window.__joborbitTouched.push(what); };
  const trap = (target, name) => {
    try {
      Object.defineProperty(target, name, {
        configurable: true,
        get() { note(name); throw new Error(name + " must not be read"); },
        set() { note(name + "="); },
      });
    } catch (error) { note("could-not-trap:" + name); }
  };
  trap(Document.prototype, "cookie");
  trap(window, "localStorage");
  trap(window, "sessionStorage");
  trap(window, "indexedDB");
  for (const proto of [HTMLInputElement.prototype, HTMLTextAreaElement.prototype, HTMLSelectElement.prototype]) {
    const original = Object.getOwnPropertyDescriptor(proto, "value");
    Object.defineProperty(proto, "value", {
      configurable: true,
      get() { note("form-value"); return original.get.call(this); },
      set(value) { original.set.call(this, value); },
    });
  }
})();
"""

PRIVATE_STRINGS = (
    "hunter2-secret",
    "someone@private.example",
    "my private note",
    "HIDDEN-TRACKER-TEXT",
    "SCRIPT-BODY",
)


@pytest.fixture(scope="module")
def playwright_manager() -> Iterator[Any]:
    """One Playwright driver per module: the sync API refuses to start a second one."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover - playwright is a pinned dependency
        pytest.skip("playwright is not installed")
    manager = sync_playwright().start()
    yield manager
    manager.stop()


@pytest.fixture(scope="module")
def chrome(playwright_manager: Any) -> Iterator[Any]:
    try:
        browser = playwright_manager.chromium.launch(channel="chrome", headless=True)
    except Exception as error:
        pytest.skip(f"Chrome is not available here: {str(error).splitlines()[0]}")
    yield browser
    browser.close()


def _extract(chrome: Any, fixture: str, url: str) -> tuple[dict[str, Any], list[str]]:
    """Serve ``fixture`` at ``url``, run extractor.js, return (result, touched)."""
    html = (FIXTURES / fixture).read_text(encoding="utf-8")
    source = (EXTENSION_DIR / "extractor.js").read_text(encoding="utf-8")
    context = chrome.new_context(java_script_enabled=True)
    try:
        context.add_init_script(TRAPS)

        def handle(route: Any) -> None:
            if route.request.url.split("#")[0] == url.split("#")[0]:
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
            else:
                route.abort()  # nothing leaves the machine

        context.route("**/*", handle)
        page = context.new_page()
        page.goto(url)
        # Indirect eval returns the script's completion value, which is exactly what
        # chrome.scripting.executeScript({files}) hands back to the popup.
        result = page.evaluate("(source) => (0, eval)(source)", source)
        touched = page.evaluate("() => window.__joborbitTouched")
        again = page.evaluate("() => joborbitExtract(document, location)")
        assert again == result
        return result, touched
    finally:
        context.close()


def _assert_private_data_untouched(result: dict[str, Any], touched: list[str]) -> None:
    assert touched == [], f"the extractor read private surfaces: {touched}"
    dumped = json.dumps(result)
    for secret in PRIVATE_STRINGS:
        assert secret not in dumped, secret


def test_extractor_reads_a_json_ld_job_posting(chrome: Any) -> None:
    result, touched = _extract(
        chrome,
        "jsonld_jobposting.html",
        "https://careers.acme-robotics.example/jobs/backend-engineer-python?utm_medium=social",
    )
    assert result["title"] == "Backend Engineer (Python)"
    assert result["company"] == "Acme Robotics"
    assert result["location"] == "Bengaluru, Karnataka, IN"
    assert result["posted_at"] == "2026-11-14"
    assert result["employment_type"] == "FULL_TIME"
    # The canonical link, with tracking stripped and the ATS job id kept.
    assert result["url"] == (
        "https://careers.acme-robotics.example/jobs/backend-engineer-python?gh_jid=4412"
    )
    assert "utm_" not in result["page_url"]
    description = result["description"]
    assert "Build REST APIs with Python and FastAPI." in description
    assert "- PostgreSQL and Docker" in description
    assert "<" not in description
    assert result["source_hint"] == ""
    assert result["extraction"]["method"] == "json-ld"
    assert result["extraction"]["confidence"] == 0.9
    assert result["extraction"]["missing"] == []
    _assert_private_data_untouched(result, touched)


def test_extractor_handles_graph_arrays_and_escaped_html(chrome: Any) -> None:
    result, touched = _extract(
        chrome, "jsonld_graph.html", "https://globex.example/careers/ml-intern"
    )
    assert result["title"] == "Machine Learning Intern"
    assert result["company"] == "Globex Corporation"
    assert result["location"] == "Remote (India); Pune, India; Hyderabad, India"
    assert result["employment_type"] == "INTERN, PART_TIME"
    assert result["posted_at"] == "2026-11-18T09:30:00+05:30"
    assert result["description"] == (
        "Train models with PyTorch.\n\nPython required; LLM experience is a plus."
    )
    assert result["url"] == "https://globex.example/careers/ml-intern"
    _assert_private_data_untouched(result, touched)


def test_extractor_reads_a_linkedin_like_job_view(chrome: Any) -> None:
    result, touched = _extract(
        chrome,
        "linkedin_like.html",
        "https://www.linkedin.com/jobs/search/?currentJobId=3912345678&trk=public_jobs&refId=abc",
    )
    assert result["title"] == "Backend Developer"
    assert result["company"] == "Initech"
    assert result["location"] == "Bengaluru, Karnataka, India"
    assert result["posted_at"] == "2 days ago"
    assert result["employment_type"] == "Full-time"
    # The canonical link points at the search page, so the job id from the query wins.
    assert result["url"] == "https://www.linkedin.com/jobs/view/3912345678/"
    assert "Python and FastAPI services" in result["description"]
    assert "- Docker and Kubernetes" in result["description"]
    assert result["source_hint"] == "linkedin"
    assert result["extraction"]["method"] == "site:linkedin"
    # og:site_name says "LinkedIn"; that is the board, never the employer.
    assert result["company"] != "LinkedIn"
    _assert_private_data_untouched(result, touched)


def test_extractor_reads_a_naukri_like_job_page(chrome: Any) -> None:
    result, touched = _extract(
        chrome,
        "naukri_like.html",
        "https://www.naukri.com/job-listings-python-developer-umbrella-tech-pune-0-to-2-years-151124012345?src=jobsearchDesk&sid=1",
    )
    assert result["title"] == "Python Developer"
    assert result["company"] == "Umbrella Tech"
    assert result["location"] == "Pune"
    assert result["posted_at"] == "3 days ago"
    assert result["employment_type"] == "Full Time, Permanent"
    assert "Django and FastAPI" in result["description"]
    assert result["url"] == (
        "https://www.naukri.com/job-listings-python-developer-umbrella-tech-pune-0-to-2-years-151124012345"
    )
    assert result["source_hint"] == "naukri"
    _assert_private_data_untouched(result, touched)


def test_extractor_reads_an_indeed_like_job_page(chrome: Any) -> None:
    result, touched = _extract(
        chrome,
        "indeed_like.html",
        "https://in.indeed.com/jobs?q=data+analyst&vjk=0123456789abcdef&from=serp",
    )
    assert result["title"] == "Data Analyst"
    assert result["company"] == "Hooli"
    assert result["location"] == "Gurugram, Haryana"
    assert result["employment_type"] == "Full-time"
    assert "dashboards for the growth team" in result["description"]
    assert result["url"] == "https://in.indeed.com/viewjob?jk=0123456789abcdef"
    assert result["source_hint"] == "indeed"
    _assert_private_data_untouched(result, touched)


def test_extractor_falls_back_to_headings_and_meta_tags(chrome: Any) -> None:
    result, touched = _extract(
        chrome,
        "no_structured_data.html",
        "https://jobs.vandelay.example/sre?utm_source=x&id=7#top",
    )
    assert result["title"] == "Site Reliability Engineer"
    assert result["company"] == "Vandelay Industries"
    assert result["description"].startswith("Join Vandelay Industries as an SRE.")
    assert result["url"] == "https://jobs.vandelay.example/sre?id=7"
    assert result["extraction"]["method"] == "generic"
    assert result["extraction"]["confidence"] <= 0.5
    assert set(result["extraction"]["missing"]) >= {"location", "posted_at"}
    _assert_private_data_untouched(result, touched)


def test_a_heuristic_that_finds_nothing_returns_nothing(chrome: Any) -> None:
    """A LinkedIn URL whose page has none of the expected markup yields empty fields,
    not the board's own name or a guess."""
    result, touched = _extract(
        chrome, "no_structured_data.html", "https://www.linkedin.com/jobs/view/123456789/"
    )
    assert result["source_hint"] == "linkedin"
    assert result["company"] == "Vandelay Industries"  # from og:title, not og:site_name
    assert result["location"] == ""
    assert result["posted_at"] == ""
    assert result["extraction"]["method"] == "generic"
    _assert_private_data_untouched(result, touched)


# --------------------------------------------------------------------------------------
# The unpacked extension, end to end
# --------------------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def live_api(engine, profile: CandidateProfile) -> Iterator[str]:
    """The real application on a loopback port, sharing the test's in-memory database."""
    import uvicorn

    from app.main import create_app

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            pytest.fail("the API did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


#: Points the popup at a chosen tab. A popup opened as a normal page has no "active tab"
#: other than itself, and there is no way to click a toolbar button headless, so the test
#: stands in for that one step. Extraction itself still goes through
#: chrome.scripting.executeScript, permitted here by the loopback host permission.
POPUP_TARGET = """
(() => {
  if (!location.pathname.endsWith("/popup.html")) return;
  const original = chrome.tabs.query.bind(chrome.tabs);
  chrome.tabs.query = () =>
    original({ url: "http://127.0.0.1/*" }).then((tabs) =>
      tabs.filter((tab) => tab.url && tab.url.includes("/capture-fixture/")));
})();
"""


def test_unpacked_extension_captures_a_page_into_the_api(
    tmp_path: Path, live_api: str, session: Session, playwright_manager: Any
) -> None:
    from playwright.sync_api import expect

    fixture_url = f"{live_api.rsplit(':', 1)[0]}:{_free_port()}/capture-fixture/job.html"
    html = (FIXTURES / "jsonld_jobposting.html").read_text(encoding="utf-8")

    context = _launch_with_extension(playwright_manager, tmp_path / "profile")
    try:
        context.route(
            fixture_url,
            lambda route: route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=html
            ),
        )
        extension_id = _extension_id(context)
        if extension_id is None:
            pytest.skip("the unpacked extension did not load in headless Chromium")
        base = f"chrome-extension://{extension_id}"

        options = context.new_page()
        options.goto(f"{base}/options.html")
        options.fill("#apiBase", live_api)
        options.click("#save")
        expect(options.locator("#message")).to_have_text("Saved.")
        stored = options.evaluate("() => chrome.storage.local.get(null)")
        assert stored["apiBase"] == live_api
        options.click("#test")
        expect(options.locator("#connection")).to_contain_text("Connected")

        job_tab = context.new_page()
        job_tab.goto(fixture_url)

        # executeScript({files}) returns the file's completion value: the popup's
        # primary path, checked directly rather than through its fallback.
        injected = options.evaluate(
            """async () => {
              const [tab] = await chrome.tabs.query({ url: "http://127.0.0.1/*" });
              const results = await chrome.scripting.executeScript({
                target: { tabId: tab.id }, files: ["extractor.js"] });
              return results[0].result;
            }"""
        )
        assert injected["title"] == "Backend Engineer (Python)"
        assert injected["extraction"]["method"] == "json-ld"

        context.add_init_script(POPUP_TARGET)
        popup = context.new_page()
        popup.goto(f"{base}/popup.html")
        expect(popup.locator("#title")).to_have_value("Backend Engineer (Python)")
        assert popup.input_value("#company") == "Acme Robotics"
        expect(popup.locator("#extraction")).to_contain_text("JSON-LD")
        expect(popup.locator("#connection")).to_contain_text("Connected")

        # The user edits a field before sending.
        popup.fill("#location", "Bengaluru (hybrid)")
        popup.click("#send")
        expect(popup.locator("#result")).to_contain_text("Added to JobOrbit")
        expect(popup.locator("#result")).to_contain_text("Score")
        link = popup.get_attribute("#result a", "href") or ""
        assert link.startswith("http://localhost:8501/job?job_id=")

        popup.click("#send")
        expect(popup.locator("#result")).to_contain_text("Already in JobOrbit")

        # JobOrbit not running: the popup says how to start it instead of failing silently.
        options.evaluate(
            "(base) => chrome.storage.local.set({ apiBase: base })",
            f"http://127.0.0.1:{_free_port()}",
        )
        popup.reload()
        expect(popup.locator("#title")).to_have_value("Backend Engineer (Python)")
        expect(popup.locator("#connection")).to_have_text("Not running")
        popup.click("#send")
        expect(popup.locator("#result")).to_contain_text("Can't reach JobOrbit")
        expect(popup.locator("#result")).to_contain_text("uvicorn app.main:app")
    finally:
        context.close()

    session.expire_all()
    job = session.scalars(select(Job)).one()
    assert job.location == "Bengaluru (hybrid)"
    reference = job.source_references[0]
    assert reference.retrieval_method == "user_capture"
    assert reference.source_metadata["extraction_method"] == "json-ld"
    assert reference.source_metadata["field_sources"]["location"] == "user"
    assert reference.source_metadata["extension_version"] == _manifest()["version"]


def _chromium_candidates() -> list[str | None]:
    """Playwright's own Chromium first, then any Chromium/Chrome for Testing build already
    in its download cache (a newer Playwright elsewhere on the machine may have put one
    there). Branded Google Chrome is not a candidate: since version 137 it ignores
    ``--load-extension``."""
    candidates: list[str | None] = [None]
    override = os.environ.get("JOBORBIT_TEST_CHROMIUM")
    if override:
        candidates.insert(0, override)
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    if not cache.is_dir():
        cache = Path.home() / ".cache" / "ms-playwright"
    patterns = ("chromium-*/chrome-mac*/*.app/Contents/MacOS/*", "chromium-*/chrome-linux*/chrome")
    for pattern in patterns:
        for path in sorted(cache.glob(pattern), reverse=True):
            if path.is_file():
                candidates.append(str(path))
    return candidates


def _launch_with_extension(playwright_manager: Any, profile_dir: Path) -> Any:
    errors: list[str] = []
    for executable in _chromium_candidates():
        try:
            return playwright_manager.chromium.launch_persistent_context(
                str(profile_dir),
                channel=None if executable else "chromium",
                executable_path=executable,
                headless=True,
                args=[
                    f"--disable-extensions-except={EXTENSION_DIR}",
                    f"--load-extension={EXTENSION_DIR}",
                ],
            )
        except Exception as error:
            errors.append(str(error).splitlines()[0])
    pytest.skip(f"no Chromium that can load an unpacked extension: {errors}")


def _extension_id(context: Any) -> str | None:
    """The loaded extension's id, asked of chrome://extensions (there is no service worker
    to read it from, by design)."""
    page = context.new_page()
    try:
        page.goto("chrome://extensions")
        infos = page.evaluate(
            "() => new Promise((resolve) => chrome.developerPrivate.getExtensionsInfo(resolve))"
        )
        for info in infos or []:
            if info.get("name") == _manifest()["name"]:
                return str(info["id"])
        return None
    except Exception:
        return None
    finally:
        page.close()
