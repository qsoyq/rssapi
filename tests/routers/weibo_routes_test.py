import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from rssapi.applications.weibo import router as weibo_router
from rssapi.applications.weibo.utils import (
    build_home_feed,
    build_user_feed,
    extract_sub_cookie,
    fetch_home_feed_data,
    fetch_post_media_video,
    fetch_post_media_video_by_cache,
    fetch_user_feed_data,
    post_to_jsonfeed_item,
)
from rssapi.main import app


def _user() -> dict[str, Any]:
    return {
        "id": "1842706721",
        "screen_name": "微博测试用户",
        "description": "<b>测试简介</b>",
        "avatar_hd": "https://cdn.example/avatar.jpg",
    }


def _post(index: int, *, is_long_text: bool = False) -> dict[str, Any]:
    return {
        "id": f"post-{index}",
        "idstr": f"post-{index}",
        "mblogid": f"Mblog{index}",
        "created_at": "Mon Sep 01 12:34:56 +0800 2026",
        "text_raw": f"Post {index}",
        "isLongText": is_long_text,
        "isAd": False,
        "reposts_count": index,
        "comments_count": index + 1,
        "attitudes_count": index + 2,
        "source": "<a>Weibo Web</a>",
        "user": _user(),
        "pic_ids": [f"image-{index}"],
        "pic_infos": {f"image-{index}": {"largest": {"url": f"https://cdn.example/image-{index}.jpg?x=1&y=2"}}},
    }


def _profile_payload(user: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": 1, "data": {"user": user or _user()}}


def _posts_payload(posts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"ok": 1, "data": {"list": posts, "since_id": "next-page"}}


def _home_payload(posts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"ok": 1, "statuses": posts, "since_id": "next-page"}


class LocalWeiboUpstream:
    def __init__(self) -> None:
        self.profile_response: tuple[int, Any, float] = (200, _profile_payload(), 0.0)
        self.page_responses: dict[int, tuple[int, Any, float]] = {}
        self.home_responses: dict[str, tuple[int, Any, float]] = {}
        self.long_text_responses: dict[str, tuple[int, Any, float]] = {}
        self.show_responses: dict[str, tuple[int, Any, float]] = {}
        self.requests: list[dict[str, Any]] = []
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                record = {
                    "path": parsed.path,
                    "uid": query.get("uid", [None])[0],
                    "page": query.get("page", [None])[0],
                    "post_id": query.get("id", [None])[0],
                    "feature": query.get("feature", [None])[0],
                    "list_id": query.get("list_id", [None])[0],
                    "count": query.get("count", [None])[0],
                    "refresh": query.get("refresh", [None])[0],
                    "since_id": query.get("since_id", [None])[0],
                    "cookie": self.headers.get("Cookie"),
                    "xsrf": self.headers.get("X-XSRF-TOKEN"),
                }
                controller.requests.append(record)

                if parsed.path == "/ajax/profile/info":
                    status_code, body, delay = controller.profile_response
                elif parsed.path == "/ajax/statuses/mymblog":
                    page = int(query.get("page", ["1"])[0])
                    status_code, body, delay = controller.page_responses.get(page, (404, "not found", 0.0))
                elif parsed.path == "/ajax/statuses/longtext":
                    post_id = query.get("id", [""])[0]
                    status_code, body, delay = controller.long_text_responses.get(post_id, (404, "not found", 0.0))
                elif parsed.path == "/ajax/statuses/show":
                    post_id = query.get("id", [""])[0]
                    status_code, body, delay = controller.show_responses.get(post_id, (404, "not found", 0.0))
                elif parsed.path in {"/ajax/feed/friendstimeline", "/ajax/feed/unreadfriendstimeline"}:
                    status_code, body, delay = controller.home_responses.get(parsed.path, (404, "not found", 0.0))
                else:
                    status_code, body, delay = 404, "not found", 0.0

                if delay:
                    time.sleep(delay)
                payload = json.dumps(body).encode() if isinstance(body, dict) else str(body).encode()
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except BrokenPipeError:
                    pass

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        address = self.server.server_address
        host_value = address[0]
        port = int(address[1])
        host = host_value.decode() if isinstance(host_value, bytes) else str(host_value)
        return f"http://{host}:{port}"

    def add_page(
        self,
        page: int,
        posts: list[dict[str, Any]] | Any,
        *,
        status_code: int = 200,
        delay: float = 0.0,
    ) -> None:
        body = _posts_payload(posts) if isinstance(posts, list) else posts
        self.page_responses[page] = (status_code, body, delay)

    def add_long_text(
        self,
        post_id: str,
        body: Any,
        *,
        status_code: int = 200,
    ) -> None:
        self.long_text_responses[post_id] = (status_code, body, 0.0)

    def add_show(
        self,
        post_id: str,
        body: Any,
        *,
        status_code: int = 200,
    ) -> None:
        self.show_responses[post_id] = (status_code, body, 0.0)

    def add_home_timeline(
        self,
        path: str,
        posts: list[dict[str, Any]] | Any,
        *,
        status_code: int = 200,
    ) -> None:
        body = _home_payload(posts) if isinstance(posts, list) else posts
        self.home_responses[path] = (status_code, body, 0.0)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@pytest.fixture
def weibo_upstream() -> Iterator[LocalWeiboUpstream]:
    upstream = LocalWeiboUpstream()
    upstream.start()
    try:
        yield upstream
    finally:
        upstream.close()


def _request(query_string: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "scheme": "https",
            "server": ("rss.example", 443),
            "path": "/api/rss/weibo/1842706721/posts",
            "query_string": query_string,
            "headers": [],
        }
    )


