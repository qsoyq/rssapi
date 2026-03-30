from typing import Any, cast

import pytest

from rssapi.core.middlewares.rss import FillImageFromAuthorAvatarMiddleware


def _make_item(*, image: str | None = None, avatar: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "1",
        "content_text": "hello world",
    }
    if image is not None:
        payload["image"] = image
    if avatar is not None:
        payload["author"] = {
            "avatar": avatar,
        }
    return payload


@pytest.fixture
def middleware():
    return FillImageFromAuthorAvatarMiddleware(app=cast(Any, None))


class TestFillImageFromAuthorAvatarMiddleware:
    def test_fill_image_from_valid_http_avatar(self, middleware):
        item = _make_item(avatar="https://example.com/avatar.png")

        result = middleware.transform_item(item)

        assert result["image"] == "https://example.com/avatar.png"

    def test_skip_invalid_data_avatar(self, middleware):
        item = _make_item(avatar="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=")

        result = middleware.transform_item(item)

        assert result["image"] is None

    def test_keep_existing_image(self, middleware):
        item = _make_item(
            image="https://example.com/original.png",
            avatar="https://example.com/avatar.png",
        )

        result = middleware.transform_item(item)

        assert result["image"] == "https://example.com/original.png"
