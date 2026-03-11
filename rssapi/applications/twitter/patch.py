import json
import logging
import random
import re
import time
from typing import Any

from twitter_cli.client import TwitterClient

logger = logging.getLogger(__file__)

HTTP_429_PATTERN = re.compile(r"\b429\b")


def _get_twitter_api_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(exc, "response", None)
    response_status_code = getattr(response, "status_code", None)
    if isinstance(response_status_code, int):
        return response_status_code

    if HTTP_429_PATTERN.search(str(exc)):
        return 429
    return None


def _patch_twitter_client_get_with_no_retry_on_429(method_name: str) -> bool:
    original_method = getattr(TwitterClient, method_name, None)
    if not callable(original_method):
        return False

    method_globals = getattr(original_method, "__globals__", {})
    twitter_api_error = method_globals.get("TwitterAPIError")
    get_session = method_globals.get("_get_cffi_session")
    json_module = method_globals.get("json", json)
    random_module = method_globals.get("random", random)
    time_module = method_globals.get("time", time)

    if isinstance(twitter_api_error, type) and issubclass(twitter_api_error, Exception):
        error_type: type[Exception] = twitter_api_error
    else:
        error_type = RuntimeError

    def _raise_api_error(status_code: int, message: str) -> None:
        raise error_type(status_code, message)

    def _parse_payload(payload: str, max_retries: int, retry_base_delay: float, attempt: int) -> Any:
        try:
            parsed = json_module.loads(payload)
        except (json.JSONDecodeError, ValueError):
            _raise_api_error(0, "Twitter API returned invalid JSON")

        if isinstance(parsed, dict) and parsed.get("errors"):
            first_error = parsed["errors"][0] if parsed["errors"] else {}
            err_msg = first_error.get("message", "Unknown error")
            err_code = first_error.get("code", 0)
            if err_code == 88 and attempt < max_retries:
                wait = retry_base_delay * (2**attempt) + random_module.uniform(0, 2)
                logger.warning(
                    "twitter_cli returned rate-limit code 88, retrying in %.1fs (attempt %d/%d)",
                    wait,
                    attempt + 1,
                    max_retries,
                )
                time_module.sleep(wait)
                return None
            if err_code in (348, 349):
                _raise_api_error(429, f"Rate limited: {err_msg} (try again later, recommended wait: 15+ minutes)")
            _raise_api_error(0, f"Twitter API returned errors: {err_msg}")

        if isinstance(parsed, dict) and "data" in parsed:
            data_obj = parsed["data"]
            if isinstance(data_obj, dict):
                for value in data_obj.values():
                    if isinstance(value, dict) and value.get("errors"):
                        inner_errors = value["errors"]
                        if inner_errors:
                            inner_msg = inner_errors[0].get("message", "Unknown error")
                            _raise_api_error(0, f"Twitter API: {inner_msg}")

        return parsed

    if method_name == "_api_request":
        if not callable(get_session):
            return False

        def _patched_api_request(
            self: TwitterClient, url: str, method: str = "GET", body: dict[str, Any] | None = None
        ) -> Any:
            if method != "GET":
                return original_method(self, url, method=method, body=body)

            headers = self._build_headers(url=url, method=method)
            session = get_session()
            max_retries = max(int(getattr(self, "_max_retries", 0)), 0)
            retry_base_delay = float(getattr(self, "_retry_base_delay", 0.0))

            for attempt in range(max_retries + 1):
                try:
                    response = session.get(url, headers=headers, timeout=30)
                    status_code = response.status_code
                    if status_code == 429:
                        message = f"Twitter API error 429: {response.text[:500]}"
                        logger.warning("twitter_cli hit 429, skipping retry and aborting request: %s", message)
                        _raise_api_error(429, message)
                    if status_code >= 400:
                        _raise_api_error(status_code, f"Twitter API error {status_code}: {response.text[:500]}")
                    payload = response.text
                except error_type:
                    raise
                except Exception as exc:
                    _raise_api_error(0, f"Twitter API network error: {exc}")

                parsed = _parse_payload(payload, max_retries, retry_base_delay, attempt)
                if parsed is not None:
                    return parsed

            _raise_api_error(429, f"Rate limited after {max_retries} retries")

        setattr(TwitterClient, method_name, _patched_api_request)
        return True

    def _patched_api_get(self: TwitterClient, url: str) -> Any:
        original_max_retries = getattr(self, "_max_retries", None)
        if original_max_retries is not None:
            self._max_retries = 0
        try:
            return original_method(self, url)
        except Exception as exc:
            if _get_twitter_api_status_code(exc) == 429:
                logger.warning("twitter_cli hit 429, skipping retry and aborting request: %s", exc)
            raise
        finally:
            if original_max_retries is not None:
                self._max_retries = original_max_retries

    setattr(TwitterClient, method_name, _patched_api_get)
    return True


def install_twitter_client_429_no_retry_patch() -> None:
    if getattr(TwitterClient, "_rssapi_no_retry_429_patch_installed", False):
        return

    patched = _patch_twitter_client_get_with_no_retry_on_429("_api_request")
    if not patched:
        patched = _patch_twitter_client_get_with_no_retry_on_429("_api_get")

    if patched:
        setattr(TwitterClient, "_rssapi_no_retry_429_patch_installed", True)
