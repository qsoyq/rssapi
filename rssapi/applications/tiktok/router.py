import asyncio
import re
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.applications.tiktok.utils import (
    TIKTOK_BASE_URL,
    TIKTOK_FAVICON,
    avatar_url,
    fetch_posts_by_sec_uid_by_cache,
    fetch_user_posts_by_cache,
    normalize_username,
    post_to_jsonfeed_item,
    video_media,
)
from rssapi.core.circuit_breaker import circuit_breaker
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.core.settings import settings

router = APIRouter(tags=["RSS"], prefix="/rss/tiktok")
_media_semaphore = asyncio.Semaphore(settings.tiktok.media_proxy_concurrency)
_RANGE_RE = re.compile(r"^bytes=(\d+)-(\d*)$")


def _absolute_url(req: Request, path: str) -> str:
    return f"{req.url.scheme}://{req.url.netloc}{path}"


def _media_url(req: Request, username: str, item_id: str, sec_uid: str, max_posts: int) -> str:
    normalized_username = normalize_username(username)
    path = (
        f"{settings.api_prefix}/rss/tiktok/media/{normalized_username}/{item_id}"
        f"?sec_uid={sec_uid}&max_posts={max_posts}"
    )
    return _absolute_url(req, path)


def _feed_item(
    req: Request,
    item: dict[str, Any],
    user: dict[str, Any],
    username: str,
    max_posts: int,
) -> JSONFeedItem:
    item_id = str(item.get("id") or "")
    playable_url, _ = video_media(item)
    sec_uid = str(user.get("secUid") or "")
    media_url = _media_url(req, username, item_id, sec_uid, max_posts) if playable_url and sec_uid else None
    return post_to_jsonfeed_item(item, user, username, media_url=media_url)


def _validated_range(range_header: str | None) -> str | None:
    if range_header is None:
        return None
    match = _RANGE_RE.fullmatch(range_header)
    if not match:
        raise HTTPException(status_code=416, detail="Only a single byte range is supported")
    start = int(match.group(1))
    end_value = match.group(2)
    if end_value:
        end = int(end_value)
        if end < start or end - start + 1 > 16 * 1024 * 1024:
            raise HTTPException(status_code=416, detail="TikTok media range is invalid or too large")
    return range_header


