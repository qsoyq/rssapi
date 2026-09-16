from typing import Any

from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse

from rssapi.applications.instagram.utils import (
    INSTAGRAM_PROFILE_BASE_URL,
    _image_url,
    _video_url,
    fetch_user_feed_data,
    fetch_user_feed_data_by_cache,
    post_to_jsonfeed_item,
    validated_http_url,
)
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed
from rssapi.core.circuit_breaker import circuit_breaker
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.utils.urls import public_request_url

router = APIRouter(tags=["RSS"], prefix="/rss/instagram")


@router.get(
    "/media/{username}/{post_id}/{index}",
    summary="Instagram 媒体稳定重定向",
    response_class=RedirectResponse,
)
@circuit_breaker(status_code=429, cooldown=30)
async def media(
    username: str = Path(..., min_length=1, max_length=30, pattern=r"^[A-Za-z0-9._]+$"),
    post_id: str = Path(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    index: int = Path(..., ge=0),
    max_posts: int = Query(12, ge=1, le=50),
    cookies: str | None = Query(None, max_length=32768),
    x_instagram_cookie: str | None = Header(None, alias="X-Instagram-Cookie", max_length=32768),
) -> RedirectResponse:
    effective_cookies = cookies if cookies is not None else x_instagram_cookie
    normalized_username = username.lower()
    _, posts_data = await fetch_user_feed_data(
        normalized_username,
        max_posts,
        cookies=effective_cookies,
    )
    post = next(
        (item for item in posts_data if str(item.get("id") or item.get("pk") or item.get("code") or "") == post_id),
        None,
    )
    if post is None:
        raise HTTPException(status_code=404, detail=f"Instagram post not found: {post_id}")
    media_items = post.get("carousel_media")
    media_list = media_items if isinstance(media_items, list) and media_items else [post]
    if index >= len(media_list) or not isinstance(media_list[index], dict):
        raise HTTPException(status_code=404, detail=f"Instagram post has no media at index {index}: {post_id}")
    child = media_list[index]
    resolved_url = _video_url(child) if child.get("media_type") == 2 else _image_url(child)
    if not resolved_url:
        raise HTTPException(status_code=404, detail=f"Instagram post has no usable media: {post_id}")
    return RedirectResponse(resolved_url, status_code=302, headers={"Cache-Control": "no-store"})


@router.get(
    "/{username}/posts",
    response_model=JSONFeed,
    summary="Instagram User Posts RSS",
    response_class=PrettyJSONFeedResponse,
)
@circuit_breaker(status_code=429, cooldown=30)
async def posts(
    req: Request,
    username: str = Path(
        ...,
        min_length=1,
        max_length=30,
        pattern=r"^[A-Za-z0-9._]+$",
        description="Instagram 用户名",
    ),
    max_posts: int = Query(12, ge=1, le=50, description="最大贴文数，默认 12，最大 50"),
    cookies: str | None = Query(
        None,
        description="Instagram 完整 Cookie；建议通过 X-Instagram-Cookie 请求头传递以避免泄露到订阅 URL",
    ),
    x_instagram_cookie: str | None = Header(
        None,
        description="Instagram 完整 Cookie",
        alias="X-Instagram-Cookie",
    ),
) -> JSONFeed:
    """获取 Instagram 用户贴文的 JSON Feed。

    Instagram 的非公开 feed 接口会对部分账号的匿名请求重定向到登录页。可通过 query 参数
    ``cookies`` 或 ``X-Instagram-Cookie`` 请求头传入完整登录 Cookie；query 参数优先级更高。
    当前验证的最小字段为 ``ds_user_id`` 与 ``sessionid``。Cookie 属于敏感凭据，推荐使用请求头。
    """
    if cookies is None and x_instagram_cookie is not None:
        cookies = x_instagram_cookie

    normalized_username = username.lower()
    user, posts_data = (
        await fetch_user_feed_data(normalized_username, max_posts, cookies=cookies)
        if cookies
        else await fetch_user_feed_data_by_cache(normalized_username, max_posts)
    )
    resolved_username = str(user.get("username") or normalized_username)
    display_name = str(user.get("full_name") or resolved_username)
    profile_url = f"{INSTAGRAM_PROFILE_BASE_URL}/{resolved_username}/"
    avatar = validated_http_url(user.get("profile_pic_url"))
    author = {
        "name": display_name,
        "url": profile_url,
        "avatar": avatar,
    }
    feed: dict[str, Any] = {
        "version": "https://jsonfeed.org/version/1",
        "title": f"{display_name} (@{resolved_username}) 的 Instagram 贴文",
        "description": f"Instagram @{resolved_username}",
        "home_page_url": profile_url,
        "feed_url": public_request_url(req, remove_query_params={"cookies"}),
        "icon": avatar or "https://www.instagram.com/static/images/ico/favicon-192.png/68d99ba29cc8.png",
        "favicon": avatar or "https://www.instagram.com/static/images/ico/favicon-192.png/68d99ba29cc8.png",
        "author": author,
        "items": [post_to_jsonfeed_item(post, user, resolved_username, req=req) for post in posts_data],
    }
    return JSONFeed.model_validate(feed)
