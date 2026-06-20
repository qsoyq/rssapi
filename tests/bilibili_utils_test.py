import pytest
from fastapi import HTTPException

from rssapi.applications.bilibili.utils import (
    BILIBILI_API_BASE,
    _extract_playable_url_from_playurl_data,
    _extract_video_cid,
    _extract_wbi_key,
    _raise_for_bilibili_error,
    fetch_user_submissions,
    format_duration,
    normalize_url,
    sign_wbi_params,
    timestamp_to_iso,
    video_to_jsonfeed_item,
)
from rssapi.applications.rss.schemas.rss.jsonfeed import JSONFeedAuthor


def test_normalize_bilibili_url():
    assert normalize_url("//i0.hdslb.com/bfs/archive/cover.jpg") == "https://i0.hdslb.com/bfs/archive/cover.jpg"
    assert normalize_url("http://i0.hdslb.com/bfs/archive/cover.jpg") == "https://i0.hdslb.com/bfs/archive/cover.jpg"
    assert normalize_url("https://i0.hdslb.com/bfs/archive/cover.jpg") == "https://i0.hdslb.com/bfs/archive/cover.jpg"
    assert normalize_url(None) is None


def test_timestamp_to_iso():
    assert timestamp_to_iso(1710000000) == "2024-03-09T16:00:00+00:00"
    assert timestamp_to_iso(None) is None


def test_format_duration():
    assert format_duration(191) == "3:11"
    assert format_duration(3661) == "1:01:01"
    assert format_duration("12:34") == "12:34"
    assert format_duration(None) is None


def test_video_to_jsonfeed_item():
    author = JSONFeedAuthor.model_validate(
        {
            "name": "初夏ChuXXia",
            "url": "https://space.bilibili.com/4186021",
            "avatar": "https://i1.hdslb.com/bfs/face/avatar.jpg",
        }
    )
    item = video_to_jsonfeed_item(
        {
            "aid": 123,
            "bvid": "BV1xx411c7mD",
            "title": "测试视频",
            "description": "测试简介",
            "pic": "//i0.hdslb.com/bfs/archive/cover.jpg",
            "created": 1710000000,
            "play": 100,
            "video_review": 20,
            "comment": 3,
            "length": "12:34",
        },
        author,
    )

    assert item.id == "bilibili-video-BV1xx411c7mD"
    assert str(item.url) == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert str(item.image) == "https://i0.hdslb.com/bfs/archive/cover.jpg"
    assert item.date_published == "2024-03-09T16:00:00+00:00"
    assert item.author == author
    assert "播放: 100" in (item.content_html or "")
    assert "<video" not in (item.content_html or "")
    assert '<img src="https://i0.hdslb.com/bfs/archive/cover.jpg"' in (item.content_html or "")


def test_video_to_jsonfeed_item_renders_playable_video():
    author = JSONFeedAuthor.model_validate({"name": "小镇阿橙", "url": "https://space.bilibili.com/507243527"})
    item = video_to_jsonfeed_item(
        {
            "aid": 123,
            "bvid": "BV1gGjB6qEnR",
            "title": "终于提车了，天天跑，油也贵了换成电车",
            "description": "测试简介",
            "pic": "//i2.hdslb.com/bfs/archive/cover.jpg",
            "created": 1781887930,
            "length": "10:36",
            "playable_url": "http://upos-sz-mirror.example.com/video.mp4?token=abc&deadline=1781890000",
        },
        author,
    )

    content_html = item.content_html or ""
    assert "<video " in content_html
    assert "controls" in content_html
    assert 'preload="metadata"' in content_html
    assert 'src="https://upos-sz-mirror.example.com/video.mp4?token=abc&amp;deadline=1781890000"' in content_html
    assert 'poster="https://i2.hdslb.com/bfs/archive/cover.jpg"' in content_html
    assert "<img " not in content_html
    assert "SESSDATA" not in content_html


def test_extract_video_cid_prefers_video_field():
    assert _extract_video_cid({"cid": 100}, {"cid": 200}) == 100


def test_extract_video_cid_from_view_pages():
    assert _extract_video_cid({}, {"pages": [{"cid": 300}]}) == 300


def test_extract_playable_url_from_durl():
    assert (
        _extract_playable_url_from_playurl_data(
            {
                "durl": [
                    {
                        "url": "http://upos-sz-mirror.example.com/video.mp4",
                        "backup_url": ["https://backup.example.com/video.mp4"],
                    }
                ]
            }
        )
        == "https://upos-sz-mirror.example.com/video.mp4"
    )


