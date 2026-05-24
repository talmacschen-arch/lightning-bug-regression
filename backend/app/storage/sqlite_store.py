"""SQLite store: engine init, session contextmanager, and CRUD helpers.

Design.md §4.2 / §4.3 / §4.4. Schema lives in alembic migration 0001 and is
mirrored 1:1 by `app.storage.models` (see that module's docstring for the
dispatch-vs-alembic discrepancy resolution).

The session contextmanager is the only blessed way to obtain a Session in
business code; it guarantees commit-on-success / rollback-on-error / close.
CRUD helpers all take an externally-managed `session` so callers can batch
multiple writes inside a single transaction.

`uniq_runs_running` enforces at-most-one row with `status='running'`. When
`create_run` would violate that index, IntegrityError is caught and
re-raised as `ActiveRunExists` so the API layer (M1-10) can translate it
into HTTP 409 without leaking SQLAlchemy types.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.storage.models import CaseResult, CaseSkipList, Run, SystemSetting

__all__ = [
    "ActiveRunExists",
    "create_run",
    "finish_run",
    "get_run",
    "get_session",
    "add_skip_list_entry",
    "delete_skip_list_entry",
    "list_settings",
    "get_setting",
    "init_engine",
    "insert_case_result",
    "list_case_results",
    "list_recent_runs_for_case",
    "list_runs",
    "set_setting",
    "get_skip_list",
]


class ActiveRunExists(Exception):
    """Raised when `create_run` would violate `uniq_runs_running` —
    i.e. another row already has status='running'. API layer translates
    this to HTTP 409 Conflict (design.md §4.2 v0.5, §5 POST /runs).
    """


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(database_url: str) -> None:
    """Idempotent. Call once at app startup before any get_session()."""
    global _engine, _SessionLocal
    _engine = create_engine(database_url, future=True)
    _SessionLocal = sessionmaker(
        bind=_engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a Session: commit on clean exit, rollback on exception, always close."""
    if _SessionLocal is None:
        raise RuntimeError("storage engine not initialized — call init_engine() first")
    sess = _SessionLocal()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


def create_run(
    session: Session,
    *,
    started_at: datetime,
    triggered_by: str | None = None,
    target_version: str | None = None,
) -> Run:
    """Insert a new `runs` row with status='running'.

    Catches IntegrityError from the `uniq_runs_running` partial index and
    re-raises as `ActiveRunExists` (API layer → HTTP 409). Other
    IntegrityErrors propagate unchanged.
    """
    run = Run(
        started_at=started_at,
        triggered_by=triggered_by,
        target_version=target_version,
        status="running",
    )
    session.add(run)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        # SQLite's error message for a partial-unique-index violation looks
        # like "UNIQUE constraint failed: runs.status". The only UNIQUE
        # constraint on runs.status is uniq_runs_running (design.md §4.2),
        # so this match is precise and won't swallow FK / NOT-NULL errors
        # (which produce different messages).
        msg = str(exc.orig)
        if "UNIQUE constraint failed: runs.status" in msg or "uniq_runs_running" in msg:
            raise ActiveRunExists("another run with status='running' already exists") from exc
        raise
    return run


def get_run(session: Session, run_id: int) -> Run | None:
    return session.get(Run, run_id)


def list_runs(session: Session, limit: int = 50) -> list[Run]:
    stmt = select(Run).order_by(Run.id.desc()).limit(limit)
    return list(session.scalars(stmt).all())


def finish_run(
    session: Session,
    run_id: int,
    *,
    status: str,
    finished_at: datetime,
    total: int | None = None,
    passed: int | None = None,
    failed: int | None = None,
    skipped: int | None = None,
) -> None:
    """Mark a run as terminated. `status` should be 'done' or 'aborted'
    (design.md §4.2). Caller is responsible for valid status strings.
    """
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    run.status = status
    run.finished_at = finished_at
    if total is not None:
        run.total = total
    if passed is not None:
        run.passed = passed
    if failed is not None:
        run.failed = failed
    if skipped is not None:
        run.skipped = skipped
    session.flush()


