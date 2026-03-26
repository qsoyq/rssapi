# https://www.reddit.com/r/programming

from datetime import datetime, timezone
from html import escape
from http.cookies import SimpleCookie
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from rdt_cli.auth import Credential
from rdt_cli.client import RedditClient
from rdt_cli.exceptions import RedditApiError
from rdt_cli.models import Post, SubredditInfo
from rdt_cli.parser import parse_listing, parse_subreddit_info

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
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
        about, items = await run_in_threadpool(_fetch_subreddit_feed, subreddit, max_posts, cookies)
    except RedditApiError as exc:
        status_code = exc.code if isinstance(exc.code, int) and 400 <= exc.code < 600 else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch subreddit posts: {exc}") from exc

    feed: dict[str, Any] = {
        "version": "https://jsonfeed.org/version/1",
        "title": about.display_name_prefixed or f"r/{subreddit}",
        "description": about.public_description or about.description or "",
        "home_page_url": f"https://www.reddit.com/r/{subreddit}/",
        "feed_url": str(req.url),
        "icon": "https://www.reddit.com/favicon.ico",
        "favicon": "https://www.reddit.com/favicon.ico",
        "items": items,
    }
    return feed


def _fetch_subreddit_feed(
    subreddit: str, max_posts: int, cookies: str | None
) -> tuple[SubredditInfo, list[JSONFeedItem]]:
    credential = _build_credential(cookies)
    with RedditClient(credential) as client:
        about = parse_subreddit_info(client.get_subreddit_about(subreddit))
        listing = parse_listing(client.get_subreddit(subreddit, limit=max_posts))
    items = [_build_feed_item(post) for post in listing.items]
    return about, items


def _build_credential(cookies: str | None) -> Credential | None:
    if not cookies:
        return None

    cookie = SimpleCookie()
    cookie.load(cookies)
    parsed_cookies = {key: morsel.value for key, morsel in cookie.items()}
    if not parsed_cookies:
        return None
    return Credential(cookies=parsed_cookies, source="rssapi")


def _build_feed_item(post: Post) -> JSONFeedItem:
    permalink_url = f"https://www.reddit.com{post.permalink}" if post.permalink else None
    target_url = post.url or permalink_url
    content_parts = []
    if post.selftext:
        content_parts.append(f"<p>{escape(post.selftext).replace(chr(10), '<br>')}</p>")
    if not post.is_self and target_url:
        safe_url = escape(target_url, quote=True)
        content_parts.append(f'<p><a href="{safe_url}">查看原帖链接</a></p>')
    content_parts.append(f"<p>👍 {post.score} · 💬 {post.num_comments}</p>")

    return JSONFeedItem.model_validate(
        {
            "id": post.id,
            "url": permalink_url or target_url,
            "external_url": target_url if target_url != permalink_url else None,
            "title": post.title,
            "date_published": _format_timestamp(post.created_utc),
            "content_html": "".join(content_parts),
            "author": {
                "name": f"u/{post.author}" if post.author else None,
                "url": f"https://www.reddit.com/user/{post.author}/" if post.author else None,
            },
            "tags": [post.subreddit] if post.subreddit else None,
        }
    )


def _format_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
