import pytest

from rssapi.core.settings import MiddlewareSettings


def test_clear_home_page_url_enabled_defaults_to_true() -> None:
    settings = MiddlewareSettings()

    assert settings.clear_home_page_url_enabled is True


def test_clear_home_page_url_enabled_accepts_short_boolean_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RSS_MIDDLEWARE_CLEAR_HOME_PAGE_URL_ENABLED", "t")
    assert MiddlewareSettings().clear_home_page_url_enabled is True

    monkeypatch.setenv("RSS_MIDDLEWARE_CLEAR_HOME_PAGE_URL_ENABLED", "f")
    assert MiddlewareSettings().clear_home_page_url_enabled is False
