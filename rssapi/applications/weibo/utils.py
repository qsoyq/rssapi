import logging
from datetime import datetime
from html import escape
from typing import Any

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from fastapi import HTTPException, Request
from pydantic import ValidationError

from rssapi.applications.rss.schemas.adapter import HttpUrlTypeAdapter
from rssapi.applications.rss.schemas.rss.jsonfeed import (
    JSONFeed,
    JSONFeedAttachment,
    JSONFeedAuthor,
    JSONFeedItem,
)

logger = logging.getLogger(__name__)

WEIBO_API_BASE_URL = "https://weibo.com"
WEIBO_PROFILE_BASE_URL = "https://weibo.com"
WEIBO_FAVICON = "https://weibo.com/favicon.ico"
WEIBO_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def extract_sub_cookie(cookies: str | None) -> str | None:
    """Return the minimum Weibo credential accepted by the AJAX endpoints."""
    if not cookies:
        return None

    for part in cookies.split(";"):
        name, separator, value = part.strip().partition("=")
        if name == "SUB" and separator and value:
            return f"SUB={value}"
    return None


def validated_http_url(value: Any) -> str | None:
    if not value:
        return None
    url = str(value)
    try:
        HttpUrlTypeAdapter.validate_python(url)
    except ValidationError:
        return None
    return url


def _authentication_required() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Weibo authentication required; provide cookies or X-Weibo-Cookie containing SUB",
    )


def _upstream_error(status_code: int, uid: int) -> HTTPException:
    if status_code == 404:
        return HTTPException(status_code=404, detail=f"Weibo user not found: {uid}")
    if status_code in {429, 432}:
        return HTTPException(status_code=429, detail="Weibo upstream rate limited or rejected the request")
    return HTTPException(status_code=502, detail=f"Weibo upstream returned HTTP {status_code}")


def _weibo_headers(uid: int, sub_cookie: str) -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{WEIBO_PROFILE_BASE_URL}/u/{uid}",
        "User-Agent": WEIBO_USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": sub_cookie,
    }


async def _fetch_json(
    client: httpx.AsyncClient,
    path: str,
    uid: int,
    sub_cookie: str,
    params: dict[str, int | str],
) -> dict[str, Any]:
    try:
        response = await client.get(path, params=params, headers=_weibo_headers(uid, sub_cookie))
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Weibo upstream request timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Failed to request Weibo upstream") from exc

    if response.status_code >= 400:
        raise _upstream_error(response.status_code, uid)

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Weibo upstream returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Weibo upstream returned an invalid payload")
    if payload.get("ok") == -100:
        raise _authentication_required()
    if payload.get("ok") != 1:
        raise HTTPException(status_code=502, detail="Weibo upstream returned an invalid payload")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Weibo upstream payload is missing data")
    return data


async def _fetch_long_text(
    client: httpx.AsyncClient,
    uid: int,
    post: dict[str, Any],
    sub_cookie: str,
) -> dict[str, Any]:
    if not post.get("isLongText"):
        return post

    post_identifier = str(post.get("mblogid") or post.get("idstr") or post.get("id") or "")
    if not post_identifier:
        return post

    try:
        data = await _fetch_json(
            client,
            "/ajax/statuses/longtext",
            uid,
            sub_cookie,
            {"id": post_identifier},
        )
    except HTTPException as exc:
        logger.warning(f"Weibo long text fetch failed: uid={uid} post={post_identifier} status={exc.status_code}")
        return post

    long_text = data.get("longTextContent")
    if not isinstance(long_text, str) or not long_text.strip():
        return post

    updated_post = {**post}
    updated_post["text_raw"] = _html_to_text(long_text)
    return updated_post


async def _resolve_long_text(
    client: httpx.AsyncClient,
    uid: int,
    post: dict[str, Any],
    sub_cookie: str,
) -> dict[str, Any]:
    resolved_post = await _fetch_long_text(client, uid, post, sub_cookie)
    retweeted_status = resolved_post.get("retweeted_status")
    if isinstance(retweeted_status, dict):
        resolved_post = {**resolved_post}
        resolved_post["retweeted_status"] = await _fetch_long_text(client, uid, retweeted_status, sub_cookie)
    return resolved_post