# ---------------------------------------------------------------------------
# case_results
# ---------------------------------------------------------------------------


def insert_case_result(
    session: Session,
    *,
    run_id: int,
    case_id: str,
    status: str | None,
    duration_ms: int | None = None,
    skip_reason: str | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    expect_detail: str | None = None,
    artifacts_path: str | None = None,
) -> CaseResult:
    row = CaseResult(
        run_id=run_id,
        case_id=case_id,
        status=status,
        skip_reason=skip_reason,
        duration_ms=duration_ms,
        stdout=stdout,
        stderr=stderr,
        expect_detail=expect_detail,
        artifacts_path=artifacts_path,
    )
    session.add(row)
    session.flush()
    return row


def list_case_results(session: Session, run_id: int) -> list[CaseResult]:
    stmt = select(CaseResult).where(CaseResult.run_id == run_id).order_by(CaseResult.id)
    return list(session.scalars(stmt).all())


def list_recent_runs_for_case(
    session: Session, case_id: str, limit: int = 10
) -> list[tuple[CaseResult, Run]]:
    """List most-recent runs that touched a given case.

    Returns (CaseResult, Run) tuples ordered by run started_at DESC, with
    `limit` cap. Used by GET /cases/:id/recent-runs (M5-3 cross-page link).

    Reuses the existing `case_results` + `runs` schema (§14 R26 — no inline
    SQL or duplicate storage logic).
    """
    stmt = (
        select(CaseResult, Run)
        .join(Run, CaseResult.run_id == Run.id)
        .where(CaseResult.case_id == case_id)
        .order_by(Run.started_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).tuples())


# ---------------------------------------------------------------------------
# case_skip_list
# ---------------------------------------------------------------------------


def get_skip_list(session: Session) -> list[CaseSkipList]:
    """Return all skip-list rows (caller filters by until_date / version)."""
    stmt = select(CaseSkipList).order_by(CaseSkipList.id)
    return list(session.scalars(stmt).all())


def add_skip_list_entry(
    session: Session,
    *,
    case_id: str,
    reason: str,
    applies_to_version: str | None = None,
    upstream_issue: str | None = None,
    until_date: date | None = None,
) -> CaseSkipList:
    """Insert a new skip-list row. Returns the row with id populated."""
    row = CaseSkipList(
        case_id=case_id,
        reason=reason,
        applies_to_version=applies_to_version,
        upstream_issue=upstream_issue,
        until_date=until_date,
    )
    session.add(row)
    session.flush()
    return row


def delete_skip_list_entry(session: Session, entry_id: int) -> bool:
    """Delete by primary key; return True if a row was removed."""
    row = session.get(CaseSkipList, entry_id)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def list_settings(session: Session) -> list[SystemSetting]:
    """Return all settings rows ordered by key."""
    stmt = select(SystemSetting).order_by(SystemSetting.key)
    return list(session.scalars(stmt).all())


# ---------------------------------------------------------------------------
# system_settings
# ---------------------------------------------------------------------------


def get_setting(session: Session, key: str) -> dict | None:
    """Return the stored value for `key`, parsed as JSON, or None.

    The alembic schema stores `value` as TEXT (with a separate `value_type`
    column) so that a single column can hold strings / ints / bools / JSON.
    For the M1-3 dispatch we standardize on JSON-serialized values; callers
    that need scalars wrap them like `{"v": 42}`. value_type is fixed to
    'json'.
    """
    row = session.get(SystemSetting, key)
    if row is None:
        return None
    return json.loads(row.value)


def set_setting(session: Session, key: str, value: dict) -> None:
    """Upsert (key, value) into system_settings. Refreshes updated_at."""
    row = session.get(SystemSetting, key)
    serialized = json.dumps(value, sort_keys=True)
    now = datetime.utcnow()
    if row is None:
        row = SystemSetting(
            key=key,
            value=serialized,
            value_type="json",
            updated_at=now,
        )
        session.add(row)
    else:
        row.value = serialized
        row.value_type = "json"
        row.updated_at = now
    session.flush()
