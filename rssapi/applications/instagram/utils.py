import logging
from datetime import datetime, timezone
from html import escape
from typing import Any

import httpx
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

INSTAGRAM_API_BASE_URL = "https://www.instagram.com"
INSTAGRAM_PROFILE_BASE_URL = "https://www.instagram.com"
INSTAGRAM_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def _instagram_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{INSTAGRAM_PROFILE_BASE_URL}/",
        "User-Agent": INSTAGRAM_USER_AGENT,
        "X-IG-App-ID": settings.instagram.app_id,
    }


def validated_http_url(value: Any) -> str | None:
    if not value:
        return None
    url = str(value)
    try:
        HttpUrlTypeAdapter.validate_python(url)
    except ValidationError:
        return None
    return url


def _upstream_error(status_code: int, username: str) -> HTTPException:
    if status_code == 404:
        return HTTPException(status_code=404, detail=f"Instagram user not found: {username}")
    if status_code == 429:
        return HTTPException(status_code=429, detail="Instagram rate limit exceeded")
    return HTTPException(status_code=502, detail=f"Instagram upstream returned HTTP {status_code}")


async def _fetch_page(
    client: httpx.AsyncClient,
    username: str,
    cursor: str | None,
) -> dict[str, Any]:
    params: dict[str, int | str] = {"count": 12}
    if cursor:
        params["max_id"] = cursor

    try:
        response = await client.get(
            f"/api/v1/feed/user/{username}/username/",
            params=params,
            headers=_instagram_headers(),
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Instagram upstream request timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Failed to request Instagram upstream") from exc

    if response.status_code >= 400:
        raise _upstream_error(response.status_code, username)

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Instagram upstream returned invalid JSON") from exc

    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise HTTPException(status_code=502, detail="Instagram upstream returned an invalid payload")
    if not isinstance(payload.get("items"), list):
        raise HTTPException(status_code=502, detail="Instagram upstream payload is missing items")
    return payload


async def fetch_user_feed_data(
    username: str,
    max_posts: int,
    *,
    base_url: str | None = None,
    timeout: float = 20.0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized_username = username.lower()
    items: list[dict[str, Any]] = []
    seen_item_ids: set[str] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None
    user: dict[str, Any] = {}
    page_count = 0
    max_pages = (max_posts + 11) // 12 + 1

    async with httpx.AsyncClient(
        base_url=base_url or INSTAGRAM_API_BASE_URL,
        follow_redirects=False,
        timeout=httpx.Timeout(timeout),
    ) as client:
        while len(items) < max_posts and page_count < max_pages:
            payload = await _fetch_page(client, normalized_username, cursor)
            page_count += 1
            page_user = payload.get("user")
            if not user and isinstance(page_user, dict):
                user = page_user
            if user.get("is_private"):
                raise HTTPException(status_code=403, detail=f"Instagram profile is private: {normalized_username}")

            for item in payload["items"]:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or item.get("pk") or item.get("code") or "")
                if not item_id or item_id in seen_item_ids:
                    continue
                seen_item_ids.add(item_id)
                items.append(item)
                if len(items) >= max_posts:
                    break

            if len(items) >= max_posts or not payload.get("more_available"):
                break

            next_cursor = payload.get("next_max_id")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                logger.warning(f"Instagram pagination stopped for @{normalized_username}: missing or repeated cursor")
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    return user, items[:max_posts]


@cached(RandomTTLCache(settings.instagram.user_posts_cache_maxsize, settings.instagram.user_posts_cache_ttl))
async def fetch_user_feed_data_by_cache(
    username: str,
    max_posts: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return await fetch_user_feed_data(username, max_posts)


def _image_url(media: dict[str, Any]) -> str | None:
    image_versions = media.get("image_versions2")
    if isinstance(image_versions, dict):
        candidates = image_versions.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, dict) and candidate.get("url"):
                    if url := validated_http_url(candidate["url"]):
                        return url
    display_uri = media.get("display_uri")
    return validated_http_url(display_uri)


def _video_url(media: dict[str, Any]) -> str | None:
    versions = media.get("video_versions")
    if isinstance(versions, list):
        for version in versions:
            if isinstance(version, dict) and version.get("url"):
                if url := validated_http_url(version["url"]):
                    return url
    return None


def _media_html(media: dict[str, Any]) -> tuple[str, list[JSONFeedAttachment]]:
    image_url = _image_url(media)
    media_type = media.get("media_type")
    if media_type == 2:
        video_url = _video_url(media)
        if video_url:
            safe_video_url = escape(video_url, quote=True)
            poster = f' poster="{escape(image_url, quote=True)}"' if image_url else ""
            attachment = JSONFeedAttachment.model_validate({"url": video_url, "mime_type": "video/mp4"})
            return (
                f'<video controls preload="metadata" src="{safe_video_url}"{poster}></video>',
                [attachment],
            )

    if image_url:
        accessibility_caption = media.get("accessibility_caption") or "Instagram image"
        return (
            f'<img src="{escape(image_url, quote=True)}" alt="{escape(str(accessibility_caption), quote=True)}" />',
            [],
        )
    return "", []


def _post_media_html(post: dict[str, Any]) -> tuple[str, list[JSONFeedAttachment]]:
    carousel_media = post.get("carousel_media")
    media = carousel_media if isinstance(carousel_media, list) and carousel_media else [post]
    html_parts: list[str] = []
    attachments: list[JSONFeedAttachment] = []
    for child in media:
        if not isinstance(child, dict):
            continue
        child_html, child_attachments = _media_html(child)
        if child_html:
            html_parts.append(child_html)
        attachments.extend(child_attachments)
    return "".join(html_parts), attachments


def _caption(post: dict[str, Any]) -> str:
    caption = post.get("caption")
    if isinstance(caption, dict) and caption.get("text"):
        return str(caption["text"])
    return ""


def _author(user: dict[str, Any], username: str) -> JSONFeedAuthor:
    resolved_username = str(user.get("username") or username)
    return JSONFeedAuthor(
        name=str(user.get("full_name") or resolved_username),
        url=f"{INSTAGRAM_PROFILE_BASE_URL}/{resolved_username}/",
        avatar=validated_http_url(user.get("profile_pic_url")),
    )


def _published_at(post: dict[str, Any]) -> str | None:
    taken_at = post.get("taken_at")
    if taken_at is None:
        return None
    try:
        return datetime.fromtimestamp(int(taken_at), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def post_to_jsonfeed_item(post: dict[str, Any], profile_user: dict[str, Any], username: str) -> JSONFeedItem:
    code = str(post.get("code") or "")
    post_id = str(post.get("id") or post.get("pk") or code)
    post_url = f"{INSTAGRAM_PROFILE_BASE_URL}/p/{code}/" if code else f"{INSTAGRAM_PROFILE_BASE_URL}/{username}/"
    caption = _caption(post)
    first_caption_line = next((line.strip() for line in caption.splitlines() if line.strip()), "")
    title = first_caption_line or (f"Instagram post {code}" if code else f"@{username} Instagram post")

    media_html, attachments = _post_media_html(post)
    content_parts: list[str] = []
    if caption:
        safe_caption = escape(caption).replace("\n", "<br>")
        content_parts.append(f"<p>{safe_caption}</p>")
    if media_html:
        content_parts.append(f"<div>{media_html}</div>")

    metrics: list[str] = []
    if isinstance(post.get("like_count"), int):
        metrics.append(f"❤️ {post['like_count']}")
    if isinstance(post.get("comment_count"), int):
        metrics.append(f"💬 {post['comment_count']}")
    location = post.get("location")
    if isinstance(location, dict) and location.get("name"):
        metrics.append(f"📍 {escape(str(location['name']))}")
    if metrics:
        content_parts.append(f"<p>{' · '.join(metrics)}</p>")
    if not content_parts:
        content_parts.append("<p>Instagram post</p>")

    item_user = post.get("user")
    author_user = item_user if isinstance(item_user, dict) else profile_user
    image_url = _image_url(post)
    return JSONFeedItem.model_validate(
        {
            "id": post_id,
            "url": post_url,
            "title": title,
            "content_html": "".join(content_parts),
            "summary": caption or None,
            "image": image_url,
            "date_published": _published_at(post),
            "author": _author(author_user, username),
            "attachments": attachments or None,
        }
    )
