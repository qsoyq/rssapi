from unittest.mock import patch

import pytest
from fastapi import HTTPException

from rssapi.core.circuit_breaker import circuit_breaker

COOLDOWN = 10


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------


def _make_sync_fn(status_code: int | list[int] = 429, cooldown: int = COOLDOWN):
    """Return a circuit-breaker-wrapped sync function whose raise behaviour is
    controlled by the ``should_raise`` keyword argument."""

    @circuit_breaker(status_code=status_code, cooldown=cooldown)
    def fn(*, should_raise: int | None = None):
        if should_raise is not None:
            raise HTTPException(status_code=should_raise, detail="upstream error")
        return "ok"

    return fn


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------


def _make_async_fn(status_code: int | list[int] = 429, cooldown: int = COOLDOWN):
    @circuit_breaker(status_code=status_code, cooldown=cooldown)
    async def fn(*, should_raise: int | None = None):
        if should_raise is not None:
            raise HTTPException(status_code=should_raise, detail="upstream error")
        return "ok"

    return fn


# ===== Sync tests ==========================================================


class TestSyncCircuitBreaker:
    def test_normal_call(self):
        fn = _make_sync_fn()
        assert fn() == "ok"

    @patch("rssapi.core.circuit_breaker.time")
    def test_trips_on_matching_status(self, mock_time):
        mock_time.monotonic.return_value = 100.0
        fn = _make_sync_fn()

        with pytest.raises(HTTPException) as exc_info:
            fn(should_raise=429)
        assert exc_info.value.status_code == 429

        mock_time.monotonic.return_value = 101.0
        with pytest.raises(HTTPException) as exc_info:
            fn()
        assert exc_info.value.status_code == 429
        assert "[circuit-breaker]" in exc_info.value.detail

    @patch("rssapi.core.circuit_breaker.time")
    def test_recovers_after_cooldown(self, mock_time):
        mock_time.monotonic.return_value = 100.0
        fn = _make_sync_fn()

        with pytest.raises(HTTPException):
            fn(should_raise=429)

        mock_time.monotonic.return_value = 100.0 + COOLDOWN + 1
        assert fn() == "ok"

    def test_non_matching_status_does_not_trip(self):
        fn = _make_sync_fn(status_code=429)

        with pytest.raises(HTTPException) as exc_info:
            fn(should_raise=500)
        assert exc_info.value.status_code == 500

        assert fn() == "ok"

    @patch("rssapi.core.circuit_breaker.time")
    def test_list_status_codes(self, mock_time):
        mock_time.monotonic.return_value = 100.0
        fn = _make_sync_fn(status_code=[429, 503])

        with pytest.raises(HTTPException):
            fn(should_raise=503)

        mock_time.monotonic.return_value = 101.0
        with pytest.raises(HTTPException) as exc_info:
            fn()
        assert exc_info.value.status_code == 503
        assert "[circuit-breaker]" in exc_info.value.detail


# ===== Async tests ==========================================================


class TestAsyncCircuitBreaker:
    @pytest.mark.asyncio
    async def test_normal_call(self):
        fn = _make_async_fn()
        assert await fn() == "ok"

    @pytest.mark.asyncio
    @patch("rssapi.core.circuit_breaker.time")
    async def test_trips_on_matching_status(self, mock_time):
        mock_time.monotonic.return_value = 100.0
        fn = _make_async_fn()

        with pytest.raises(HTTPException) as exc_info:
            await fn(should_raise=429)
        assert exc_info.value.status_code == 429

        mock_time.monotonic.return_value = 101.0
        with pytest.raises(HTTPException) as exc_info:
            await fn()
        assert exc_info.value.status_code == 429
        assert "[circuit-breaker]" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("rssapi.core.circuit_breaker.time")
    async def test_recovers_after_cooldown(self, mock_time):
        mock_time.monotonic.return_value = 100.0
        fn = _make_async_fn()

        with pytest.raises(HTTPException):
            await fn(should_raise=429)

        mock_time.monotonic.return_value = 100.0 + COOLDOWN + 1
        assert await fn() == "ok"

    @pytest.mark.asyncio
    async def test_non_matching_status_does_not_trip(self):
        fn = _make_async_fn(status_code=429)

        with pytest.raises(HTTPException) as exc_info:
            await fn(should_raise=500)
        assert exc_info.value.status_code == 500

        assert await fn() == "ok"

    @pytest.mark.asyncio
    @patch("rssapi.core.circuit_breaker.time")
    async def test_list_status_codes(self, mock_time):
        mock_time.monotonic.return_value = 100.0
        fn = _make_async_fn(status_code=[429, 503])

        with pytest.raises(HTTPException):
            await fn(should_raise=503)

        mock_time.monotonic.return_value = 101.0
        with pytest.raises(HTTPException) as exc_info:
            await fn()
        assert exc_info.value.status_code == 503
        assert "[circuit-breaker]" in exc_info.value.detail
