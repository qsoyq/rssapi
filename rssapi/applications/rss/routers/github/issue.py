import logging
from typing import Any
import httpx
from fastapi import APIRouter, Query, Path, HTTPException, Request
from rssapi.applications.rss.schemas.github.issues import GithubIssue
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.core.responses import PrettyJSONResponse
from rssapi.utils.cache import RandomTTLCache
from asyncache import cached


router = APIRouter(tags=["RSS"], prefix="/rss/github/issues")

logger = logging.getLogger(__file__)


@router.get(
    "/repos/{owner}/{repo}",
    summary="Github Repo Issues RSS",
    response_model=JSONFeed,
    response_class=PrettyJSONResponse,
)
async def commits_list(
    req: Request,
    token: str | None = Query(None, description="Github API Token"),
    owner: str = Path(..., description="Github Repo Owner"),
    repo: str = Path(..., description="Github Repo Name"),
    per_page: int = Query(30, ge=1, le=100),
    page: int = Query(1, ge=1),
):
    """
    此接口未token疑似会触发限流

    参数详见文档: https://docs.github.com/en/rest/issues/issues?apiVersion=2022-11-28
    """
    host = req.url.hostname
    items: list[JSONFeedItem] = await fetch_feeds(owner, repo, token, per_page, page)
    feed = {
        "version": "https://jsonfeed.org/version/1",
        "title": f"{owner}/{repo}",
        "description": "",
        "home_page_url": f"https://github.com/{owner}/{repo}",
        "feed_url": f"{req.url.scheme}://{host}{req.url.path}?{req.url.query}",
        "icon": f"https://github.com/{owner}.png",
        "favicon": f"https://github.com/{owner}.png",
        "items": items,
    }

    return feed


@cached(RandomTTLCache(4096, 300))
async def fetch_feeds(owner: str, repo: str, token: str | None, per_page: int, page: int) -> list[JSONFeedItem]:
    items = []

    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    params = {
        "per_page": per_page,
        "page": page,
    }
    async with httpx.AsyncClient(headers=headers) as client:
        res = await client.get(url, params=params)
        if res.is_error:
            raise HTTPException(status_code=res.status_code, detail=res.text)
        results: list[GithubIssue] = [GithubIssue.model_validate(x) for x in res.json()]

    for item in results:
        assert item.user
        payload: dict[str, Any] = {
            "id": f"github-issues-{owner}-{repo}-{item.id}",
            "url": item.html_url,
            "title": item.title,
            "content_text": "",
            "date_published": item.created_at,
            "date_modified": item.updated_at,
            "author": {
                "url": item.user.html_url,
                "name": item.user.login,
                "avatar": item.user.avatar_url,
            },
        }
        items.append(JSONFeedItem.model_validate(payload))
    return items
