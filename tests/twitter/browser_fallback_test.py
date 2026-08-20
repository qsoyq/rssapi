from types import SimpleNamespace

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from rssapi.applications.twitter import browser_fallback


class _PlaywrightContext:
    def __init__(self, playwright):
        self.playwright = playwright

    def __enter__(self):
        return self.playwright

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _Browser:
    def __init__(self, page_factory):
        self.page_factory = page_factory

    def new_context(self):
        return _Context(self.page_factory)

    def close(self):
        return None


class _Context:
    def __init__(self, page_factory):
        self.page_factory = page_factory

    def add_cookies(self, cookies):
        return None

    def new_page(self):
        return self.page_factory()

    def close(self):
        return None


def _playwright_with_chromium(chromium):
    return _PlaywrightContext(SimpleNamespace(chromium=chromium))


def test_browser_fallback_reports_chromium_startup_failure(monkeypatch: pytest.MonkeyPatch):
    class _Chromium:
        def launch(self, *, headless: bool):
            raise RuntimeError("browser executable missing")

    monkeypatch.setattr(browser_fallback, "sync_playwright", lambda: _playwright_with_chromium(_Chromium()))

    with pytest.raises(browser_fallback.TwitterBrowserFallbackError) as exc_info:
        browser_fallback.fetch_user_posts_with_browser("targetuser", 5, "")

    assert exc_info.value.kind == "startup"
    assert exc_info.value.status_code == 503
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_browser_fallback_reports_navigation_timeout(monkeypatch: pytest.MonkeyPatch):
    class _Page:
        def goto(self, *args, **kwargs):
            raise PlaywrightTimeoutError("navigation timed out")

        def close(self):
            return None

    class _Chromium:
        def launch(self, *, headless: bool):
            return _Browser(_Page)

    monkeypatch.setattr(browser_fallback, "sync_playwright", lambda: _playwright_with_chromium(_Chromium()))

    with pytest.raises(browser_fallback.TwitterBrowserFallbackError) as exc_info:
        browser_fallback.fetch_user_posts_with_browser("targetuser", 5, "")

    assert exc_info.value.kind == "timeout"
    assert exc_info.value.status_code == 502
    assert isinstance(exc_info.value.__cause__, PlaywrightTimeoutError)


def test_browser_fallback_reports_no_results(monkeypatch: pytest.MonkeyPatch):
    class _Mouse:
        def wheel(self, x: int, y: int):
            return None

    class _Page:
        mouse = _Mouse()

        def goto(self, *args, **kwargs):
            return None

        def wait_for_selector(self, *args, **kwargs):
            raise PlaywrightTimeoutError("articles not found")

        def evaluate(self, *args, **kwargs):
            return []

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def close(self):
            return None

    class _Chromium:
        def launch(self, *, headless: bool):
            return _Browser(_Page)

    monkeypatch.setattr(browser_fallback, "sync_playwright", lambda: _playwright_with_chromium(_Chromium()))

    with pytest.raises(browser_fallback.TwitterBrowserFallbackError) as exc_info:
        browser_fallback.fetch_user_posts_with_browser("targetuser", 5, "")

    assert exc_info.value.kind == "no_results"
    assert exc_info.value.status_code == 502
