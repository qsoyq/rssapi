import inspect
import logging
from collections.abc import Iterator
from urllib.parse import quote

import pytest
from cachetools.keys import hashkey
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from rssapi.applications.douyin.router import (
    get_feeds,
    get_feeds_by_cache,
    router,
    topic_feeds_cache,
    user_feeds_cache,
)
from rssapi.applications.douyin.utils import (
    DouyinCredentialLogFilter,
    normalize_topic,
    parse_cookies,
    playwright_cookies,
    resolve_cookie,
    topic_posts_to_feeds,
)
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeed
from rssapi.core.middlewares.rss import add_middleware
from rssapi.utils.basic import ShelveStorage
from rssapi.utils.rss.douyin import AccessHistory, DouyinPlaywrightTask, to_feeds


def post(index: int, *, hashtag: str = "示例话题", timestamp: int = 1_700_000_000) -> dict:
    return {
        "aweme_id": str(index),
        "create_time": timestamp,
        "item_title": f"作品 {index}",
        "desc": f"作品 {index} #{hashtag}",
        "video_tag": [],
        "text_extra": [{"hashtag_name": hashtag, "type": 1}],
        "author": {
            "sec_uid": f"creator-{index}",
            "nickname": f"作者 {index}",
            "avatar_thumb": {"url_list": [f"https://cdn.example/{index}-avatar.jpg"]},
        },
        "video": {
            "bit_rate": [{"play_addr": {"url_list": [f"https://cdn.example/{index}.mp4"]}}],
            "cover": {"url_list": [f"https://cdn.example/{index}.jpg"]},
        },
    }


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    add_middleware(app)
    user_feeds_cache.clear()
    topic_feeds_cache.clear()
    with TestClient(app) as client:
        yield client
    user_feeds_cache.clear()
    topic_feeds_cache.clear()


def test_legacy_path_keeps_auth_ids_url_and_response(client: TestClient) -> None:
    original = to_feeds("creator", {"aweme_list": [post(1)]})
    user_feeds_cache[hashkey("creator", "sessionid_ss=path-session")] = original
    user_feeds_cache[hashkey("creator", "sessionid_ss=query-session")] = to_feeds("creator", {"aweme_list": [post(2)]})
    user_feeds_cache[hashkey("creator", "sessionid_ss=header-session")] = to_feeds(
        "creator", {"aweme_list": [post(3)]}
    )
    path = "/api/rss/douyin/user/creator/path-session"
    response = client.get(path)
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["id"] == "douyin.user.creator.1"
    assert body["feed_url"] == f"http://testserver{path}?"
    assert body["title"] == "作者 1"
    assert body["items"][0]["author"]["url"] == "https://www.douyin.com/user/creator"
    assert body["items"][0]["date_published"] == original[0].date_published
    assert response.headers["content-type"].startswith("application/feed+json")

    overridden = client.get(
        path,
        params={"cookies": "sessionid_ss=query-session", "timeout": 10},
        headers={"X-Douyin-Cookie": "sessionid_ss=header-session"},
    )
    assert overridden.status_code == 200
    assert overridden.json()["items"] == body["items"]
    assert overridden.json()["feed_url"].startswith(f"http://testserver{path}?")


@pytest.mark.parametrize("kind", ["user", "topic"])
def test_new_routes_share_query_header_priority_and_cookie_isolated_cache(client: TestClient, kind: str) -> None:
    for cookie, index in [("sessionid_ss=query-session", 1), ("sessionid_ss=header-session", 2)]:
        if kind == "user":
            user_feeds_cache[hashkey("creator", cookie)] = to_feeds("creator", {"aweme_list": [post(index)]})
        else:
            topic_feeds_cache[hashkey("示例话题", cookie, 15)] = topic_posts_to_feeds("示例话题", [post(index)])
    path = f"/api/rss/douyin/{kind}/{'creator' if kind == 'user' else '示例话题'}"
    query_only = client.get(path, params={"cookies": "sessionid_ss=query-session"})
    header_only = client.get(path, headers={"X-Douyin-Cookie": "sessionid_ss=header-session"})
    both = client.get(
        path,
        params={"cookies": "sessionid_ss=query-session"},
        headers={"X-Douyin-Cookie": "sessionid_ss=header-session"},
    )
    assert query_only.status_code == header_only.status_code == both.status_code == 200
    assert query_only.json()["items"][0]["id"].endswith(".1")
    assert header_only.json()["items"][0]["id"].endswith(".2")
    assert both.json()["items"] == header_only.json()["items"]
    assert "cookies=" not in query_only.json()["feed_url"]
    assert "cookies=" not in both.json()["feed_url"]
    assert "query-session" not in query_only.json()["feed_url"]


