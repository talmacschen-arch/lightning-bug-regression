"""Tests for the psycopg3 async SQL driver (M1-5).

Real Postgres/Greenplum is unavailable in CI, so we mock
``psycopg.AsyncConnection.connect`` and exercise the driver against
in-memory async stubs. Each test pins one observable contract from
design.md §5 / §14 R5 / R9.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import psycopg
import pytest

from app.runner.sql_driver import SqlSessionPool, execute_sql_step
from app.runner.types import StepStatus


class _FakeAsyncCursor:
    """Minimal async-context-manager cursor stub.

    Configurable knobs:
        rows_sequence: list of (description, rows, rowcount) tuples; each call
                       to execute() consumes the first one, and subsequent
                       nextset() calls advance through the remainder.
        execute_exc:   exception to raise from execute()
        execute_delay: seconds to ``await asyncio.sleep`` before execute returns
    """

    def __init__(
        self,
        rows_sequence: list[tuple[Any, list[tuple] | None, int]] | None = None,
        execute_exc: BaseException | None = None,
        execute_delay: float = 0.0,
    ) -> None:
        self._sequence = list(rows_sequence or [])
        self._idx = -1
        self._execute_exc = execute_exc
        self._execute_delay = execute_delay
        self.description: Any = None
        self.rowcount: int = -1
        self._rows: list[tuple] | None = None
        # Track every SQL string passed to .execute() — tests for
        # discard_all() rely on this to assert RESET ALL +
        # DEALLOCATE ALL are issued in order.
        self.executed: list[str] = []
        # Per-statement side-effect map: SQL prefix → exception. If a
        # call to .execute() matches a key (startswith), raise the
        # mapped exception. Used to simulate "RESET ALL refused".
        self.execute_side_effects: dict[str, BaseException] = {}

    async def __aenter__(self) -> _FakeAsyncCursor:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, sql: str) -> None:
        self.executed.append(sql)
        if self._execute_delay:
            await asyncio.sleep(self._execute_delay)
        for prefix, exc in self.execute_side_effects.items():
            if sql.startswith(prefix):
                raise exc
        if self._execute_exc is not None:
            raise self._execute_exc
        # Move to first result set, if any.
        self._idx = 0
        self._apply()

    def _apply(self) -> None:
        if 0 <= self._idx < len(self._sequence):
            desc, rows, rc = self._sequence[self._idx]
            self.description = desc
            self._rows = rows
            self.rowcount = rc
        else:
            self.description = None
            self._rows = None
            self.rowcount = -1

    def nextset(self) -> bool | None:
        if self._idx + 1 < len(self._sequence):
            self._idx += 1
            self._apply()
            return True
        return None

    async def fetchall(self) -> list[tuple]:
        return list(self._rows or [])


class _FakeConnInfo:
    """Mimics psycopg AsyncConnection.info, which exposes
    `.transaction_status` (a psycopg.pq.TransactionStatus enum value).
    Tests can monkey-set `transaction_status` to simulate INTRANS / INERROR.
    """

    def __init__(self) -> None:
        from psycopg.pq import TransactionStatus as _TS

        self.transaction_status = _TS.IDLE


class _FakeAsyncConnection:
    """Minimal AsyncConnection stub with notice-handler hooks.

    Post-§4.1.2 refactor: this driver no longer handles non-tx-safe DDL
    via autocommit (those go through psql -c / shell driver). So this
    fake doesn't need autocommit / set_autocommit machinery either.
    """

    def __init__(self, cursor: _FakeAsyncCursor) -> None:
        self._cursor = cursor
        self._handlers: list[Any] = []
        self.executed: list[str] = []
        self.closed = False
        self.rollbacks = 0
        self.commits = 0
        # Mimic psycopg's conn.info.transaction_status. discard_all() reads
        # this to decide whether to rollback before issuing DISCARD ALL.
        # Default IDLE — tests that want INTRANS overwrite via .info_status_value.
        self.info = _FakeConnInfo()

    def cursor(self) -> _FakeAsyncCursor:
        return self._cursor

    async def execute(self, sql: str) -> None:
        self.executed.append(sql)

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def commit(self) -> None:
        self.commits += 1

    async def close(self) -> None:
        self.closed = True

    def add_notice_handler(self, cb: Any) -> None:
        self._handlers.append(cb)

    def remove_notice_handler(self, cb: Any) -> None:
        if cb in self._handlers:
            self._handlers.remove(cb)

    def fire_notice(self, severity: str, message: str) -> None:
        diag = MagicMock()
        diag.severity = severity
        diag.message_primary = message
        for h in list(self._handlers):
            h(diag)


def _patch_connect(conn: _FakeAsyncConnection):
    """Patch psycopg.AsyncConnection.connect to return `conn`."""
    return patch.object(psycopg.AsyncConnection, "connect", new=AsyncMock(return_value=conn))


# ---------------------------------------------------------------------------
# (a) happy path: SELECT 5 -> status=PASS, scalar=5, row_count=1
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_happy_path_select_scalar() -> None:
    cursor = _FakeAsyncCursor(rows_sequence=[("description-marker", [(5,)], 1)])
    conn = _FakeAsyncConnection(cursor)
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    with _patch_connect(conn):
        result = await execute_sql_step(pool, "s1", "default", "SELECT 5")
    assert result.status is StepStatus.PASS
    assert result.scalar == 5
    assert result.row_count == 1
    assert result.rows_affected is None
    assert result.driver == "sql"
    assert result.step_id == "s1"
    assert result.error is None


# ---------------------------------------------------------------------------
# (b) unknown session -> status=ERROR, error mentions session name
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unknown_session_yields_error() -> None:
    pool = SqlSessionPool({"primary": "postgresql://stub/db"})
    # No patch needed: pool.acquire raises before connect is called.
    result = await execute_sql_step(pool, "s2", "missing", "SELECT 1")
    assert result.status is StepStatus.ERROR
    assert result.error is not None
    assert "missing" in result.error
    assert "sql session" in result.error.lower()


# ---------------------------------------------------------------------------
# (c) cursor.execute raises psycopg.errors.OperationalError
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_operational_error_caught_and_folded() -> None:
    cursor = _FakeAsyncCursor(execute_exc=psycopg.errors.OperationalError("connection lost"))
    conn = _FakeAsyncConnection(cursor)
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    with _patch_connect(conn):
        result = await execute_sql_step(pool, "s3", "default", "SELECT 1")
    assert result.status is StepStatus.ERROR
    assert result.error is not None
    assert "OperationalError" in result.error
    # R9: even on error, exception did not bubble — driver attempted rollback.
    assert conn.rollbacks == 1


# ---------------------------------------------------------------------------
# (d) NOTICE handler fires twice -> stderr contains both joined by newline
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_notice_capture_joins_lines() -> None:
    cursor = _FakeAsyncCursor(rows_sequence=[(None, None, 0)])

    captured_conn: dict[str, _FakeAsyncConnection] = {}

    class _NoticingCursor(_FakeAsyncCursor):
        async def execute(self, sql: str) -> None:
            # Fire two notices while "running" the query.
            captured_conn["c"].fire_notice("NOTICE", "first message")
            captured_conn["c"].fire_notice("WARNING", "second message")
            await super().execute(sql)

    cursor = _NoticingCursor(rows_sequence=[(None, None, 0)])
    conn = _FakeAsyncConnection(cursor)
    captured_conn["c"] = conn
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    with _patch_connect(conn):
        result = await execute_sql_step(pool, "s4", "default", "VACUUM analyze t")
    assert result.status is StepStatus.PASS
    assert "NOTICE: first message" in result.stderr
    assert "WARNING: second message" in result.stderr
    # Both notices present, separated by newline.
    assert "\n" in result.stderr


# ---------------------------------------------------------------------------
# (e) timeout_ms=10 and mock takes 5s -> ERROR mentions TimeoutError
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_asyncio_timeout_fires_when_psycopg_hangs() -> None:
    # execute_delay=5s, timeout_ms=10 -> asyncio.wait_for budget ~1.01s -> fires.
    cursor = _FakeAsyncCursor(
        rows_sequence=[(None, None, 0)],
        execute_delay=5.0,
    )
    conn = _FakeAsyncConnection(cursor)
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    with _patch_connect(conn):
        result = await execute_sql_step(pool, "s5", "default", "SELECT pg_sleep(60)", timeout_ms=10)
    assert result.status is StepStatus.ERROR
    assert result.error is not None
    assert "TimeoutError" in result.error
    # statement_timeout SET was issued on the connection before exec.
    assert any("statement_timeout = 10" in q for q in conn.executed)


# ---------------------------------------------------------------------------
# (f) multi-result-set -> last set is the one exposed via scalar/row_count
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multi_result_set_exposes_last_set() -> None:
    # Two result sets: first SELECT 1, second SELECT 99, 98 (two rows).
    cursor = _FakeAsyncCursor(
        rows_sequence=[
            ("desc1", [(1,)], 1),
            ("desc2", [(99,), (98,)], 2),
        ]
    )
    conn = _FakeAsyncConnection(cursor)
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    with _patch_connect(conn):
        result = await execute_sql_step(
            pool, "s6", "default", "SELECT 1; SELECT 99 UNION ALL SELECT 98;"
        )
    assert result.status is StepStatus.PASS
    # The LAST result set's first row's first col.
    assert result.scalar == 99
    assert result.row_count == 2
    assert result.rows_affected is None


# ---------------------------------------------------------------------------
# (g) SqlSessionPool reuses same conn for repeated acquire(same name)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_session_pool_reuses_connection() -> None:
    cursor = _FakeAsyncCursor(rows_sequence=[("d", [(1,)], 1)])
    conn = _FakeAsyncConnection(cursor)
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    connect_mock = AsyncMock(return_value=conn)
    with patch.object(psycopg.AsyncConnection, "connect", new=connect_mock):
        c1 = await pool.acquire("default")
        c2 = await pool.acquire("default")
    assert c1 is c2
    # connect() called exactly once despite two acquires.
    assert connect_mock.await_count == 1


# ---------------------------------------------------------------------------
# (h) close_all() closes all opened conns without raising
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_close_all_closes_all_conns() -> None:
    cursor_a = _FakeAsyncCursor(rows_sequence=[("d", [(1,)], 1)])
    cursor_b = _FakeAsyncCursor(rows_sequence=[("d", [(2,)], 1)])
    conn_a = _FakeAsyncConnection(cursor_a)
    conn_b = _FakeAsyncConnection(cursor_b)
    pool = SqlSessionPool({"a": "postgresql://stub/a", "b": "postgresql://stub/b"})
    # Two different DSNs -> connect() must return the matching conn per call.
    connect_mock = AsyncMock(side_effect=[conn_a, conn_b])
    with patch.object(psycopg.AsyncConnection, "connect", new=connect_mock):
        await pool.acquire("a")
        await pool.acquire("b")

    # Even if one close() raises, close_all swallows and still closes the rest.
    async def _boom() -> None:
        raise RuntimeError("close failed")

    conn_a.close = _boom  # type: ignore[assignment]
    await pool.close_all()
    assert conn_b.closed is True
    # Internal map cleared.
    assert pool._conns == {}


# ---------------------------------------------------------------------------
# (i) Non-tx-safe DDL handling REMOVED per §4.1.2 (M4a-2 dogfood refactor)
#     VACUUM / CREATE DATABASE / REINDEX CONCURRENTLY / etc. now go through
#     `kind: shell + cmd: psql -c '...'` in YAML, NOT through sql_driver.
#     The old tests for autocommit branch / rollback-before-autocommit /
#     SET-before-autocommit / restore-autocommit-False have been deleted —
#     that code path is gone. Tests (j) / (k) / (n) / (o) removed with it.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (l) EXPLAIN query populates plan_text with joined plan rows (F-2)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_explain_query_populates_plan_text() -> None:
    plan_row = "Seq Scan on t  (cost=0.00..1.01 rows=1 width=4)"
    cursor = _FakeAsyncCursor(rows_sequence=[("description-marker", [(plan_row,)], 1)])
    conn = _FakeAsyncConnection(cursor)
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    with _patch_connect(conn):
        result = await execute_sql_step(pool, "s_explain", "default", "EXPLAIN SELECT 1")
    assert result.status is StepStatus.PASS
    assert result.plan_text is not None
    assert result.plan_text != ""
    # plan_text must contain the actual plan line, not repr'd tuples
    assert plan_row in result.plan_text
    assert result.plan_text == plan_row


# ---------------------------------------------------------------------------
# (m) Non-EXPLAIN query has plan_text=None (F-2)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_non_explain_query_has_no_plan_text() -> None:
    cursor = _FakeAsyncCursor(rows_sequence=[("description-marker", [(1,)], 1)])
    conn = _FakeAsyncConnection(cursor)
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    with _patch_connect(conn):
        result = await execute_sql_step(pool, "s_select", "default", "SELECT 1")
    assert result.status is StepStatus.PASS
    assert result.plan_text is None


# Tests (n) and (o) (autocommit DDL SET-ordering / timeout opt-in) removed
# with the autocommit branch per §4.1.2 refactor — see comment block at (i).


# ---------------------------------------------------------------------------
# (p) discard_all() — orchestrator session-state isolation between cases
#     (dogfood 2026-05-26: bug-0011 SET work_mem='256kB' leaked into
#     xs-zombodb at suite tail; per-case session reset is the fix)
#
#     Implementation note: PR-F's original DISCARD ALL fell over because
#     PostgreSQL refuses DISCARD ALL inside a transaction block, and
#     psycopg3 with autocommit=False wraps every execute() in an
#     implicit BEGIN — 12/17 cases errored at 2-8ms with
#     InFailedSqlTransaction in dogfood run #32. Approach A
#     (2026-05-26): replace with RESET ALL + DEALLOCATE ALL (both
#     tx-safe), and on the exception path roll back so a failed reset
#     doesn't poison the conn for the next case.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_discard_all_issues_reset_and_deallocate_on_every_open_conn() -> None:
    """discard_all() must issue ``RESET ALL`` + ``DEALLOCATE ALL`` (in
    that order) on every conn in ``_conns``.

    Mocks two open sessions, calls discard_all(), asserts both cursors
    saw RESET ALL then DEALLOCATE ALL, and no DISCARD ALL was issued
    on the conn directly (the old broken path).
    """
    pool = SqlSessionPool({"a": "postgresql://stub/a", "b": "postgresql://stub/b"})
    cur_a = _FakeAsyncCursor()
    cur_b = _FakeAsyncCursor()
    conn_a = _FakeAsyncConnection(cur_a)
    conn_b = _FakeAsyncConnection(cur_b)
    # Inject directly into pool's internal map (skip real connect for unit-purity).
    pool._conns["a"] = conn_a  # type: ignore[assignment]
    pool._conns["b"] = conn_b  # type: ignore[assignment]
    await pool.discard_all()
    # Cursor-level: both RESET ALL and DEALLOCATE ALL issued, in order.
    assert cur_a.executed == ["RESET ALL", "DEALLOCATE ALL"]
    assert cur_b.executed == ["RESET ALL", "DEALLOCATE ALL"]
    # Conn-level: NO DISCARD ALL was issued via conn.execute — that
    # path is what triggered InFailedSqlTransaction in dogfood run #32.
    assert "DISCARD ALL" not in conn_a.executed
    assert "DISCARD ALL" not in conn_b.executed
    # Each conn's reset is committed so the next case starts clean.
    assert conn_a.commits == 1
    assert conn_b.commits == 1


@pytest.mark.asyncio
async def test_discard_all_is_noop_when_no_sessions_open() -> None:
    """Idempotent on an empty pool — must not raise."""
    pool = SqlSessionPool({"a": "postgresql://stub/a"})
    await pool.discard_all()  # no conns opened → should be silent no-op


@pytest.mark.asyncio
async def test_discard_all_rolls_back_when_conn_in_transaction() -> None:
    """If a conn is INTRANS/INERROR, rollback() must be called BEFORE
    the reset SQL — and the reset SQL is RESET ALL + DEALLOCATE ALL
    (both tx-safe), not DISCARD ALL.
    """
    from psycopg.pq import TransactionStatus

    pool = SqlSessionPool({"a": "postgresql://stub/a"})
    cur = _FakeAsyncCursor()
    conn = _FakeAsyncConnection(cur)
    conn.info.transaction_status = TransactionStatus.INTRANS
    pool._conns["a"] = conn  # type: ignore[assignment]
    await pool.discard_all()
    # Pre-reset rollback fires, then RESET ALL + DEALLOCATE ALL, then commit.
    assert conn.rollbacks == 1
    assert cur.executed == ["RESET ALL", "DEALLOCATE ALL"]
    assert conn.commits == 1


@pytest.mark.asyncio
async def test_discard_all_skips_rollback_when_conn_idle() -> None:
    """If conn is already IDLE, do NOT issue a needless rollback."""
    pool = SqlSessionPool({"a": "postgresql://stub/a"})
    cur = _FakeAsyncCursor()
    conn = _FakeAsyncConnection(cur)
    # default info.transaction_status == IDLE
    pool._conns["a"] = conn  # type: ignore[assignment]
    await pool.discard_all()
    assert conn.rollbacks == 0
    assert cur.executed == ["RESET ALL", "DEALLOCATE ALL"]


@pytest.mark.asyncio
async def test_discard_all_per_conn_error_does_not_block_others() -> None:
    """R9 fold-don't-bubble: one session's reset raising must not
    prevent the next session's reset. Dogfood-critical: a single bad
    conn shouldn't silently break isolation for every other case.
    """
    pool = SqlSessionPool({"a": "postgresql://stub/a", "b": "postgresql://stub/b"})
    cur_a = _FakeAsyncCursor()
    cur_b = _FakeAsyncCursor()
    # Configure cur_a's RESET ALL to raise; cur_b stays healthy.
    cur_a.execute_side_effects["RESET ALL"] = RuntimeError("RESET ALL refused")
    conn_a = _FakeAsyncConnection(cur_a)
    conn_b = _FakeAsyncConnection(cur_b)

    pool._conns["a"] = conn_a  # type: ignore[assignment]
    pool._conns["b"] = conn_b  # type: ignore[assignment]
    # Must not raise.
    await pool.discard_all()
    # conn_b still got its full reset despite conn_a blowing up.
    assert cur_b.executed == ["RESET ALL", "DEALLOCATE ALL"]


# ---------------------------------------------------------------------------
# (p2) RESET ALL failure → best-effort rollback so the conn is usable
#     by the next case (the regression class behind dogfood run #32:
#     bare except left the conn in INERROR → next case errored at 2-8ms
#     with InFailedSqlTransaction). NEW in Approach A 2026-05-26.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_discard_all_rolls_back_on_reset_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If the reset SQL raises, discard_all must:

    1. Log a warning naming the session.
    2. Call ``conn.rollback()`` so the conn isn't left in INERROR.
    3. Not propagate the exception to the caller.
    """
    import logging

    pool = SqlSessionPool({"a": "postgresql://stub/a"})
    cur = _FakeAsyncCursor()
    cur.execute_side_effects["RESET ALL"] = RuntimeError("simulated reset failure")
    conn = _FakeAsyncConnection(cur)
    pool._conns["a"] = conn  # type: ignore[assignment]

    with caplog.at_level(logging.WARNING, logger="app.runner.sql_driver"):
        # Must not raise.
        await pool.discard_all()

    # Warning logged, naming the session.
    assert any("session a reset failed" in rec.getMessage() for rec in caplog.records), (
        f"expected warning naming session 'a'; got {[r.getMessage() for r in caplog.records]}"
    )
    # Best-effort rollback fired (the conn was IDLE at start, so the
    # only rollback comes from the except-path recovery).
    assert conn.rollbacks == 1
    # No commit happened (we failed mid-reset).
    assert conn.commits == 0


