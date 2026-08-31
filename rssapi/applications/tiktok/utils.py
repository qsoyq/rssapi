import asyncio
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from html import escape
from typing import Any
from urllib.parse import urlparse

import curl_cffi
from asyncache import cached
from fastapi import HTTPException
from pydantic import ValidationError

from rssapi.applications.rss.schemas.adapter import HttpUrlTypeAdapter
from rssapi.applications.rss.schemas.rss.jsonfeed import (
    JSONFeedAttachment,
    JSONFeedAuthor,
    JSONFeedItem,
)
from rssapi.core.settings import settings
from rssapi.utils.cache import RandomTTLCache

logger = logging.getLogger(__name__)
requests = curl_cffi.requests
RequestsError = curl_cffi.requests.errors.RequestsError

TIKTOK_BASE_URL = "https://www.tiktok.com"
TIKTOK_FAVICON = "https://www.tiktok.com/favicon.ico"
TIKTOK_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
TIKTOK_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": TIKTOK_USER_AGENT,
}

_fetch_semaphore = asyncio.Semaphore(settings.tiktok.fetch_concurrency)
_SIGI_STATE_RE = re.compile(r'<script[^>]+id=["\']SIGI_STATE["\'][^>]*>(.*?)</script>', re.DOTALL)
_EMPTY_PAGE_LOOKBACK = 12
_EMPTY_PAGE_STEP_MS = 7 * 24 * 60 * 60 * 1000


class TikTokRestrictedError(Exception):
    """TikTok returned a challenge, empty body, or otherwise blocked response."""


def normalize_username(username: str) -> str:
    return username.removeprefix("@").lower()


def validated_http_url(value: Any) -> str | None:
    if not value:
        return None
    url = str(value)
    if url.startswith("//"):
        url = f"https:{url}"
    try:
        HttpUrlTypeAdapter.validate_python(url)
    except ValidationError:
        return None
    return url


def _urls_from_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [validated] if (validated := validated_http_url(value)) else []
    if not isinstance(value, dict):
        return []
    urls: list[str] = []
    url_list = value.get("urlList") or value.get("UrlList")
    if isinstance(url_list, list):
        for url in url_list:
            if validated := validated_http_url(url):
                urls.append(validated)
    for key in ("url", "uri"):
        if validated := validated_http_url(value.get(key)):
            urls.append(validated)
    return list(dict.fromkeys(urls))


def _url_from_value(value: Any) -> str | None:
    return next(iter(_urls_from_value(value)), None)


def avatar_url(user: dict[str, Any]) -> str | None:
    for key in ("avatarLarger", "avatarMedium", "avatarThumb"):
        if url := _url_from_value(user.get(key)):
            return url
    return None


def _creator_params(username: str, sec_uid: str, device_id: str, cursor: int, count: int) -> dict[str, str]:
    profile_url = f"{TIKTOK_BASE_URL}/@{username}"
    return {
        "aid": "1988",
        "app_language": "en",
        "app_name": "tiktok_web",
        "browser_language": "en-US",
        "browser_name": "Mozilla",
        "browser_online": "true",
        "browser_platform": "Win32",
        "browser_version": "5.0 (Windows)",
        "channel": "tiktok_web",
        "cookie_enabled": "true",
        "count": str(count),
        "cursor": str(cursor),
        "device_id": device_id,
        "device_platform": "web_pc",
        "focus_state": "true",
        "from_page": "user",
        "history_len": "2",
        "is_fullscreen": "false",
        "is_page_visible": "true",
        "language": "en",
        "os": "windows",
        "priority_region": "",
        "referer": profile_url,
        "region": "US",
        "screen_height": "1080",
        "screen_width": "1920",
        "secUid": sec_uid,
        "type": "1",
        "tz_name": "UTC",
        "verifyFp": "verify_abcdef1",
        "webcast_language": "en",
    }


