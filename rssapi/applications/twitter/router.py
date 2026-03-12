from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Path, Query, Request

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed
from rssapi.applications.twitter.feed import (
    fetch_feed_jsonfeed_items,
    fetch_user_posts_jsonfeed_items,
)
from rssapi.applications.twitter.utils import AuthorScreenNameMapping
from rssapi.core.responses import PrettyJSONFeedResponse

router = APIRouter(tags=["RSS"], prefix="/rss/twitter")


@router.get(
    "/{screen_name}/posts",
    response_model=JSONFeed,
    summary="Twitter User Posts RSS",
    response_class=PrettyJSONFeedResponse,
)
async def posts(
    req: Request,
    screen_name: str = Path(..., description="Twitter 用户名"),
    max_tweets: int = Query(50, description="最大推文数"),
    cookies: str | None = Query(None, description="Twitter 用户 cookie"),
    x_twitter_cookie: str | None = Header(None, description="Twitter 用户 cookie", alias="X-Twitter-Cookie"),
):
    """Twitter Timeline RSS"""
    if cookies is None and x_twitter_cookie is not None:
        cookies = x_twitter_cookie

    if cookies is None:
        raise HTTPException(status_code=401, detail="cookies or X-Twitter-Cookie are required")

    items = await fetch_user_posts_jsonfeed_items(screen_name, max_tweets, cookies)
    host = req.url.hostname
    feed: dict[str, Any] = {
        "version": "https://jsonfeed.org/version/1",
        "title": screen_name,
        "description": "",
        "home_page_url": f"https://x.com/{screen_name}",
        "feed_url": f"{req.url.scheme}://{host}{req.url.path}?{req.url.query}",
        "icon": "https://abs.twimg.com/favicons/twitter-pip.3.ico",
        "favicon": "https://abs.twimg.com/favicons/twitter-pip.3.ico",
        "items": items,
    }
    for item in items:
        if item.author and item.author.name:
            _screen_name = AuthorScreenNameMapping.get(item.author.name)
            if _screen_name is not None and _screen_name == screen_name:
                feed["author"] = item.author
                feed["title"] = item.author.name
                feed["icon"] = feed["favicon"] = item.author.avatar
                break

    return feed


@router.get(
    "/user/timeline/{feed_type}",
    response_model=JSONFeed,
    summary="Twitter User Timeline RSS",
    response_class=PrettyJSONFeedResponse,
)
async def timeline(
    req: Request,
    feed_type: Literal["for-you", "following"] = Path(..., description="Timeline 类型"),
    max_tweets: int = Query(50, description="最大推文数"),
    cookies: str | None = Query(None, description="Twitter 用户 cookie"),
    x_twitter_cookie: str | None = Header(None, description="Twitter 用户 cookie", alias="X-Twitter-Cookie"),
):
    """Twitter Timeline RSS (for-you / following)

    - for-you: 获取用户的时间线
    - following: 获取用户关注的用户的时间线

    - 如果 cookies 为空，则从 X-Twitter-Cookie 头中获取
    - 如果 cookies 和 X-Twitter-Cookie 头都为空，则返回 401 错误
    """
    if cookies is None and x_twitter_cookie is not None:
        cookies = x_twitter_cookie

    if cookies is None:
        raise HTTPException(status_code=401, detail="cookies or X-Twitter-Cookie are required")

    cached_items = await fetch_feed_jsonfeed_items(max_tweets, cookies, feed_type)
    items = [
        item.model_copy(update={"title": f"@{item.author.name} {item.title}"})
        if item.author and item.author.name
        else item
        for item in cached_items
    ]
    host = req.url.hostname
    feed: dict[str, Any] = {
        "version": "https://jsonfeed.org/version/1",
        "title": f"Twitter Timeline ({feed_type})",
        "description": "",
        "home_page_url": "https://x.com/home",
        "feed_url": f"{req.url.scheme}://{host}{req.url.path}?{req.url.query}",
        "icon": "https://abs.twimg.com/favicons/twitter-pip.3.ico",
        "favicon": "https://abs.twimg.com/favicons/twitter-pip.3.ico",
        "items": items,
    }
    # TODO: 通过twitter_cli 读取当前用户 profile 信息
    return feed
