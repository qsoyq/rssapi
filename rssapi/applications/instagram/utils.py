import json
import logging
import os
import secrets
from datetime import datetime, timezone
from html import escape
from typing import Any

import httpx
from asyncache import cached
from bs4 import BeautifulSoup
from fastapi import HTTPException, Request
from pydantic import ValidationError

from rssapi.applications.rss.schemas.adapter import HttpUrlTypeAdapter
from rssapi.applications.rss.schemas.rss.jsonfeed import (
    JSONFeedAttachment,
    JSONFeedAuthor,
    JSONFeedItem,
)
from rssapi.core.settings import settings
from rssapi.utils.cache import RandomTTLCache
from rssapi.utils.urls import public_url

logger = logging.getLogger(__name__)

INSTAGRAM_API_BASE_URL = "https://www.instagram.com"
INSTAGRAM_PROFILE_BASE_URL = "https://www.instagram.com"
INSTAGRAM_MEDIA_PATH_PREFIX = "/rss/instagram/media"
INSTAGRAM_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def _post_shortcode(post_id: str) -> str:
    media_id = post_id.split("_", 1)[0]
    if not media_id.isdigit():
        return post_id
    value = int(media_id)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    code = ""
    while value:
        value, digit = divmod(value, 64)
        code = alphabet[digit] + code
    return code or "A"


