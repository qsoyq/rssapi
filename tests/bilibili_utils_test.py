import pytest
from fastapi import HTTPException

from rssapi.applications.bilibili.utils import (
    _raise_for_bilibili_error,
    format_duration,
    normalize_url,
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
