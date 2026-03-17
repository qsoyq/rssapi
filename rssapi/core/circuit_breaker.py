import asyncio
import time
from collections.abc import Callable
from functools import wraps

from fastapi import HTTPException


def circuit_breaker(status_code: int | list[int] = 429, cooldown: int = 60) -> Callable:
    """Route-level circuit breaker decorator.

    When the wrapped route raises an HTTPException matching *status_code*,
    all subsequent calls within the next *cooldown* seconds are short-circuited
    with the same status code / detail without invoking the real handler.

    Works with both sync and async route functions.
    Each decorated function maintains its own independent trip state.

    Args:
        status_code: The HTTP status code(s) that trigger the breaker.
        cooldown: Seconds to keep the breaker open after it trips.
    """
    codes: set[int] = {status_code} if isinstance(status_code, int) else set(status_code)

    def _check_tripped(
        tripped_at: float | None,
        tripped_code: int | None,
        tripped_detail: str | None,
    ) -> tuple[float | None, int | None, str | None]:
        if tripped_at is not None:
            elapsed = time.monotonic() - tripped_at
            if elapsed < cooldown:
                raise HTTPException(
                    status_code=tripped_code if tripped_code is not None else 429,
                    detail=f"[circuit-breaker] {tripped_detail} (retry after {cooldown - elapsed:.0f}s)",
                )
            return None, None, None
        return tripped_at, tripped_code, tripped_detail

    def _handle_exc(exc: HTTPException) -> tuple[float, int, str | None]:
        return time.monotonic(), exc.status_code, exc.detail

    def decorator(fn: Callable) -> Callable:
        tripped_at: float | None = None
        tripped_code: int | None = None
        tripped_detail: str | None = None

        if asyncio.iscoroutinefunction(fn):

            @wraps(fn)
            async def async_wrapper(*args, **kwargs):
                nonlocal tripped_at, tripped_code, tripped_detail
                tripped_at, tripped_code, tripped_detail = _check_tripped(tripped_at, tripped_code, tripped_detail)
                try:
                    return await fn(*args, **kwargs)
                except HTTPException as exc:
                    if exc.status_code in codes:
                        tripped_at, tripped_code, tripped_detail = _handle_exc(exc)
                    raise

            return async_wrapper

        @wraps(fn)
        def sync_wrapper(*args, **kwargs):
            nonlocal tripped_at, tripped_code, tripped_detail
            tripped_at, tripped_code, tripped_detail = _check_tripped(tripped_at, tripped_code, tripped_detail)
            try:
                return fn(*args, **kwargs)
            except HTTPException as exc:
                if exc.status_code in codes:
                    tripped_at, tripped_code, tripped_detail = _handle_exc(exc)
                raise

        return sync_wrapper

    return decorator
