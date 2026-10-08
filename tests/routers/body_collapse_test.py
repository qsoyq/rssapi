from collections.abc import Iterator
from typing import Any, cast

import pytest
from bs4 import BeautifulSoup, Tag
from fastapi import Request

from rssapi.applications.instagram.utils import post_to_jsonfeed_item as instagram_item
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedItem
from rssapi.applications.telegram.router import message_to_jsonfeed_item
from rssapi.applications.telegram.schemas import TelegramChannalMessage
from rssapi.applications.tiktok.utils import post_to_jsonfeed_item as tiktok_item
from rssapi.applications.twitter.feed import _tweets_to_jsonfeed_items
from rssapi.applications.twitter.types import Tweet
from rssapi.applications.weibo.utils import post_to_jsonfeed_item as weibo_item
from rssapi.core.middlewares.rss import AppendOriginalPostLinkMiddleware
from rssapi.core.settings import settings

SOURCES = ["twitter", "instagram", "tiktok", "weibo", "telegram"]
IMAGE_URL = "https://cdn.example/image.jpg"
VIDEO_URL = "https://cdn.example/video.mp4"
BODY = "正文第一段\n正文第二段"


@pytest.fixture(params=[True, False], ids=["enabled", "disabled"])
def collapse_enabled(request: pytest.FixtureRequest) -> Iterator[bool]:
    previous = settings.rss_collapse_body_enabled
    enabled = request.param
    settings.rss_collapse_body_enabled = enabled
    try:
        yield enabled
    finally:
        settings.rss_collapse_body_enabled = previous


def _telegram_message(text: str, with_media: bool) -> TelegramChannalMessage:
    return TelegramChannalMessage.model_validate(
        {
            "msgid": "1",
            "channelName": "sample",
            "username": "sample",
            "title": "Telegram post",
            "text": text,
            "updated": "2026-10-07T12:00:00+08:00",
            "contentHtml": text or None,
            "media": [
                {"kind": "image", "url": IMAGE_URL, "mime_type": "image/jpeg"},
                {"kind": "video", "url": VIDEO_URL, "mime_type": "video/mp4"},
            ]
            if with_media
            else [],
        }
    )


def _source_item(source: str, text: str, with_media: bool) -> JSONFeedItem:
    if source == "twitter":
        tweet = Tweet.model_validate(
            {
                "id": "1",
                "text": text,
                "author": {"name": "Sample", "screenName": "sample"},
                "metrics": {},
                "createdAt": "2026-10-07T12:00:00+08:00",
                "quotedTweet": {
                    "id": "2",
                    "text": "引用内容",
                    "author": {"name": "Quoted", "screenName": "quoted"},
                }
                if text
                else None,
                "media": [{"type": "photo", "url": IMAGE_URL}, {"type": "video", "url": VIDEO_URL}]
                if with_media
                else [],
            }
        )
        return _tweets_to_jsonfeed_items([tweet])[0]
    if source == "instagram":
        post: dict[str, Any] = {"id": "1", "code": "Example", "caption": {"text": text}}
        if text:
            post.update({"like_count": 3, "comment_count": 4, "location": {"name": "A&B"}})
        if with_media:
            post["carousel_media"] = [
                {"media_type": 1, "display_uri": IMAGE_URL},
                {"media_type": 2, "video_versions": [{"url": VIDEO_URL}]},
            ]
        return instagram_item(post, {"username": "sample"}, "sample")
    if source == "tiktok":
        post = {"id": "1", "desc": text}
        if text:
            post["stats"] = {"diggCount": 3, "commentCount": 4}
        if with_media:
            post["video"] = {"playAddr": {"urlList": [VIDEO_URL]}}
            post["imagePost"] = {"images": [{"imageURL": {"urlList": [IMAGE_URL]}}]}
        return tiktok_item(post, {"uniqueId": "sample"}, "sample")
    if source == "weibo":
        post = {"id": "1", "text_raw": text}
        if text:
            post.update(
                {
                    "reposts_count": 3,
                    "comments_count": 4,
                    "source": "<a>Weibo Web</a>",
                    "retweeted_status": {"text_raw": "引用内容", "user": {"screen_name": "Quoted"}},
                }
            )
        if with_media:
            post["pic_ids"] = ["image"]
            post["pic_infos"] = {"image": {"largest": {"url": IMAGE_URL}}}
            post["page_info"] = {"urls": {"mp4_hd_mp4": VIDEO_URL}}
        return weibo_item(post, {"id": "1", "screen_name": "Sample"}, 1)
    if source == "telegram":
        return message_to_jsonfeed_item(_telegram_message(text, with_media))
    raise ValueError(f"Unknown source: {source}")


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize(
    ("text", "with_media"), [(BODY, True), (BODY, False), ("", True)], ids=["mixed", "body-only", "media-only"]
)
def test_sources_obey_body_collapse_setting(source: str, text: str, with_media: bool, collapse_enabled: bool) -> None:
    item = _source_item(source, text, with_media)
    document = BeautifulSoup(item.content_html or "", "html.parser")
    details = document.find_all("details")

    if collapse_enabled and text:
        assert len(details) == 1
        assert details[0].summary and details[0].summary.get_text() == "查看正文"
        assert not details[0].has_attr("open")
        assert not details[0].find(["img", "video"])
    else:
        assert not details
        assert not document.find("summary")

    if text:
        assert document.get_text().count("正文第一段") == 1
        assert document.get_text().count("正文第二段") == 1
    if with_media:
        assert document.find("img", src=IMAGE_URL)
        assert document.find("video", src=VIDEO_URL)
        if text:
            html = item.content_html or ""
            assert html.index(IMAGE_URL) < html.index("正文第一段")
            assert html.index(VIDEO_URL) < html.index("正文第一段")
    else:
        assert not document.find(["img", "video"])

    middleware = AppendOriginalPostLinkMiddleware(app=cast(Any, None))
    result = middleware.transform_feed_item(item)
    document = BeautifulSoup(result.content_html or "", "html.parser")
    original_link = document.find("a", string="查看原贴")
    assert isinstance(original_link, Tag)
    assert original_link["href"] == str(item.url)
    assert original_link.find_parent("details") is None


