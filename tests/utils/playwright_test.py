import pytest

from rssapi.utils.playwright import _browser_platform, _browser_user_agent
from rssapi.utils.playwright_proxy import (
    playwright_launch_options,
    playwright_proxy_from_environment,
)


@pytest.mark.parametrize(
    ("runtime_platform", "expected_platform"),
    [
        ("darwin", "Macintosh; Intel Mac OS X 10_15_7"),
        ("linux", "X11; Linux x86_64"),
        ("win32", "Windows NT 10.0; Win64; x64"),
    ],
)
def test_browser_platform_matches_runtime(runtime_platform: str, expected_platform: str) -> None:
    assert _browser_platform(runtime_platform) == expected_platform


def test_browser_user_agent_matches_runtime_and_browser_version() -> None:
    user_agent = _browser_user_agent("149.0.7632.6", "linux")

    assert "X11; Linux x86_64" in user_agent
    assert "Chrome/149.0.0.0" in user_agent
    assert "HeadlessChrome" not in user_agent


def test_launch_options_omit_proxy_when_not_configured() -> None:
    assert playwright_launch_options(headless=True, environment={}) == {"headless": True}


def test_launch_options_passes_configured_proxy_to_chromium() -> None:
    assert playwright_launch_options(
        headless=True, environment={"HTTP_PROXY": "http://host.docker.internal:7890"}
    ) == {
        "headless": True,
        "proxy": {"server": "http://host.docker.internal:7890"},
    }


def test_proxy_prefers_https_and_preserves_bypass_rules() -> None:
    proxy = playwright_proxy_from_environment(
        {
            "HTTPS_PROXY": "http://secure-proxy.example:8443",
            "HTTP_PROXY": "http://fallback-proxy.example:8080",
            "NO_PROXY": "localhost,127.0.0.1,.internal.example",
        }
    )

    assert proxy == {
        "server": "http://secure-proxy.example:8443",
        "bypass": "localhost,127.0.0.1,.internal.example",
    }


def test_proxy_supports_lowercase_variables_and_credentials() -> None:
    proxy = playwright_proxy_from_environment({"https_proxy": "http://user:p%40ss@proxy.example:8080"})

    assert proxy == {
        "server": "http://proxy.example:8080",
        "username": "user",
        "password": "p@ss",
    }


def test_proxy_rejects_an_invalid_port() -> None:
    with pytest.raises(ValueError, match="invalid port"):
        playwright_proxy_from_environment({"http_proxy": "http://proxy.example:not-a-port"})
