from collections.abc import Iterator

import pytest

from rssapi.core.settings import settings
from rssapi.utils.html import render_collapsible_body


@pytest.fixture(params=[True, False], ids=["enabled", "disabled"])
def collapse_enabled(request: pytest.FixtureRequest) -> Iterator[bool]:
    previous = settings.rss_collapse_body_enabled
    enabled = request.param
    settings.rss_collapse_body_enabled = enabled
    try:
        yield enabled
    finally:
        settings.rss_collapse_body_enabled = previous


@pytest.mark.parametrize(
    "content_html",
    [
        "",
        "正文",
        "<p>正文</p>",
        '<p>A &amp; B<br>下一行</p>\n<blockquote><a href="https://example.com">引用</a></blockquote>',
    ],
)
def test_render_collapsible_body_preserves_html(content_html: str, collapse_enabled: bool) -> None:
    result = render_collapsible_body(content_html)

    if collapse_enabled and content_html:
        assert result == f"<details><summary>查看正文</summary>{content_html}</details>"
    else:
        assert result == content_html