def test_extract_sub_cookie_keeps_only_minimum_credential() -> None:
    assert extract_sub_cookie("SUB=minimum; XSRF-TOKEN=ignored; SUBP=ignored") == "SUB=minimum"
    assert extract_sub_cookie("XSRF-TOKEN=missing-sub") is None
    assert extract_sub_cookie(None) is None


@pytest.mark.asyncio
async def test_fetch_user_feed_paginates_deduplicates_and_only_sends_sub(
    weibo_upstream: LocalWeiboUpstream,
) -> None:
    first_page = [_post(index) for index in range(20)]
    advertisement = _post(999)
    advertisement["isAd"] = True
    first_page.append(advertisement)
    second_page = [_post(index) for index in range(19, 39)]
    weibo_upstream.add_page(1, first_page)
    weibo_upstream.add_page(2, second_page)

    user, posts = await fetch_user_feed_data(
        1842706721,
        25,
        sub_cookie="SUB=minimum",
        base_url=weibo_upstream.base_url,
    )

    assert user["screen_name"] == "微博测试用户"
    assert [post["idstr"] for post in posts] == [f"post-{index}" for index in range(25)]
    post_requests = [request for request in weibo_upstream.requests if request["path"] == "/ajax/statuses/mymblog"]
    assert [request["page"] for request in post_requests] == ["1", "2"]
    assert all(request["uid"] == "1842706721" for request in post_requests)
    assert all(request["feature"] == "0" for request in post_requests)
    assert all(request["cookie"] == "SUB=minimum" for request in weibo_upstream.requests)
    assert all(request["xsrf"] is None for request in weibo_upstream.requests)


