import logging
from typing import Any, cast

import httpx
from asyncache import cached
from fastapi import APIRouter, Header, HTTPException, Path, Query, Request

from rssapi.applications.github.schemas import AuthorSchema
from rssapi.applications.github.schemas.commits import CommitItemSchema, CommitSchema
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed, JSONFeedItem
from rssapi.core.responses import PrettyJSONFeedResponse
from rssapi.utils.cache import RandomTTLCache

router = APIRouter(tags=["RSS"], prefix="/rss/github/commits")

logger = logging.getLogger(__file__)


@router.get(
    "/repos/{owner}/{repo}",
    summary="Github Repo Commits RSS",
    response_model=JSONFeed,
    response_class=PrettyJSONFeedResponse,
)
async def commits_list(
    req: Request,
    token: str | None = Query(
        None,
        description="Github API Token，可与 X-Github-Api-Token 二选一；若同时提供则优先使用 X-Github-Api-Token",
    ),
    x_github_api_token: str | None = Header(
        None,
        description="Github API Token，可与 query 参数 token 二选一；若同时提供则优先使用当前请求头",
        alias="X-Github-Api-Token",
    ),
    owner: str = Path(..., description="Github Repo Owner"),
    repo: str = Path(..., description="Github Repo Name"),
    per_page: int = Query(30, ge=1, le=100),
    page: int = Query(1, ge=1),
):
    """
    Github API Token 支持两种传法，二选一即可：
    - query 参数 `token`
    - 请求头 `X-Github-Api-Token`
    若同时提供，优先使用 `X-Github-Api-Token`

    参数详见文档: https://docs.github.com/en/rest/commits/commits?apiVersion=2022-11-28
    """
    effective_token = x_github_api_token if x_github_api_token is not None else token
    host = req.url.hostname
    items: list[JSONFeedItem] = await fetch_feeds(owner, repo, effective_token, per_page, page)
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


@cached(RandomTTLCache(4096, 1800))
async def fetch_feeds(owner: str, repo: str, token: str | None, per_page: int, page: int) -> list[JSONFeedItem]:
    items = []

    url = f"https://api.github.com/repos/{owner}/{repo}/commits"
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
        res = await client.get(url, params=params, follow_redirects=True)
        if res.is_error:
            raise HTTPException(status_code=res.status_code, detail=res.text)
        body = res.json()
        if not isinstance(body, list):
            logger.error(f"Invalid response body: {body}")
            raise HTTPException(status_code=502, detail=f"github API error, body: {body}")
        commit_list: list[CommitItemSchema] = [CommitItemSchema.model_construct(**x) for x in body]

    for commit in commit_list:
        commit.commit = CommitSchema(**cast(dict, commit.commit))
        if commit.author is not None:
            commit.author = AuthorSchema(**cast(dict, commit.author))
        if not commit.commit.author:
            continue
        payload: dict[str, Any] = {
            "id": f"github-commits-{owner}-{repo}-{commit.sha}",
            "url": commit.html_url,
            "title": commit.commit.message,
            "content_text": "",
            "date_published": commit.commit.author.date,
            "date_modified": commit.commit.author.date,
            "author": {
                "url": commit.author.html_url if commit.author else None,
                "name": commit.author.login if commit.author else None,
                "avatar": commit.author.avatar_url if commit.author else None,
            },
        }
        items.append(JSONFeedItem(**payload))
    return items