def _embedded_post(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        post = value.get("shortcode_media")
        if isinstance(post, dict):
            return post
        context = value.get("contextJSON")
        if isinstance(context, str):
            try:
                if post := _embedded_post(json.loads(context)):
                    return post
            except ValueError:
                pass
        for child in value.values():
            if isinstance(child, (dict, list)) and (post := _embedded_post(child)):
                return post
    elif isinstance(value, list):
        for child in value:
            if post := _embedded_post(child):
                return post
    return None


async def fetch_post_media(
    post_id: str,
    *,
    base_url: str | None = None,
    cookies: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    shortcode = _post_shortcode(post_id)
    effective_base_url = base_url or INSTAGRAM_API_BASE_URL
    proxy = None
    if not effective_base_url.startswith("http://"):
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    try:
        async with httpx.AsyncClient(
            base_url=effective_base_url,
            follow_redirects=False,
            timeout=timeout,
            trust_env=False,
            proxy=proxy,
            verify=False,
        ) as client:
            # Browser user agents receive the login shell instead of the public embed payload.
            headers = {"User-Agent": "curl/8.7.1", "Accept": "*/*"}
            if cookies:
                headers["Cookie"] = cookies
            response = await client.get(f"/p/{shortcode}/embed/captioned/", headers=headers)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Instagram upstream request timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Failed to request Instagram upstream") from exc
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Instagram post not found: {post_id}")
    if response.status_code in (301, 302, 303, 307, 308, 401):
        raise _authentication_required()
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code if response.status_code == 429 else 502,
            detail=f"Instagram upstream returned HTTP {response.status_code}",
        )
    soup = BeautifulSoup(response.text, "html.parser")
    for script in soup.find_all("script"):
        source = script.get_text()
        if script.get("type") != "application/json":
            # ServerJS wraps a JSON object in JavaScript; decode only the object, never execute it.
            marker = "s.handle("
            if marker not in source:
                continue
            source = source.split(marker, 1)[1]
        try:
            payload, _ = json.JSONDecoder().raw_decode(source.lstrip())
            post = _embedded_post(payload)
        except ValueError:
            continue
        if post is None or post.get("shortcode") != shortcode:
            continue
        if post_id.split("_", 1)[0].isdigit() and str(post.get("id")) != post_id.split("_", 1)[0]:
            raise HTTPException(status_code=502, detail="Instagram upstream returned a different post")
        edges = post.get("edge_sidecar_to_children", {}).get("edges", [])
        children = [edge["node"] for edge in edges if isinstance(edge, dict) and isinstance(edge.get("node"), dict)]
        media_items = children or [post]
        media = {
            "carousel_media": [
                {
                    "media_type": 2 if child.get("is_video") else 1,
                    "display_uri": child.get("display_url"),
                    "video_versions": [{"url": child.get("video_url")}],
                }
                for child in media_items
            ]
        }
        if any(child["media_type"] == 2 and not _video_url(child) for child in media["carousel_media"]):
            return await fetch_graphql_post_media(
                post_id, base_url=effective_base_url, cookies=cookies, timeout=timeout
            )
        return media
    raise HTTPException(status_code=502, detail="Instagram upstream page is missing post media")


async def fetch_graphql_post_media(
    post_id: str,
    *,
    base_url: str | None = None,
    cookies: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    # Query and doc_id source: https://github.com/shamu4life/mbedfx/blob/main/src/platforms/instagram/fetch.ts
    # Verified cookie-free with DeG_Vlzp2O7 on 2026-10-06. Query IDs may rotate independently of CDN URLs.
    shortcode = _post_shortcode(post_id)
    lsd = secrets.token_hex(12)
    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-FB-Friendly-Name": "PolarisPostRootQuery",
        "X-FB-LSD": lsd,
    }
    if cookies:
        headers["Cookie"] = cookies
    effective_base_url = base_url or INSTAGRAM_API_BASE_URL
    proxy = None
    if not effective_base_url.startswith("http://"):
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    try:
        async with httpx.AsyncClient(
            base_url=effective_base_url,
            follow_redirects=False,
            timeout=timeout,
            trust_env=False,
            proxy=proxy,
            verify=False,
        ) as client:
            response = await client.post(
                "/graphql/query/",
                headers=headers,
                data={
                    "doc_id": settings.instagram.graphql_doc_id,
                    "lsd": lsd,
                    "server_timestamps": "true",
                    "variables": json.dumps(
                        {
                            "shortcode": shortcode,
                            "__relay_internal__pv__PolarisAIGMMediaWebLabelEnabledrelayprovider": False,
                        }
                    ),
                },
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Instagram upstream request timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Failed to request Instagram upstream") from exc
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Instagram post not found: {post_id}")
    if response.status_code in (301, 302, 303, 307, 308, 401):
        raise _authentication_required()
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code if response.status_code == 429 else 502,
            detail=f"Instagram upstream returned HTTP {response.status_code}",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Instagram upstream returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("errors"):
        raise HTTPException(status_code=502, detail="Instagram GraphQL query failed")
    data = payload.get("data")
    root = data.get("xdt_api__v1__media__shortcode__web_info") if isinstance(data, dict) else None
    items = root.get("items") if isinstance(root, dict) else None
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise HTTPException(status_code=502, detail="Instagram upstream payload is missing post media")
    post = items[0]
    expected_id = post_id.split("_", 1)[0]
    actual_id = str(post.get("id") or post.get("pk") or "").split("_", 1)[0]
    if post.get("code") != shortcode or (expected_id.isdigit() and actual_id != expected_id):
        raise HTTPException(status_code=502, detail="Instagram upstream returned a different post")
    media_items = _post_media(post)
    if any(not isinstance(child, dict) for child in media_items):
        raise HTTPException(status_code=502, detail="Instagram upstream returned invalid post media")
    return {"carousel_media": media_items}


@cached(RandomTTLCache(256, 60))
async def fetch_post_media_by_cache(post_id: str) -> dict[str, Any]:
    return await fetch_post_media(post_id)


def _instagram_headers(cookies: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{INSTAGRAM_PROFILE_BASE_URL}/",
        "User-Agent": INSTAGRAM_USER_AGENT,
        "X-IG-App-ID": settings.instagram.app_id,
    }
    if cookies:
        headers["Cookie"] = cookies
    return headers


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


def _authentication_required() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=(
            "Instagram authentication required; provide cookies or X-Instagram-Cookie "
            "containing ds_user_id and sessionid"
        ),
    )


async def _fetch_page(
    client: httpx.AsyncClient,
    username: str,
    cursor: str | None,
    cookies: str | None = None,
) -> dict[str, Any]:
    params: dict[str, int | str] = {"count": 12}
    if cursor:
        params["max_id"] = cursor

    try:
        response = await client.get(
            f"/api/v1/feed/user/{username}/username/",
            params=params,
            headers=_instagram_headers(cookies),
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Instagram upstream request timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Failed to request Instagram upstream") from exc

    if response.status_code == 302:
        raise _authentication_required()
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
    if not isinstance(payload.get("user"), dict):
        raise _authentication_required()
    return payload


async def fetch_user_feed_data(
    username: str,
    max_posts: int,
    *,
    base_url: str | None = None,
    timeout: float = 20.0,
    cookies: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized_username = username.lower()
    items: list[dict[str, Any]] = []
    seen_item_ids: set[str] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None
    user: dict[str, Any] = {}
    page_count = 0
    max_pages = (max_posts + 11) // 12 + 1

    effective_base_url = base_url or INSTAGRAM_API_BASE_URL
    proxy = None
    if not effective_base_url.startswith("http://"):
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    async with httpx.AsyncClient(
        base_url=effective_base_url,
        follow_redirects=False,
        timeout=httpx.Timeout(timeout),
        # Avoid an unrelated ALL_PROXY=socks5 environment value; Instagram is reachable directly.
        trust_env=False,
        proxy=proxy,
        verify=False,
    ) as client:
        while len(items) < max_posts and page_count < max_pages:
            payload = await _fetch_page(client, normalized_username, cursor, cookies)
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


def _media_url(req: Request, username: str, post_id: str, index: int) -> str:
    return public_url(req, f"{settings.api_prefix}{INSTAGRAM_MEDIA_PATH_PREFIX}/{username}/{post_id}/{index}")


def _post_media(post: dict[str, Any]) -> list[dict[str, Any]]:
    carousel_media = post.get("carousel_media")
    return carousel_media if isinstance(carousel_media, list) and carousel_media else [post]


def _media_html(
    media: dict[str, Any],
    *,
    rendered_url: str | None = None,
) -> tuple[str, list[JSONFeedAttachment]]:
    image_url = _image_url(media)
    media_type = media.get("media_type")
    if media_type == 2:
        video_url = _video_url(media)
        if video_url:
            effective_video_url = rendered_url or video_url
            safe_video_url = escape(effective_video_url, quote=True)
            poster = f' poster="{escape(image_url, quote=True)}"' if image_url else ""
            attachment = JSONFeedAttachment.model_validate({"url": effective_video_url, "mime_type": "video/mp4"})
            return (
                f'<video controls preload="metadata" src="{safe_video_url}"{poster}></video>',
                [attachment],
            )

    if image_url:
        accessibility_caption = media.get("accessibility_caption") or "Instagram image"
        effective_image_url = rendered_url or image_url
        return (
            f'<img src="{escape(effective_image_url, quote=True)}" alt="{escape(str(accessibility_caption), quote=True)}" />',
            [],
        )
    return "", []


def _post_media_html(
    post: dict[str, Any],
    *,
    req: Request | None = None,
    username: str = "",
    post_id: str = "",
) -> tuple[str, list[JSONFeedAttachment]]:
    media = _post_media(post)
    html_parts: list[str] = []
    attachments: list[JSONFeedAttachment] = []
    for index, child in enumerate(media):
        if not isinstance(child, dict):
            continue
        rendered_url = _media_url(req, username, post_id, index) if req is not None and post_id else None
        child_html, child_attachments = _media_html(child, rendered_url=rendered_url)
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


def post_to_jsonfeed_item(
    post: dict[str, Any],
    profile_user: dict[str, Any],
    username: str,
    *,
    req: Request | None = None,
) -> JSONFeedItem:
    code = str(post.get("code") or "")
    post_id = str(post.get("id") or post.get("pk") or code)
    post_url = f"{INSTAGRAM_PROFILE_BASE_URL}/p/{code}/" if code else f"{INSTAGRAM_PROFILE_BASE_URL}/{username}/"
    caption = _caption(post)
    first_caption_line = next((line.strip() for line in caption.splitlines() if line.strip()), "")
    title = first_caption_line or (f"Instagram post {code}" if code else f"@{username} Instagram post")

    media_html, attachments = _post_media_html(post, req=req, username=username, post_id=post_id)
    content_parts: list[str] = []
    if media_html:
        content_parts.append(f"<div>{media_html}</div>")

    body_parts: list[str] = []
    if caption:
        safe_caption = escape(caption).replace("\n", "<br>")
        body_parts.append(f"<p>{safe_caption}</p>")

    metrics: list[str] = []
    if isinstance(post.get("like_count"), int):
        metrics.append(f"❤️ {post['like_count']}")
    if isinstance(post.get("comment_count"), int):
        metrics.append(f"💬 {post['comment_count']}")
    location = post.get("location")
    if isinstance(location, dict) and location.get("name"):
        metrics.append(f"📍 {escape(str(location['name']))}")
    if metrics:
        body_parts.append(f"<p>{' · '.join(metrics)}</p>")
    if body_parts:
        content_parts.append(f"<details><summary>查看正文</summary>{''.join(body_parts)}</details>")
    if not content_parts:
        content_parts.append("<p>Instagram post</p>")

    item_user = post.get("user")
    author_user = item_user if isinstance(item_user, dict) else profile_user
    image_url = _image_url(post)
    rendered_image_url = (
        _media_url(req, username, post_id, 0) if req is not None and image_url and post_id else image_url
    )
    return JSONFeedItem.model_validate(
        {
            "id": post_id,
            "url": post_url,
            "title": title,
            "content_html": "".join(content_parts),
            "summary": caption or None,
            "image": rendered_image_url,
            "date_published": _published_at(post),
            "author": _author(author_user, username),
            "attachments": attachments or None,
        }
    )
