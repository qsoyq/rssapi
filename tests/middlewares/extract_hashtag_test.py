from typing import Any, cast

import pytest

from rssapi.core.middlewares.rss import ExtractHashtagMiddleware


def _make_item(*, content_text=None, content_html=None, tags=None) -> dict:
    payload = {"id": "1"}
    if content_text is not None:
        payload["content_text"] = content_text
    if content_html is not None:
        payload["content_html"] = content_html
    if tags is not None:
        payload["tags"] = tags
    return payload


@pytest.fixture
def middleware() -> ExtractHashtagMiddleware:
    return ExtractHashtagMiddleware(app=cast(Any, None))


class TestExtractHashtags:
    def test_extract_from_content_text(self, middleware: ExtractHashtagMiddleware):
        item = _make_item(content_text="hello #world #python")
        result = middleware.extract_hashtags(item)
        assert result["tags"] == ["#python", "#world"]

    def test_extract_chinese_hashtag(self, middleware):
        item = _make_item(content_text="今天 #广告 #互推 来了")
        result = middleware.extract_hashtags(item)
        assert "#广告" in result["tags"]
        assert "#互推" in result["tags"]

    def test_fallback_to_content_html(self, middleware: ExtractHashtagMiddleware):
        item = _make_item(content_html="<p>check #design trends</p>")
        result = middleware.extract_hashtags(item)
        assert "#design" in result["tags"]

    def test_content_text_preferred_over_html(self, middleware: ExtractHashtagMiddleware):
        item = _make_item(
            content_text="only #textTag here",
            content_html="<p>only #htmlTag here</p>",
        )
        result = middleware.extract_hashtags(item)
        assert "#textTag" in result["tags"]
        assert "#htmlTag" not in result["tags"]

    def test_merge_with_existing_tags(self, middleware: ExtractHashtagMiddleware):
        item = _make_item(content_text="#new content", tags=["#existing"])
        result = middleware.extract_hashtags(item)
        assert "#existing" in result["tags"]
        assert "#new" in result["tags"]

    def test_no_duplicate_tags(self, middleware: ExtractHashtagMiddleware):
        item = _make_item(content_text="#dup #dup #dup")
        result = middleware.extract_hashtags(item)
        assert result["tags"] == ["#dup"]

    def test_no_hashtag_returns_none(self, middleware: ExtractHashtagMiddleware):
        item = _make_item(content_text="no tags here")
        result = middleware.extract_hashtags(item)
        assert result["tags"] is None

    def test_tags_are_sorted(self, middleware: ExtractHashtagMiddleware):
        item = _make_item(content_text="#zebra #alpha #mid")
        result = middleware.extract_hashtags(item)
        assert result["tags"] == ["#alpha", "#mid", "#zebra"]

    def test_hashtag_with_numbers(
        self,
        middleware: ExtractHashtagMiddleware,
    ):
        item = _make_item(content_text="#100DaysOfCode #python3")
        result = middleware.extract_hashtags(item)
        assert "#100DaysOfCode" in result["tags"]
        assert "#python3" in result["tags"]

    def test_hashtag_at_line_boundary(self, middleware: ExtractHashtagMiddleware):
        item = _make_item(content_text="#start\nmiddle\n#end")
        result = middleware.extract_hashtags(item)
        assert "#start" in result["tags"]
        assert "#end" in result["tags"]

    def test_existing_tags_preserved_when_no_new_found(self, middleware: ExtractHashtagMiddleware):
        item = _make_item(content_text="plain text", tags=["#keep"])
        result = middleware.extract_hashtags(item)
        assert result["tags"] == ["#keep"]
