import pytest

from rssapi.utils.playwright_capacity import PlaywrightCapacityError, PlaywrightCapacityLimiter


def test_capacity_rejects_the_next_browser_and_recovers_after_release() -> None:
    limiter = PlaywrightCapacityLimiter(2)
    first = limiter.acquire("first")
    second = limiter.acquire("second")

    with pytest.raises(PlaywrightCapacityError) as exc_info:
        limiter.acquire("overflow")

    assert exc_info.value.source == "overflow"
    assert exc_info.value.capacity == 2
    assert exc_info.value.in_use == 2
    assert limiter.in_use == 2

    first.release()
    replacement = limiter.acquire("replacement")

    assert limiter.in_use == 2

    replacement.release()
    second.release()

    assert limiter.in_use == 0


@pytest.mark.asyncio
async def test_async_and_sync_callers_share_the_same_capacity() -> None:
    limiter = PlaywrightCapacityLimiter(1)
    sync_lease = limiter.acquire("sync")

    with pytest.raises(PlaywrightCapacityError):
        await limiter.acquire_async("async")

    sync_lease.release()
    async_lease = await limiter.acquire_async("async")

    assert limiter.in_use == 1

    async_lease.release()

    assert limiter.in_use == 0


def test_releasing_a_lease_twice_is_safe() -> None:
    limiter = PlaywrightCapacityLimiter(1)
    lease = limiter.acquire("test")

    lease.release()
    lease.release()

    assert limiter.in_use == 0
