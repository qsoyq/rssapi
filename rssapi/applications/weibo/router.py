from fastapi import APIRouter, Header, HTTPException, Path, Query, Request

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed
from rssapi.applications.weibo.utils import (
    build_user_feed,
    extract_sub_cookie,
    fetch_user_feed_data,
)
from rssapi.core.circuit_breaker import circuit_breaker
from rssapi.core.responses import PrettyJSONFeedResponse

router = APIRouter(tags=["RSS"], prefix="/rss/weibo")


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
