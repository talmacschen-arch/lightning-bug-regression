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

    async def __aenter__(self) -> _FakeAsyncCursor:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, sql: str) -> None:
        if self._execute_delay:
            await asyncio.sleep(self._execute_delay)
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


class _FakeAsyncConnection:
    """Minimal AsyncConnection stub with notice-handler hooks.

    Matches psycopg AsyncConnection's API contract for autocommit: the
    `autocommit` attribute is readable (so production code can do
    `getattr(conn, "autocommit", False)` for the rollback guard) but
    must be mutated via the async `set_autocommit()` method — direct
    assignment would fail on a real AsyncConnection (M4a-2 dogfood
    case lg-bug-0008 tripped this when sql_driver.py used `conn.
    autocommit = True` which is read-only on async connections).
    """

    def __init__(self, cursor: _FakeAsyncCursor) -> None:
        self._cursor = cursor
        self._handlers: list[Any] = []
        self.executed: list[str] = []
        self.closed = False
        self.rollbacks = 0
        self.autocommit: bool = False

    def cursor(self) -> _FakeAsyncCursor:
        return self._cursor

    async def execute(self, sql: str) -> None:
        self.executed.append(sql)

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closed = True

    async def set_autocommit(self, value: bool) -> None:
        """psycopg AsyncConnection requires this async setter; the
        attribute is read-only as a property on real connections.
        Tests can still read `.autocommit` via getattr for assertions."""
        self.autocommit = value

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
# (i) DROP DATABASE triggers autocommit=True, restored to False after (F-3)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ddl_runs_with_autocommit() -> None:
    """DROP DATABASE is detected as non-tx-safe DDL; driver switches autocommit=True."""
    cursor = _FakeAsyncCursor(rows_sequence=[(None, None, 0)])
    conn = _FakeAsyncConnection(cursor)
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    with _patch_connect(conn):
        result = await execute_sql_step(pool, "ddl-step", "default", "DROP DATABASE IF EXISTS mydb")
    assert result.status is StepStatus.PASS
    # autocommit was set to True during execution, then restored to False.
    assert conn.autocommit is False  # restored


# ---------------------------------------------------------------------------
# (j) Regular SELECT does not modify conn.autocommit (F-3)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_regular_sql_does_not_touch_autocommit() -> None:
    """Regular SELECT does not modify conn.autocommit."""
    cursor = _FakeAsyncCursor(rows_sequence=[("d", [(1,)], 1)])
    conn = _FakeAsyncConnection(cursor)
    assert conn.autocommit is False
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    with _patch_connect(conn):
        result = await execute_sql_step(pool, "s1", "default", "SELECT 1")
    assert result.status is StepStatus.PASS
    assert conn.autocommit is False  # unchanged


# ---------------------------------------------------------------------------
# (k) rollback() is called before switching to autocommit (F-3)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ddl_rollback_called_before_autocommit() -> None:
    """Driver calls rollback() before switching to autocommit (clears any open tx)."""
    cursor = _FakeAsyncCursor(rows_sequence=[(None, None, 0)])
    conn = _FakeAsyncConnection(cursor)
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    with _patch_connect(conn):
        await execute_sql_step(pool, "ddl", "default", "CREATE DATABASE testdb")
    assert conn.rollbacks >= 1  # rollback was called before autocommit switch


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


# ---------------------------------------------------------------------------
# (n) Autocommit DDL branch issues SET statement_timeout BEFORE switching
#     to autocommit (§14 R5 — symmetric timeout layering).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_autocommit_ddl_sets_statement_timeout_before_autocommit() -> None:
    """DDL path must SET statement_timeout while still inside the implicit tx,
    i.e. BEFORE conn.autocommit = True. Once autocommit is True there is no
    implicit transaction context for SET to live in.

    This test pins the ordering: we record which SQL strings hit conn.execute
    (driver-level, used for SET) vs cursor.execute (DDL itself) and verify the
    SET happens first in conn.executed AND that autocommit was flipped True
    *after* the SET (we observe via the rollback->SET->autocommit ordering).
    """
    cursor = _FakeAsyncCursor(rows_sequence=[(None, None, 0)])

    # Track autocommit transition timestamps relative to executed-list growth.
    # We override __setattr__ via a subclass so we can capture WHEN the
    # autocommit flag flipped relative to the conn.executed list snapshot.
    class _OrderingConn(_FakeAsyncConnection):
        def __init__(self, cur: _FakeAsyncCursor) -> None:
            super().__init__(cur)
            self.executed_len_when_autocommit_set: int | None = None

        def __setattr__(self, name: str, value: object) -> None:
            if name == "autocommit" and value is True:
                # Capture the size of executed at the moment autocommit flips True.
                # Use object.__setattr__ to avoid recursion / the not-yet-initialized
                # attribute case during base __init__.
                executed = self.__dict__.get("executed")
                if executed is not None:
                    object.__setattr__(self, "executed_len_when_autocommit_set", len(executed))
            object.__setattr__(self, name, value)

    conn = _OrderingConn(cursor)
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    with _patch_connect(conn):
        result = await execute_sql_step(
            pool,
            "ddl-timeout",
            "default",
            "DROP DATABASE IF EXISTS mydb",
            timeout_ms=5000,
        )
    assert result.status is StepStatus.PASS
    # SET statement_timeout was issued.
    set_indices = [i for i, q in enumerate(conn.executed) if "statement_timeout = 5000" in q]
    assert set_indices, f"expected SET statement_timeout in conn.executed, got {conn.executed!r}"
    # The SET must appear BEFORE autocommit was switched to True. The captured
    # length equals the number of conn.execute() calls completed prior to the
    # flip — the SET's index must be < that length.
    assert conn.executed_len_when_autocommit_set is not None, "autocommit was never set to True"
    assert set_indices[0] < conn.executed_len_when_autocommit_set, (
        f"SET (idx={set_indices[0]}) must precede autocommit flip "
        f"(executed_len at flip={conn.executed_len_when_autocommit_set})"
    )
    # And rollback happened before SET (clears any pre-existing tx state).
    assert conn.rollbacks >= 1


# ---------------------------------------------------------------------------
# (o) Autocommit DDL branch with timeout_ms=None issues NO SET — preserve
#     existing behavior when caller declines a timeout (§14 R5: opt-in).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_autocommit_ddl_without_timeout_issues_no_set() -> None:
    """When timeout_ms is None or 0, the DDL path must not issue any SET on
    the connection (matches the tx branch's opt-in behavior)."""
    cursor = _FakeAsyncCursor(rows_sequence=[(None, None, 0)])
    conn = _FakeAsyncConnection(cursor)
    pool = SqlSessionPool({"default": "postgresql://stub/db"})
    with _patch_connect(conn):
        result = await execute_sql_step(
            pool, "ddl-no-timeout", "default", "DROP DATABASE IF EXISTS mydb"
        )
    assert result.status is StepStatus.PASS
    assert not any("statement_timeout" in q for q in conn.executed), (
        f"expected no SET statement_timeout when timeout_ms=None, got {conn.executed!r}"
    )