def test_extract_playable_url_from_dash_video_fallback():
    assert (
        _extract_playable_url_from_playurl_data(
            {
                "dash": {
                    "video": [
                        {
                            "base_url": "",
                            "backup_url": ["//upos-sz-mirror.example.com/video.m4s"],
                        }
                    ]
                }
            }
        )
        == "https://upos-sz-mirror.example.com/video.m4s"
    )


def test_raise_for_bilibili_error():
    with pytest.raises(HTTPException) as exc_info:
        _raise_for_bilibili_error({"code": -352, "message": "风控校验失败"}, "user videos")

    assert exc_info.value.status_code == 502
    assert "风控校验失败" in exc_info.value.detail


def test_raise_for_bilibili_rate_limit_error():
    with pytest.raises(HTTPException) as exc_info:
        _raise_for_bilibili_error({"code": -799, "message": "请求过于频繁，请稍后再试"}, "user videos")

    assert exc_info.value.status_code == 429
    assert "请求过于频繁" in exc_info.value.detail


def test_extract_wbi_key():
    img_url = "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png"
    sub_url = "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png"
    assert _extract_wbi_key(img_url) == "7cd084941338484aae1ad9425b84077c"
    assert _extract_wbi_key(sub_url) == "4932caff0ff746eab6f01bf08b70ac45"


def test_sign_wbi_params():
    signed = sign_wbi_params(
        {"mid": 4186021, "ps": 30},
        "7cd084941338484aae1ad9425b84077c",
        "4932caff0ff746eab6f01bf08b70ac45",
    )
    assert isinstance(signed["wts"], int)
    assert len(signed["w_rid"]) == 32
    # 原始参数保留
    assert signed["mid"] == 4186021
    assert signed["ps"] == 30


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    """按 URL 分派的假 curl_cffi 会话，用于隔离网络。"""

    def __init__(self, nav: _FakeResponse, arc: _FakeResponse):
        self._nav = nav
        self._arc = arc

    def get(self, url: str, params=None):
        if url.endswith("/x/web-interface/nav"):
            return self._nav
        if url.endswith("/x/space/wbi/arc/search"):
            assert params and "w_rid" in params and "wts" in params
            return self._arc
        raise AssertionError(f"unexpected url: {url}")


_NAV_OK = _FakeResponse(
    200,
    {
        "code": -101,  # 未登录仍带 wbi_img
        "data": {
            "wbi_img": {
                "img_url": f"{BILIBILI_API_BASE}/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                "sub_url": f"{BILIBILI_API_BASE}/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
            }
        },
    },
)


@pytest.mark.asyncio
async def test_fetch_user_submissions_parses_vlist():
    arc = _FakeResponse(
        200,
        {
            "code": 0,
            "data": {
                "list": {
                    "vlist": [
                        {
                            "aid": 1,
                            "bvid": "BV1aa",
                            "title": "投稿A",
                            "description": "简介A",
                            "pic": "//i0.hdslb.com/a.jpg",
                            "created": 1710000000,
                            "length": "3:11",
                            "play": 100,
                            "video_review": 20,
                            "comment": 3,
                        },
                        {"aid": 2, "bvid": "BV1bb", "title": "投稿B", "created": 1709990000},
                        {"aid": 3, "bvid": "BV1cc", "title": "投稿C", "created": 1709980000},
                    ]
                }
            },
        },
    )
    client = _FakeClient(_NAV_OK, arc)
    videos = await fetch_user_submissions(client, 4186021, 2)
    assert [v["bvid"] for v in videos] == ["BV1aa", "BV1bb"]
    assert videos[0]["title"] == "投稿A"


@pytest.mark.asyncio
async def test_fetch_user_submissions_rate_limit():
    arc = _FakeResponse(200, {"code": -799, "message": "请求过于频繁，请稍后再试"})
    client = _FakeClient(_NAV_OK, arc)
    with pytest.raises(HTTPException) as exc_info:
        await fetch_user_submissions(client, 4186021, 30)
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_fetch_user_submissions_http_412():
    arc = _FakeResponse(412, {}, text="rejected")
    client = _FakeClient(_NAV_OK, arc)
    with pytest.raises(HTTPException) as exc_info:
        await fetch_user_submissions(client, 4186021, 30)
    assert exc_info.value.status_code == 429
