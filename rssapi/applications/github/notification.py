import logging
from typing import Any, cast

import httpx
from asyncache import cached
from fastapi import APIRouter, Header, HTTPException, Path, Query, Request

from rssapi.applications.github.schemas.notifications import NotificationSchema
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedItem
from rssapi.utils.cache import RandomTTLCache

router = APIRouter(tags=["RSS"], prefix="/rss/github/notifications")

logger = logging.getLogger(__file__)


@router.get(
    "/user/{token}",
    summary="Github Repo Notifications RSS",
)
async def notifications(
    req: Request,
    token: str = Path(..., description="Github User API Token, Personal access tokens (classic)"),
    all_: bool = Query(False, description="If true, show notifications marked as read.", alias="all"),
    participating: bool = Query(
        False,
        description="If true, only shows notifications in which the user is directly participating or mentioned.",
    ),
    since: str | None = Query(
        None,
        description="Only show results that were last updated after the given time. This is a timestamp in ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ.",
    ),
    before: str | None = Query(
        None,
        description="Only show results that were last updated after the given time. This is a timestamp in ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ.",
    ),
    per_page: int = Query(50, ge=1, le=50),
    page: int = Query(1, ge=1),
):
    """
    参数详见文档: https://docs.github.com/en/rest/activity/notifications?apiVersion=2022-11-28#list-notifications-for-the-authenticated-user

    This endpoint does not work with GitHub App user access tokens, GitHub App installation access tokens, or fine-grained personal access tokens.
    """
    return await build_notifications_feed(req, token, all_, participating, since, before, per_page, page)


@router.get(
    "/user",
    summary="Github Repo Notifications RSS",
)
async def notifications_without_path_token(
    req: Request,
    token: str | None = Query(
        None,
        description="Github User API Token, Personal access tokens (classic). 可与 X-Github-Api-Token 二选一；若同时提供则优先使用 X-Github-Api-Token",
    ),
    x_github_api_token: str | None = Header(
        None,
        description="Github User API Token, Personal access tokens (classic). 可与 query 参数 token 二选一；若同时提供则优先使用当前请求头",
        alias="X-Github-Api-Token",
    ),
    all_: bool = Query(False, description="If true, show notifications marked as read.", alias="all"),
    participating: bool = Query(
        False,
        description="If true, only shows notifications in which the user is directly participating or mentioned.",
    ),
    since: str | None = Query(
        None,
        description="Only show results that were last updated after the given time. This is a timestamp in ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ.",
    ),
    before: str | None = Query(
        None,
        description="Only show results that were last updated after the given time. This is a timestamp in ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ.",
    ),
    per_page: int = Query(50, ge=1, le=50),
    page: int = Query(1, ge=1),
):
    """
    Github API Token 支持两种传法，二选一即可：
    - query 参数 `token`
    - 请求头 `X-Github-Api-Token`
    若同时提供，优先使用 `X-Github-Api-Token`

    参数详见文档: https://docs.github.com/en/rest/activity/notifications?apiVersion=2022-11-28#list-notifications-for-the-authenticated-user

    This endpoint does not work with GitHub App user access tokens, GitHub App installation access tokens, or fine-grained personal access tokens.
    """
    effective_token = x_github_api_token if x_github_api_token is not None else token
    if effective_token is None:
        raise HTTPException(
            status_code=422,
            detail="Github API Token is required via query parameter `token` or header `X-Github-Api-Token`",
        )

    return await build_notifications_feed(req, effective_token, all_, participating, since, before, per_page, page)


async def build_notifications_feed(
    req: Request,
    token: str,
    all_: bool,
    participating: bool,
    since: str | None,
    before: str | None,
    per_page: int,
    page: int,
):
    host = req.url.hostname
    items: list[JSONFeedItem] = await fetch_feeds(token, all_, participating, since, before, per_page, page)
    feed = {
        "version": "https://jsonfeed.org/version/1",
        "title": "Github User Notifications",
        "description": "",
        "home_page_url": "https://github.com/notifications",
        "feed_url": f"{req.url.scheme}://{host}{req.url.path}?{req.url.query}",
        "icon": "https://github.com/favicon.ico",
        "favicon": "https://github.com/favicon.ico",
        "items": items,
    }

    return feed


@cached(RandomTTLCache(4096, 300))
async def fetch_feeds(
    token: str,
    all_: bool,
    participating: bool,
    since: str | None,
    before: str | None,
    per_page: int,
    page: int,
) -> list[JSONFeedItem]:
    items = []

    url = "https://api.github.com/notifications"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    headers["Authorization"] = f"Bearer {token}"

    params = {
        "per_page": per_page,
        "page": page,
        "all": all_,
        "participating": participating,
        "since": since,
        "before": before,
    }
    params = {k: v for k, v in params.items() if v is not None}
    async with httpx.AsyncClient(headers=headers) as client:
        res = await client.get(url, params=params)
        if res.is_error:
            raise HTTPException(status_code=res.status_code, detail=res.text)
        notifications: list[NotificationSchema] = [NotificationSchema(**x) for x in res.json()]

    for notification in notifications:
        url = get_url_by_notification(notification)
        payload: dict[str, Any] = {
            "id": f"github-notifications-{notification.id}",
            "url": url,
            "title": f"{notification.subject.type} - {notification.subject.title}",
            "content_text": "",
            "date_published": notification.updated_at,
            "date_modified": notification.updated_at,
            "author": {
                "url": notification.repository.owner.html_url,
                "name": notification.repository.owner.login,
                "avatar": notification.repository.owner.avatar_url,
            },
        }
        items.append(JSONFeedItem(**payload))
    return items


def get_url_by_notification(notification: NotificationSchema) -> str:
    match notification.subject.type:
        case "Release":
            _, _, _, _, owner, repo, _, releaseid = notification.subject.url.split("/")
            return f"https://github.com/{owner}/{repo}/releases"
        case "Issue":
            _, _, _, _, owner, repo, _, issueid = notification.subject.url.split("/")
            return f"https://github.com/{owner}/{repo}/issues/{issueid}"
        case "PullRequest":
            _, _, _, _, owner, repo, _, pullid = notification.subject.url.split("/")
            return f"https://github.com/{owner}/{repo}/pull/{pullid}"

    return cast(str, notification.url)
