import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import cast

import pytest

from rssapi.applications.twitter import client_transaction


class FakePage:
    def __init__(self, events: list[tuple[str, int]], evaluate_started: threading.Event | None = None) -> None:
        self.events = events
        self.evaluate_started = evaluate_started
        self.release_evaluate = threading.Event()
        self.closed = False
        self.fail_evaluate = False

    def goto(self, *_args, **_kwargs) -> None:
        self.events.append(("goto", threading.get_ident()))

    def wait_for_function(self, *_args, **_kwargs) -> None:
        self.events.append(("wait_for_function", threading.get_ident()))

    def wait_for_timeout(self, *_args, **_kwargs) -> None:
        self.events.append(("wait_for_timeout", threading.get_ident()))

    def evaluate(self, _script, arguments) -> str:
        self.events.append((f"evaluate:{arguments['path']}", threading.get_ident()))
        if self.evaluate_started is not None:
            self.evaluate_started.set()
            self.release_evaluate.wait(timeout=2)
        if self.fail_evaluate:
            raise RuntimeError("evaluation failed")
        return cast(str, arguments["path"])

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.events.append(("page.close", threading.get_ident()))
        self.closed = True


class FakeBrowser:
    def __init__(self, page: FakePage, events: list[tuple[str, int]]) -> None:
        self.page = page
        self.events = events

    def new_page(self) -> FakePage:
        self.events.append(("new_page", threading.get_ident()))
        return self.page

    def close(self) -> None:
        self.events.append(("browser.close", threading.get_ident()))


class FakePlaywright:
    def __init__(self, page: FakePage, events: list[tuple[str, int]]) -> None:
        self.chromium = self
        self.browser = FakeBrowser(page, events)
        self.events = events

    def launch(self, **_kwargs) -> FakeBrowser:
        self.events.append(("launch", threading.get_ident()))
        return self.browser

    def stop(self) -> None:
        self.events.append(("playwright.stop", threading.get_ident()))


class FakePlaywrightContext:
    def __init__(self, playwright: FakePlaywright, events: list[tuple[str, int]]) -> None:
        self.playwright = playwright
        self.events = events

    def start(self) -> FakePlaywright:
        self.events.append(("playwright.start", threading.get_ident()))
        return self.playwright


def make_signer(monkeypatch, *, operation_timeout=1.0, evaluate_started=None):
    events: list[tuple[str, int]] = []
    page = FakePage(events, evaluate_started)
    playwright = FakePlaywright(page, events)
    monkeypatch.setattr(
        client_transaction,
        "sync_playwright",
        lambda: FakePlaywrightContext(playwright, events),
    )
    return client_transaction.TwitterClientTransactionSigner(operation_timeout), page, events


def test_concurrent_signs_are_serialized_on_owner_thread(monkeypatch) -> None:
    signer, _page, events = make_signer(monkeypatch)
    barrier = threading.Barrier(5)

    def sign(index: int) -> str | None:
        barrier.wait()
        return cast(str | None, signer.sign(f"https://x.com/path/{index}", "get", "https://x.com"))

    with ThreadPoolExecutor(max_workers=4) as callers:
        futures = [callers.submit(sign, index) for index in range(4)]
        barrier.wait()
        assert {future.result() for future in futures} == {f"/path/{index}" for index in range(4)}

    owner_ids = {thread_id for _event, thread_id in events}
    assert len(owner_ids) == 1
    assert next(iter(owner_ids)) != threading.get_ident()
    assert len([event for event, _thread_id in events if event == "playwright.start"]) == 1
    signer.close()


def test_failure_closes_resources_on_owner_thread_and_next_sign_recreates(monkeypatch) -> None:
    signer, page, events = make_signer(monkeypatch)
    page.fail_evaluate = True

    with pytest.raises(RuntimeError, match="evaluation failed"):
        signer.sign("https://x.com/fail", "get", "https://x.com")

    assert [event for event, _thread_id in events[-3:]] == ["page.close", "browser.close", "playwright.stop"]
    page.fail_evaluate = False
    assert signer.sign("https://x.com/retry", "get", "https://x.com") == "/retry"
    assert len([event for event, _thread_id in events if event == "playwright.start"]) == 2
    signer.close()


def test_timeout_queues_owner_thread_cleanup(monkeypatch) -> None:
    evaluate_started = threading.Event()
    signer, page, events = make_signer(monkeypatch, operation_timeout=0.02, evaluate_started=evaluate_started)

    with pytest.raises(TimeoutError):
        signer.sign("https://x.com/slow", "get", "https://x.com")
    assert evaluate_started.is_set()

    page.release_evaluate.set()
    deadline = time.monotonic() + 1
    while "playwright.stop" not in [event for event, _thread_id in events] and time.monotonic() < deadline:
        time.sleep(0.01)

    close_events = [
        (event, thread_id) for event, thread_id in events if event.endswith("close") or event.endswith("stop")
    ]
    assert [event for event, _thread_id in close_events] == ["page.close", "browser.close", "playwright.stop"]
    assert {thread_id for _event, thread_id in close_events} == {signer._owner_thread_id}


def test_close_from_any_thread_is_idempotent_and_signer_remains_reusable(monkeypatch) -> None:
    signer, _page, events = make_signer(monkeypatch)
    assert signer.sign("https://x.com/first", "get", "https://x.com") == "/first"

    caller_thread_id: list[int] = []

    def close() -> None:
        caller_thread_id.append(threading.get_ident())
        signer.close()

    thread = threading.Thread(target=close)
    thread.start()
    thread.join()
    first_owner_thread_id = signer._owner_thread_id
    signer.close()

    close_thread_ids = {thread_id for event, thread_id in events if event.endswith("close") or event.endswith("stop")}
    assert close_thread_ids == {first_owner_thread_id}
    assert caller_thread_id[0] != first_owner_thread_id
    assert signer.sign("https://x.com/second", "get", "https://x.com") == "/second"
    signer.close()


def test_close_stops_owner_executor_until_signer_is_reused(monkeypatch) -> None:
    signer, _page, _events = make_signer(monkeypatch)
    assert signer.sign("https://x.com/first", "get", "https://x.com") == "/first"
    assert any(thread.name.startswith("twitter-transaction-signer") for thread in threading.enumerate())

    signer.close()
    assert signer._executor is None
    assert not any(thread.name.startswith("twitter-transaction-signer") for thread in threading.enumerate())
    assert signer.sign("https://x.com/second", "get", "https://x.com") == "/second"
    assert any(thread.name.startswith("twitter-transaction-signer") for thread in threading.enumerate())
    signer.close()
