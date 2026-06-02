"""Unit tests for the SSE event broker (M6-1)."""

from __future__ import annotations

import asyncio

import pytest

from app.runner import event_broker


@pytest.fixture(autouse=True)
def _reset_broker():
    event_broker._reset_for_tests()
    yield
    event_broker._reset_for_tests()


@pytest.mark.asyncio
async def test_publish_without_subscriber_is_noop():
    """A run that finishes before anyone subscribes must not error."""
    # No subscriber registered for run_id=999
    event_broker.publish_case_done(999, "bug-0001", "pass", duration_ms=12)
    event_broker.publish_run_done(999, {"total": 1, "passed": 1, "failed": 0, "skipped": 0})
    # No raise → pass


@pytest.mark.asyncio
async def test_subscribe_receives_published_events():
    received: list[dict] = []

    async def consumer():
        async with event_broker.subscribe(42) as q:
            while True:
                ev = await q.get()
                received.append(ev)
                if event_broker.is_terminal(ev):
                    return

    task = asyncio.create_task(consumer())
    # Yield once so consumer registers
    await asyncio.sleep(0)

    event_broker.publish_case_done(42, "bug-0001", "pass", duration_ms=10)
    event_broker.publish_case_done(42, "bug-0002", "fail", duration_ms=20, error="boom")
    event_broker.publish_run_done(42, {"total": 2, "passed": 1, "failed": 1, "skipped": 0})

    await asyncio.wait_for(task, timeout=2.0)
    assert [e["type"] for e in received] == ["case_done", "case_done", "run_done"]
    assert received[1]["error"] == "boom"
    assert received[2]["summary"]["failed"] == 1


@pytest.mark.asyncio
async def test_run_aborted_terminal_event():
    received: list[dict] = []

    async def consumer():
        async with event_broker.subscribe(7) as q:
            while True:
                ev = await q.get()
                received.append(ev)
                if event_broker.is_terminal(ev):
                    return

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)

    event_broker.publish_run_aborted(7, reason="ZeroDivisionError: division by zero")
    await asyncio.wait_for(task, timeout=2.0)
    assert received[-1]["type"] == "run_aborted"
    assert "ZeroDivision" in received[-1]["reason"]


@pytest.mark.asyncio
async def test_multiple_subscribers_each_receive_events():
    """Two browser tabs streaming the same run should each get all events."""
    rec_a: list[dict] = []
    rec_b: list[dict] = []

    async def consume(target):
        async with event_broker.subscribe(11) as q:
            while True:
                ev = await q.get()
                target.append(ev)
                if event_broker.is_terminal(ev):
                    return

    ta = asyncio.create_task(consume(rec_a))
    tb = asyncio.create_task(consume(rec_b))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    event_broker.publish_case_done(11, "c1", "pass", duration_ms=1)
    event_broker.publish_run_done(11, {"total": 1, "passed": 1, "failed": 0, "skipped": 0})
    await asyncio.wait_for(asyncio.gather(ta, tb), timeout=2.0)
    assert len(rec_a) == 2
    assert len(rec_b) == 2
    assert rec_a == rec_b


@pytest.mark.asyncio
async def test_subscriber_cleanup_on_exit():
    async with event_broker.subscribe(99) as _q:
        assert 99 in event_broker._subscribers
    assert 99 not in event_broker._subscribers


def test_is_terminal_marks_only_terminal_types():
    assert event_broker.is_terminal({"type": event_broker.EVENT_RUN_DONE})
    assert event_broker.is_terminal({"type": event_broker.EVENT_RUN_ABORTED})
    assert not event_broker.is_terminal({"type": event_broker.EVENT_CASE_DONE})
    assert not event_broker.is_terminal({"type": "snapshot"})
