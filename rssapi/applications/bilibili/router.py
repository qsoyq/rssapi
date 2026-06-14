from asyncache import cached
from cachetools.keys import hashkey
from fastapi import APIRouter, Header, Path, Query, Request

from rssapi.applications.bilibili.utils import (
    BILIBILI_FAVICON,
    BILIBILI_SPACE_BASE,
    fetch_user_feed_data,
    fetch_user_submissions_feed_data,
)
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.core.settings import settings
from rssapi.utils.cache import RandomTTLCache

router = APIRouter(tags=["RSS"], prefix="/rss/bilibili")


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
            "items": items,
        }
    )


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