def _response_payload(response: Any, username: str) -> dict[str, Any]:
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"TikTok user not found: {username}")
    if response.status_code == 429:
        raise HTTPException(status_code=429, detail="TikTok rate limit exceeded")
    if response.status_code >= 400:
        raise TikTokRestrictedError(f"TikTok upstream returned HTTP {response.status_code}")
    if not response.content:
        raise TikTokRestrictedError("TikTok upstream returned an empty response")
    content_type = response.headers.get("content-type", "").lower()
    if "json" not in content_type:
        raise TikTokRestrictedError("TikTok upstream returned a challenge page")
    try:
        payload = response.json()
    except ValueError as exc:
        raise TikTokRestrictedError("TikTok upstream returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise TikTokRestrictedError("TikTok upstream returned an invalid payload")
    return payload


def _request_json(
    session: Any,
    base_url: str,
    path: str,
    params: dict[str, str],
    username: str,
) -> dict[str, Any]:
    response = session.get(f"{base_url}{path}", params=params)
    return _response_payload(response, username)


def _find_profile_user(value: Any, username: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        unique_id = value.get("uniqueId")
        sec_uid = value.get("secUid")
        if isinstance(unique_id, str) and unique_id.lower() == username and isinstance(sec_uid, str) and sec_uid:
            return value
        for child in value.values():
            if user := _find_profile_user(child, username):
                return user
    elif isinstance(value, list):
        for child in value:
            if user := _find_profile_user(child, username):
                return user
    return None


def _profile_user_from_live_page(response: Any, username: str) -> dict[str, Any]:
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"TikTok user not found: {username}")
    if response.status_code == 429:
        raise HTTPException(status_code=429, detail="TikTok rate limit exceeded")
    if response.status_code >= 400:
        raise TikTokRestrictedError(f"TikTok profile returned HTTP {response.status_code}")
    match = _SIGI_STATE_RE.search(response.text)
    if not match:
        raise HTTPException(status_code=502, detail="TikTok profile is missing public hydration data")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise TikTokRestrictedError("TikTok profile returned invalid hydration data") from exc
    user = _find_profile_user(payload, username)
    if not user:
        raise HTTPException(status_code=404, detail=f"TikTok user not found: {username}")
    if user.get("privateAccount") or user.get("secret"):
        raise HTTPException(status_code=403, detail=f"TikTok profile is private: {username}")
    return user


def _session_kwargs(timeout: float, proxy: str | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "headers": TIKTOK_HEADERS,
        "impersonate": "chrome136",
        "timeout": timeout,
    }
    if proxy:
        kwargs["proxy"] = proxy
    return kwargs


def _fetch_posts_with_session(
    session: Any,
    username: str,
    sec_uid: str,
    max_posts: int,
    *,
    base_url: str,
) -> list[dict[str, Any]]:
    device_id = str(7_250_000_000_000_000_000 + secrets.randbelow(75_099_899_999_994_578))
    posts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    cursor = int(time.time() * 1000)
    max_pages = (max_posts + 14) // 15 + _EMPTY_PAGE_LOOKBACK
    for _ in range(max_pages):
        count = min(15, max_posts - len(posts))
        payload = _request_json(
            session,
            base_url,
            "/api/creator/item_list/",
            _creator_params(username, sec_uid, device_id, cursor, count),
            username,
        )
        status_code = payload.get("statusCode")
        if status_code not in (None, 0):
            raise TikTokRestrictedError(f"TikTok post list returned status {status_code}")
        raw_item_list = payload.get("itemList", [])
        if not isinstance(raw_item_list, list):
            raise TikTokRestrictedError("TikTok post list returned invalid itemList")
        item_list = [item for item in raw_item_list if isinstance(item, dict)]
        for item in item_list:
            item_id = str(item.get("id") or "")
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            posts.append(item)
            if len(posts) >= max_posts:
                break
        if len(posts) >= max_posts:
            break
        if item_list:
            timestamps = [item.get("createTime") for item in item_list]
            valid_timestamps = [
                int(value) for value in timestamps if isinstance(value, (int, str)) and str(value).isdigit()
            ]
            if valid_timestamps:
                next_cursor = min(valid_timestamps) * 1000
                cursor = next_cursor if next_cursor < cursor else cursor - _EMPTY_PAGE_STEP_MS
            else:
                cursor -= _EMPTY_PAGE_STEP_MS
        else:
            cursor -= _EMPTY_PAGE_STEP_MS
        if not payload.get("hasMorePrevious"):
            break

    if not posts:
        raise HTTPException(status_code=403, detail=f"TikTok profile has no accessible public posts: {username}")
    return posts[:max_posts]


def _fetch_attempt(
    username: str,
    max_posts: int,
    *,
    base_url: str,
    timeout: float,
    proxy: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with requests.Session(**_session_kwargs(timeout, proxy)) as session:
        profile_response = session.get(f"{base_url}/@{username}/live")
        user = _profile_user_from_live_page(profile_response, username)
        posts = _fetch_posts_with_session(session, username, str(user["secUid"]), max_posts, base_url=base_url)
        return user, posts


def _fetch_user_posts_sync(
    username: str,
    max_posts: int,
    *,
    base_url: str,
    timeout: float,
    proxy: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    last_restricted_error: TikTokRestrictedError | None = None
    for attempt in range(2):
        try:
            return _fetch_attempt(
                username,
                max_posts,
                base_url=base_url,
                timeout=timeout,
                proxy=proxy,
            )
        except HTTPException:
            raise
        except TikTokRestrictedError as exc:
            last_restricted_error = exc
            logger.warning(f"TikTok request attempt {attempt + 1} failed for @{username}: {exc}")
        except RequestsError as exc:
            message = str(exc).lower()
            if "timeout" in message or "timed out" in message:
                raise HTTPException(status_code=504, detail="TikTok upstream request timed out") from exc
            raise HTTPException(status_code=502, detail="Failed to request TikTok upstream") from exc
    detail = str(last_restricted_error or "TikTok upstream request was restricted")
    raise HTTPException(status_code=502, detail=detail)


def _fetch_posts_by_sec_uid_sync(
    username: str,
    sec_uid: str,
    max_posts: int,
    *,
    base_url: str,
    timeout: float,
    proxy: str | None,
) -> list[dict[str, Any]]:
    last_restricted_error: TikTokRestrictedError | None = None
    for attempt in range(2):
        try:
            with requests.Session(**_session_kwargs(timeout, proxy)) as session:
                return _fetch_posts_with_session(session, username, sec_uid, max_posts, base_url=base_url)
        except HTTPException:
            raise
        except TikTokRestrictedError as exc:
            last_restricted_error = exc
            logger.warning(f"TikTok post request attempt {attempt + 1} failed for @{username}: {exc}")
        except RequestsError as exc:
            message = str(exc).lower()
            if "timeout" in message or "timed out" in message:
                raise HTTPException(status_code=504, detail="TikTok upstream request timed out") from exc
            raise HTTPException(status_code=502, detail="Failed to request TikTok upstream") from exc
    detail = str(last_restricted_error or "TikTok upstream request was restricted")
    raise HTTPException(status_code=502, detail=detail)


async def fetch_user_posts(
    username: str,
    max_posts: int,
    *,
    base_url: str | None = None,
    timeout: float | None = None,
    proxy: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized_username = normalize_username(username)
    async with _fetch_semaphore:
        return await asyncio.to_thread(
            _fetch_user_posts_sync,
            normalized_username,
            max_posts,
            base_url=base_url or TIKTOK_BASE_URL,
            timeout=timeout or settings.tiktok.request_timeout,
            proxy=proxy if proxy is not None else settings.tiktok.proxy,
        )


async def fetch_posts_by_sec_uid(
    username: str,
    sec_uid: str,
    max_posts: int,
    *,
    base_url: str | None = None,
    timeout: float | None = None,
    proxy: str | None = None,
) -> list[dict[str, Any]]:
    normalized_username = normalize_username(username)
    async with _fetch_semaphore:
        return await asyncio.to_thread(
            _fetch_posts_by_sec_uid_sync,
            normalized_username,
            sec_uid,
            max_posts,
            base_url=base_url or TIKTOK_BASE_URL,
            timeout=timeout or settings.tiktok.request_timeout,
            proxy=proxy if proxy is not None else settings.tiktok.proxy,
        )


@cached(RandomTTLCache(settings.tiktok.user_posts_cache_maxsize, settings.tiktok.user_posts_cache_ttl))
async def fetch_user_posts_by_cache(
    username: str,
    max_posts: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return await fetch_user_posts(username, max_posts)


@cached(RandomTTLCache(settings.tiktok.user_posts_cache_maxsize, settings.tiktok.user_posts_cache_ttl))
async def fetch_posts_by_sec_uid_by_cache(
    username: str,
    sec_uid: str,
    max_posts: int,
) -> list[dict[str, Any]]:
    return await fetch_posts_by_sec_uid(username, sec_uid, max_posts)


def _published_at(item: dict[str, Any]) -> str | None:
    created_at = item.get("createTime")
    if not isinstance(created_at, (int, str)):
        return None
    try:
        return datetime.fromtimestamp(int(created_at), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def video_media(item: dict[str, Any]) -> tuple[str | None, str | None]:
    video = item.get("video")
    if not isinstance(video, dict):
        return None, None
    bitrate_urls: list[str] = []
    bitrate_info = video.get("bitrateInfo")
    if isinstance(bitrate_info, list):
        for bitrate in bitrate_info:
            if not isinstance(bitrate, dict):
                continue
            bitrate_urls.extend(_urls_from_value(bitrate.get("PlayAddr") or bitrate.get("playAddr")))
    playable_bitrate_url = next(
        (url for url in bitrate_urls if urlparse(url).hostname == "www.tiktok.com"),
        None,
    )
    video_url = (
        playable_bitrate_url or _url_from_value(video.get("playAddr")) or _url_from_value(video.get("downloadAddr"))
    )
    cover_url = _url_from_value(video.get("cover")) or _url_from_value(video.get("dynamicCover"))
    return video_url, cover_url


def _image_urls(item: dict[str, Any]) -> list[str]:
    image_post = item.get("imagePost")
    if not isinstance(image_post, dict) or not isinstance(image_post.get("images"), list):
        return []
    urls: list[str] = []
    for image in image_post["images"]:
        if not isinstance(image, dict):
            continue
        if url := _url_from_value(image.get("imageURL")):
            urls.append(url)
    return urls


def _tags(item: dict[str, Any]) -> list[str] | None:
    text_extra = item.get("textExtra")
    if not isinstance(text_extra, list):
        return None
    tags = [str(value["hashtagName"]) for value in text_extra if isinstance(value, dict) and value.get("hashtagName")]
    return list(dict.fromkeys(tags)) or None


def post_to_jsonfeed_item(
    item: dict[str, Any],
    profile_user: dict[str, Any],
    username: str,
    *,
    media_url: str | None = None,
) -> JSONFeedItem:
    item_id = str(item.get("id") or "")
    description = str(item.get("desc") or "")
    title = next((line.strip() for line in description.splitlines() if line.strip()), f"TikTok post {item_id}")
    item_author = item.get("author")
    author_user = item_author if isinstance(item_author, dict) else profile_user
    resolved_username = str(author_user.get("uniqueId") or username)
    display_name = str(author_user.get("nickname") or resolved_username)
    post_url = f"{TIKTOK_BASE_URL}/@{resolved_username}/video/{item_id}"
    video_url, cover_url = video_media(item)
    image_urls = _image_urls(item)

    media_html: list[str] = []
    attachments: list[JSONFeedAttachment] = []
    if video_url:
        rendered_video_url = media_url or video_url
        poster = f' poster="{escape(cover_url, quote=True)}"' if cover_url else ""
        media_html.append(
            f'<video controls preload="metadata" src="{escape(rendered_video_url, quote=True)}"{poster}></video>'
        )
        attachments.append(JSONFeedAttachment.model_validate({"url": rendered_video_url, "mime_type": "video/mp4"}))
    for image_url in image_urls:
        media_html.append(f'<img src="{escape(image_url, quote=True)}" loading="lazy">')
        attachments.append(JSONFeedAttachment.model_validate({"url": image_url, "mime_type": "image/jpeg"}))

    body_html: list[str] = []
    if description:
        body_html.append(f"<p>{escape(description).replace(chr(10), '<br>')}</p>")
    stats = item.get("stats")
    if isinstance(stats, dict):
        metrics: list[str] = []
        for key, icon in (("diggCount", "❤️"), ("commentCount", "💬"), ("shareCount", "↗️"), ("playCount", "▶️")):
            if isinstance(stats.get(key), int):
                metrics.append(f"{icon} {stats[key]}")
        if metrics:
            body_html.append(f"<p>{' · '.join(metrics)}</p>")

    content_parts: list[str] = []
    if media_html:
        content_parts.append(f"<div>{''.join(media_html)}</div>")
    if body_html:
        content_parts.append(f"<details><summary>查看正文</summary>{''.join(body_html)}</details>")
    if not content_parts:
        content_parts.append("<p>TikTok post</p>")

    return JSONFeedItem.model_validate(
        {
            "id": item_id,
            "url": post_url,
            "title": title,
            "content_html": "".join(content_parts),
            "summary": description or None,
            "image": cover_url or (image_urls[0] if image_urls else None),
            "date_published": _published_at(item),
            "tags": _tags(item),
            "author": JSONFeedAuthor(
                name=display_name,
                url=f"{TIKTOK_BASE_URL}/@{resolved_username}",
                avatar=avatar_url(author_user),
            ),
            "attachments": attachments or None,
        }
    )
