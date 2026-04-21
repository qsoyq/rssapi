import asyncio
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import pytz

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedItem
from rssapi.core.settings import AppSettings
from rssapi.utils.basic import ShelveStorage, URLToolkit  # type: ignore
from rssapi.utils.playwright import AsyncPlaywright

logger = logging.getLogger(__file__)

Headless = AppSettings().rss_douyin_user_headless


class TimeoutException(Exception):
    pass


@dataclass(frozen=True)
class DouyinPlaywrightTask:
    username: str
    cookie: str


class AccessHistory:
    storage = ShelveStorage(AppSettings().rss_douyin_user_history_storage)
    lock = asyncio.Lock()

    @staticmethod
    async def get_history(shuffle: bool = True) -> list[DouyinPlaywrightTask]:
        async with AccessHistory.lock:
            with AccessHistory.storage:
                items = await asyncio.to_thread(AccessHistory.storage.iterall)

            result = [DouyinPlaywrightTask(*item) for item in items]
            if shuffle:
                random.shuffle(result)
            return result

    @staticmethod
    async def append(username: str, cookie: str):
        async with AccessHistory.lock:
            with AccessHistory.storage:
                await asyncio.to_thread(AccessHistory.storage.__setitem__, username, cookie)


class DouyinPlaywright(AsyncPlaywright):
    WATCH_URL_PATH = "/web/aweme/post"


def _extract_video_url(post: dict) -> str | None:
    bit_rate = post.get("video", {}).get("bit_rate", [])
    if not bit_rate:
        return None
    try:
        return cast(str, bit_rate[0]["play_addr"]["url_list"][-1])
    except Exception as e:
        logger.warning(f"[_extract_video_url] error: {e}")
        pass
    return None


def _extract_cover(post: dict) -> str | None:
    video = post.get("video", {})
    cover = (
        video.get("cover", {}).get("url_list", [None])[-1]  # HD
        or video.get("origin_cover", {}).get("url_list", [None])[-1]  # LD
    )
    return cover and URLToolkit.resolve_url(cover)


def _extract_image_gallery(post: dict) -> list[str]:
    if not post.get("images"):
        return []
    return [img["url_list"][0] for img in post.get("images", [])]


def _extract_tags(post: dict) -> list[str]:
    desc_tags = {x.replace("#", "") for x in re.findall(r"#\w+", post["desc"])}
    video_tags = {x["tag_name"] for x in post["video_tag"] if x["tag_name"]}
    return list(video_tags | desc_tags)


def _build_content_html(
    video_url: str | None,
    cover: str | None,
    gallery: list[str],
    *,
    video_autoplay: bool,
) -> str:
    parts: list[str] = []
    if video_url:
        parts.append(URLToolkit.make_video_tag_by_url(video_url, autoplay=video_autoplay))
    elif cover:
        parts.append(URLToolkit.make_img_tag_by_url(cover))
    if gallery:
        parts.append("<br>".join(URLToolkit.make_img_tag_by_url(img) for img in gallery))
    return "".join(f" {p}<br>" for p in parts)


def _build_feed_payload(
    post: dict,
    username: str,
    feed_author: dict,
    *,
    video_autoplay: bool,
) -> dict[str, Any]:
    video_url = _extract_video_url(post)
    cover = _extract_cover(post)
    gallery = _extract_image_gallery(post)
    aweme_id = post["aweme_id"]

    payload: dict[str, Any] = {
        "id": f"douyin.user.{username}.{aweme_id}",
        "title": post["item_title"] or "",
        "content_html": _build_content_html(video_url, cover, gallery, video_autoplay=video_autoplay),
        "url": f"https://www.douyin.com/video/{aweme_id}",
        "date_published": int(post["create_time"]),
        "tags": _extract_tags(post),
        "author": feed_author,
    }
    return payload


def _format_published_at(timestamp: int) -> str:
    return pytz.timezone("Asia/Shanghai").localize(datetime.fromtimestamp(timestamp)).strftime("%Y-%m-%dT%H:%M:%S%z")


def _fill_title_from_tags(item: JSONFeedItem) -> None:
    if not item.title and item.tags:
        item.title = "/".join(item.tags)


def to_feeds(username: str, body: dict, *, video_autoplay: bool = True) -> list[JSONFeedItem]:
    if not body["aweme_list"]:
        return []
    author = body["aweme_list"][0]["author"]
    nickname = author["nickname"]
    feed_author = {
        "url": f"https://www.douyin.com/user/{username}",
        "avatar": author["avatar_thumb"]["url_list"][-1],
        "name": nickname,
    }

    feeds: list[dict[str, Any]] = [
        _build_feed_payload(post, username, feed_author, video_autoplay=video_autoplay) for post in body["aweme_list"]
    ]
    feeds.sort(key=lambda x: -x["date_published"])
    for feed in feeds:
        feed["date_published"] = _format_published_at(feed["date_published"])
    leatest_date = feeds[0]["date_published"] if feeds else None

    logger.info(f"[DouyinPlaywright] [to_feeds] user: {nickname} {leatest_date}")
    output = [JSONFeedItem.model_validate(x) for x in feeds]
    for item in output:
        _fill_title_from_tags(item)
    return output
