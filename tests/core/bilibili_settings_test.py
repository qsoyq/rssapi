import pytest

from rssapi.core.settings import BilibiliSettings


class TestBilibiliSettings:
    def test_media_url_template_default(self):
        settings = BilibiliSettings()

        assert settings.media_url_template is None

    def test_media_url_template_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RSS_BILIBILI_MEDIA_URL_TEMPLATE", "https://example.org/api/bilibili/video/{bvid}")
        settings = BilibiliSettings()

        assert settings.media_url_template == "https://example.org/api/bilibili/video/{bvid}"
