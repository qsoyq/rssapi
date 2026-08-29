from typing import Any

from fastapi import APIRouter, Path, Query, Request

from rssapi.applications.instagram.utils import (
    INSTAGRAM_PROFILE_BASE_URL,
    fetch_user_feed_data_by_cache,
    post_to_jsonfeed_item,
    validated_http_url,
)
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed
from rssapi.core.circuit_breaker import circuit_breaker
from rssapi.core.responses import PrettyJSONFeedResponse

router = APIRouter(tags=["RSS"], prefix="/rss/instagram")


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
) -> JSONFeed:
    normalized_username = username.lower()
    user, posts_data = await fetch_user_feed_data_by_cache(normalized_username, max_posts)
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
        "feed_url": str(req.url),
        "icon": avatar or "https://www.instagram.com/static/images/ico/favicon-192.png/68d99ba29cc8.png",
        "favicon": avatar or "https://www.instagram.com/static/images/ico/favicon-192.png/68d99ba29cc8.png",
        "author": author,
        "items": [post_to_jsonfeed_item(post, user, resolved_username) for post in posts_data],
    }
    return JSONFeed.model_validate(feed)
