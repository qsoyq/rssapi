import contextlib
import logging
import threading
from typing import cast
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

logger = logging.getLogger(__file__)


class TwitterClientTransactionSigner:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._bootstrap_url: str | None = None

    def sign(self, url: str, method: str, bootstrap_url: str) -> str | None:
        path = urlparse(url).path
        if not path:
            return None

        with self._lock:
            page = self._ensure_page(bootstrap_url)
            return cast(
                str | None,
                page.evaluate(
                    """
                async ({ path, method }) => {
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
                  return await signer(path, method.toUpperCase());
                }
                """,
                    {"path": path, "method": method},
                ),
            )

    def close(self) -> None:
        with self._lock:
            page = self._page
            browser = self._browser
            playwright = self._playwright
            self._page = None
            self._browser = None
            self._playwright = None
            self._bootstrap_url = None

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
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        self._playwright = playwright
        self._browser = browser
        page.goto(bootstrap_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_function(
            """
            () => document.querySelector('meta[name="twitter-site-verification"]')
              && document.querySelectorAll('path[d]').length >= 8
            """,
            timeout=15_000,
        )
        page.wait_for_timeout(1_000)
        self._page = page
        self._bootstrap_url = bootstrap_url
        logger.info(f"Twitter ClientTransaction Playwright signer initialized from {bootstrap_url}")
        return page


client_transaction_signer = TwitterClientTransactionSigner()
