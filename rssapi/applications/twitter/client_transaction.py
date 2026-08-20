import contextlib
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from typing import cast
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

logger = logging.getLogger(__file__)


class TwitterClientTransactionSigner:
    def __init__(self, operation_timeout: float = 60.0) -> None:
        self._operation_timeout = operation_timeout
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="twitter-transaction-signer"
        )
        self._submission_lock = threading.RLock()
        self._owner_thread_id: int | None = None
        self._cleanup_required = threading.Event()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._bootstrap_url: str | None = None

    def sign(self, url: str, method: str, bootstrap_url: str) -> str | None:
        path = urlparse(url).path
        if not path:
            return None

        future = self._submit(self._sign_on_owner, path, method, bootstrap_url)
        try:
            return cast(str | None, future.result(timeout=self._operation_timeout))
        except TimeoutError:
            self._cleanup_required.set()
            raise

    def close(self) -> None:
        if threading.get_ident() == self._owner_thread_id:
            self._close_on_owner()
            return

        # Hold the submission lock until the executor is stopped so no new sign can race with
        # shutdown. A subsequent sign lazily creates a fresh owner thread.
        with self._submission_lock:
            executor = self._executor
            if executor is None:
                return
            executor.submit(self._close_on_owner).result(timeout=self._operation_timeout)
            executor.shutdown(wait=True, cancel_futures=True)
            if self._executor is executor:
                self._executor = None

    def _submit(self, function, *args) -> Future:
        with self._submission_lock:
            if self._executor is None:
                self._owner_thread_id = None
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="twitter-transaction-signer")
            return self._executor.submit(function, *args)

    def _sign_on_owner(self, path: str, method: str, bootstrap_url: str) -> str | None:
        self._set_owner_thread()
        if self._cleanup_required.is_set():
            self._close_on_owner()

        try:
            page = self._ensure_page(bootstrap_url)
            result = cast(
                str | None,
                page.evaluate(
                    """
                async ({ path, method, timeoutMs }) => {
                  if (!window.__rssapiTwitterSignUrlPromise) {
                    window.__rssapiTwitterSignUrlPromise = (async () => {
                      const urls = [...new Set(
                        [...document.querySelectorAll('script[src], link[href]')]
                          .map((el) => el.src || el.href)
                          .filter((url) => url && url.includes('/x-web/x-web/') && url.endsWith('.js'))
                      )];
                      for (const url of urls) {
                        try {
                          const text = await fetch(url).then((response) => response.text());
                          const match = text.match(/\\.\\/((?:sign\\.o-)[^`'"]+\\.js)/);
                          if (match) {
                            return new URL(match[1], url).href;
                          }
                        } catch {
                        }
                      }
                      throw new Error('X sign module URL not found');
                    })();
                  }

                  if (!window.__rssapiTwitterSignerPromise) {
                    window.__rssapiTwitterSignerPromise = window.__rssapiTwitterSignUrlPromise
                      .then((signUrl) => import(signUrl))
                      .then((module) => module.default());
                  }

                  const signer = await window.__rssapiTwitterSignerPromise;
                  return await Promise.race([
                    signer(path, method.toUpperCase()),
                    new Promise((_, reject) => setTimeout(
                      () => reject(new Error('Twitter signer evaluation timed out')),
                      timeoutMs,
                    )),
                  ]);
                }
                """,
                    {"path": path, "method": method, "timeoutMs": self._operation_timeout * 1000},
                ),
            )
            if self._cleanup_required.is_set():
                self._close_on_owner()
            return result
        except BaseException:
            self._close_on_owner()
            raise

    def _set_owner_thread(self) -> None:
        thread_id = threading.get_ident()
        if self._owner_thread_id is None:
            self._owner_thread_id = thread_id
        elif self._owner_thread_id != thread_id:
            raise RuntimeError("Twitter ClientTransaction signer executor changed owner thread")

    def _close_on_owner(self) -> None:
        self._set_owner_thread()
        page = self._page
        browser = self._browser
        playwright = self._playwright
        self._page = None
        self._browser = None
        self._playwright = None
        self._bootstrap_url = None
        self._cleanup_required.clear()

        if page is not None:
            with contextlib.suppress(Exception):
                page.close()
        if browser is not None:
            with contextlib.suppress(Exception):
                browser.close()
        if playwright is not None:
            with contextlib.suppress(Exception):
                playwright.stop()

    def _ensure_page(self, bootstrap_url: str) -> Page:
        if self._page is not None and not self._page.is_closed() and self._bootstrap_url == bootstrap_url:
            return self._page

        self.close()
        playwright = sync_playwright().start()
        self._playwright = playwright
        browser = playwright.chromium.launch(headless=True)
        self._browser = browser
        page = browser.new_page()
        self._page = page
        page.goto(bootstrap_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_function(
            """
            () => document.querySelector('meta[name="twitter-site-verification"]')
              && document.querySelectorAll('path[d]').length >= 8
            """,
            timeout=15_000,
        )
        page.wait_for_timeout(1_000)
        self._bootstrap_url = bootstrap_url
        logger.info(f"Twitter ClientTransaction Playwright signer initialized from {bootstrap_url}")
        return page


client_transaction_signer = TwitterClientTransactionSigner()
