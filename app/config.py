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

    # ---------- Open job-feed discovery ----------
    feed_discovery_enabled: bool = False
    arbeitnow_enabled: bool = False
    remoteok_enabled: bool = False
    remotive_enabled: bool = False
    himalayas_enabled: bool = False
    jobicy_enabled: bool = False
    feed_max_pages: int = Field(default=3, ge=1, le=50)

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
    def import_dir(self) -> Path:
        """Copies of uploaded import payloads, kept for audit."""
        return self.data_dir / "imports"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        """Create the private data directories with owner-only permissions."""
        for directory in (self.data_dir, self.resume_dir, self.artifact_dir, self.import_dir):
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
