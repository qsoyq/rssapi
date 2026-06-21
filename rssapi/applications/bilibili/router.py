import html
import re
from typing import Any, cast

import httpx
from asyncache import cached
from cachetools.keys import hashkey
from curl_cffi import requests
from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse

from rssapi.applications.bilibili.utils import (
    BILIBILI_FAVICON,
    BILIBILI_HEADERS,
    BILIBILI_SPACE_BASE,
    fetch_playable_video_url,
    fetch_user_feed_data,
    fetch_user_submissions_feed_data,
)
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.core.settings import settings
from rssapi.utils.cache import RandomTTLCache

router = APIRouter(tags=["RSS"], prefix="/rss/bilibili")

_BILIBILI_VIDEO_ID_RE = re.compile(r"^bilibili-video-(?P<bvid>BV[a-zA-Z0-9]+)$")
_BILIBILI_VIDEO_URL_RE = re.compile(r"/video/(?P<bvid>BV[a-zA-Z0-9]+)")
_VIDEO_SRC_RE = re.compile(r'(<video\b[^>]*\bsrc=")[^"]*(")', re.IGNORECASE)


@router.get(
    "/user/{mid}",
    response_model=JSONFeed,
    summary="Bilibili 用户投稿视频 RSS 订阅",
    response_class=PrettyJSONFeedResponse,
)
async def user_videos(
    req: Request,
    mid: int = Path(..., description="Bilibili 用户 UID/mid", examples=[4186021]),
    page_size: int = Query(30, ge=1, le=50, description="返回视频数量，默认 30，最大 50"),
    use_cache: bool = Query(True, description="是否从缓存返回"),
    cookies: str | None = Query(None, description="Bilibili 用户 cookie，用于规避风控（可选）"),
    x_bilibili_cookie: str | None = Header(None, description="Bilibili 用户 cookie", alias="X-Bilibili-Cookie"),
):
    """获取 Bilibili 用户最新投稿视频的 JSON Feed。

    - cookies 可选，传入后用于携带登录态以规避 Bilibili 风控
    - 如果 cookies 为空，则从 X-Bilibili-Cookie 头中获取
    - 两者都为空时仍以匿名方式请求公开投稿
    """
    if cookies is None and x_bilibili_cookie is not None:
        cookies = x_bilibili_cookie

    user, items = (
        await fetch_user_feed_data_by_cache(mid, page_size, cookies)
        if use_cache
        else await fetch_user_feed_data(mid, page_size, cookies)
    )
    return _build_user_feed(req, mid, user, items)


@router.get(
    "/v2/user/{mid}",
    response_model=JSONFeed,
    summary="Bilibili 用户完整投稿视频 RSS 订阅",
    response_class=PrettyJSONFeedResponse,
)
async def user_submissions(
    req: Request,
    mid: int = Path(..., description="Bilibili 用户 UID/mid", examples=[4186021]),
    page_size: int = Query(30, ge=1, le=50, description="返回视频数量，默认 30，最大 50"),
    use_cache: bool = Query(True, description="是否从缓存返回"),
    cookies: str | None = Query(None, description="Bilibili 用户 cookie，强烈建议传入以规避风控"),
    x_bilibili_cookie: str | None = Header(None, description="Bilibili 用户 cookie", alias="X-Bilibili-Cookie"),
):
    """获取 Bilibili 用户**完整投稿列表**的 JSON Feed（基于 WBI `/x/space/wbi/arc/search`）。

    - 与 `/user/{mid}`（仅合集/系列）不同，此端点返回完整投稿，内容更全。
    - cookie 强烈建议传入：匿名请求 `/x/space/wbi/arc/search` 极易被 Bilibili 风控拦截（412/-352/-799）。
    - cookies 为空时回退到 X-Bilibili-Cookie 头；两者都为空时仍以匿名方式尝试。
    """
    if cookies is None and x_bilibili_cookie is not None:
        cookies = x_bilibili_cookie

    user, items = (
        await fetch_user_submissions_feed_data_by_cache(mid, page_size, cookies)
        if use_cache
        else await fetch_user_submissions_feed_data(mid, page_size, cookies)
    )
    return _build_user_feed(req, mid, user, items)