@pytest.mark.parametrize("source", SOURCES)
def test_switching_collapse_preserves_body_and_metadata(source: str, collapse_enabled: bool) -> None:
    settings.rss_collapse_body_enabled = False
    plain = _source_item(source, BODY, True)
    settings.rss_collapse_body_enabled = True
    folded = _source_item(source, BODY, True)

    assert plain.model_dump(exclude={"content_html"}) == folded.model_dump(exclude={"content_html"})
    assert plain.content_html == (
        (folded.content_html or "").replace("<details><summary>查看正文</summary>", "").replace("</details>", "")
    )


def test_telegram_repeated_conversion_keeps_cached_message_unchanged(collapse_enabled: bool) -> None:
    message = _telegram_message('<div class="js-message_text"><b>正文</b><br>下一行</div>', True)
    original = message.model_dump()

    first = message_to_jsonfeed_item(message)
    second = message_to_jsonfeed_item(message)

    assert message.model_dump() == original
    assert first == second
    assert (second.content_html or "").count("<details>") == int(collapse_enabled)


def test_telegram_stable_media_urls_and_legacy_photos(collapse_enabled: bool) -> None:
    request = Request({"type": "http", "scheme": "https", "server": ("rss.example", 443), "path": "/", "headers": []})
    message = _telegram_message(BODY, True)
    item = message_to_jsonfeed_item(message, req=request)
    stable_prefix = "https://rss.example/api/rss/telegram/media/sample/1"

    assert str(item.image) == f"{stable_prefix}/0"
    assert item.image == item.banner_image
    assert item.attachments and str(item.attachments[0].url) == f"{stable_prefix}/1"
    assert f'src="{stable_prefix}/0"' in (item.content_html or "")
    assert f'src="{stable_prefix}/1"' in (item.content_html or "")
    assert not BeautifulSoup(item.content_html or "", "html.parser").select("details img, details video")

    legacy_message = _telegram_message(BODY, False)
    legacy_message.photoUrls = [message.media[0].url]
    legacy_item = message_to_jsonfeed_item(legacy_message)
    assert f'src="{IMAGE_URL}"' in (legacy_item.content_html or "")
    assert not legacy_item.attachments
