from typing import Any, cast

from fastapi import Request

from rssapi.core.middlewares.rss import FillFeedIconFromAuthorAvatarMiddleware


def test_feed_icon_from_author_avatar_does_not_override_explicit_icons() -> None:
    middleware = FillFeedIconFromAuthorAvatarMiddleware(app=cast(Any, None))
    body = {
        "version": "https://jsonfeed.org/version/1",
        "author": {"name": "频道", "avatar": "https://cdn.example/channel.jpg"},
        "icon": "https://example.com/site.ico",
        "favicon": "https://example.com/site.ico",
    }

    result = middleware.transform_body(body, cast(Request, None))

    assert result["icon"] == "https://example.com/site.ico"
    assert result["favicon"] == "https://example.com/site.ico"


def test_feed_icon_from_author_avatar_fills_missing_icons() -> None:
    middleware = FillFeedIconFromAuthorAvatarMiddleware(app=cast(Any, None))
    body = {
        "version": "https://jsonfeed.org/version/1",
        "author": {"name": "频道", "avatar": "https://cdn.example/channel.jpg"},
    }

    result = middleware.transform_body(body, cast(Request, None))

    assert result["icon"] == "https://cdn.example/channel.jpg"
    assert result["favicon"] == "https://cdn.example/channel.jpg"