@pytest.mark.asyncio
async def test_discard_all_rollback_recovery_tolerates_rollback_failure() -> None:
    """If even the recovery rollback() raises, discard_all must still
    not propagate (R9 fold-don't-bubble all the way down).
    """
    pool = SqlSessionPool({"a": "postgresql://stub/a"})
    cur = _FakeAsyncCursor()
    cur.execute_side_effects["RESET ALL"] = RuntimeError("simulated reset failure")
    conn = _FakeAsyncConnection(cur)

    async def _rollback_boom() -> None:
        raise RuntimeError("rollback also failed")

    conn.rollback = _rollback_boom  # type: ignore[assignment]
    pool._conns["a"] = conn  # type: ignore[assignment]
    # Must not raise.
    await pool.discard_all()


@pytest.mark.asyncio
async def test_discard_all_deallocate_runs_after_reset() -> None:
    """If RESET ALL succeeds but DEALLOCATE ALL fails, discard_all
    still rolls back so the conn is usable.
    """
    pool = SqlSessionPool({"a": "postgresql://stub/a"})
    cur = _FakeAsyncCursor()
    cur.execute_side_effects["DEALLOCATE ALL"] = RuntimeError("dealloc failed")
    conn = _FakeAsyncConnection(cur)
    pool._conns["a"] = conn  # type: ignore[assignment]
    await pool.discard_all()
    # Both statements were attempted in order.
    assert cur.executed == ["RESET ALL", "DEALLOCATE ALL"]
    # Recovery rollback fired.
    assert conn.rollbacks == 1
    assert conn.commits == 0
