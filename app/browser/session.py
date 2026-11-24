"""The one browser JobOrbit drives, owned by one thread.

Playwright's synchronous API must be used from the thread that started it, while
auto-apply runs execute on worker threads the API spawns. So every browser operation is
posted to a single :class:`BrowserWorker` thread and its result handed back. That also
makes submissions strictly sequential, which is the pace a person applies at anyway.

The browser is a **persistent Chrome profile of its own** (``JA_BROWSER_PROFILE_DIR``),
never the user's everyday profile: Chrome refuses to share a profile directory between two
running instances, and a dedicated one keeps the bot's cookies separate from everything
else. Sign in to anything the bot needs once, by hand, in the window it opens.

Tabs that need the user — a CAPTCHA, an unclear outcome — are left open after a run, which
is why the browser outlives individual runs and is only closed on shutdown.
"""

from __future__ import annotations

import os
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from app.logging_conf import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from playwright.sync_api import BrowserContext

logger = get_logger(__name__)

T = TypeVar("T")


class BrowserUnavailable(RuntimeError):
    """Playwright or the configured browser could not be started."""


class BrowserWorker:
    """Runs callables against one persistent browser context, on one thread."""

    def __init__(
        self,
        *,
        profile_dir: Path,
        channel: str = "chrome",
        headless: bool = False,
        page_timeout_s: int = 45,
    ) -> None:
        self._profile_dir = profile_dir
        self._channel = channel
        self._headless = headless
        self._page_timeout_ms = page_timeout_s * 1000
        self._jobs: queue.Queue[tuple[Callable[[BrowserContext], Any], Future[Any]] | None] = (
            queue.Queue()
        )
        self._ready = threading.Event()
        self._start_error: BaseException | None = None
        self._thread = threading.Thread(target=self._main, name="joborbit-browser", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=90)
        if self._start_error is not None:
            raise BrowserUnavailable(str(self._start_error)) from self._start_error
        if not self._ready.is_set():
            raise BrowserUnavailable("the browser did not start within 90 seconds")

    def _main(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:  # pragma: no cover - dependency is declared
            self._start_error = error
            self._ready.set()
            return
        try:
            playwright = sync_playwright().start()
            self._profile_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self._profile_dir, 0o700)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self._profile_dir),
                channel=self._channel or None,
                headless=self._headless,
                viewport=None if not self._headless else {"width": 1280, "height": 900},
                accept_downloads=False,
            )
            context.set_default_timeout(self._page_timeout_ms)
        except Exception as error:  # noqa: BLE001 - reported to the caller verbatim
            self._start_error = error
            self._ready.set()
            return
        self._ready.set()
        logger.info("browser_started", extra={"profile_dir": str(self._profile_dir)})
        while True:
            item = self._jobs.get()
            if item is None:
                break
            func, future = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(func(context))
            except BaseException as error:  # noqa: BLE001 - re-raised in the caller's thread
                future.set_exception(error)
        try:
            context.close()
        finally:
            playwright.stop()

    def call(self, func: Callable[[BrowserContext], T], *, timeout_s: float = 600) -> T:
        """Run ``func(context)`` on the browser thread and return its result."""
        if not self._thread.is_alive():
            raise BrowserUnavailable("the browser thread has stopped")
        future: Future[T] = Future()
        self._jobs.put((func, future))
        return future.result(timeout=timeout_s)

    def close(self) -> None:
        self._jobs.put(None)
        self._thread.join(timeout=30)

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()


_lock = threading.Lock()
_worker: BrowserWorker | None = None


def get_browser() -> BrowserWorker:
    """Return the process-wide browser, starting it on first use."""
    global _worker
    from app.config import get_settings

    with _lock:
        if _worker is None or not _worker.alive:
            settings = get_settings()
            _worker = BrowserWorker(
                profile_dir=Path(settings.browser_profile_dir),
                channel=settings.browser_channel,
                headless=settings.browser_headless,
                page_timeout_s=settings.browser_page_timeout_s,
            )
        return _worker


def shutdown_browser() -> None:
    """Close the browser if it was started. Called on application shutdown."""
    global _worker
    with _lock:
        if _worker is not None:
            _worker.close()
            _worker = None


__all__ = ["BrowserUnavailable", "BrowserWorker", "get_browser", "shutdown_browser"]
