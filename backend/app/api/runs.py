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

  SSE streaming of run events lives at GET /runs/{id}/stream (M6-1).

  Per-step artifact listing + download lives at GET /runs/{id}/cases/
  {case_id}/artifacts and .../artifacts/{filename} (M6-2). Files written
  by orchestrator under <artifacts_root>/<run_id>/<case_id>/.

Out-of-scope here (deferred to later milestones):
  * cancel / abort — needs orchestrator support, deferred
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.auth import CurrentUser
from app.api.cases import _iter_case_files, _load_categories
from app.runner import event_broker, orchestrator
from app.runner.case_normalizer import normalize_case
from app.runner.dsn_builder import dsn_map_from_external_or_env
from app.runner.external_deps_loader import (
    collect_external_deps,
    load_external_context,
)
from app.runner.sql_driver import SqlSessionPool
from app.storage import sqlite_store
from app.storage.models import CaseCategory, Run
from app.utils.time import as_utc

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
    errored: int | None = None
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


class ArtifactInfo(BaseModel):
    """One artifact file under a case's artifacts_path (M6-2).

    `step_idx` / `step_id` populated when filename matches the runner's
    `step-NN-stepid.{stdout,stderr,error,log}.txt` pattern; else None
    (file written by something else, kept for transparency).

    `kind` values:
      * `stdout`  — driver stdout buffer
      * `stderr`  — driver stderr buffer (NOTICE/WARNING etc.)
      * `error`   — driver-level exception text (e.g. psycopg.errors.*
                    from sql_driver._err()); only written when the
                    StepResult.error field is non-empty
      * `log`     — auxiliary log captured by the runner
      * `other`   — filename did not match the per-step pattern
    """

    filename: str
    size_bytes: int
    kind: str  # 'stdout' | 'stderr' | 'error' | 'log' | 'other'
    step_idx: int | None = None
    step_id: str | None = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _artifacts_root() -> Path:
    return Path(os.getenv("ARTIFACTS_ROOT", "artifacts"))


