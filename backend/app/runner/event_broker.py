"""In-memory event broker for SSE (M6-1).

Pattern: per-run asyncio.Queue published by orchestrator, consumed by
the SSE endpoint. Decoupled so:
  - orchestrator does not depend on FastAPI primitives
  - the broker survives without subscribers (publish is best-effort)
  - subscribing after publish has started replays NOTHING — frontend
    must do an initial GET /runs/{id} to render baseline state, then
    subscribe for deltas. (Acceptable: a single missed event is filled
    by the next case_done event causing the frontend to refetch state.)

Not threadsafe across event loops — assumes single uvicorn worker
process for SSE consumers. For multi-worker, swap to Redis pub/sub
(out of scope for M6-1; design.md §13.12).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

# event types — terminal events close the SSE stream
EVENT_CASE_DONE = "case_done"
EVENT_RUN_DONE = "run_done"
EVENT_RUN_ABORTED = "run_aborted"

_TERMINAL_EVENTS = {EVENT_RUN_DONE, EVENT_RUN_ABORTED}

# Per-run queue registry. key = run_id, value = list of asyncio.Queue
# (list because multiple subscribers — e.g. two browser tabs — may
# stream the same run). Each queue gets its own copy of every event.
_subscribers: dict[int, list[asyncio.Queue[dict[str, Any]]]] = {}


def publish(run_id: int, event: dict[str, Any]) -> None:
    """Non-blocking publish. Drops on queue-full (subscriber too slow).

    Safe to call from any coroutine. No-op if no subscribers (the run
    may have finished before anyone opened the stream, which is fine —
    the frontend's initial GET /runs/{id} sees the final state).
    """
    queues = _subscribers.get(run_id)
    if not queues:
        return
    for q in queues:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "event_broker run=%d queue full, dropping event %s", run_id, event.get("type")
            )


@asynccontextmanager
async def subscribe(run_id: int) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
    """Register a queue + yield it; on exit deregister + drain.

    Usage:
        async with subscribe(run_id) as q:
            while True:
                event = await q.get()
                ...
                if event["type"] in TERMINAL:
                    break
    """
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
    _subscribers.setdefault(run_id, []).append(q)
    try:
        yield q
    finally:
        try:
            _subscribers[run_id].remove(q)
            if not _subscribers[run_id]:
                del _subscribers[run_id]
        except (KeyError, ValueError):
            pass  # already removed


def is_terminal(event: dict[str, Any]) -> bool:
    return event.get("type") in _TERMINAL_EVENTS


def publish_case_done(
    run_id: int,
    case_id: str,
    status: str,
    duration_ms: int | None = None,
    error: str | None = None,
) -> None:
    publish(
        run_id,
        {
            "type": EVENT_CASE_DONE,
            "run_id": run_id,
            "case_id": case_id,
            "status": status,
            "duration_ms": duration_ms,
            "error": error,
        },
    )


def publish_run_done(run_id: int, summary: dict[str, Any]) -> None:
    publish(run_id, {"type": EVENT_RUN_DONE, "run_id": run_id, "summary": summary})


def publish_run_aborted(run_id: int, reason: str | None = None) -> None:
    publish(run_id, {"type": EVENT_RUN_ABORTED, "run_id": run_id, "reason": reason})


# Test helper — reset broker state between tests. Not part of public API.
def _reset_for_tests() -> None:
    _subscribers.clear()