@pytest.mark.asyncio
async def test_fetch_user_feed_expands_long_text_and_falls_back_on_failure(
    weibo_upstream: LocalWeiboUpstream,
) -> None:
    expanded = _post(1, is_long_text=True)
    fallback = _post(2, is_long_text=True)
    fallback["text_raw"] = "List fallback"
    weibo_upstream.add_page(1, [expanded, fallback])
    weibo_upstream.add_long_text(
        "Mblog1",
        {"ok": 1, "data": {"longTextContent": "<p>Expanded <strong>long text</strong></p>"}},
    )
    weibo_upstream.add_long_text("Mblog2", "upstream failure", status_code=500)

    _, posts = await fetch_user_feed_data(
        1842706721,
        12,
        sub_cookie="SUB=minimum",
        base_url=weibo_upstream.base_url,
    )

    assert "Expanded" in posts[0]["text_raw"]
    assert "long text" in posts[0]["text_raw"]
    assert posts[1]["text_raw"] == "List fallback"
    long_text_requests = [
        request for request in weibo_upstream.requests if request["path"] == "/ajax/statuses/longtext"
    ]
    assert [request["post_id"] for request in long_text_requests] == ["Mblog1", "Mblog2"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "body", "expected_status"),
    [
        (404, "not found", 404),
        (429, "limited", 429),
        (432, "rejected", 429),
        (200, {"ok": -100, "data": {}}, 401),
        (200, "not json", 502),
        (200, {"ok": 1, "data": {}}, 502),
    ],
)
async def test_fetch_user_feed_maps_profile_errors(
    weibo_upstream: LocalWeiboUpstream,
    status_code: int,
    body: Any,
    expected_status: int,
) -> None:
    weibo_upstream.profile_response = (status_code, body, 0.0)

    with pytest.raises(HTTPException) as exc_info:
        await fetch_user_feed_data(
            1842706721,
            12,
            sub_cookie="SUB=minimum",
            base_url=weibo_upstream.base_url,
        )

    assert exc_info.value.status_code == expected_status


@pytest.mark.asyncio
async def test_fetch_user_feed_maps_timeout(weibo_upstream: LocalWeiboUpstream) -> None:
    weibo_upstream.profile_response = (200, _profile_payload(), 0.1)

    with pytest.raises(HTTPException) as exc_info:
        await fetch_user_feed_data(
            1842706721,
            12,
            sub_cookie="SUB=minimum",
            base_url=weibo_upstream.base_url,
            timeout=0.01,
        )

    assert exc_info.value.status_code == 504


@pytest.mark.asyncio
async def test_fetch_follow_home_feed_uses_friend_timeline_and_resolves_long_text(
    weibo_upstream: LocalWeiboUpstream,
) -> None:
    long_post = _post(1, is_long_text=True)
    advertisement = _post(2)
    advertisement["isAd"] = True
    invalid_card = {"id": "card-1", "text_raw": "not a post"}
    weibo_upstream.add_home_timeline(
        "/ajax/feed/friendstimeline",
        [long_post, advertisement, long_post, invalid_card],
    )
    weibo_upstream.add_long_text("Mblog1", {"ok": 1, "data": {"longTextContent": "<p>Expanded home text</p>"}})

    posts = await fetch_home_feed_data(
        "follow",
        20,
        sub_cookie="SUB=minimum",
        base_url=weibo_upstream.base_url,
    )

    assert [post["idstr"] for post in posts] == ["post-1"]
    assert posts[0]["text_raw"] == "Expanded home text"
    home_request = next(
        request for request in weibo_upstream.requests if request["path"] == "/ajax/feed/friendstimeline"
    )
    assert home_request["list_id"] is None
    assert home_request["count"] == "20"
    assert home_request["refresh"] == "4"
    assert home_request["since_id"] is None
    assert not any(request["path"] == "/ajax/setting/getBasicInfo" for request in weibo_upstream.requests)
    assert all(request["cookie"] == "SUB=minimum" for request in weibo_upstream.requests)


@pytest.mark.asyncio
async def test_fetch_for_you_home_feed_excludes_follow_only_parameters(weibo_upstream: LocalWeiboUpstream) -> None:
    weibo_upstream.add_home_timeline("/ajax/feed/unreadfriendstimeline", [_post(1), _post(2)])

    posts = await fetch_home_feed_data(
        "foryou",
        1,
        sub_cookie="SUB=minimum",
        base_url=weibo_upstream.base_url,
    )

    assert [post["idstr"] for post in posts] == ["post-1"]
    home_request = next(
        request for request in weibo_upstream.requests if request["path"] == "/ajax/feed/unreadfriendstimeline"
    )
    assert home_request["list_id"] is None
    assert home_request["since_id"] is None
    assert home_request["count"] == "1"
    assert home_request["refresh"] == "4"


