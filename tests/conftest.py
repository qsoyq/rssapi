import os
from collections.abc import Iterator

import pytest


def pytest_configure() -> None:
    # Apply test configuration before collection imports the application settings.
    # Background upstream requests belong to external tests, not every TestClient.
    os.environ["RSS_NGA_SMILES_PRELOAD_ENABLE"] = "false"
    os.environ["RSS_DOUYIN_USER_AUTO_FETCH_ENABLE"] = "false"


@pytest.fixture(autouse=True)
def local_network_environment(request: pytest.FixtureRequest) -> Iterator[None]:
    if request.node.get_closest_marker("external_api") is not None:
        yield
        return

    # Local services must not be forwarded through a developer's upstream proxy.
    proxy_keys = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    proxies = {key: os.environ.pop(key) for key in proxy_keys if key in os.environ}
    try:
        yield
    finally:
        os.environ.update(proxies)
