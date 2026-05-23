"""Runs router — POST /runs, GET /runs, GET /runs/{id} (design.md §5.2 / §4.2).

Concurrency contract:
  POST /runs creates the runs row with status='running' synchronously.
  The partial-unique index `uniq_runs_running` (§4.2 v0.5) means a
  second POST while another run is active is rejected by
  `sqlite_store.create_run` (typed `ActiveRunExists`) which we translate
  into HTTP 409.

  Execution itself runs in a FastAPI BackgroundTask so the HTTP response
  returns immediately with 202 + run_id. The task body calls
  `orchestrator.run_suite` and then `finish_run` to flip status to
  'done' (or 'aborted' on unexpected failure).

  SSE streaming of run events lives in M5; this router only exposes
  CRUD-shaped endpoints.

Out-of-scope here (deferred to later milestones):
  * /runs/{id}/stream (SSE) — M5
  * cancel / abort — needs orchestrator support, deferred
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.cases import _iter_case_files, _load_categories
from app.runner import orchestrator
from app.runner.case_normalizer import normalize_case
from app.storage import sqlite_store
from app.storage.models import CaseCategory, Run

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])


# ---------------------------------------------------------------------------
# Pydantic shapes
# ---------------------------------------------------------------------------


class CreateRunRequest(BaseModel):
    case_ids: list[str] | None = None
    target_version: str | None = None
    triggered_by: str | None = None


class CreateRunResponse(BaseModel):
    run_id: int
    status: str
    started_at: datetime
    location: str


class RunSummary(BaseModel):
    id: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    total: int | None = None
    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None
    target_version: str | None = None
    triggered_by: str | None = None


class CaseResultOut(BaseModel):
    case_id: str
    status: str | None = None
    duration_ms: int | None = None
    skip_reason: str | None = None
    expect_detail: str | None = None
    artifacts_path: str | None = None


class RunDetail(RunSummary):
    case_results: list[CaseResultOut] = []


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _artifacts_root() -> Path:
    return Path(os.getenv("ARTIFACTS_ROOT", "artifacts"))


def _load_jinja_context_and_dut_hosts() -> tuple[dict[str, Any], set[str]]:
    """Read jinja_context + dut_hosts from system_settings.

    M1-11 dogfood seeds these via system_settings before triggering runs.
    Missing → empty dict / empty set so dev/test runs work without setup.
    """
    jinja_ctx: dict[str, Any] = {}
    dut_hosts: set[str] = set()
    try:
        with sqlite_store.get_session() as sess:
            jc = sqlite_store.get_setting(sess, "jinja_context")
            if isinstance(jc, dict):
                jinja_ctx = jc
            dh = sqlite_store.get_setting(sess, "dut_hosts")
            if isinstance(dh, dict):
                # stored as {"hosts": ["mdw", "sdw1", ...]}
                hosts = dh.get("hosts")
                if isinstance(hosts, list):
                    dut_hosts = {str(h) for h in hosts}
            elif isinstance(dh, list):
                dut_hosts = {str(h) for h in dh}
    except Exception as e:  # noqa: BLE001 — startup-style; log and continue
        logger.warning("could not read jinja_context/dut_hosts settings: %s", e)
    return jinja_ctx, dut_hosts


def _load_cases_from_disk(
    requested_ids: list[str] | None,
    categories: list[CaseCategory],
) -> list[dict[str, Any]]:
    """Read selected case YAMLs from disk into orchestrator-shaped dicts.

    If `requested_ids` is None, load every *.yaml under every active
    category's dir_path. Otherwise filter by id (stem).

    A YAML that fails to parse is skipped (logged); same for cases whose
    normalization fails (e.g. step missing `kind`).

    Calls `case_normalizer.normalize_case` to convert raw §4.1 YAML
    (setup: list[str], step's kind/driver/name aliases, per-step database
    override) into the dict shape orchestrator expects. Without this,
    raw `setup: list[str]` items reach `_execute_one_step(step: dict)`
    and crash at `_step_id`'s `step.get("id")`. M2 dogfood revealed this
    on 2026-05-24; previously only the M1 dogfood script normalized
    (design.md §14 R26 候选 — dual code path divergence).
    """
    requested = set(requested_ids) if requested_ids is not None else None
    out: list[dict[str, Any]] = []
    for path, _cat_name in _iter_case_files(categories):
        if requested is not None and path.stem not in requested:
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as e:
            logger.warning("skipping unreadable case %s: %s", path, e)
            continue
        if not isinstance(data, dict):
            logger.warning("skipping case %s: top-level YAML not a mapping", path)
            continue
        try:
            normalized = normalize_case(data)
        except ValueError as e:
            logger.warning("skipping case %s: normalize failed: %s", path, e)
            continue
        out.append(normalized)
    return out


async def _execute_run(
    run_id: int,
    cases: list[dict[str, Any]],
    artifacts_root: Path,
    jinja_context: dict[str, Any],
    dut_hosts: set[str],
) -> None:
    """Background task body. Folds all exceptions: status flips to
    'aborted' on unexpected failure, never re-raises (BackgroundTasks
    swallows exceptions but logs them — we want our own structured log)."""
    try:
        summary = await orchestrator.run_suite(
            cases,
            run_id=run_id,
            artifacts_root=artifacts_root,
            jinja_context=jinja_context,
            dut_hosts=dut_hosts,
            session_factory=sqlite_store.get_session,
        )
        with sqlite_store.get_session() as sess:
            sqlite_store.finish_run(
                sess,
                run_id,
                status="done",
                finished_at=datetime.utcnow(),
                total=summary.total,
                passed=summary.passed,
                failed=summary.failed,
                skipped=summary.skipped,
            )
    except Exception:  # noqa: BLE001 — background task must not re-raise
        logger.exception("run %d aborted by unexpected exception", run_id)
        try:
            with sqlite_store.get_session() as sess:
                sqlite_store.finish_run(
                    sess,
                    run_id,
                    status="aborted",
                    finished_at=datetime.utcnow(),
                )
        except Exception:  # noqa: BLE001
            logger.exception("failed to mark run %d aborted", run_id)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=CreateRunResponse)
def create_run(
    body: CreateRunRequest,
    background_tasks: BackgroundTasks,
    response: Response,
) -> CreateRunResponse | JSONResponse:
    """Create a run row and spawn the orchestrator in the background.

    Returns 202 with `{run_id, status, started_at, location}`. The
    `Location` header also points to `/runs/<id>` for the standard REST
    pattern.

    Returns 409 with `{detail, active_run_id}` if another run is already
    in flight (uniq_runs_running enforced by SQLite).
    """
    started_at = datetime.utcnow()
    categories = _load_categories()
    cases = _load_cases_from_disk(body.case_ids, categories)

    # Reserve the run row (this is the 409 trigger if another is active).
    try:
        with sqlite_store.get_session() as sess:
            run = sqlite_store.create_run(
                sess,
                started_at=started_at,
                triggered_by=body.triggered_by,
                target_version=body.target_version,
            )
            run_id = run.id
    except sqlite_store.ActiveRunExists:
        # Find the active run's id so the client can poll it.
        with sqlite_store.get_session() as sess:
            active = sess.scalars(select(Run).where(Run.status == "running")).first()
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "another run is already active",
                "active_run_id": active.id if active is not None else None,
            },
        )

    jinja_context, dut_hosts = _load_jinja_context_and_dut_hosts()
    artifacts_root = _artifacts_root()

    background_tasks.add_task(
        _execute_run,
        run_id,
        cases,
        artifacts_root,
        jinja_context,
        dut_hosts,
    )

    response.headers["Location"] = f"/runs/{run_id}"
    return CreateRunResponse(
        run_id=run_id,
        status="running",
        started_at=started_at,
        location=f"/runs/{run_id}",
    )


@router.get("", response_model=list[RunSummary])
def list_runs(limit: int = 50) -> list[RunSummary]:
    """Return the most recent runs (newest first), capped at `limit`."""
    with sqlite_store.get_session() as sess:
        rows = sqlite_store.list_runs(sess, limit=limit)
        return [
            RunSummary(
                id=r.id,
                status=r.status,
                started_at=r.started_at,
                finished_at=r.finished_at,
                total=r.total,
                passed=r.passed,
                failed=r.failed,
                skipped=r.skipped,
                target_version=r.target_version,
                triggered_by=r.triggered_by,
            )
            for r in rows
        ]


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: int) -> RunDetail:
    """Return one run + its case_results array. 404 if the id doesn't
    exist."""
    with sqlite_store.get_session() as sess:
        run = sqlite_store.get_run(sess, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} not found")
        cr_rows = sqlite_store.list_case_results(sess, run_id)
        return RunDetail(
            id=run.id,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            total=run.total,
            passed=run.passed,
            failed=run.failed,
            skipped=run.skipped,
            target_version=run.target_version,
            triggered_by=run.triggered_by,
            case_results=[
                CaseResultOut(
                    case_id=cr.case_id,
                    status=cr.status,
                    duration_ms=cr.duration_ms,
                    skip_reason=cr.skip_reason,
                    expect_detail=cr.expect_detail,
                    artifacts_path=cr.artifacts_path,
                )
                for cr in cr_rows
            ],
        )


__all__ = ["router"]
