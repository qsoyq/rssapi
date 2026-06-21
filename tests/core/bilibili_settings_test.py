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

    def test_playable_url_fetch_concurrency_default(self):
        settings = BilibiliSettings()

        assert settings.playable_url_fetch_concurrency == 5

    def test_playable_url_fetch_concurrency_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RSS_BILIBILI_PLAYABLE_URL_FETCH_CONCURRENCY", "3")
        settings = BilibiliSettings()

        assert settings.playable_url_fetch_concurrency == 3
