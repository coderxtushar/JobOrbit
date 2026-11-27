"""Application configuration.

Every setting is read from the environment (optionally via a ``.env`` file) and has a
default that is safe for a single-user local install. Nothing here contains a secret
value; secrets are only ever read from the environment.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProviderName = Literal["none", "openai", "openai_compatible"]

_LOOPBACK_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


class Settings(BaseSettings):
    """Runtime configuration, loaded once per process."""

    model_config = SettingsConfigDict(
        env_prefix="JA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- Server ----------
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_token: str = ""
    log_level: str = "INFO"
    display_timezone: str = "Asia/Kolkata"

    #: Public-demo deployment. Seeds a fictional profile and sample jobs, and **refuses
    #: resume uploads**, because a shared deployment has no per-user login: one visitor's
    #: resume would be readable by the next. Enforced in the API, not just hidden in the UI.
    demo_mode: bool = False

    # ---------- Accounts (hosted mode) ----------
    #: ``local``: one person, no sign-in (every request acts as the local owner).
    #: ``google``: every request must carry a session created from a verified Google
    #: sign-in, and each signed-in user sees only their own profile and applications.
    auth_mode: Literal["local", "google"] = "local"
    #: The OAuth client id Google issues the website; ID tokens must be minted for it.
    google_client_id: str = ""
    session_days: int = Field(default=30, ge=1, le=365)
    #: Sign-ups beyond this many accounts are refused (a free-tier database is small).
    max_users: int = Field(default=200, ge=1, le=100000)
    #: Comma-separated emails allowed to run installation-wide actions in google mode
    #: (discovery, imports, source settings, the emergency stop).
    admin_emails: str = ""
    #: In google mode jobs are shared, so archiving uses this installation-wide age rather
    #: than one person's limit; each person's own limit still applies to their matches.
    archive_after_days: int = Field(default=60, ge=1, le=3650)

    # ---------- Storage ----------
    database_url: str = "sqlite+pysqlite:///./var/jobassist.db"
    data_dir: Path = Path("./var")
    max_upload_mb: int = Field(default=10, ge=1, le=100)

    # ---------- LLM ----------
    llm_provider: LLMProviderName = "none"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_timeout_seconds: int = Field(default=60, ge=5, le=600)

    # ---------- Scheduler ----------
    scheduler_enabled: bool = False
    discovery_interval_minutes: int = Field(default=360, ge=15, le=10080)

    # ---------- Email job-alert ingestion ----------
    email_ingest_enabled: bool = False
    email_imap_host: str = ""
    email_imap_port: int = 993
    email_username: str = ""
    email_app_password: str = ""
    email_folder: str = "INBOX"

    # ---------- ATS job-board discovery ----------
    ats_discovery_enabled: bool = True
    ats_timeout_seconds: int = Field(default=20, ge=5, le=120)
    ats_max_attempts: int = Field(default=3, ge=1, le=6)
    ats_max_pages: int = Field(default=20, ge=1, le=200)
    greenhouse_boards: str = ""
    lever_boards: str = ""
    workable_boards: str = ""
    ashby_boards: str = ""
    smartrecruiters_boards: str = ""
    #: SmartRecruiters' postings list carries no job description; it lives on a
    #: per-posting detail endpoint. Each description therefore costs one extra request,
    #: so the number fetched per run is capped rather than unbounded.
    smartrecruiters_detail_limit: int = Field(default=60, ge=0, le=1000)
    #: ISO-2 country code ("in") passed to SmartRecruiters' own ``country`` filter, so a
    #: global employer's board returns only that country's postings. Empty = every country.
    smartrecruiters_country: str = Field(default="", pattern=r"^([A-Za-z]{2})?$")

    # ---------- Open job-feed discovery ----------
    feed_discovery_enabled: bool = False
    arbeitnow_enabled: bool = False
    remoteok_enabled: bool = False
    remotive_enabled: bool = False
    himalayas_enabled: bool = False
    jobicy_enabled: bool = False
    feed_max_pages: int = Field(default=3, ge=1, le=50)

    # ---------- Browser submission (Greenhouse / Lever / Ashby forms) ----------
    # Off by default. When on, auto-apply runs open each employer's own application form
    # in a dedicated Chrome profile, fill it from verified answers and press Submit. A
    # visible CAPTCHA, a sign-in wall or any unanswered question stops that job and hands
    # it to you; nothing is ever guessed and no challenge is ever solved by the program.
    browser_submission_enabled: bool = False
    browser_profile_dir: Path = Path("./var/browser/chrome")
    #: Playwright browser channel. "chrome" drives the installed Google Chrome; empty
    #: means Playwright's bundled Chromium (needs `playwright install chromium`).
    browser_channel: str = "chrome"
    browser_headless: bool = False
    browser_action_delay_min_ms: int = Field(default=350, ge=0, le=10000)
    browser_action_delay_max_ms: int = Field(default=1100, ge=0, le=20000)
    #: Pause between two submitted applications, so a run proceeds at a human pace.
    browser_between_applications_min_s: int = Field(default=20, ge=0, le=3600)
    browser_between_applications_max_s: int = Field(default=60, ge=0, le=3600)
    browser_confirmation_timeout_s: int = Field(default=25, ge=3, le=300)
    browser_page_timeout_s: int = Field(default=45, ge=5, le=300)
    #: Hard ceiling on applications dispatched through the browser per calendar day.
    browser_daily_submission_cap: int = Field(default=25, ge=1, le=500)
    #: Browser submissions allowed to run at the same time on one platform, across runs.
    browser_max_concurrent_per_platform: int = Field(default=1, ge=1, le=4)
    #: Consecutive failures on one platform that open its circuit breaker for the run.
    circuit_breaker_threshold: int = Field(default=3, ge=1, le=20)
    #: How long a job lock lasts before a crashed worker's lock may be taken over.
    job_lock_ttl_s: int = Field(default=900, ge=60, le=86400)
    #: A RUNNING run with no heartbeat for this long is treated as interrupted.
    run_stale_after_s: int = Field(default=180, ge=30, le=86400)
    #: Base delay before retrying a transient failure; doubled per attempt.
    retry_backoff_s: int = Field(default=30, ge=0, le=3600)

    # ---------- Evidence ----------
    #: Screenshots and browser events older than this are deleted by the cleanup task.
    evidence_retention_days: int = Field(default=30, ge=1, le=3650)
    #: Take a screenshot of the confirmation (or failure) page for every browser attempt.
    evidence_screenshots: bool = True

    # ---------- Email response tracking (opt-in, read-only Gmail OAuth) ----------
    email_tracking_enabled: bool = False
    #: OAuth client of type "Desktop app" created by the user in their own Google Cloud
    #: project. The installed-app client secret is not confidential by Google's design.
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    email_sync_days: int = Field(default=30, ge=1, le=365)
    email_max_messages: int = Field(default=200, ge=1, le=2000)
    #: Where OAuth tokens are kept: ``auto`` uses the OS keychain when available.
    secret_backend: Literal["auto", "keychain", "file"] = "auto"

    # ---------- Compensation ----------
    #: Optional INR per USD rate for showing USD salaries in INR. Never guessed.
    usd_inr_rate: float | None = Field(default=None, gt=0)

    @field_validator("usd_inr_rate", mode="before")
    @classmethod
    def _blank_rate_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    # ---------- Company research ----------
    #: Allow fetching a company's own website (title and meta description) on request.
    company_research_external: bool = False

    # ---------- Analytics ----------
    #: Minutes a person typically spends on one application form, for "time saved".
    minutes_per_manual_application: int = Field(default=12, ge=1, le=240)

    # ---------- Bulk preparation ----------
    batch_concurrency: int = Field(default=4, ge=1, le=16)
    batch_max_attempts: int = Field(default=3, ge=1, le=10)
    batch_max_jobs: int = Field(default=500, ge=1, le=5000)

    def board_tokens(self, source: str) -> tuple[str, ...]:
        """Board identifiers the user configured for one ATS, comma-separated in the env."""
        raw = {
            "greenhouse": self.greenhouse_boards,
            "lever": self.lever_boards,
            "workable": self.workable_boards,
            "ashby": self.ashby_boards,
            "smartrecruiters": self.smartrecruiters_boards,
        }.get(source, "")
        seen: dict[str, None] = {}
        for token in raw.replace(";", ",").split(","):
            cleaned = token.strip().strip("/")
            if cleaned:
                seen.setdefault(cleaned, None)
        return tuple(seen)

    def feed_enabled(self, source: str) -> bool:
        """Whether one open job feed is switched on, requiring the global switch too."""
        if not self.feed_discovery_enabled:
            return False
        return {
            "arbeitnow": self.arbeitnow_enabled,
            "remoteok": self.remoteok_enabled,
            "remotive": self.remotive_enabled,
            "himalayas": self.himalayas_enabled,
            "jobicy": self.jobicy_enabled,
        }.get(source, False)

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return upper

    @model_validator(mode="after")
    def _require_token_when_exposed(self) -> Settings:
        """Refuse to start unauthenticated on a non-loopback interface."""
        if not self.is_loopback_only and not self.api_token:
            raise ValueError(
                "JA_API_HOST is not a loopback address, which would expose resume and "
                "application data on the network. Set JA_API_TOKEN to a non-empty secret "
                "or bind to 127.0.0.1."
            )
        return self

    @model_validator(mode="after")
    def _require_google_settings(self) -> Settings:
        """Google mode without a client id or a service token would accept anyone."""
        if self.auth_mode == "google":
            if not self.google_client_id.strip():
                raise ValueError("JA_AUTH_MODE=google needs JA_GOOGLE_CLIENT_ID.")
            if not self.api_token:
                raise ValueError(
                    "JA_AUTH_MODE=google needs JA_API_TOKEN: the website proves it is the "
                    "website with it before any session is trusted."
                )
            if self.demo_mode:
                raise ValueError("JA_AUTH_MODE=google and JA_DEMO_MODE cannot both be on.")
        return self

    @property
    def is_multi_user(self) -> bool:
        return self.auth_mode == "google"

    @property
    def admin_email_set(self) -> frozenset[str]:
        return frozenset(
            email.strip().lower() for email in self.admin_emails.split(",") if email.strip()
        )

    @property
    def is_loopback_only(self) -> bool:
        host = self.api_host.strip().strip("[]")
        if host in _LOOPBACK_HOSTNAMES:
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    @property
    def llm_enabled(self) -> bool:
        """True only when a provider is selected AND a key is present."""
        return self.llm_provider != "none" and bool(self.llm_api_key)

    @property
    def resume_dir(self) -> Path:
        return self.data_dir / "resumes"

    @property
    def artifact_dir(self) -> Path:
        """Generated cover letters and resume variants."""
        return self.data_dir / "artifacts"

    @property
    def evidence_dir(self) -> Path:
        """Submission screenshots. May show personal data, so owner-only and never served."""
        return self.data_dir / "screenshots"

    @property
    def secrets_dir(self) -> Path:
        """Fallback token store when no OS keychain is available. Owner-only."""
        return self.data_dir / "secrets"

    @property
    def import_dir(self) -> Path:
        """Copies of uploaded import payloads, kept for audit."""
        return self.data_dir / "imports"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        """Create the private data directories with owner-only permissions."""
        for directory in (
            self.data_dir,
            self.resume_dir,
            self.artifact_dir,
            self.import_dir,
            self.evidence_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
            try:
                directory.chmod(0o700)
            except OSError:  # pragma: no cover - platform dependent (e.g. Windows)
                pass


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the settings cache. Used by tests that patch the environment."""
    get_settings.cache_clear()
