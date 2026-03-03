import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

import httpx

logger = logging.getLogger(__file__)


def retry_http(
    *,
    max_attempts: int = 3,
    retry_backoff_seconds: float = 0,
    retry_on_status: Callable[[int], bool] | None = None,
    log_prefix: str = "[ retry_http ]",
) -> Callable[[Callable[..., httpx.Response]], Callable[..., httpx.Response]]:
    """内部捕获 HTTPX 请求导致的网络或状态码异常

    重试最多 max_attempts 次
    重试等待间隔根据 retry_backoff_seconds 计算, 每次等待时间 = retry_backoff_seconds * attempt
    如果 retry_on_status 返回 True, 则重试, 默认对于状态码大于等于 500 的进行重试
    内部不会因为状态码而抛出异常, 仅会抛出因为重试达到上限后遇到的 httpx 内部网络异常
    """
    max_attempts = max(1, max_attempts)

    def _default_retry_on_status(status_code: int) -> bool:
        return 500 <= status_code

    if retry_on_status is None:
        retry_on_status = _default_retry_on_status

    def decorator(func: Callable[..., httpx.Response]) -> Callable[..., httpx.Response]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> httpx.Response:
            for attempt in range(1, max_attempts + 1):
                wait_seconds = retry_backoff_seconds * attempt
                try:
                    resp = func(*args, **kwargs)
                    if retry_on_status(resp.status_code):
                        if attempt < max_attempts:
                            logger.warning(f"{log_prefix} HTTP {resp.status_code}，准备重试 {attempt}/{max_attempts}")
                            if retry_backoff_seconds:
                                time.sleep(wait_seconds)
                            continue
                        else:
                            logger.warning(f"{log_prefix} 请求失败 {resp.status_code} {resp.text}")
                            return resp
                    return resp
                except httpx.HTTPError as exc:
                    if attempt < max_attempts:
                        logger.warning(f"{log_prefix} 请求异常，准备重试 {attempt}/{max_attempts}: {exc}")
                        if retry_backoff_seconds:
                            time.sleep(wait_seconds)
                        continue
                    raise exc
            raise RuntimeError(f"{log_prefix} 未预期执行到重试逻辑末尾")

        return wrapper

    return decorator
