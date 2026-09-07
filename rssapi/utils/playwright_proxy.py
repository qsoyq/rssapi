import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, urlsplit

from playwright.async_api import ProxySettings

_HTTPS_PROXY_KEYS = ("HTTPS_PROXY", "https_proxy")
_HTTP_PROXY_KEYS = ("HTTP_PROXY", "http_proxy")
_NO_PROXY_KEYS = ("NO_PROXY", "no_proxy")


def _first_value(environment: Mapping[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if value := environment.get(key):
            return value
    return None


def playwright_proxy_from_environment(environment: Mapping[str, str] | None = None) -> ProxySettings | None:
    source = os.environ if environment is None else environment
    proxy_url = _first_value(source, _HTTPS_PROXY_KEYS) or _first_value(source, _HTTP_PROXY_KEYS)
    if proxy_url is None:
        return None

    parsed = urlsplit(proxy_url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError("Playwright proxy URL must include a scheme and hostname")

    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    server = f"{parsed.scheme}://{host}"
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Playwright proxy URL contains an invalid port") from exc
    if port is not None:
        server = f"{server}:{port}"

    proxy: ProxySettings = {"server": server}
    if parsed.username is not None:
        proxy["username"] = unquote(parsed.username)
    if parsed.password is not None:
        proxy["password"] = unquote(parsed.password)
    if bypass := _first_value(source, _NO_PROXY_KEYS):
        proxy["bypass"] = bypass
    return proxy


def playwright_launch_options(
    *,
    headless: bool,
    environment: Mapping[str, str] | None = None,
    **options: Any,
) -> dict[str, Any]:
    result = {"headless": headless, **options}
    if proxy := playwright_proxy_from_environment(environment):
        result["proxy"] = proxy
    return result
