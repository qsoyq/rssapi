import datetime as _dt
import logging
from typing import Any, Optional, cast

from asyncache import cached
from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from githubkit import GitHub, TokenAuthStrategy
from githubkit.exception import RequestFailed
from githubkit.versions.latest.models import Thread, ThreadPropSubject

from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedItem
from rssapi.core.settings import settings
from rssapi.utils.cache import RandomTTLCache

# GitHub API 实际返回的 latest_comment_url 可能为 null，但 githubkit OpenAPI spec 未标注为 nullable
ThreadPropSubject.__annotations__["latest_comment_url"] = Optional[str]
ThreadPropSubject.model_fields["latest_comment_url"].annotation = Optional[str]  # type: ignore[assignment]
ThreadPropSubject.__pydantic_complete__ = False
ThreadPropSubject.model_rebuild(_types_namespace={"Optional": Optional, "str": str})
Thread.__pydantic_complete__ = False
Thread.model_rebuild(force=True)

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


@cached(RandomTTLCache(settings.github.notification_cache_maxsize, settings.github.notification_cache_ttl))
async def fetch_feeds(
    token: str,
    all_: bool,
    participating: bool,
    since: str | None,
    before: str | None,
    per_page: int,
    page: int,
) -> list[JSONFeedItem]:
    since_dt = _dt.datetime.fromisoformat(since) if since else None
    before_dt = _dt.datetime.fromisoformat(before) if before else None

    kwargs: dict[str, Any] = {
        "all_": all_,
        "participating": participating,
        "per_page": per_page,
        "page": page,
    }
    if since_dt is not None:
        kwargs["since"] = since_dt
    if before_dt is not None:
        kwargs["before"] = before_dt

    try:
        async with GitHub(TokenAuthStrategy(token)) as github:
            resp = await github.rest.activity.async_list_notifications_for_authenticated_user(**kwargs)
    except RequestFailed as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc

    notifications: list[Thread] = resp.parsed_data
    items: list[JSONFeedItem] = []
    for notification in notifications:
        html_url = _get_html_url(notification)
        payload: dict[str, Any] = {
            "id": f"github-notifications-{notification.id}",
            "url": html_url,
            "title": f"{notification.subject.type} - {notification.repository.full_name} - {notification.subject.title}",
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


def _get_html_url(notification: Thread) -> str:
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
