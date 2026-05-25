"""Async psycopg3 SQL driver (design.md §5, §14 R5/R9).

Per-session connection pool: maps session name (from step.on / YAML
sessions.<name>) to a persistent psycopg AsyncConnection so a suite's
SET / BEGIN / temp-table state survives across steps with the same on:.

**Scope (per design.md §4.1.2)**: this driver is for tx-safe SQL ONLY.
Non-tx-safe DDL (VACUUM / ANALYZE 顶层 / CREATE DATABASE / DROP DATABASE /
REINDEX CONCURRENTLY / CREATE INDEX CONCURRENTLY / CREATE/DROP TABLESPACE /
ALTER SYSTEM / CLUSTER) MUST be written in YAML as `kind: shell` +
`cmd: su - gpadmin -c "psql -c '<DDL>'"` per the §4.1.2 convention. This
driver does NOT attempt to detect or auto-route non-tx-safe DDL — earlier
versions had a `_needs_autocommit` regex + autocommit branch but it kept
tripping over psycopg AsyncConnection semantics (`autocommit` is a
read-only property + can't switch while INTRANS); maintaining it was an
arms race. Non-tx-safe DDL sent through `kind: sql` will fail with PG's
own error ("VACUUM cannot run inside a transaction block") which is the
desired fail-fast: the YAML author then rewrites per §4.1.2.

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
import logging
import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime

import psycopg
from psycopg import AsyncConnection
from psycopg.pq import TransactionStatus

from app.runner.types import StepError, StepResult, StepStatus

logger = logging.getLogger(__name__)

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

    async def discard_all(self) -> None:
        """Reset session state on every open connection.

        Called by orchestrator at the start of each case to prevent
        session-level GUC + prepared-statement leakage from one case to
        the next (dogfood 2026-05-26: lg-bug-0011/0012's non-LOCAL
        ``SET work_mem='256kB'`` + ``SET enable_seqscan = off`` persisted
        into the persistent AsyncConnection and broke lg-xs-zombodb at
        the suite tail).

        Uses ``RESET ALL`` + ``DEALLOCATE ALL`` (both tx-safe) rather
        than ``DISCARD ALL`` — PostgreSQL refuses ``DISCARD ALL`` inside
        a transaction block, and psycopg3 with autocommit=False wraps
        every ``execute()`` in an implicit ``BEGIN``. PR-F's original
        ``DISCARD ALL`` cascaded into ``InFailedSqlTransaction`` across
        12/17 cases in dogfood run #32: the failed DISCARD aborted the
        implicit tx, the bare except just logged a warning and left the
        conn in INERROR, then the next case's first SQL hit the poisoned
        connection and errored at 2-8ms.

        What this DOES NOT clear vs ``DISCARD ALL``: temp tables, plan
        cache, sequence cache. None of these are case-isolation pain
        points in practice — cases don't share temp tables (CREATE TEMP
        TABLE is session-local + the next case's setup explicitly
        DROPs/CREATEs its own state). If any of these become a pain
        point, escalate to a real ``DISCARD ALL`` via an autocommit
        toggle.

        Idempotent — no-op on unopened sessions (empty ``_conns``).

        R9 fold-don't-bubble: per-connection errors caught + logged, AND
        a best-effort ``rollback()`` so a failed reset doesn't leave the
        conn in aborted-tx state poisoning the next case (the regression
        class above).
        """
        for session_name, conn in self._conns.items():
            try:
                # If a prior step left the conn in INTRANS / INERROR,
                # rollback first so RESET ALL / DEALLOCATE ALL see a
                # clean tx state.
                if conn.info.transaction_status != TransactionStatus.IDLE:
                    await conn.rollback()
                async with conn.cursor() as cur:
                    await cur.execute("RESET ALL")
                    await cur.execute("DEALLOCATE ALL")
                await conn.commit()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "session %s reset failed (RESET ALL / DEALLOCATE ALL): %s "
                    "— rolling back to leave conn usable",
                    session_name,
                    e,
                )
                try:
                    await conn.rollback()
                except Exception:  # noqa: BLE001
                    pass


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
        try:
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
            # Commit the step's tx so subsequent steps — especially cross-driver
            # shell+psql steps — see this step's CREATE TABLE / INSERT data.
            # Without this commit: psycopg long-lived AsyncConnection holds an
            # uncommitted tx; a separate `psql -c` subprocess can't see those
            # writes. M4a-2/-3 lg-bug-0008 exposed this when the case mixed
            # kind: sql (setup INSERT) with kind: shell (VACUUM FULL via psql).
            # For all-sql cases the commit doesn't change intra-case visibility
            # (same-tx already saw own writes); teardown DROP still cleans up.
            await conn.commit()
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
            # Roll back any open tx so the connection is usable for the next
            # step. Per §4.1.2 we no longer try to handle non-tx-safe DDL
            # here — those go through psql -c / shell driver, so this driver
            # is always inside a normal tx that rollback restores cleanly.
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