@router.get(
    "/media/{bvid}",
    summary="Bilibili CDN 视频中转",
)
async def media(
    bvid: str = Path(..., description="Bilibili BV 号", examples=["BV1gGjB6qEnR"]),
    range_header: str | None = Header(None, alias="Range"),
):
    """实时解析 Bilibili CDN URL，并带播放页 Referer 转发视频请求。

    RSS 中的 CDN 直链会过期，因此 feed 内 `<video>` 使用这个稳定中转地址。
    """
    referer = f"https://www.bilibili.com/video/{bvid}"
    headers = {**BILIBILI_HEADERS, "Referer": referer}
    with requests.Session(headers=headers, timeout=30, impersonate="chrome136") as client:
        playable_url = await fetch_playable_video_url(client, {"bvid": bvid})
    if not playable_url:
        raise HTTPException(status_code=502, detail=f"fetch bilibili media url error: {bvid}")

    upstream_headers = {**headers}
    if range_header:
        upstream_headers["Range"] = range_header

    upstream_client, upstream = await _open_upstream_media(playable_url, upstream_headers)
    if upstream.status_code >= 400:
        detail = (await upstream.aread()).decode(errors="replace")
        await upstream.aclose()
        await upstream_client.aclose()
        raise HTTPException(status_code=upstream.status_code, detail=detail)

    response_headers = {
        name: upstream.headers[name]
        for name in ("content-length", "content-range", "accept-ranges", "last-modified")
        if name in upstream.headers
    }
    response_headers["Cache-Control"] = "no-store"
    media_type = upstream.headers.get("content-type") or "video/mp4"

    async def iter_content():
        try:
            async for chunk in upstream.aiter_bytes(chunk_size=1024 * 256):
                if chunk:
                    yield chunk
        finally:
            await upstream.aclose()
            await upstream_client.aclose()

    return StreamingResponse(
        iter_content(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=media_type,
    )


async def _open_upstream_media(playable_url: str, headers: dict[str, str]):
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
    )
    request = client.build_request("GET", playable_url, headers=headers)
    try:
        response = await client.send(request, stream=True)
    except Exception:
        await client.aclose()
        raise
    return client, response


def _build_user_feed(req: Request, mid: int, user, items) -> JSONFeed:
    user_name = (user or {}).get("name") or str(mid)
    user_sign = (user or {}).get("sign") or ""
    user_face = (user or {}).get("face") or BILIBILI_FAVICON
    return JSONFeed.model_validate(
        {
            "version": "https://jsonfeed.org/version/1",
            "title": f"{user_name} 的 Bilibili 投稿",
            "description": user_sign,
            "home_page_url": f"{BILIBILI_SPACE_BASE}/{mid}",
            "feed_url": f"{req.url.scheme}://{req.url.hostname}{req.url.path}?{req.url.query}",
            "icon": user_face,
            "favicon": user_face,
            "author": {
                "name": user_name,
                "url": f"{BILIBILI_SPACE_BASE}/{mid}",
                "avatar": user_face,
            },
            "items": [_with_stable_media_url(req, item) for item in items],
        }
    )


def _absolute_url(req: Request, path: str) -> str:
    return f"{req.url.scheme}://{req.url.netloc}{path}"


def _item_payload(item) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return cast("dict[str, Any]", item.model_dump(mode="json"))
    return dict(item)


def _item_bvid(item: dict[str, Any]) -> str | None:
    item_id = item.get("id") or ""
    if match := _BILIBILI_VIDEO_ID_RE.match(item_id):
        return match.group("bvid")
    item_url = item.get("url") or ""
    if match := _BILIBILI_VIDEO_URL_RE.search(item_url):
        return match.group("bvid")
    return None


def _with_stable_media_url(req: Request, item) -> dict[str, Any]:
    payload = _item_payload(item)
    content_html = payload.get("content_html") or ""
    bvid = _item_bvid(payload)
    if not bvid or "<video" not in content_html:
        return payload

    media_url = _absolute_url(req, f"{settings.api_prefix}/rss/bilibili/media/{bvid}")
    payload["content_html"] = _VIDEO_SRC_RE.sub(
        lambda match: f"{match.group(1)}{html.escape(media_url, quote=True)}{match.group(2)}",
        content_html,
        count=1,
    )
    return payload


@cached(
    RandomTTLCache(settings.bilibili.user_videos_cache_maxsize, settings.bilibili.user_videos_cache_ttl),
    # cookie 只影响请求是否被风控放行，不影响公开投稿内容，故不计入缓存 key
    key=lambda mid, page_size, cookies=None: hashkey(mid, page_size),
)
async def fetch_user_feed_data_by_cache(mid: int, page_size: int, cookies: str | None = None):
    return await fetch_user_feed_data(mid, page_size, cookies)


@cached(
    RandomTTLCache(settings.bilibili.user_videos_cache_maxsize, settings.bilibili.user_videos_cache_ttl),
    # cookie 只影响请求是否被风控放行，不影响公开投稿内容，故不计入缓存 key
    key=lambda mid, page_size, cookies=None: hashkey("submissions", mid, page_size),
)
async def fetch_user_submissions_feed_data_by_cache(mid: int, page_size: int, cookies: str | None = None):
    return await fetch_user_submissions_feed_data(mid, page_size, cookies)
