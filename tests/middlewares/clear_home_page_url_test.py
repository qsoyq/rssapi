from typing import Any, cast

from fastapi import Request

from rssapi.core.middlewares import rss as rss_middleware
from rssapi.core.middlewares.rss import ClearHomePageUrlMiddleware


def test_clear_home_page_url_middleware_clears_home_page_url(monkeypatch) -> None:
    monkeypatch.setattr(rss_middleware.settings.middleware, "clear_home_page_url_enabled", True)
    middleware = ClearHomePageUrlMiddleware(app=cast(Any, None))
    body = {"version": "https://jsonfeed.org/version/1", "home_page_url": "https://example.com"}

    result = middleware.transform_body(body, cast(Request, None))

    assert result["home_page_url"] == ""


def test_clear_home_page_url_middleware_preserves_home_page_url_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(rss_middleware.settings.middleware, "clear_home_page_url_enabled", False)
    middleware = ClearHomePageUrlMiddleware(app=cast(Any, None))
    body = {"version": "https://jsonfeed.org/version/1", "home_page_url": "https://example.com"}

    result = middleware.transform_body(body, cast(Request, None))

    assert result["home_page_url"] == "https://example.com"
