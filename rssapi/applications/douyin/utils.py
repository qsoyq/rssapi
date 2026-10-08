import logging
import re
from datetime import datetime
from html import escape
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedAuthor, JSONFeedItem

DOUYIN_BASE_URL = "https://www.douyin.com"
TOPIC_PAGE_SIZE = 15


def resolve_cookie(cookies: str | None, cookie_header: str | None) -> str:
    effective = cookie_header if cookie_header is not None else cookies
    if effective is None or not effective.strip():
        raise HTTPException(401, detail="cookies or X-Douyin-Cookie are required")
    return effective.strip()


def parse_cookies(cookie: str) -> dict[str, str]:
    result = {}
    for part in cookie.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            result[name.strip()] = value.strip()
    return result


def playwright_cookies(cookie: str, url: str) -> list[dict[str, str]]:
    return [{"name": name, "value": value, "url": url} for name, value in parse_cookies(cookie).items()]


def normalize_topic(topic: str) -> str:
    topic = topic.strip().removeprefix("#").strip()
    if not topic:
        raise HTTPException(422, detail="话题不能为空")
    return topic


def topic_page_url(topic: str) -> str:
    return f"{DOUYIN_BASE_URL}/jingxuan/search/{quote(f'#{topic}', safe='')}"


def _urls(value: Any) -> list[str]:
    if not isinstance(value, dict) or not isinstance(value.get("url_list"), list):
        return []
    return [
        f"https:{url}" if url.startswith("//") else url
        for url in value["url_list"]
        if isinstance(url, str) and url.startswith(("https://", "http://", "//"))
    ]


def post_hashtags(post: dict[str, Any]) -> list[str]:
    entries = post.get("text_extra")
    if not isinstance(entries, list):
        return []
    return list(
        dict.fromkeys(
            entry["hashtag_name"]
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("hashtag_name"), str) and entry["hashtag_name"]
        )
    )


def post_matches_topic(topic: str, post: dict[str, Any]) -> bool:
    return any(topic in hashtag for hashtag in post_hashtags(post))


def topic_posts_to_feeds(topic: str, posts: list[dict[str, Any]]) -> list[JSONFeedItem]:
    items: dict[str, tuple[int, JSONFeedItem]] = {}
    for post in posts:
        tags = post_hashtags(post)
        aweme_id = post.get("aweme_id")
        if not post_matches_topic(topic, post) or not aweme_id:
            continue
        try:
            timestamp = int(post["create_time"])
            published_at = datetime.fromtimestamp(timestamp, ZoneInfo("Asia/Shanghai")).isoformat()
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        author = post.get("author") or {}
        if not isinstance(author, dict):
            author = {}
        avatars = _urls(author.get("avatar_thumb"))
        sec_uid = author.get("sec_uid")
        feed_author = JSONFeedAuthor(
            name=author.get("nickname") or None,
            url=f"{DOUYIN_BASE_URL}/user/{quote(str(sec_uid), safe='')}" if sec_uid else None,
            avatar=avatars[-1] if avatars else None,
        )
        video = post.get("video") or {}
        if not isinstance(video, dict):
            video = {}
        cover_urls = _urls(video.get("cover")) or _urls(video.get("origin_cover"))
        cover = cover_urls[-1] if cover_urls else None
        video_urls: list[str] = []
        for bitrate in video.get("bit_rate") or []:
            if isinstance(bitrate, dict):
                video_urls = _urls(bitrate.get("play_addr"))
                if video_urls:
                    break
        video_urls = video_urls or _urls(video.get("play_addr"))
        gallery = [urls[0] for image in post.get("images") or [] if (urls := _urls(image))]
        desc = str(post.get("desc") or "")
        content = [f"<p>{escape(desc)}</p>"] if desc else []
        if gallery:
            content.extend(f'<img src="{escape(url, quote=True)}">' for url in gallery)
        elif video_urls:
            poster = f' poster="{escape(cover, quote=True)}"' if cover else ""
            content.append(
                f'<video controls preload="none"{poster} src="{escape(video_urls[-1], quote=True)}"></video>'
            )
        elif cover:
            content.append(f'<img src="{escape(cover, quote=True)}">')
        item = JSONFeedItem.model_validate(
            {
                "id": f"douyin.aweme.{aweme_id}",
                "url": f"{DOUYIN_BASE_URL}/video/{quote(str(aweme_id), safe='')}",
                "title": str(post.get("item_title") or desc or f"#{topic}"),
                "content_text": desc,
                "content_html": "\n".join(content),
                "date_published": published_at,
                "image": cover or (gallery[0] if gallery else None),
                "author": feed_author,
                "tags": tags,
            }
        )
        items.setdefault(str(aweme_id), (timestamp, item))
    return [item for _, item in sorted(items.values(), key=lambda value: value[0], reverse=True)]


def redact_credentials(text: str) -> str:
    text = re.sub(
        r"(/rss/douyin/user/[^/?\s\"']+/)[^/?\s\"']+",
        r"\1<redacted>",
        text,
    )
    text = re.sub(
        r"(?i)(\b(?:cookie|x-douyin-cookie)[\"']?\s*:\s*)([\"'])(.*?)\2",
        r"\1'<redacted>'",
        text,
    )
    return re.sub(
        r"(?i)(\b(?:cookies|sessionid_ss|sessionid|msToken|ttwid|uifid|a_bogus|sid_tt|sid_guard|"
        r"verifyFp|fp|x-secsdk-web-signature)=)[^&;\s\"']*",
        r"\1<redacted>",
        text,
    )


class DouyinCredentialLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_credentials(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_credentials(str(value)) if isinstance(value, (str, httpx.URL)) else value
                for value in record.args
            )
        return True


def install_log_redaction(playwright_logger: logging.Logger) -> None:
    for logger in (logging.getLogger("uvicorn.access"), logging.getLogger("httpx"), playwright_logger):
        if not any(isinstance(filter_, DouyinCredentialLogFilter) for filter_ in logger.filters):
            logger.addFilter(DouyinCredentialLogFilter())
