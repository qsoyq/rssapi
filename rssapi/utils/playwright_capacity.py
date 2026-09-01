import logging
import threading
from dataclasses import dataclass

from rssapi.core.settings import settings

logger = logging.getLogger(__name__)


class PlaywrightCapacityError(RuntimeError):
    def __init__(self, source: str, *, capacity: int, in_use: int) -> None:
        super().__init__(f"Playwright capacity is exhausted for {source}")
        self.source = source
        self.capacity = capacity
        self.in_use = in_use


@dataclass
class PlaywrightLease:
    _limiter: "PlaywrightCapacityLimiter"
    source: str
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._limiter._release(self.source)

    def __enter__(self) -> "PlaywrightLease":
        return self

    def __exit__(self, *_: object) -> None:
        self.release()

    async def __aenter__(self) -> "PlaywrightLease":
        return self

    async def __aexit__(self, *_: object) -> None:
        self.release()


class PlaywrightCapacityLimiter:
    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("Playwright capacity must be at least one")
        self._capacity = capacity
        self._semaphore = threading.BoundedSemaphore(capacity)
        self._lock = threading.Lock()
        self._in_use = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def in_use(self) -> int:
        with self._lock:
            return self._in_use

    def acquire(self, source: str) -> PlaywrightLease:
        if not self._semaphore.acquire(blocking=False):
            in_use = self.in_use
            logger.warning(f"Playwright capacity exhausted source={source} in_use={in_use} capacity={self._capacity}")
            raise PlaywrightCapacityError(source, capacity=self._capacity, in_use=in_use)

        with self._lock:
            self._in_use += 1
            in_use = self._in_use
        logger.debug(f"Playwright slot acquired source={source} in_use={in_use} capacity={self._capacity}")
        return PlaywrightLease(self, source)

    async def acquire_async(self, source: str) -> PlaywrightLease:
        return self.acquire(source)

    def _release(self, source: str) -> None:
        with self._lock:
            if self._in_use < 1:
                raise RuntimeError("Playwright capacity release without an active lease")
            self._in_use -= 1
            in_use = self._in_use
        self._semaphore.release()
        logger.debug(f"Playwright slot released source={source} in_use={in_use} capacity={self._capacity}")


_playwright_capacity_limiter = PlaywrightCapacityLimiter(settings.rss_playwright_concurrency)


def acquire_playwright_slot(source: str) -> PlaywrightLease:
    return _playwright_capacity_limiter.acquire(source)


async def acquire_playwright_slot_async(source: str) -> PlaywrightLease:
    return await _playwright_capacity_limiter.acquire_async(source)