@pytest.mark.asyncio
async def test_fetch_home_feed_requires_statuses_payload(weibo_upstream: LocalWeiboUpstream) -> None:
    weibo_upstream.add_home_timeline("/ajax/feed/friendstimeline", {"ok": 1})

    with pytest.raises(HTTPException) as exc_info:
        await fetch_home_feed_data(
            "follow",
            20,
            sub_cookie="SUB=minimum",
            base_url=weibo_upstream.base_url,
        )

    assert exc_info.value.status_code == 502


def test_post_to_jsonfeed_item_renders_global_media_before_collapsible_text() -> None:
    post = _post(1)
    post["text_raw"] = "<Outer text>\nsecond line"
    post["pic_ids"] = ["outer-image", "live-image"]
    post["pic_infos"] = {
        "outer-image": {"largest": {"url": "https://cdn.example/outer.jpg"}},
        "live-image": {
            "largest": {"url": "https://cdn.example/live-poster.jpg"},
            "videoSrc": "https://cdn.example/live.mp4",
        },
    }
    post["page_info"] = {
        "page_pic": {"url": "https://cdn.example/outer-video-poster.jpg"},
        "urls": {"mp4_720p_mp4": "https://cdn.example/outer-video.mp4"},
    }
    repost = _post(2)
    repost["text_raw"] = "Original text"
    repost["pic_infos"] = {"repost-image": {"largest": {"url": "https://cdn.example/repost.jpg"}}}
    repost["pic_ids"] = ["repost-image"]
    repost["page_info"] = {
        "page_pic": {"url": "https://cdn.example/repost-video-poster.jpg"},
        "urls": {"mp4_hd_mp4": "https://cdn.example/repost-video.mp4"},
    }
    post["retweeted_status"] = repost

    item = post_to_jsonfeed_item(post, _user(), 1842706721)

    content_html = item.content_html or ""
    assert content_html.index("outer.jpg") < content_html.index("live-poster.jpg") < content_html.index("repost.jpg")
    assert (
        content_html.index("live.mp4") < content_html.index("outer-video.mp4") < content_html.index("repost-video.mp4")
    )
    assert content_html.index("repost.jpg") < content_html.index("live.mp4") < content_html.index("<details>")
    assert "&lt;Outer text&gt;<br>second line" in content_html
    assert "转发 @微博测试用户" in content_html
    assert item.attachments and [str(attachment.url) for attachment in item.attachments] == [
        "https://cdn.example/live.mp4",
        "https://cdn.example/outer-video.mp4",
        "https://cdn.example/repost-video.mp4",
    ]
    assert item.image and str(item.image) == "https://cdn.example/outer.jpg"


def test_target_post_livephoto_keeps_cover_and_uses_stable_https_media_url() -> None:
    post = _post(1)
    post["idstr"] = "RfVuw48hg"
    post["mblogid"] = "RfVuw48hg"
    post["text_raw"] = "喝酒不叫我？"
    post["pic_ids"] = ["live-image"]
    post["pic_infos"] = {
        "live-image": {
            "type": "livephoto",
            "largest": {"url": "https://wx1.sinaimg.cn/large/live-cover.jpg"},
            "media_info": {"video_url": "http://f.video.weibocdn.com/live.mp4?Expires=1&ssig=x"},
        }
    }

    item = post_to_jsonfeed_item(post, _user(), 7499813000, req=_request())

    assert item.image and str(item.image) == "https://wx1.sinaimg.cn/large/live-cover.jpg"
    assert item.attachments and [str(attachment.url) for attachment in item.attachments] == [
        "https://rss.example/api/rss/weibo/media/RfVuw48hg/0"
    ]
    content_html = item.content_html or ""
    assert content_html.index("live-cover.jpg") < content_html.index("/media/RfVuw48hg/0")
    assert "http://f.video.weibocdn.com" not in content_html


