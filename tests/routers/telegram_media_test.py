import pytest
from fastapi import Request

from rssapi.applications.telegram.router import fetch_feeds
from rssapi.applications.telegram.schemas import TelegramChannalMessage


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "scheme": "https",
            "server": ("rss.example", 443),
            "path": "/api/rss/telegram/channel",
            "query_string": b"channels=example",
            "headers": [],
        }
    )


async def _messages(_channel: str) -> list[TelegramChannalMessage]:
    return [
        TelegramChannalMessage(
            head="https://cdn.example/avatar.jpg",
            msgid="123",
            channelName="example",
            username="example",
            title="Photo",
            text="Photo",
            updated="2026-09-15T00:00:00Z",
            authorName=None,
            contentHtml="<div>Photo</div>",
            photoUrls=["https://cdn.example/photo.jpg"],
            tags=[],
        )
    ]


@pytest.mark.asyncio
async def test_telegram_feed_uses_stable_media_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rssapi.applications.telegram.router.get_channel_messages", _messages)

    items = await fetch_feeds(["example"], req=_request())

    assert len(items) == 1
    stable_url = "https://rss.example/api/rss/telegram/media/example/123/0"
    assert str(items[0].image) == stable_url
    assert stable_url in (items[0].content_html or "")
