import pytest

from rssapi.core.settings import TikTokSettings


def test_tiktok_playwright_defaults() -> None:
    settings = TikTokSettings()

    assert settings.playwright_timeout == 35.0
    assert settings.playwright_concurrency == 1
    assert settings.playwright_max_inflight == 3
    assert settings.playwright_storage_state_path is None
    assert settings.cookie_query_enabled is True
    assert settings.v2_media_mode == "direct"


def test_tiktok_playwright_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RSS_TIKTOK_PLAYWRIGHT_TIMEOUT", "45")
    monkeypatch.setenv("RSS_TIKTOK_PLAYWRIGHT_CONCURRENCY", "2")
    monkeypatch.setenv("RSS_TIKTOK_PLAYWRIGHT_MAX_INFLIGHT", "4")
    monkeypatch.setenv("RSS_TIKTOK_PLAYWRIGHT_STORAGE_STATE_PATH", "/run/secrets/tiktok-state.json")
    monkeypatch.setenv("RSS_TIKTOK_COOKIE_QUERY_ENABLED", "false")
    monkeypatch.setenv("RSS_TIKTOK_V2_MEDIA_MODE", "proxy")

    settings = TikTokSettings()

    assert settings.playwright_timeout == 45.0
    assert settings.playwright_concurrency == 2
    assert settings.playwright_max_inflight == 4
    assert settings.playwright_storage_state_path == "/run/secrets/tiktok-state.json"
    assert settings.cookie_query_enabled is False
    assert settings.v2_media_mode == "proxy"