@pytest.mark.parametrize("path", ["/api/rss/douyin/user/creator", "/api/rss/douyin/topic/示例话题"])
def test_new_routes_reject_missing_or_empty_credentials(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401
    assert client.get(path, params={"cookies": " "}).status_code == 401
    assert (
        client.get(path, params={"cookies": "sessionid_ss=value"}, headers={"X-Douyin-Cookie": ""}).status_code == 401
    )


def test_topic_normalization_and_publisher_survive_feed_middlewares(client: TestClient) -> None:
    items = topic_posts_to_feeds("示例话题", [post(1), post(2)])
    topic_feeds_cache[hashkey("示例话题", "sessionid_ss=value", 15)] = items
    response = client.get(
        f"/api/rss/douyin/topic/{quote('#示例话题', safe='')}", headers={"X-Douyin-Cookie": "sessionid_ss=value"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["author"]["name"] == "抖音话题订阅"
    assert [item["author"]["name"] for item in body["items"]] == ["作者 1", "作者 2"]
    assert body["icon"] == "https://www.douyin.com/favicon.ico"
    assert items[0].author is not None
    assert items[0].author.avatar == "https://cdn.example/1-avatar.jpg"
    assert (
        client.get("/api/rss/douyin/topic/%23", headers={"X-Douyin-Cookie": "sessionid_ss=value"}).status_code == 422
    )


def test_cookie_parser_preserves_padding_and_header_presence() -> None:
    cookie = " sessionid_ss=value; msToken=abc==; token=part=value; invalid; "
    assert parse_cookies(cookie) == {"sessionid_ss": "value", "msToken": "abc==", "token": "part=value"}
    assert playwright_cookies(cookie, "https://www.douyin.com")[1]["value"] == "abc=="
    assert resolve_cookie("query", " header ") == "header"
    with pytest.raises(HTTPException) as exc:
        resolve_cookie("query", " ")
    assert exc.value.status_code == 401
    assert normalize_topic(" #示例话题 ") == "示例话题"


def test_topic_conversion_handles_gallery_nulls_contained_tags_and_deduplication() -> None:
    gallery = post(2, timestamp=1_700_000_100)
    gallery.update(item_title=None, video_tag=None, video=None, desc="<script>bad()</script> #示例话题")
    gallery["images"] = [{"url_list": ["https://cdn.example/image.jpg?x=1&y=2"]}, None, {"url_list": []}]
    related = post(3, hashtag="示例话题延伸")
    prefixed = post(5, hashtag="关联示例话题")
    unrelated = post(6, hashtag="其他标签")
    unrelated["desc"] = "#示例话题"
    missing_tags = post(7)
    missing_tags["text_extra"] = None
    missing_time = post(4)
    missing_time.pop("create_time")
    items = topic_posts_to_feeds(
        "示例话题", [post(1), gallery, post(1), related, prefixed, unrelated, missing_tags, missing_time]
    )
    feed = JSONFeed.model_validate({"title": "话题订阅", "items": items})
    assert [item.id for item in feed.items] == ["douyin.aweme.2", "douyin.aweme.1", "douyin.aweme.3", "douyin.aweme.5"]
    names = []
    for item in items:
        assert item.author is not None
        names.append(item.author.name)
    assert names == ["作者 2", "作者 1", "作者 3", "作者 5"]
    assert items[0].content_html is not None
    assert items[1].content_html is not None
    assert '<img src="https://cdn.example/image.jpg?x=1&amp;y=2">' in items[0].content_html
    assert "<script>" not in items[0].content_html
    assert "&lt;script&gt;" in items[0].content_html
    assert "<video" in items[1].content_html
    assert items[1].date_published == "2023-11-15T06:13:20+08:00"


def test_topic_openapi_documents_paging_and_matching(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/api/rss/douyin/topic/{topic}"]["get"]
    schema = next(parameter["schema"] for parameter in operation["parameters"] if parameter["name"] == "max_posts")
    assert schema["default"] == 15
    assert schema["minimum"] == 1
    assert schema["maximum"] == 120
    assert "ceil(max_posts / 15)" in operation["description"]
    assert "包含" in operation["description"]
    assert "不补页" in operation["description"]


@pytest.mark.parametrize("max_posts", [0, 121])
def test_topic_rejects_out_of_range_max_posts(client: TestClient, max_posts: int) -> None:
    assert (
        client.get(
            "/api/rss/douyin/topic/示例话题",
            params={"max_posts": max_posts},
            headers={"X-Douyin-Cookie": "sessionid_ss=value"},
        ).status_code
        == 422
    )


@pytest.mark.parametrize("max_posts", [15, 16, 45, 46, 120])
def test_topic_accepts_page_boundaries(client: TestClient, max_posts: int) -> None:
    topic_feeds_cache[hashkey("示例话题", "sessionid_ss=value", max_posts)] = topic_posts_to_feeds(
        "示例话题", [post(1)]
    )
    response = client.get(
        "/api/rss/douyin/topic/示例话题",
        params={"max_posts": max_posts},
        headers={"X-Douyin-Cookie": "sessionid_ss=value"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_history_and_background_function_contract_are_unchanged(tmp_path) -> None:
    assert list(inspect.signature(get_feeds).parameters) == ["username", "cookie"]
    assert list(inspect.signature(get_feeds_by_cache).parameters) == ["username", "cookie"]
    previous_storage = AccessHistory.storage
    AccessHistory.storage = ShelveStorage(tmp_path / "douyin.history")
    try:
        await AccessHistory.append("creator", "sessionid_ss=legacy-session")
        assert await AccessHistory.get_history(shuffle=False) == [
            DouyinPlaywrightTask("creator", "sessionid_ss=legacy-session")
        ]
        await AccessHistory.append("creator", "sessionid_ss=new-session; msToken=abc==")
        assert (await AccessHistory.get_history(shuffle=False))[0].cookie == "sessionid_ss=new-session; msToken=abc=="
    finally:
        AccessHistory.storage = previous_storage


def test_access_and_http_client_logs_redact_credentials() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/api/rss/douyin/user/name/path-secret?cookies=sessionid_ss%3Dquery-secret", "1.1", 200),
        None,
    )
    filter_ = DouyinCredentialLogFilter()
    assert filter_.filter(record)
    assert "path-secret" not in record.getMessage()
    assert "query-secret" not in record.getMessage()
    assert isinstance(record.args, tuple)
    assert record.args[-1] == 200
    request_record = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        "GET %s %s",
        ("https://www.douyin.com/api?msToken=token-secret", "200 OK"),
        None,
    )
    assert filter_.filter(request_record)
    assert "token-secret" not in request_record.getMessage()
