import pytest

from rssapi.core.settings import AppSettings, TikTokSettings


def test_tiktok_playwright_defaults() -> None:
    settings = TikTokSettings()

    assert settings.playwright_timeout == 35.0
    assert settings.playwright_queue_timeout == 35.0
    assert settings.playwright_startup_timeout == 5.0
    assert settings.playwright_navigation_timeout == 15.0
    assert settings.playwright_concurrency == 1
    assert settings.playwright_max_inflight == 3
    assert settings.playwright_storage_state_path is None
    assert settings.cookie_query_enabled is True
    assert settings.v2_media_mode == "direct"


def test_tiktok_playwright_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RSS_TIKTOK_PLAYWRIGHT_TIMEOUT", "45")
    monkeypatch.setenv("RSS_TIKTOK_PLAYWRIGHT_QUEUE_TIMEOUT", "6")
    monkeypatch.setenv("RSS_TIKTOK_PLAYWRIGHT_STARTUP_TIMEOUT", "7")
    monkeypatch.setenv("RSS_TIKTOK_PLAYWRIGHT_NAVIGATION_TIMEOUT", "20")
    monkeypatch.setenv("RSS_TIKTOK_PLAYWRIGHT_CONCURRENCY", "2")
    monkeypatch.setenv("RSS_TIKTOK_PLAYWRIGHT_MAX_INFLIGHT", "4")
    monkeypatch.setenv("RSS_TIKTOK_PLAYWRIGHT_STORAGE_STATE_PATH", "/run/secrets/tiktok-state.json")
    monkeypatch.setenv("RSS_TIKTOK_COOKIE_QUERY_ENABLED", "false")
    monkeypatch.setenv("RSS_TIKTOK_V2_MEDIA_MODE", "proxy")

    settings = TikTokSettings()

    assert settings.playwright_timeout == 45.0
    assert settings.playwright_queue_timeout == 6.0
    assert settings.playwright_startup_timeout == 7.0
    assert settings.playwright_navigation_timeout == 20.0
    assert settings.playwright_concurrency == 2
    assert settings.playwright_max_inflight == 4
    assert settings.playwright_storage_state_path == "/run/secrets/tiktok-state.json"
    assert settings.cookie_query_enabled is False
    assert settings.v2_media_mode == "proxy"


def test_global_playwright_concurrency_can_be_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RSS_PLAYWRIGHT_CONCURRENCY", "13")

    settings = AppSettings()

    assert settings.rss_playwright_concurrency == 13
