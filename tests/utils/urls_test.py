from fastapi import Request

from rssapi.core.settings import PublicURLSettings, settings
from rssapi.utils.urls import public_request_url, public_url


def _request(*, host: str = "rss.example:8443", scheme: str = "http", query: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "scheme": scheme,
            "server": ("127.0.0.1", 8000),
            "path": "/api/rss/example",
            "query_string": query,
            "headers": [(b"host", host.encode())],
        }
    )


def test_public_url_uses_inbound_host_and_default_https(monkeypatch) -> None:
    monkeypatch.setattr(settings.public_url, "scheme", "https")

    assert public_url(_request(), "/api/rss/example/media/1") == "https://rss.example:8443/api/rss/example/media/1"


def test_public_url_scheme_can_be_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings.public_url, "scheme", "http")

    assert public_url(_request(), "/media/1") == "http://rss.example:8443/media/1"


def test_public_scheme_reads_rss_public_scheme_environment(monkeypatch) -> None:
    monkeypatch.setenv("RSS_PUBLIC_SCHEME", "http")

    assert PublicURLSettings().scheme == "http"


def test_public_request_url_preserves_query_and_excludes_sensitive_values() -> None:
    request = _request(query=b"channels=one&channels=two&cookies=secret")

    assert public_request_url(request, remove_query_params={"cookies"}) == (
        "https://rss.example:8443/api/rss/example?channels=one&channels=two"
    )
