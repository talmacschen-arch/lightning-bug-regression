"""Async psycopg3 SQL driver (design.md §5, §14 R5/R9).

Per-session connection pool: maps session name (from step.on / YAML
sessions.<name>) to a persistent psycopg AsyncConnection so a suite's
SET / BEGIN / temp-table state survives across steps with the same on:.

Timeout: dual-layer per §14 R5:
  layer 1: psycopg `SET statement_timeout = <ms>` per connection
  layer 2: asyncio.wait_for(coro, timeout=ms/1000 + 1.0)
The +1.0s slack lets psycopg's own timeout fire first with a useful
'canceling statement due to statement timeout' message; only when
psycopg deadlocks does asyncio rescue.

NOTICE capture: register a psycopg notice_handler that appends each
notice line to a per-step buffer. Stored into StepResult.stderr so
log_grep assertions and humans can see 'do not have statistics' etc.
(lg-bug-0002 / lg-bug-0003 depend on this.)

R9: NEVER let an exception bubble. Catch everything -> StepResult(status=ERROR, error=str(exc)).
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime

import psycopg
from psycopg import AsyncConnection

from app.runner.types import StepError, StepResult, StepStatus

# Regex: SQL that cannot run inside a transaction block (per §14 R5/R9 / F-3).
# Matches if ANY statement in the SQL starts with one of these DDL keywords.
#
# **Known uncovered patterns** (defense-in-depth gap, accepted per §4.1.2):
#   - CREATE / DROP INDEX CONCURRENTLY  (PG: explicitly non-tx)
#   - CREATE / DROP TABLESPACE          (some distros require non-tx)
#   - other vendor-specific DDL we haven't catalogued
#
# We do NOT try to exhaustively enumerate every non-tx-safe DDL — that
# arms race is brittle (every new PG version may add one). The **first-line
# defense** is the design.md §4.1.2 convention: YAML authors write
# `psql -c '<DDL>'` for ANY non-tx-safe DDL, which the dogfood normalizer
# routes to shell_driver and never enters this sql_driver code path.
# This regex is the **second-line tripwire** — only catches what we know
# about. Missing patterns slip through and surface as a clear PG error
# ("CREATE INDEX CONCURRENTLY cannot run inside a transaction block")
# in stderr, at which point the YAML author should rewrite the case per
# §4.1.2 rather than us patching this regex.
_NON_TX_DDL_RE = re.compile(
    r"(?:^|;\s*)(?:DROP\s+DATABASE|CREATE\s+DATABASE|VACUUM|REINDEX\s+CONCURRENTLY"
    r"|ALTER\s+SYSTEM|CLUSTER)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _needs_autocommit(sql: str) -> bool:
    """Return True if sql contains non-transaction-safe DDL (F-3 defense-in-depth).

    Primary convention is design.md §4.1.2 (`psql -c '<DDL>'` in YAML);
    this only catches cases that slipped past it. Known uncovered patterns
    listed in `_NON_TX_DDL_RE` docstring above.
    """
    return bool(_NON_TX_DDL_RE.search(sql))


# Regex: detect whether an SQL string starts with EXPLAIN (per F-2 plan_text populate).
_EXPLAIN_RE = re.compile(r"(?:^|;)\s*EXPLAIN\b", re.IGNORECASE)


def _is_explain_query(sql: str) -> bool:
    return bool(_EXPLAIN_RE.search(sql))


class SqlSessionPool:
    """Owns one AsyncConnection per session-name. Idempotent acquire,
    explicit close_all() at suite end."""

    def __init__(self, dsn_per_session: Mapping[str, str]):
        """dsn_per_session: session_name -> psycopg DSN string.
        Caller resolves coordinator host / external service config to DSNs
        before constructing the pool."""
        self._dsn = dict(dsn_per_session)
        self._conns: dict[str, AsyncConnection] = {}

    async def acquire(self, session: str) -> AsyncConnection:
        """Open the connection on first use; reuse thereafter.
        Raises StepError if session name not in DSN map."""
        if session not in self._dsn:
            raise StepError(f"unknown sql session: {session!r}")
        if session not in self._conns:
            self._conns[session] = await psycopg.AsyncConnection.connect(
                self._dsn[session], autocommit=False
            )
        return self._conns[session]

    async def close_all(self) -> None:
        for conn in self._conns.values():
            try:
                await conn.close()
            except Exception:
                pass
        self._conns.clear()


async def execute_sql_step(
    pool: SqlSessionPool,
    step_id: str,
    session: str,
    sql: str,
    timeout_ms: int | None = None,
) -> StepResult:
    """Execute one SQL step on a session connection.

    - statement_timeout enforced both via SET on the conn and asyncio.wait_for.
    - Captures NOTICE/WARNING lines into stderr.
    - For multi-statement SQL: cursor.execute() runs the whole batch but only
      the LAST result set is exposed via row_count / scalar.
    - scalar = first row first column of last result set, or None.
    - rows_affected = cursor.rowcount when last statement was a DML and not a SELECT.

    Returns StepResult always - never raises (R9).
    """
    started = _iso_now()
    t0 = time.monotonic()
    notices: list[str] = []

    async def _run() -> StepResult:
        try:
            conn = await pool.acquire(session)
        except StepError as e:
            return _err(step_id, started, t0, str(e), notices)
        except Exception as exc:
            return _err(step_id, started, t0, f"{type(exc).__name__}: {exc}", notices)

        # Notice handler: psycopg AsyncConnection has add_notice_handler.
        # The callback receives a psycopg.errors.Diagnostic.
        def _on_notice(diag: object) -> None:
            try:
                severity = getattr(diag, "severity", None) or "NOTICE"
                message = getattr(diag, "message_primary", None) or str(diag)
                notices.append(f"{severity}: {message}")
            except Exception:
                try:
                    notices.append(str(diag))
                except Exception:
                    pass

        conn.add_notice_handler(_on_notice)
        needs_ac = _needs_autocommit(sql)
        try:
            if needs_ac:
                # Non-tx-safe DDL: must run outside a transaction.
                # Roll back any open transaction first (e.g. from SET statement_timeout
                # on a prior step), then issue our own SET inside the still-implicit
                # transaction, then switch to autocommit mode. Order matters:
                # SET statement_timeout requires an active transaction context;
                # once autocommit=True there is no implicit tx, so SET would either
                # fail or behave inconsistently (§14 R5 — symmetric timeout layering
                # must apply to autocommit DDL too, not just the tx branch).
                try:
                    await conn.rollback()
                except Exception:
                    pass
                if timeout_ms is not None and timeout_ms > 0:
                    await conn.execute(f"SET statement_timeout = {int(timeout_ms)}")
                # psycopg AsyncConnection.autocommit is read-only as property —
                # must use await set_autocommit() (sync conn allows assignment;
                # AsyncConnection does not). M4a-2 dogfood (case lg-bug-0008
                # VACUUM FULL) tripped this with AttributeError.
                await conn.set_autocommit(True)
                async with conn.cursor() as cur:
                    await cur.execute(sql)
                    # DDL returns no rows.
                    ended = _iso_now()
                    duration_ms = int((time.monotonic() - t0) * 1000)
                    return StepResult(
                        status=StepStatus.PASS,
                        step_id=step_id,
                        driver="sql",
                        started_at=started,
                        ended_at=ended,
                        duration_ms=duration_ms,
                        stdout="",
                        stderr="\n".join(notices),
                        rows_affected=cur.rowcount if cur.rowcount >= 0 else None,
                    )
            else:
                if timeout_ms is not None and timeout_ms > 0:
                    await conn.execute(f"SET statement_timeout = {int(timeout_ms)}")
                async with conn.cursor() as cur:
                    await cur.execute(sql)
                    # Walk to LAST result set when multi-statement.
                    last_rows: list[tuple] | None = None
                    last_rowcount: int = cur.rowcount
                    last_description = cur.description
                    if cur.description is not None:
                        last_rows = await cur.fetchall()
                    # Cycle through additional result sets if present (F-3 multi-statement).
                    while cur.nextset():
                        last_rowcount = cur.rowcount
                        last_description = cur.description
                        if cur.description is not None:
                            last_rows = await cur.fetchall()
                    ended = _iso_now()
                    duration_ms = int((time.monotonic() - t0) * 1000)
                    scalar = None
                    row_count: int | None = None
                    rows_affected: int | None = None
                    stdout = ""
                    if last_description is not None and last_rows is not None:
                        row_count = len(last_rows)
                        if last_rows and last_rows[0]:
                            scalar = last_rows[0][0]
                        # render small preview
                        stdout = "\n".join(repr(r) for r in last_rows[:20])
                    else:
                        rows_affected = last_rowcount if last_rowcount >= 0 else None
                    # F-2: populate plan_text from EXPLAIN output (raw line strings, not repr'd).
                    plan_text: str | None = None
                    if (
                        _is_explain_query(sql)
                        and last_description is not None
                        and last_rows is not None
                    ):
                        # EXPLAIN output: each row is typically (plan_line,) — 1-column text.
                        plan_text = "\n".join(str(r[0]) for r in last_rows)
                    return StepResult(
                        status=StepStatus.PASS,
                        step_id=step_id,
                        driver="sql",
                        started_at=started,
                        ended_at=ended,
                        duration_ms=duration_ms,
                        stdout=stdout,
                        stderr="\n".join(notices),
                        scalar=scalar,
                        row_count=row_count,
                        rows_affected=rows_affected,
                        plan_text=plan_text,
                    )
        except Exception as exc:
            # In autocommit mode (F-3 DDL path) there's no open tx to roll back —
            # `rollback()` is harmless but misleading. Guard so the call only fires
            # when it's semantically meaningful.
            if not getattr(conn, "autocommit", False):
                try:
                    await conn.rollback()
                except Exception:
                    pass
            return _err(step_id, started, t0, f"{type(exc).__name__}: {exc}", notices)
        finally:
            try:
                conn.remove_notice_handler(_on_notice)
            except Exception:
                pass
            if needs_ac:
                # Restore autocommit=False so future steps on this connection are
                # transactional. AsyncConnection requires await set_autocommit()
                # (see comment at line ~170 — same bug, symmetric fix).
                try:
                    await conn.set_autocommit(False)
                except Exception:
                    pass

    if timeout_ms is not None and timeout_ms > 0:
        try:
            return await asyncio.wait_for(_run(), timeout=(timeout_ms / 1000.0) + 1.0)
        except TimeoutError:
            return _err(
                step_id,
                started,
                t0,
                f"asyncio.TimeoutError (statement_timeout={timeout_ms}ms exceeded by >1s)",
                notices,
            )
    else:
        return await _run()


def _iso_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _err(step_id: str, started: str, t0: float, msg: str, notices: list[str]) -> StepResult:
    return StepResult(
        status=StepStatus.ERROR,
        step_id=step_id,
        driver="sql",
        started_at=started,
        ended_at=_iso_now(),
        duration_ms=int((time.monotonic() - t0) * 1000),
        stdout="",
        stderr="\n".join(notices),
        error=msg,
    )