async def fetch_user_feed_data(
    uid: int,
    max_posts: int,
    *,
    sub_cookie: str,
    base_url: str | None = None,
    timeout: float = 20.0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not extract_sub_cookie(sub_cookie):
        raise _authentication_required()

    items: list[dict[str, Any]] = []
    seen_item_ids: set[str] = set()
    max_pages = (max_posts + 19) // 20 + 1

    async with httpx.AsyncClient(
        base_url=base_url or WEIBO_API_BASE_URL,
        follow_redirects=True,
        timeout=httpx.Timeout(timeout),
        verify=False,
    ) as client:
        profile_data = await _fetch_json(client, "/ajax/profile/info", uid, sub_cookie, {"uid": uid})
        user = profile_data.get("user")
        if not isinstance(user, dict):
            raise HTTPException(status_code=502, detail="Weibo profile payload is missing user")

        page = 1
        while len(items) < max_posts and page <= max_pages:
            page_data = await _fetch_json(
                client,
                "/ajax/statuses/mymblog",
                uid,
                sub_cookie,
                {"uid": uid, "page": page, "feature": 0},
            )
            page_posts = page_data.get("list")
            if not isinstance(page_posts, list):
                raise HTTPException(status_code=502, detail="Weibo post payload is missing list")

            for post in page_posts:
                if not isinstance(post, dict) or post.get("isAd"):
                    continue
                post_id = _post_id(post)
                if not post_id or post_id in seen_item_ids:
                    continue
                seen_item_ids.add(post_id)
                items.append(post)
                if len(items) >= max_posts:
                    break

            if len(items) >= max_posts or len(page_posts) < 20:
                break
            page += 1

        resolved_items = [await _resolve_long_text(client, uid, post, sub_cookie) for post in items]

    return user, resolved_items


def _post_id(post: dict[str, Any]) -> str:
    return str(post.get("idstr") or post.get("id") or post.get("mblogid") or "")


def _html_to_text(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    return "\n".join(lines)


def _post_text(post: dict[str, Any]) -> str:
    text_raw = post.get("text_raw")
    if isinstance(text_raw, str) and text_raw.strip():
        return text_raw.strip()
    text = post.get("text")
    return _html_to_text(text) if isinstance(text, str) else ""


def _picture_info(post: dict[str, Any]) -> list[dict[str, Any]]:
    pic_infos = post.get("pic_infos")
    if not isinstance(pic_infos, dict):
        return []

    ordered: list[dict[str, Any]] = []
    seen_picture_ids: set[str] = set()
    pic_ids = post.get("pic_ids")
    if isinstance(pic_ids, list):
        for picture_id in pic_ids:
            key = str(picture_id)
            picture = pic_infos.get(key)
            if isinstance(picture, dict):
                ordered.append(picture)
                seen_picture_ids.add(key)

    for picture_id, picture in pic_infos.items():
        if str(picture_id) not in seen_picture_ids and isinstance(picture, dict):
            ordered.append(picture)
    return ordered


def _picture_url(picture: dict[str, Any]) -> str | None:
    for size in ("largest", "large", "original", "mw2000", "bmiddle", "thumbnail"):
        candidate = picture.get(size)
        if isinstance(candidate, dict) and (url := validated_http_url(candidate.get("url"))):
            return url
    return validated_http_url(picture.get("url"))


def _picture_urls(post: dict[str, Any]) -> list[str]:
    return [url for picture in _picture_info(post) if (url := _picture_url(picture))]


def _page_poster(post: dict[str, Any]) -> str | None:
    page_info = post.get("page_info")
    if not isinstance(page_info, dict):
        return None
    page_pic = page_info.get("page_pic")
    if isinstance(page_pic, dict) and (url := validated_http_url(page_pic.get("url"))):
        return url
    return validated_http_url(page_info.get("page_pic_url"))


def _first_valid_url(containers: list[dict[str, Any]], fields: tuple[str, ...]) -> str | None:
    for container in containers:
        for field in fields:
            if url := validated_http_url(container.get(field)):
                return url
    return None


def _video_media(post: dict[str, Any]) -> list[tuple[str, str | None]]:
    videos: list[tuple[str, str | None]] = []
    seen_video_urls: set[str] = set()

    for picture in _picture_info(post):
        video_url = validated_http_url(picture.get("videoSrc"))
        if video_url and video_url not in seen_video_urls:
            seen_video_urls.add(video_url)
            videos.append((video_url, _picture_url(picture)))

    page_info = post.get("page_info")
    if not isinstance(page_info, dict):
        return videos
    urls = page_info.get("urls")
    media_info = page_info.get("media_info")
    containers = [value for value in (urls, media_info) if isinstance(value, dict)]
    video_url = _first_valid_url(
        containers,
        (
            "mp4_720p_mp4",
            "mp4_hd_mp4",
            "mp4_hd_url",
            "stream_url_hd",
            "mp4_ld_mp4",
            "mp4_sd_url",
            "stream_url",
            "hevc_mp4_hd",
        ),
    )
    if video_url and video_url not in seen_video_urls:
        videos.append((video_url, _page_poster(post)))
    return videos


def _media(post: dict[str, Any]) -> tuple[list[str], list[tuple[str, str | None]]]:
    statuses = [post]
    retweeted_status = post.get("retweeted_status")
    if isinstance(retweeted_status, dict):
        statuses.append(retweeted_status)

    images: list[str] = []
    seen_images: set[str] = set()
    for status in statuses:
        for image_url in _picture_urls(status):
            if image_url not in seen_images:
                seen_images.add(image_url)
                images.append(image_url)

    videos: list[tuple[str, str | None]] = []
    seen_videos: set[str] = set()
    for status in statuses:
        for video in _video_media(status):
            if video[0] not in seen_videos:
                seen_videos.add(video[0])
                videos.append(video)
    return images, videos


def _author(user: dict[str, Any], fallback_uid: int) -> JSONFeedAuthor:
    user_id = str(user.get("id") or fallback_uid)
    name = str(user.get("screen_name") or user_id)
    return JSONFeedAuthor(
        name=name,
        url=f"{WEIBO_PROFILE_BASE_URL}/u/{user_id}",
        avatar=validated_http_url(user.get("avatar_hd") or user.get("profile_image_url")),
    )


def _published_at(post: dict[str, Any]) -> str | None:
    created_at = post.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        return None
    try:
        published_at: datetime = date_parser.parse(created_at)
    except (TypeError, ValueError, OverflowError):
        return None
    return published_at.isoformat()


def _body_html(post: dict[str, Any]) -> str:
    body_parts: list[str] = []
    if text := _post_text(post):
        body_parts.append(f"<p>{escape(text).replace(chr(10), '<br>')}</p>")

    retweeted_status = post.get("retweeted_status")
    if isinstance(retweeted_status, dict):
        retweet_author = retweeted_status.get("user")
        retweet_name = (
            str(retweet_author.get("screen_name"))
            if isinstance(retweet_author, dict) and retweet_author.get("screen_name")
            else "原微博"
        )
        retweet_text = _post_text(retweeted_status) or "原微博已不可见"
        safe_retweet_text = escape(retweet_text).replace("\n", "<br>")
        body_parts.append(f"<p>转发 @{escape(retweet_name)}：</p><blockquote><p>{safe_retweet_text}</p></blockquote>")

    source = post.get("source")
    if isinstance(source, str) and (source_text := _html_to_text(source)):
        body_parts.append(f"<p>来自 {escape(source_text)}</p>")

    metrics: list[str] = []
    for label, field in (("🔁", "reposts_count"), ("💬", "comments_count"), ("👍", "attitudes_count")):
        value = post.get(field)
        if isinstance(value, int):
            metrics.append(f"{label} {value}")
    if metrics:
        body_parts.append(f"<p>{' · '.join(metrics)}</p>")

    return "".join(body_parts)


def post_to_jsonfeed_item(post: dict[str, Any], profile_user: dict[str, Any], uid: int) -> JSONFeedItem:
    post_id = _post_id(post)
    mblogid = str(post.get("mblogid") or post.get("idstr") or post_id)
    item_user = post.get("user")
    author_user = item_user if isinstance(item_user, dict) else profile_user
    author = _author(author_user, uid)
    post_user_id = str(author_user.get("id") or uid)
    post_url = f"{WEIBO_PROFILE_BASE_URL}/{post_user_id}/{mblogid}" if mblogid else f"{WEIBO_PROFILE_BASE_URL}/u/{uid}"

    text = _post_text(post)
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    title = first_line or f"微博 {post_id or uid}"

    images, videos = _media(post)
    content_parts: list[str] = []
    if images or videos:
        media_html = [f'<img src="{escape(image_url, quote=True)}" alt="Weibo image" />' for image_url in images]
        attachments: list[JSONFeedAttachment] = []
        for video_url, poster_url in videos:
            poster = f' poster="{escape(poster_url, quote=True)}"' if poster_url else ""
            media_html.append(
                f'<video controls preload="metadata" src="{escape(video_url, quote=True)}"{poster}></video>'
            )
            attachments.append(JSONFeedAttachment.model_validate({"url": video_url, "mime_type": "video/mp4"}))
        content_parts.append(f"<div>{''.join(media_html)}</div>")
    else:
        attachments = []

    body_html = _body_html(post)
    if body_html:
        content_parts.append(f"<details><summary>查看正文</summary>{body_html}</details>")
    if not content_parts:
        content_parts.append("<p>微博动态</p>")

    first_video_poster = next((poster for _, poster in videos if poster), None)
    return JSONFeedItem.model_validate(
        {
            "id": post_id or mblogid,
            "url": post_url,
            "title": title,
            "content_html": "".join(content_parts),
            "summary": text or None,
            "image": images[0] if images else first_video_poster,
            "date_published": _published_at(post),
            "author": author,
            "attachments": attachments or None,
        }
    )


def build_user_feed(req: Request, uid: int, user: dict[str, Any], posts: list[dict[str, Any]]) -> JSONFeed:
    display_name = str(user.get("screen_name") or uid)
    profile_url = f"{WEIBO_PROFILE_BASE_URL}/u/{uid}"
    avatar = validated_http_url(user.get("avatar_hd") or user.get("profile_image_url"))
    description = _html_to_text(user["description"]) if isinstance(user.get("description"), str) else ""
    return JSONFeed.model_validate(
        {
            "version": "https://jsonfeed.org/version/1",
            "title": f"{display_name} (@{uid}) 的微博",
            "description": description,
            "home_page_url": profile_url,
            "feed_url": str(req.url.remove_query_params("cookies")),
            "icon": avatar or WEIBO_FAVICON,
            "favicon": avatar or WEIBO_FAVICON,
            "author": {
                "name": display_name,
                "url": profile_url,
                "avatar": avatar,
            },
            "items": [post_to_jsonfeed_item(post, user, uid) for post in posts],
        }
    )
