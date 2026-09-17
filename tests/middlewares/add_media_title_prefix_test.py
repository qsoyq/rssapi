from typing import Any, cast

import pytest

from rssapi.core.middlewares.rss import AddMediaTitlePrefixMiddleware


def _make_item(*, title: str | None, content_html: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": "1"}
    if title is not None:
        payload["title"] = title
    if content_html is not None:
        payload["content_html"] = content_html
    return payload


@pytest.fixture
def middleware() -> AddMediaTitlePrefixMiddleware:
    return AddMediaTitlePrefixMiddleware(app=cast(Any, None))


class TestAddMediaTitlePrefixMiddleware:
    def test_add_audio_video_prefix(self, middleware: AddMediaTitlePrefixMiddleware):
        item = _make_item(
            title="Audio video",
            content_html='<video src="https://proxy.example.com/api/convert/dash/mp4?dash_url=abc"></video>',
        )

        result = middleware.transform_item(item)

        assert result["title"] == "🔊 Audio video"

    def test_add_video_prefix_for_iframe_embed(self, middleware: AddMediaTitlePrefixMiddleware):
        item = _make_item(
            title="Embedded video",
            content_html='<iframe src="https://www.youtube.com/embed/demo"></iframe>',
        )

        result = middleware.transform_item(item)

        assert result["title"] == "▶️ Embedded video"

    def test_add_gallery_prefix_for_multiple_images(self, middleware: AddMediaTitlePrefixMiddleware):
        item = _make_item(
            title="Gallery post",
            content_html='<div><img src="https://example.com/1.jpg" /><img src="https://example.com/2.jpg" /></div>',
        )

        result = middleware.transform_item(item)

        assert result["title"] == "📸 Gallery post"

    def test_add_gif_prefix_for_looping_video(self, middleware: AddMediaTitlePrefixMiddleware):
        item = _make_item(
            title="Gif clip",
            content_html='<video autoplay loop muted src="https://example.com/clip.mp4"></video>',
        )

        result = middleware.transform_item(item)

        assert result["title"] == "🎞️ Gif clip"

    def test_add_preview_image_prefix_for_single_image(self, middleware: AddMediaTitlePrefixMiddleware):
        item = _make_item(
            title="Preview image",
            content_html='<p><img src="https://example.com/preview.jpg" /></p>',
        )

        result = middleware.transform_item(item)

        assert result["title"] == "🖼️ Preview image"

    def test_add_multiple_prefixes(self, middleware: AddMediaTitlePrefixMiddleware):
        item = _make_item(
            title="Mixed media",
            content_html=(
                '<video src="https://proxy.example.com/api/convert/dash/mp4?dash_url=abc"></video>'
                '<div><img src="https://example.com/1.jpg" /><img src="https://example.com/2.jpg" /></div>'
            ),
        )

        result = middleware.transform_item(item)

        assert result["title"] == "📸 🔊 Mixed media"

    def test_keep_existing_media_prefix(self, middleware: AddMediaTitlePrefixMiddleware):
        item = _make_item(
            title="▶️ Existing title",
            content_html='<iframe src="https://www.youtube.com/embed/demo"></iframe>',
        )

        result = middleware.transform_item(item)

        assert result["title"] == "▶️ Existing title"

    def test_keep_multiple_existing_media_prefixes(self, middleware: AddMediaTitlePrefixMiddleware):
        item = _make_item(
            title="🔊 📸 Existing title",
            content_html=(
                '<video src="https://proxy.example.com/api/convert/dash/mp4?dash_url=abc"></video>'
                '<div><img src="https://example.com/1.jpg" /><img src="https://example.com/2.jpg" /></div>'
            ),
        )

        result = middleware.transform_item(item)

        assert result["title"] == "🔊 📸 Existing title"

    def test_add_missing_prefixes_after_existing_prefixes(self, middleware: AddMediaTitlePrefixMiddleware):
        item = _make_item(
            title="▶️ Existing title",
            content_html=(
                '<iframe src="https://www.youtube.com/embed/demo"></iframe>'
                '<p><img src="https://example.com/preview.jpg" /></p>'
            ),
        )

        result = middleware.transform_item(item)

        assert result["title"] == "🖼️ ▶️ Existing title"

    def test_weibo_emoji_does_not_add_preview_image_prefix(self, middleware: AddMediaTitlePrefixMiddleware):
        item = _make_item(
            title="门口遇到两只猫猫打架，奶牛猫在追狸花猫。我高声喝止！",
            content_html=(
                "<details><summary>查看正文</summary><p>"
                '<img class="weibo-emoji" alt="[兔子]" '
                'src="https://face.t.sinajs.cn/t4/appstyle/expression/ext/normal/ba/201810_tuzi_mobile.png" '
                'width="20" height="20" />今天又维护了猫猫世界的和平</p></details>'
            ),
        )

        result = middleware.transform_item(item)

        assert result["title"] == "门口遇到两只猫猫打架，奶牛猫在追狸花猫。我高声喝止！"
        assert "<img" not in result["title"]

    def test_weibo_emoji_with_content_image_still_adds_preview_prefix(self, middleware: AddMediaTitlePrefixMiddleware):
        item = _make_item(
            title="睡觉的两小只[兔子]",
            content_html=(
                '<div><img src="https://wx2.sinaimg.cn/large/cat.jpg" alt="Weibo image" /></div>'
                '<p><img class="weibo-emoji" alt="[兔子]" '
                'src="https://face.t.sinajs.cn/t4/appstyle/expression/ext/normal/ba/201810_tuzi_mobile.png" /></p>'
            ),
        )

        result = middleware.transform_item(item)

        assert result["title"] == "🖼️ 睡觉的两小只[兔子]"