def test_post_to_jsonfeed_item_skips_invalid_media_urls() -> None:
    post = _post(1)
    post["pic_infos"] = {"bad-image": {"largest": {"url": "javascript:alert(1)"}}}
    post["pic_ids"] = ["bad-image"]
    post["page_info"] = {"urls": {"mp4_720p_mp4": "not-a-url"}}
    post["user"]["avatar_hd"] = "data:text/html,unsafe"

    item = post_to_jsonfeed_item(post, _user(), 1842706721)

    assert "javascript:" not in (item.content_html or "")
    assert "not-a-url" not in (item.content_html or "")
    assert item.image is None
    assert item.attachments is None
    assert item.author and item.author.avatar is None


def test_build_user_feed_hides_cookie_query_parameter() -> None:
    feed = build_user_feed(_request(b"max_posts=12&cookies=SUB%3Dsecret"), 1842706721, _user(), [_post(1)])

    assert feed.title == "微博测试用户 (@1842706721) 的微博"
    assert feed.feed_url and "cookies=" not in str(feed.feed_url)
    assert feed.author and feed.author.avatar == "https://cdn.example/avatar.jpg"


def test_build_home_feed_hides_cookie_query_parameter_and_uses_post_authors() -> None:
    post = _post(1)
    post["user"]["screen_name"] = "首页作者"

    feed = build_home_feed(_request(b"max_posts=12&cookies=SUB%3Dsecret"), "foryou", [post])

    assert feed.title == "微博推荐流"
    assert str(feed.home_page_url) == "https://weibo.com"
    assert feed.feed_url and "cookies=" not in str(feed.feed_url)
    assert feed.author is None
    assert feed.items[0].author and feed.items[0].author.name == "首页作者"


def test_weibo_route_requires_sub_cookie() -> None:
    with TestClient(app) as client:
        no_cookie_response = client.get("/api/rss/weibo/1842706721/posts")
        invalid_cookie_response = client.get(
            "/api/rss/weibo/1842706721/posts",
            headers={"X-Weibo-Cookie": "XSRF-TOKEN=not-enough"},
        )
        follow_response = client.get("/api/rss/weibo/home/follow")
        for_you_response = client.get("/api/rss/weibo/home/foryou")
        openapi = client.get("/openapi.json").json()

    assert no_cookie_response.status_code == 401
    assert invalid_cookie_response.status_code == 401
    assert follow_response.status_code == 401
    assert for_you_response.status_code == 401
    parameters = openapi["paths"]["/api/rss/weibo/{uid}/posts"]["get"]["parameters"]
    max_posts = next(parameter for parameter in parameters if parameter["name"] == "max_posts")
    assert max_posts["schema"]["default"] == 20
    for endpoint in ("/api/rss/weibo/home/follow", "/api/rss/weibo/home/foryou"):
        home_parameters = openapi["paths"][endpoint]["get"]["parameters"]
        home_max_posts = next(parameter for parameter in home_parameters if parameter["name"] == "max_posts")
        assert home_max_posts["schema"]["default"] == 20


def _video_show_payload(
    *,
    video_url: str | None = "https://f.video.weibocdn.com/o0/abc.mp4?Expires=1&ssig=x",
    mblogid: str = "R7sQzgTAY",
    is_ad: bool = False,
) -> dict[str, Any]:
    post = _post(1)
    post["idstr"] = mblogid
    post["mblogid"] = mblogid
    post["isAd"] = is_ad
    post["pic_ids"] = []
    post["pic_infos"] = {}
    if video_url is None:
        post["page_info"] = {}
    else:
        post["page_info"] = {"urls": {"mp4_720p_mp4": video_url}}
    return {"ok": 1, **post}


