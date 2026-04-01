# https://www.reddit.com/r/programming

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from rdt_cli.exceptions import RedditApiError

from rssapi.applications.reddit.utils import fetch_subreddit_feed
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed
from rssapi.core.circuit_breaker import circuit_breaker
from rssapi.core.responses import PrettyJSONFeedResponse

router = APIRouter(tags=["RSS"], prefix="/rss/reddit")


@router.get(
    "/subreddit/{subreddit}",
    response_model=JSONFeed,
    summary="Reddit Subreddit Posts RSS",
    response_class=PrettyJSONFeedResponse,
)
@circuit_breaker(status_code=429, cooldown=30)
async def posts(
    req: Request,
    subreddit: str = Path(..., description="Reddit 子版块"),
    max_posts: int = Query(20, description="最大帖子数"),
    cookies: str | None = Query(None, description="Reddit 用户 cookie"),
    x_reddit_cookie: str | None = Header(None, description="Reddit 用户 cookie", alias="X-Reddit-Cookie"),
):
    """Reddit Subreddit Posts RSS"""
    if cookies is None and x_reddit_cookie is not None:
        cookies = x_reddit_cookie

    try:
        about, items = await run_in_threadpool(fetch_subreddit_feed, subreddit, max_posts, cookies)
    except RedditApiError as exc:
        status_code = exc.code if isinstance(exc.code, int) and 400 <= exc.code < 600 else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch subreddit posts: {exc}") from exc

    feed: dict[str, Any] = {
        "version": "https://jsonfeed.org/version/1",
        "title": about.display_name_prefixed or f"r/{subreddit}",
        "description": about.public_description or about.description or about.title or "",
        "home_page_url": f"https://www.reddit.com/r/{subreddit}/",
        "feed_url": str(req.url),
        "icon": "https://www.reddit.com/favicon.ico",
        "favicon": "https://www.reddit.com/favicon.ico",
        "items": items,
    }
    return feed
