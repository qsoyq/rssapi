from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed
from rssapi.applications.weibo.utils import (
    build_home_feed,
    build_user_feed,
    extract_sub_cookie,
    fetch_home_feed_data,
    fetch_post_media_video_by_cache,
    fetch_user_feed_data,
)
from rssapi.core.circuit_breaker import circuit_breaker
from rssapi.core.responses import PrettyJSONFeedResponse

router = APIRouter(tags=["RSS"], prefix="/rss/weibo")


async def _home_feed(
    req: Request,
    timeline: str,
    max_posts: int,
    cookies: str | None,
    x_weibo_cookie: str | None,
) -> JSONFeed:
    if cookies is None and x_weibo_cookie is not None:
        cookies = x_weibo_cookie

    sub_cookie = extract_sub_cookie(cookies)
    if not sub_cookie:
        raise HTTPException(
            status_code=401,
            detail="Weibo authentication required; provide cookies or X-Weibo-Cookie containing SUB",
        )

    posts_data = await fetch_home_feed_data(timeline, max_posts, sub_cookie=sub_cookie)
    return build_home_feed(req, timeline, posts_data)


@router.get(
    "/{uid}/posts",
    response_model=JSONFeed,
    summary="Weibo User Posts RSS",
    response_class=PrettyJSONFeedResponse,
)
@circuit_breaker(status_code=429, cooldown=30)
async def posts(
    req: Request,
    uid: int = Path(..., ge=1, description="微博用户 UID", examples=[1842706721]),
    max_posts: int = Query(20, ge=1, le=50, description="最大微博数量，默认 20，最大 50"),
    cookies: str | None = Query(
        None,
        description="微博 Cookie；仅使用其中的 SUB，建议通过 X-Weibo-Cookie 请求头传递以避免泄露到订阅 URL",
    ),
    x_weibo_cookie: str | None = Header(None, description="微博 Cookie", alias="X-Weibo-Cookie"),
) -> JSONFeed:
    """获取微博用户动态的 JSON Feed。

    微博网页端 AJAX 接口要求登录态。可传入完整 Cookie，但本路由只会向上游转发最小字段
    ``SUB``；query 参数优先于 ``X-Weibo-Cookie`` 请求头。Cookie 属于敏感凭据，推荐使用请求头。
    """
    if cookies is None and x_weibo_cookie is not None:
        cookies = x_weibo_cookie

    sub_cookie = extract_sub_cookie(cookies)
    if not sub_cookie:
        raise HTTPException(
            status_code=401,
            detail="Weibo authentication required; provide cookies or X-Weibo-Cookie containing SUB",
        )

    user, posts_data = await fetch_user_feed_data(uid, max_posts, sub_cookie=sub_cookie)
    return build_user_feed(req, uid, user, posts_data)


@router.get(
    "/home/follow",
    response_model=JSONFeed,
    summary="Weibo Follow Timeline RSS",
    response_class=PrettyJSONFeedResponse,
)
@circuit_breaker(status_code=429, cooldown=30)
async def follow(
    req: Request,
    max_posts: int = Query(20, ge=1, le=50, description="最大微博数量，默认 20，最大 50"),
    cookies: str | None = Query(
        None,
        description="微博 Cookie；仅使用其中的 SUB，建议通过 X-Weibo-Cookie 请求头传递以避免泄露到订阅 URL",
    ),
    x_weibo_cookie: str | None = Header(None, description="微博 Cookie", alias="X-Weibo-Cookie"),
) -> JSONFeed:
    """获取当前登录用户关注账号的微博时间线。"""
    return await _home_feed(req, "follow", max_posts, cookies, x_weibo_cookie)


@router.get(
    "/home/foryou",
    response_model=JSONFeed,
    summary="Weibo For You Timeline RSS",
    response_class=PrettyJSONFeedResponse,
)
@circuit_breaker(status_code=429, cooldown=30)
async def foryou(
    req: Request,
    max_posts: int = Query(20, ge=1, le=50, description="最大微博数量，默认 20，最大 50"),
    cookies: str | None = Query(
        None,
        description="微博 Cookie；仅使用其中的 SUB，建议通过 X-Weibo-Cookie 请求头传递以避免泄露到订阅 URL",
    ),
    x_weibo_cookie: str | None = Header(None, description="微博 Cookie", alias="X-Weibo-Cookie"),
) -> JSONFeed:
    """获取当前登录用户的微博推荐时间线。"""
    return await _home_feed(req, "foryou", max_posts, cookies, x_weibo_cookie)


@router.get(
    "/media/{post_id}/{index}",
    summary="Weibo 视频稳定中转地址",
    response_class=RedirectResponse,
)
@circuit_breaker(status_code=429, cooldown=30)
async def media(
    post_id: str = Path(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9]+$",
        description="微博帖子 id（idstr）或 mblogid",
    ),
    index: int = Path(..., ge=0, description="同一帖子内多个视频时的序号"),
    cookies: str | None = Query(
        None,
        description="微博 Cookie；仅使用其中的 SUB，建议通过 X-Weibo-Cookie 请求头传递以避免泄露到订阅 URL",
    ),
    x_weibo_cookie: str | None = Header(None, description="微博 Cookie", alias="X-Weibo-Cookie"),
) -> RedirectResponse:
    """为微博视频签发一个临时签名地址并 302 重定向。

    微博视频 CDN 地址带 ``Expires`` + ``ssig`` 签名，寿命约 60 分钟；而 feed 只返回最新
    20 条，条目掉出窗口后客户端拿到的签名无法再续期。这里在每次请求时按 ``post_id``
    向上游重新解析，因此返回的地址对任意历史帖子都长期可用。
    """
    if cookies is None and x_weibo_cookie is not None:
        cookies = x_weibo_cookie

    sub_cookie = extract_sub_cookie(cookies)
    if not sub_cookie:
        raise HTTPException(
            status_code=401,
            detail="Weibo authentication required; provide cookies or X-Weibo-Cookie containing SUB",
        )

    video_url = await fetch_post_media_video_by_cache(post_id, index, sub_cookie=sub_cookie)
    # 客户端注入 Referer 的规则只匹配 https，而上游签名地址是 http，这里统一升级 scheme。
    location = video_url.replace("http://", "https://", 1) if video_url.startswith("http://") else video_url
    # 重定向响应本身不可缓存，否则客户端会重放已经过期的签名。
    return RedirectResponse(location, status_code=302, headers={"Cache-Control": "no-store"})