@pytest.mark.asyncio
async def test_fetch_post_media_video_resolves_by_single_post_id(weibo_upstream: LocalWeiboUpstream) -> None:
    weibo_upstream.add_show("R7sQzgTAY", _video_show_payload())

    url = await fetch_post_media_video("R7sQzgTAY", sub_cookie="SUB=minimum", base_url=weibo_upstream.base_url)

    assert url.startswith("https://f.video.weibocdn.com/")
    assert "Expires=" in url and "ssig=" in url
    show_requests = [request for request in weibo_upstream.requests if request["path"] == "/ajax/statuses/show"]
    assert [request["post_id"] for request in show_requests] == ["R7sQzgTAY"]
    assert all(request["cookie"] == "SUB=minimum" for request in show_requests)


@pytest.mark.asyncio
async def test_fetch_target_post_livephoto_resolves_dynamic_media(weibo_upstream: LocalWeiboUpstream) -> None:
    post = _post(1)
    post["idstr"] = "RfVuw48hg"
    post["mblogid"] = "RfVuw48hg"
    post["pic_ids"] = ["live-image"]
    post["pic_infos"] = {
        "live-image": {
            "type": "livephoto",
            "largest": {"url": "https://wx1.sinaimg.cn/large/live-cover.jpg"},
            "media_info": {"video_url": "https://f.video.weibocdn.com/live.mp4?Expires=1&ssig=x"},
        }
    }
    weibo_upstream.add_show("RfVuw48hg", {"ok": 1, **post})

    url = await fetch_post_media_video("RfVuw48hg", sub_cookie="SUB=minimum", base_url=weibo_upstream.base_url)

    assert url == "https://f.video.weibocdn.com/live.mp4?Expires=1&ssig=x"
    assert [request["post_id"] for request in weibo_upstream.requests if request["path"] == "/ajax/statuses/show"] == [
        "RfVuw48hg"
    ]


@pytest.mark.asyncio
async def test_fetch_post_media_video_requires_sub_cookie(weibo_upstream: LocalWeiboUpstream) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await fetch_post_media_video("R7sQzgTAY", sub_cookie="XSRF-TOKEN=only", base_url=weibo_upstream.base_url)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"ok": 0, "error_code": 20101}, {"ok": -100}])
async def test_fetch_post_media_video_maps_missing_post_and_bad_auth(
    weibo_upstream: LocalWeiboUpstream,
    payload: dict[str, Any],
) -> None:
    weibo_upstream.add_show("R7sQzgTAY", payload)

    expected_status = 401 if payload.get("ok") == -100 else 404
    with pytest.raises(HTTPException) as exc_info:
        await fetch_post_media_video("R7sQzgTAY", sub_cookie="SUB=minimum", base_url=weibo_upstream.base_url)

    assert exc_info.value.status_code == expected_status


@pytest.mark.asyncio
async def test_fetch_post_media_video_rejects_post_without_video(weibo_upstream: LocalWeiboUpstream) -> None:
    weibo_upstream.add_show("R7sQzgTAY", _video_show_payload(video_url=None))

    with pytest.raises(HTTPException) as exc_info:
        await fetch_post_media_video("R7sQzgTAY", sub_cookie="SUB=minimum", base_url=weibo_upstream.base_url)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_fetch_post_media_video_rejects_out_of_range_index(weibo_upstream: LocalWeiboUpstream) -> None:
    weibo_upstream.add_show("R7sQzgTAY", _video_show_payload())

    with pytest.raises(HTTPException) as exc_info:
        await fetch_post_media_video("R7sQzgTAY", 3, sub_cookie="SUB=minimum", base_url=weibo_upstream.base_url)

    assert exc_info.value.status_code == 404