def _dut_hosts_from_external() -> set[str]:
    """Read DUT host list from `external/dut.yml` (post-Settings removal).

    Replaces the M1-era system_settings reader: dut config moved to a
    single source of truth under external/, unifying with the M6-5
    external_deps mechanism. Missing file / missing `hosts` field →
    empty set (caller can still ssh as root to non-DUT boxes).

    `hosts` field shape: a YAML list like `[mdw, sdw1, sdw2]`. Anything
    else (None, dict, scalar) → empty set + warning.
    """
    dut = load_external_context(["dut"]).get("dut") or {}
    hosts_raw = dut.get("hosts")
    if not isinstance(hosts_raw, list):
        if hosts_raw is not None:
            logger.warning(
                "external/dut.yml: `hosts` must be a list, got %s; "
                "no DUT hosts will route to gpadmin user",
                type(hosts_raw).__name__,
            )
        return set()
    return {str(h) for h in hosts_raw}


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
    swallows exceptions but logs them — we want our own structured log).

    Builds a SqlSessionPool from PG* env vars (host/port/user/database)
    before invoking orchestrator. Without this, SQL steps unconditionally
    error with "sql step requires sql_pool to be configured" — M2 dogfood
    2026-05-24 followup.
    """
    sql_pool = SqlSessionPool(dsn_map_from_external_or_env(cases))
    # M6-5 + post-Settings: load external/<svc>.yml for every svc referenced
    # by cases' external_deps, PLUS always include `dut` so cases can
    # template `{{ external.dut.host }}` etc. Inject under
    # jinja_context["external"].
    svc_names = sorted({"dut", *collect_external_deps(cases)})
    external_ctx = load_external_context(svc_names)
    if external_ctx:
        # Merge but don't clobber: a user-supplied jinja_context.external
        # takes precedence (lets caller override per-run).
        existing_external = jinja_context.get("external")
        if isinstance(existing_external, dict):
            merged_external = {**external_ctx, **existing_external}
        else:
            merged_external = external_ctx
        jinja_context = {**jinja_context, "external": merged_external}

    # M6-6 wiring fix: load case_skip_list from DB and pass to orchestrator.
    # The M6-4 PR added CRUD endpoints for the table but the runner side
    # was never wired — discovered during dogfood when adding a skip via
    # /admin/skip-list did not actually skip the case. orchestrator's
    # run_suite already supports skip_list param; just plumb it in.
    try:
        with sqlite_store.get_session() as sess:
            skip_rows = sqlite_store.get_skip_list(sess)
            skip_list = [
                {
                    "case_id": r.case_id,
                    "applies_to_version": r.applies_to_version,
                    "reason": r.reason,
                    "until_date": r.until_date,
                    "upstream_issue": r.upstream_issue,
                }
                for r in skip_rows
            ]
    except Exception as e:  # noqa: BLE001 — startup-style, log + continue
        logger.warning("could not load skip_list, proceeding without: %s", e)
        skip_list = []

    try:
        summary = await orchestrator.run_suite(
            cases,
            run_id=run_id,
            artifacts_root=artifacts_root,
            jinja_context=jinja_context,
            dut_hosts=dut_hosts,
            session_factory=sqlite_store.get_session,
            sql_pool=sql_pool,
            skip_list=skip_list,
        )
        with sqlite_store.get_session() as sess:
            sqlite_store.finish_run(
                sess,
                run_id,
                status="done",
                finished_at=datetime.now(UTC),
                total=summary.total,
                passed=summary.passed,
                failed=summary.failed,
                skipped=summary.skipped,
                errored=summary.errored,
            )
        event_broker.publish_run_done(
            run_id,
            {
                "total": summary.total,
                "passed": summary.passed,
                "failed": summary.failed,
                "skipped": summary.skipped,
                "errored": summary.errored,
            },
        )
    except Exception as e:  # noqa: BLE001 — background task must not re-raise
        logger.exception("run %d aborted by unexpected exception", run_id)
        try:
            with sqlite_store.get_session() as sess:
                sqlite_store.finish_run(
                    sess,
                    run_id,
                    status="aborted",
                    finished_at=datetime.now(UTC),
                )
        except Exception:  # noqa: BLE001
            logger.exception("failed to mark run %d aborted", run_id)
        event_broker.publish_run_aborted(run_id, reason=f"{type(e).__name__}: {e}")
    finally:
        # Close pooled connections so they don't leak across runs (each
        # run gets a fresh pool — different cases may target different DBs).
        try:
            await sql_pool.close_all()
        except Exception:  # noqa: BLE001
            logger.exception("run %d: sql_pool.close_all failed", run_id)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=CreateRunResponse)
def create_run(
    body: CreateRunRequest,
    background_tasks: BackgroundTasks,
    response: Response,
    user: CurrentUser,
) -> CreateRunResponse | JSONResponse:
    """Create a run row and spawn the orchestrator in the background.

    Returns 202 with `{run_id, status, started_at, location}`. The
    `Location` header also points to `/runs/<id>` for the standard REST
    pattern.

    Returns 409 with `{detail, active_run_id}` if another run is already
    in flight (uniq_runs_running enforced by SQLite).

    v1.17+ auth: requires Bearer token. Auto-fills `triggered_by` with
    the authenticated user's username if the client doesn't supply one
    (single-user mode = always 'admin'). External curl scripts can still
    override by explicitly sending `triggered_by` in the body (e.g. CI
    bots want a distinct name).
    """
    started_at = datetime.now(UTC)
    categories = _load_categories()
    cases = _load_cases_from_disk(body.case_ids, categories)

    # v1.17: triggered_by defaults to current user; client can override.
    triggered_by = body.triggered_by or user.username

    # Reserve the run row (this is the 409 trigger if another is active).
    try:
        with sqlite_store.get_session() as sess:
            run = sqlite_store.create_run(
                sess,
                started_at=started_at,
                triggered_by=triggered_by,
                target_version=body.target_version,
                # Write total upfront so the UI progress bar can render
                # real done/total ratios live, not 0 → 100% jump at finish
                # (dogfood 2026-05-26: total stayed None during run; UI
                # fell back to case_results.length growing alongside done).
                total=len(cases),
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

    # Jinja context starts empty; `_execute_run` merges in external.*
    # context from external/<svc>.yml (M6-5) + external/dut.yml.
    jinja_context: dict[str, Any] = {}
    dut_hosts = _dut_hosts_from_external()
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
        started_at=as_utc(started_at),
        location=f"/runs/{run_id}",
    )


@router.get("", response_model=list[RunSummary])
def list_runs(
    limit: int = 50,
    case_id: str | None = None,
) -> list[RunSummary]:
    """Return the most recent runs (newest first), capped at `limit`.

    Optional `case_id` query param filters to runs that touched the
    given case (post-M6 UX, 2026-05-25). Example:
    `GET /runs?case_id=lg-bug-0009-union-all-const-distributed-row-order`
    returns only runs whose case_results array contains that case.
    """
    with sqlite_store.get_session() as sess:
        rows = sqlite_store.list_runs(sess, limit=limit, case_id=case_id)
        return [
            RunSummary(
                id=r.id,
                status=r.status,
                started_at=as_utc(r.started_at),
                finished_at=as_utc(r.finished_at),
                total=r.total,
                passed=r.passed,
                failed=r.failed,
                skipped=r.skipped,
                errored=r.errored,
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
            started_at=as_utc(run.started_at),
            finished_at=as_utc(run.finished_at),
            total=run.total,
            passed=run.passed,
            failed=run.failed,
            skipped=run.skipped,
            errored=run.errored,
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


# ---------------------------------------------------------------------------
# M6-1 SSE stream — GET /runs/{run_id}/stream
# ---------------------------------------------------------------------------


def _sse_format(event: dict[str, Any]) -> str:
    """Encode a JSON-serializable dict as one SSE event.

    SSE spec: `data: <line>\\n\\n` (blank line terminates an event).
    We use a single-line data field (JSON has no embedded newlines after
    json.dumps with default separators).
    """
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


async def _stream_run_events(run_id: int) -> AsyncIterator[str]:
    """Async generator yielding SSE-formatted lines for one run.

    Lifecycle:
      1. Emit `snapshot` event with current Run + CaseResults state
         (so a late subscriber sees baseline even if it missed earlier
         case_done events).
      2. Subscribe to broker; relay each event.
      3. Stop on terminal event (run_done / run_aborted) or if the run
         is ALREADY in a terminal lifecycle state at subscribe time.

    Heartbeat: every 20s emit `: keepalive\\n\\n` (SSE comment) to keep
    proxies/loadbalancers from closing the idle connection.
    """
    # Initial snapshot from DB
    with sqlite_store.get_session() as sess:
        run = sqlite_store.get_run(sess, run_id)
        if run is None:
            yield _sse_format({"type": "error", "message": f"run {run_id} not found"})
            return
        cr_rows = sqlite_store.list_case_results(sess, run_id)
        snapshot = {
            "type": "snapshot",
            "run_id": run.id,
            "status": run.status,
            "total": run.total,
            "passed": run.passed,
            "failed": run.failed,
            "skipped": run.skipped,
            "errored": run.errored,
            "case_results": [
                {
                    "case_id": cr.case_id,
                    "status": cr.status,
                    "duration_ms": cr.duration_ms,
                }
                for cr in cr_rows
            ],
        }
        is_already_terminal = run.status in ("done", "aborted")

    yield _sse_format(snapshot)

    # If the run already finished before the client subscribed, close
    # immediately with a synthetic terminal event so the client knows
    # to stop and refetch final state.
    if is_already_terminal:
        synthetic = {
            "type": "run_done" if snapshot["status"] == "done" else "run_aborted",
            "run_id": run_id,
            "summary": {
                "total": snapshot["total"],
                "passed": snapshot["passed"],
                "failed": snapshot["failed"],
                "skipped": snapshot["skipped"],
                "errored": snapshot["errored"],
            },
            "synthetic": True,
        }
        yield _sse_format(synthetic)
        return

    async with event_broker.subscribe(run_id) as q:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=20.0)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield _sse_format(event)
            if event_broker.is_terminal(event):
                return


@router.get("/{run_id}/stream")
async def stream_run(run_id: int) -> StreamingResponse:
    """SSE stream of run events.

    Browser usage:
        const es = new EventSource(`/runs/${id}/stream`);
        es.onmessage = (e) => { ... JSON.parse(e.data) ... };
        es.onerror = () => es.close();

    Headers `Cache-Control: no-cache` + `X-Accel-Buffering: no` ensure
    proxies don't buffer the stream.
    """
    return StreamingResponse(
        _stream_run_events(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# M6-2 artifacts download
# ---------------------------------------------------------------------------

_STEP_FILENAME_RE = re.compile(r"^step-(\d+)-(.+?)\.(stdout|stderr|error|log)\.txt$")


def _case_artifacts_dir_or_404(run_id: int, case_id: str) -> Path:
    """Resolve the artifacts directory for one (run, case).

    Returns the absolute path, or raises HTTPException 404 if:
      * run row does not exist
      * case_results row for this (run, case) does not exist
      * artifacts_path field is empty or points to a missing/non-dir path
    """
    with sqlite_store.get_session() as sess:
        run = sqlite_store.get_run(sess, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} not found")
        cr_rows = sqlite_store.list_case_results(sess, run_id)
        match = next((c for c in cr_rows if c.case_id == case_id), None)
        if match is None:
            raise HTTPException(
                status_code=404,
                detail=f"case {case_id!r} not found in run {run_id}",
            )
        ap = match.artifacts_path
        if not ap:
            raise HTTPException(
                status_code=404,
                detail=f"case {case_id!r} in run {run_id} has no artifacts dir",
            )
    d = Path(ap)
    if not d.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"artifacts dir gone: {ap}",
        )
    return d.resolve()


def _classify_artifact(name: str) -> tuple[str, int | None, str | None]:
    """Return (kind, step_idx, step_id) parsed from a filename.

    Recognized: `step-NN-<step_id>.{stdout|stderr|error|log}.txt`. Anything
    else is reported as ('other', None, None) — still listed so the
    user sees what's in the dir.
    """
    m = _STEP_FILENAME_RE.match(name)
    if m is None:
        return ("other", None, None)
    return (m.group(3), int(m.group(1)), m.group(2))


@router.get(
    "/{run_id}/cases/{case_id}/artifacts",
    response_model=list[ArtifactInfo],
)
def list_case_artifacts(run_id: int, case_id: str) -> list[ArtifactInfo]:
    """List artifact files for one case in a run.

    Empty list = case ran but produced no artifact files (e.g., all
    steps had empty stdout/stderr). 404 = run/case unknown OR artifacts
    dir gone.
    """
    d = _case_artifacts_dir_or_404(run_id, case_id)
    out: list[ArtifactInfo] = []
    for child in sorted(d.iterdir()):
        if not child.is_file():
            continue
        try:
            size = child.stat().st_size
        except OSError:
            continue
        kind, step_idx, step_id = _classify_artifact(child.name)
        out.append(
            ArtifactInfo(
                filename=child.name,
                size_bytes=size,
                kind=kind,
                step_idx=step_idx,
                step_id=step_id,
            )
        )
    return out


@router.get("/{run_id}/cases/{case_id}/artifacts/{filename}")
def download_case_artifact(
    run_id: int,
    case_id: str,
    filename: str,
) -> FileResponse:
    """Download one artifact file as text/plain attachment.

    Path-traversal protection: reject filenames containing path
    separators or `..`; further, verify the resolved path is inside
    the case's artifacts dir (defense-in-depth against symlinks).
    """
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="invalid filename")
    if ".." in Path(filename).parts:
        raise HTTPException(status_code=400, detail="invalid filename")

    d = _case_artifacts_dir_or_404(run_id, case_id)
    target = (d / filename).resolve()
    try:
        target.relative_to(d)
    except ValueError:
        # symlink or other escape
        raise HTTPException(status_code=400, detail="invalid filename") from None
    if not target.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"artifact {filename!r} not found",
        )
    # Build an RFC 5987 / RFC 6266 Content-Disposition header.
    # ASGI encodes response headers as latin-1, so a raw non-ASCII
    # `filename="..."` (em-dash, Chinese, etc.) raises UnicodeEncodeError
    # at the transport layer (500 ISE). The spec-compliant fix is to
    # provide an ASCII-only `filename="..."` fallback plus a UTF-8
    # percent-encoded `filename*=UTF-8''...` parameter; browsers honor
    # `filename*` when present.
    ascii_fallback = filename.encode("ascii", errors="replace").decode("ascii").replace('"', "_")
    encoded = quote(filename, safe="")
    return FileResponse(
        path=target,
        media_type="text/plain; charset=utf-8",
        filename=filename,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"
            )
        },
    )


__all__ = ["router"]
