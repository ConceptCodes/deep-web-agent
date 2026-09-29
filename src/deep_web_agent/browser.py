"""Own a browser and serialize its entire lifetime on one worker thread."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import TypeVar

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

T = TypeVar("T")


class BrowserSession:
    """Run page actions serially; close permits reuse, shutdown ends the lifetime.

    Actions run on the owner thread and must not call back into this session.
    Page objects must stay inside actions. Shutdown waits for accepted actions.
    """

    def __init__(self, *, playwright_factory=sync_playwright) -> None:
        self._factory = playwright_factory
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright")
        self._lock = Lock()
        self._closed = False
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._playwright: Playwright | None = None

    def run(self, action: Callable[[Page], T]) -> T:
        return self._submit(lambda: action(self._get_page()))

    def close(self) -> None:
        """Close browser resources on their owner thread, allowing later reopen."""
        self._submit(self._close)

    def shutdown(self) -> None:
        """Reject new actions, release browser resources, and join the worker."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            cleanup = self._executor.submit(self._close)
        try:
            cleanup.result()
        finally:
            self._executor.shutdown(wait=True)

    def _submit(self, action: Callable[[], T]) -> T:
        with self._lock:
            if self._closed:
                raise RuntimeError("Browser session has shut down")
            future = self._executor.submit(action)
        return future.result()

    def _get_page(self) -> Page:
        if self._page is not None and not self._page.is_closed():
            return self._page
        self._close()
        try:
            self._playwright = self._factory().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            context = self._browser.new_context()
            context.set_default_timeout(10_000)
            self._page = context.new_page()
            return self._page
        except BaseException:
            try:
                self._close()
            except Exception:
                pass  # Preserve the startup failure after attempting both cleanups.
            raise

    def _close(self) -> None:
        browser, playwright = self._browser, self._playwright
        self._browser = self._page = self._playwright = None
        try:
            if browser is not None:
                browser.close()
        finally:
            if playwright is not None:
                playwright.stop()