def test_weibo_media_route_redirects_to_fresh_signed_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """302 只应把客户端送去新签发的 https 地址，响应本身不可缓存。"""

    async def fake_resolve(post_id: str, index: int = 0, *, sub_cookie: str, **_: Any) -> str:
        assert post_id == "R7sQzgTAY"
        assert index == 0
        assert sub_cookie == "SUB=minimum"
        return "http://f.video.weibocdn.com/o0/abc.mp4?Expires=1&ssig=x"

    monkeypatch.setattr(weibo_router, "fetch_post_media_video_by_cache", fake_resolve)

    with TestClient(app) as client:
        response = client.get(
            "/api/rss/weibo/media/R7sQzgTAY/0",
            headers={"X-Weibo-Cookie": "SUB=minimum"},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "https://f.video.weibocdn.com/o0/abc.mp4?Expires=1&ssig=x"
    assert response.headers["cache-control"] == "no-store"


def test_weibo_media_route_requires_sub_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(app) as client:
        response = client.get("/api/rss/weibo/media/R7sQzgTAY/0", follow_redirects=False)

    assert response.status_code == 401


def test_weibo_media_route_validates_post_id() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/rss/weibo/media/not-a-valid-id!/0",
            headers={"X-Weibo-Cookie": "SUB=minimum"},
            follow_redirects=False,
        )

    assert response.status_code == 422


def test_weibo_media_route_requires_index_path_segment() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/rss/weibo/media/R7sQzgTAY",
            headers={"X-Weibo-Cookie": "SUB=minimum"},
            follow_redirects=False,
        )

    assert response.status_code == 404


def test_build_user_feed_uses_stable_media_url_for_video_src() -> None:
    post = _post(1)
    post["page_info"] = {"urls": {"mp4_720p_mp4": "https://f.video.weibocdn.com/o0/abc.mp4?Expires=1&ssig=x"}}

    feed = build_user_feed(_request(), 1842706721, _user(), [post])

    item = feed.items[0]
    assert item.attachments and [str(attachment.url) for attachment in item.attachments] == [
        "https://rss.example/api/rss/weibo/media/post-1/0"
    ]
    assert "https://rss.example/api/rss/weibo/media/post-1/0" in (item.content_html or "")
    assert "ssig=x" not in (item.content_html or "")


def test_build_user_feed_keeps_upstream_url_without_request_context() -> None:
    post = _post(1)
    post["page_info"] = {"urls": {"mp4_720p_mp4": "https://f.video.weibocdn.com/o0/abc.mp4?Expires=1&ssig=x"}}

    item = post_to_jsonfeed_item(post, _user(), 1842706721)

    assert item.attachments and [str(attachment.url) for attachment in item.attachments] == [
        "https://f.video.weibocdn.com/o0/abc.mp4?Expires=1&ssig=x"
    ]


def test_build_home_feed_uses_stable_media_url_for_video_src() -> None:
    post = _post(1)
    post["page_info"] = {"urls": {"mp4_720p_mp4": "https://f.video.weibocdn.com/o0/abc.mp4?Expires=1&ssig=x"}}

    feed = build_home_feed(_request(), "follow", [post])

    item = feed.items[0]
    assert item.attachments and [str(attachment.url) for attachment in item.attachments] == [
        "https://rss.example/api/rss/weibo/media/post-1/0"
    ]


@pytest.mark.asyncio
async def test_fetch_post_media_video_by_cache_reuses_result(weibo_upstream: LocalWeiboUpstream) -> None:
    """短 TTL 缓存避免播放器 seek 时反复打上游；key 不含 Cookie。"""
    weibo_upstream.add_show(
        "cache-key-1", _video_show_payload(mblogid="cache-key-1", video_url="https://cdn.example/a.mp4?x=1")
    )

    first = await fetch_post_media_video_by_cache(
        "cache-key-1",
        0,
        sub_cookie="SUB=minimum",
        base_url=weibo_upstream.base_url,
    )
    second = await fetch_post_media_video_by_cache(
        "cache-key-1",
        0,
        sub_cookie="SUB=minimum",
        base_url=weibo_upstream.base_url,
    )

    assert first == second == "https://cdn.example/a.mp4?x=1"
    show_requests = [request for request in weibo_upstream.requests if request["path"] == "/ajax/statuses/show"]
    assert len(show_requests) == 1