async def proxy_media_response(
    playable_url: str,
    referer: str,
    range_header: str | None,
    *,
    allowed_hosts: tuple[str, ...] = ("www.tiktok.com", ".tiktok.com", ".tiktokcdn.com"),
) -> StreamingResponse:
    range_header = _validated_range(range_header)
    headers = {
        "Referer": referer,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
    }
    if range_header:
        headers["Range"] = range_header

    await _media_semaphore.acquire()
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.tiktok.request_timeout),
        follow_redirects=True,
        trust_env=False,
        proxy=settings.tiktok.proxy,
    )
    request = client.build_request("GET", playable_url, headers=headers)
    try:
        upstream = await client.send(request, stream=True)
    except httpx.TimeoutException as exc:
        await client.aclose()
        _media_semaphore.release()
        raise HTTPException(status_code=504, detail="TikTok media request timed out") from exc
    except httpx.RequestError as exc:
        await client.aclose()
        _media_semaphore.release()
        raise HTTPException(status_code=502, detail="Failed to request TikTok media") from exc

    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        _media_semaphore.release()
        raise HTTPException(
            status_code=upstream.status_code, detail=f"TikTok media returned HTTP {upstream.status_code}"
        )
    final_host = upstream.url.host
    if not any(final_host == host or (host.startswith(".") and final_host.endswith(host)) for host in allowed_hosts):
        await upstream.aclose()
        await client.aclose()
        _media_semaphore.release()
        raise HTTPException(status_code=502, detail="TikTok media redirected to an unsupported host")

    response_headers = {
        name: upstream.headers[name]
        for name in ("content-length", "content-range", "accept-ranges", "etag", "last-modified")
        if name in upstream.headers
    }
    response_headers["Cache-Control"] = "no-store"
    media_type = upstream.headers.get("content-type") or "video/mp4"

    async def iter_content():
        try:
            async for chunk in upstream.aiter_bytes(chunk_size=256 * 1024):
                if chunk:
                    yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()
            _media_semaphore.release()

    return StreamingResponse(
        iter_content(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=media_type,
    )


@router.get(
    "/media/{username}/{item_id}",
    summary="TikTok 视频媒体代理",
)
async def media(
    username: str = Path(
        ...,
        min_length=1,
        max_length=24,
        pattern=r"^[A-Za-z0-9._]{1,24}$",
        description="TikTok 用户名，不包含 @ 前缀",
    ),
    item_id: str = Path(..., pattern=r"^\d{15,22}$", description="TikTok 帖子 ID"),
    sec_uid: str = Query(
        ...,
        min_length=20,
        max_length=128,
        pattern=r"^MS4wLjABAAAA[A-Za-z0-9_-]+$",
        description="TikTok 用户 secUid",
    ),
    max_posts: int = Query(12, ge=1, le=50, description="重新解析视频时最多读取的帖子数"),
    range_header: str | None = Header(None, alias="Range"),
) -> StreamingResponse:
    normalized_username = normalize_username(username)
    posts_data = await fetch_posts_by_sec_uid_by_cache(normalized_username, sec_uid, max_posts)
    item = next((post for post in posts_data if str(post.get("id") or "") == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"TikTok post not found in feed: {item_id}")
    playable_url, _ = video_media(item)
    if not playable_url:
        raise HTTPException(status_code=404, detail=f"TikTok post has no playable video: {item_id}")
    referer = f"https://www.tiktok.com/@{normalized_username}/video/{item_id}"
    return await proxy_media_response(playable_url, referer, range_header)


@router.get(
    "/{username}/posts",
    response_model=JSONFeed,
    summary="TikTok User Posts RSS",
    response_class=PrettyJSONFeedResponse,
)
@circuit_breaker(status_code=[429, 502], cooldown=60)
async def posts(
    req: Request,
    username: str = Path(
        ...,
        min_length=1,
        max_length=25,
        pattern=r"^@?[A-Za-z0-9._]{1,24}$",
        description="TikTok 用户名，可包含 @ 前缀",
        examples=["arimariash", "@arimariash"],
    ),
    max_posts: int = Query(12, ge=1, le=50, description="最大贴文数，默认 12，最大 50"),
) -> JSONFeed:
    """获取 TikTok 用户公开 Posts 的 JSON Feed。

    用户资料通过公开页面中的 ``SIGI_STATE`` hydration 数据解析，再调用 TikTok creator 接口获取 Posts。
    TikTok 可能对频繁请求或特定出口 IP 返回 HTTP 200 的风控壳页；该响应不包含 hydration 数据，端点会明确
    返回 502，而不会误报为空 Feed。成功结果使用 3 小时基础 TTL 的动态内存缓存，但进程重启会清空缓存；部署时
    可通过 ``RSS_TIKTOK_PROXY`` 配置不同出口以降低风控影响。

    Feed 内的视频使用本服务媒体代理。代理仅携带稳定的用户 ``secUid`` 和帖子 ID，播放时重新解析当前媒体地址，
    并携带 TikTok 原帖 Referer 转发单段 Range 请求，避免地址过期及浏览器防盗链。
    """
    normalized_username = normalize_username(username)
    user, posts_data = await fetch_user_posts_by_cache(normalized_username, max_posts)
    resolved_username = str(user.get("uniqueId") or normalized_username)
    display_name = str(user.get("nickname") or resolved_username)
    profile_url = f"{TIKTOK_BASE_URL}/@{resolved_username}"
    avatar = avatar_url(user)
    author = {"name": display_name, "url": profile_url, "avatar": avatar}
    feed: dict[str, Any] = {
        "version": "https://jsonfeed.org/version/1",
        "title": f"{display_name} (@{resolved_username}) 的 TikTok 贴文",
        "description": f"TikTok @{resolved_username}",
        "home_page_url": profile_url,
        "feed_url": str(req.url),
        "icon": avatar or TIKTOK_FAVICON,
        "favicon": avatar or TIKTOK_FAVICON,
        "author": author,
        "items": [_feed_item(req, item, user, resolved_username, max_posts) for item in posts_data],
    }
    return JSONFeed.model_validate(feed)
