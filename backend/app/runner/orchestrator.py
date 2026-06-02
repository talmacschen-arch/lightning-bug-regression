"""Case + suite orchestrator (design.md §5.3 / §5.3.1 / §5.3.2 / §5.3.3, §14 R5/R9/R11/R12/R13).

Wires together drivers (sql / shell / log_grep), Jinja rendering,
assertions, and SQLite storage. Pure async, no FastAPI / no UI.

Public entrypoints:

    run_case(case, run_id, *, artifacts_root, jinja_context, dut_hosts, ...)
        Execute one case's setup -> steps -> teardown sequence. Returns a
        CaseExecutionResult dataclass. Never raises (R9 fold-don't-bubble
        applies at case scope too).

    run_suite(cases, *, run_id, artifacts_root, jinja_context, dut_hosts,
              session_factory, sql_pool=None, skip_list=None)
        Sort cases (destructive last, §5.3.3), iterate, persist a
        CaseResult per case via session_factory(). Aggregates counts into
        SuiteSummary. A case-level exception (NOT step-level) is caught;
        case is recorded as status=error and the suite continues.

Wiring rules (§5.3.3):
  - step exception -> StepResult(status=error); does NOT bubble.
  - first non-pass step in a group -> break further steps in that group;
    other groups keep running.
  - teardown always runs best-effort (even if setup or steps failed);
    teardown failures are logged into the result but do NOT change the
    case's final status.
  - setup failure -> case status = error, main steps[] are skipped, but
    teardown still runs best-effort.
  - destructive: true cases sort to the END of the suite list.
  - "the database system is in recover mode" appearing in server.log
    after any step -> abort remaining steps, mark cluster_crashed=True,
    case status=error.

R-cross-refs in this module:
  - R5  : per-step timeout_ms is honored by drivers (60s default applied
          by caller layer, not here — keeps orchestrator domain-pure).
  - R9  : every driver call is in a try/except that folds exceptions to
          StepResult(status=error). Same protection at case level inside
          run_suite.
  - R11 : profile.d sourcing is the YAML author's responsibility — handled
          inside the rendered cmd: string; orchestrator does not inject.
  - R12 : warmup retry is also a YAML-author concern (seed step writes
          its own retry loop).
  - R13 : decide_ssh_user(host, dut_hosts) is invoked for shell steps
          that declare a `host` field; orchestrator passes the user via
          the rendering context as `ssh_user`, so YAML can write
          `ssh {{ ssh_user }}@{{ host }} '...'` (host gets rendered first).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.runner.assertions import UnknownExpectKey, evaluate
from app.runner.jinja_render import (
    TemplateRenderError,
    decide_ssh_user,
    render,
)
from app.runner.log_grep_driver import execute_log_grep_step
from app.runner.shell_driver import execute_shell_step
from app.runner.sql_driver import SqlSessionPool, execute_sql_step
from app.runner.types import StepResult, StepStatus

logger = logging.getLogger(__name__)

# Pattern that, if found in server.log between steps, aborts the case.
RECOVER_MODE_PATTERN = "the database system is in recover mode"

# Default per-driver timeouts (R5; §5.3 表). The YAML step's own timeout_ms
# overrides these. Kept here so the orchestrator does not require a separate
# config injection just to function in tests.
DEFAULT_TIMEOUTS_MS: dict[str, int] = {
    "sql": 60_000,
    "shell": 60_000,
    "log_grep": 10_000,
}


# ---------------------------------------------------------------------------
# result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CaseExecutionResult:
    """In-memory result of running one case. Suite layer flattens this
    into a CaseResult row before persisting."""

    case_id: str
    status: StepStatus
    duration_ms: int
    step_results: list[StepResult] = field(default_factory=list)
    setup_results: list[StepResult] = field(default_factory=list)
    teardown_results: list[StepResult] = field(default_factory=list)
    skip_reason: str | None = None
    expect_detail: str = ""
    cluster_crashed: bool = False
    error: str | None = None  # case-level error (e.g. setup failed)
    artifacts_dir: str | None = None


@dataclass
class SuiteSummary:
    total: int
    passed: int
    failed: int
    errored: int
    skipped: int
    case_results: list[CaseExecutionResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _step_kind(step: dict[str, Any]) -> str:
    """The dispatch alternately calls this 'kind' and 'driver'.
    Accept either, with 'kind' taking priority."""
    k = step.get("kind") or step.get("driver")
    if not k:
        raise ValueError(f"step missing kind/driver: {step.get('id', '<no-id>')}")
    return str(k)


def _step_id(step: dict[str, Any], idx: int) -> str:
    return str(step.get("id") or f"step-{idx:02d}")


# Path-separator + Windows-reserved chars that would corrupt
# `Path(case_dir) / f"step-NN-{step_id}.txt"` into nested subdirs.
# Whitespace + non-ASCII (e.g. Chinese) preserved — POSIX/UTF-8 filesystems
# handle them fine; the only failure mode observed in dogfood run #26 was
# the `/` in step names like `precondition: ES /_cluster/health ...` causing
# `_cluster/` to become a directory under the case artifacts dir, hiding the
# artifact from `list_case_artifacts`' non-recursive `iterdir()` listing.
_ARTIFACT_NAME_ILLEGAL = re.compile(r'[\\/:*?"<>|]')


def _sanitize_step_id_for_filename(step_id: str) -> str:
    """Replace path-separator and other illegal filename chars so
    `Path(case_dir) / f"step-NN-{step_id}.txt"` stays inside case_dir
    instead of creating accidental subdirs.

    Replacement char: underscore. Whitespace + Chinese / non-ASCII
    preserved (filesystems handle UTF-8; the issue is ONLY path
    separators and Windows-reserved chars).
    """
    return _ARTIFACT_NAME_ILLEGAL.sub("_", step_id)


def _normalize_expect(raw: Any) -> dict[str, Any]:
    """Accept either:
      - dict: {row_count: 5, exit_code: 0}              (spec shape)
      - list of single-key mappings: [{row_count: 5}, ...]  (yaml_loader shape)
    Return a dict mapping expect_key -> expected_value.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, list):
        out: dict[str, Any] = {}
        for entry in raw:
            if isinstance(entry, dict) and len(entry) == 1:
                ((k, v),) = entry.items()
                out[k] = v
            else:
                # ignore malformed silently here — yaml_loader would have rejected
                # it earlier; orchestrator's job is to run, not re-validate.
                continue
        return out
    return {}


# Maps expect_key -> attribute on StepResult that holds the actual value.
# Keeps the orchestrator's evaluator wiring in one place, mirroring the
# table in assertions.py.
_ACTUAL_SOURCE: dict[str, str] = {
    "exit_code": "exit_code",
    "scalar": "scalar",
    "scalar_eq": "scalar",
    "scalar_ne": "scalar",
    "scalar_ge": "scalar",
    "scalar_le": "scalar",
    "scalar_gt": "scalar",
    "scalar_lt": "scalar",
    "row_count": "row_count",
    "rows_affected": "rows_affected",
    "plan_contains": "plan_text",
    "plan_contains_any": "plan_text",
    "stdout_contains": "stdout",
    "not_contains": "stdout",
    "regex": "stdout",
    "matches": "matches",
    "matches_lt": "matches",
    "matches_ge": "matches",
    "duration_lt_ms": "duration_ms",
}


def _apply_assertions(step_result: StepResult, expect: dict[str, Any]) -> None:
    """Run every expect clause against the StepResult and append
    (key, passed, detail) tuples to step_result.assertions. If any
    assertion fails AND step is currently PASS, downgrade to FAIL.
    Never flips an existing ERROR status to FAIL.
    """
    if not expect:
        return
    for key, expected_value in expect.items():
        actual_attr = _ACTUAL_SOURCE.get(key)
        actual = getattr(step_result, actual_attr, None) if actual_attr else None
        # Fallback: plan assertions use stdout when plan_text is None (F-2 fix §5.3)
        if key in ("plan_contains", "plan_contains_any") and actual is None:
            actual = step_result.stdout or None
        try:
            passed, detail = evaluate(key, actual, expected_value)
        except UnknownExpectKey as e:
            passed, detail = False, f"unknown expect key {key!r}: {e}"
        step_result.assertions.append((key, passed, detail))
        if not passed and step_result.status is StepStatus.PASS:
            step_result.status = StepStatus.FAIL


def _write_artifact(
    path: Path,
    content: str | None,
) -> str | None:
    """Write content to path; return str(path) on success, None on error /
    empty content. Errors are swallowed (artifact-write should never
    affect a step's verdict)."""
    if not content:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)
    except OSError as e:
        logger.warning("artifact write failed for %s: %s", path, e)
        return None


def _render_step_fields(
    step: dict[str, Any],
    jinja_context: dict[str, Any],
    dut_hosts: set[str],
) -> dict[str, Any]:
    """Render the templated fields of a step in-place (returns a shallow
    copy). Raises TemplateRenderError on undefined / syntax error — caller
    converts to StepResult(status=error).

    Templated fields: sql, cmd, run, host. Other fields pass through.
    Also injects `ssh_user` into the local render context for shell steps
    that include a `host` field (§5.3.2 / R13), so YAML can write
    `ssh {{ ssh_user }}@{{ host }} '...'`.
    """
    out = dict(step)
    # First render host (it influences ssh_user).
    host_template = step.get("host")
    rendered_host: str | None = None
    if host_template is not None:
        rendered_host = render(str(host_template), jinja_context)
        out["host"] = rendered_host

    # Build a per-step context with ssh_user + host populated so cmd
    # templates can write `ssh {{ ssh_user }}@{{ host }} ...` (§5.3.2 / R13).
    per_step_ctx = dict(jinja_context)
    per_step_ctx["ssh_user"] = decide_ssh_user(rendered_host, dut_hosts)
    if rendered_host is not None:
        per_step_ctx["host"] = rendered_host

    for field_name in ("sql", "cmd", "run"):
        if field_name in step and step[field_name] is not None:
            out[field_name] = render(str(step[field_name]), per_step_ctx)
    return out


# ---------------------------------------------------------------------------
# step execution
# ---------------------------------------------------------------------------


async def _execute_one_step(
    step: dict[str, Any],
    idx: int,
    *,
    jinja_context: dict[str, Any],
    dut_hosts: set[str],
    sql_pool: SqlSessionPool | None,
    case_artifacts_dir: Path | None,
    case_started_unix: float,
) -> StepResult:
    """Run a single step, fold all exceptions to StepResult(status=ERROR).

    Returns a StepResult with assertions populated and stdout/stderr
    written to disk under case_artifacts_dir (if provided).
    """
    step_id = _step_id(step, idx)
    started_iso = datetime.now(UTC).isoformat()
    t0 = time.monotonic()

    # --- Jinja render (errors here become case-level ERROR on this step) ---
    try:
        rendered = _render_step_fields(step, jinja_context, dut_hosts)
    except TemplateRenderError as e:
        return _make_error_result(step_id, "jinja", started_iso, t0, f"template error: {e}")
    except Exception as e:  # noqa: BLE001 — R9 fold-don't-bubble
        return _make_error_result(
            step_id, "jinja", started_iso, t0, f"unexpected render error: {type(e).__name__}: {e}"
        )

    try:
        kind = _step_kind(rendered)
    except ValueError as e:
        return _make_error_result(step_id, "unknown", started_iso, t0, str(e))

    timeout_ms = rendered.get("timeout_ms")
    if timeout_ms is None:
        timeout_ms = DEFAULT_TIMEOUTS_MS.get(kind)

    # --- dispatch ---
    try:
        if kind == "sql":
            if sql_pool is None:
                step_result = _make_error_result(
                    step_id, "sql", started_iso, t0, "sql step requires sql_pool to be configured"
                )
            else:
                session_name = rendered.get("on") or "default"
                sql_text = rendered.get("sql") or rendered.get("run") or ""
                step_result = await execute_sql_step(
                    pool=sql_pool,
                    step_id=step_id,
                    session=str(session_name),
                    sql=str(sql_text),
                    timeout_ms=timeout_ms,
                )
        elif kind == "shell":
            cmd = rendered.get("cmd") or rendered.get("run") or ""
            step_result = await execute_shell_step(
                step_id=step_id,
                command=str(cmd),
                timeout_ms=timeout_ms,
            )
        elif kind == "log_grep":
            log_path = rendered.get("log_path") or rendered.get("path") or ""
            pattern = rendered.get("pattern") or ""
            # log_grep_driver is sync — run in a thread to keep event loop free.
            step_result = await asyncio.to_thread(
                execute_log_grep_step,
                step_id,
                str(log_path),
                str(pattern),
                case_started_unix,
            )
        else:
            step_result = _make_error_result(
                step_id, kind, started_iso, t0, f"unknown step kind: {kind!r}"
            )
    except Exception as e:  # noqa: BLE001 — R9 fold-don't-bubble at orchestrator scope
        step_result = _make_error_result(
            step_id,
            kind,
            started_iso,
            t0,
            f"orchestrator caught {type(e).__name__}: {e}",
        )

    # --- assertions (only if the step actually produced a StepResult that
    #     could be evaluated — drivers always return one, but be defensive) ---
    expect = _normalize_expect(rendered.get("expect"))
    _apply_assertions(step_result, expect)

    # --- write artifacts (stdout/stderr/error) to disk ---
    # Sanitize step_id for the filename — slashes in step names create
    # accidental subdirectories that hide artifacts from the
    # non-recursive `list_case_artifacts` listing (dogfood run #26
    # `xs-zombodb-partition-text-search` step 0 incident).
    if case_artifacts_dir is not None:
        sanitized_id = _sanitize_step_id_for_filename(step_id)
        stdout_path = case_artifacts_dir / f"step-{idx:02d}-{sanitized_id}.stdout.txt"
        stderr_path = case_artifacts_dir / f"step-{idx:02d}-{sanitized_id}.stderr.txt"
        wrote_stdout = _write_artifact(stdout_path, step_result.stdout)
        wrote_stderr = _write_artifact(stderr_path, step_result.stderr)
        for p in (wrote_stdout, wrote_stderr):
            if p:
                step_result.artifacts.append(p)
        # Driver-level exception text (e.g. sql_driver._err -> step_result.error)
        # is otherwise consumed by case-level aggregation only and never lands
        # on disk. Persist it as a separate `.error.txt` artifact so the
        # download endpoint can expose it. ERROR-status steps with no
        # exception text get nothing — preserves the "no artifact = nothing
        # to say" semantic (dogfood run #26 silent invisible error fix).
        if step_result.error:
            error_path = case_artifacts_dir / f"step-{idx:02d}-{sanitized_id}.error.txt"
            wrote_error = _write_artifact(error_path, step_result.error)
            if wrote_error:
                step_result.artifacts.append(wrote_error)

    return step_result


def _make_error_result(
    step_id: str,
    driver: str,
    started_iso: str,
    t0: float,
    error_msg: str,
) -> StepResult:
    return StepResult(
        status=StepStatus.ERROR,
        step_id=step_id,
        driver=driver,
        started_at=started_iso,
        ended_at=datetime.now(UTC).isoformat(),
        duration_ms=int((time.monotonic() - t0) * 1000),
        error=error_msg,
    )


# ---------------------------------------------------------------------------
# group runner (a "group" = all steps sharing the same `on:` session)
# ---------------------------------------------------------------------------


async def _run_group(
    indexed_steps: list[tuple[int, dict[str, Any]]],
    *,
    jinja_context: dict[str, Any],
    dut_hosts: set[str],
    sql_pool: SqlSessionPool | None,
    case_artifacts_dir: Path | None,
    case_started_unix: float,
    cluster_crashed_flag: list[bool],
    server_log_path: str | None,
) -> list[StepResult]:
    """Execute one session-group sequentially.

    On first non-PASS step result, stop. After each step, peek
    server.log via log_grep_driver — if recover-mode pattern matches,
    set cluster_crashed_flag[0]=True and stop the group.
    """
    results: list[StepResult] = []
    for idx, step in indexed_steps:
        # If a sibling group already detected cluster crash, abort.
        if cluster_crashed_flag[0]:
            break
        step_result = await _execute_one_step(
            step,
            idx,
            jinja_context=jinja_context,
            dut_hosts=dut_hosts,
            sql_pool=sql_pool,
            case_artifacts_dir=case_artifacts_dir,
            case_started_unix=case_started_unix,
        )
        results.append(step_result)

        # Recover-mode guard (§5.3 / §14 R9 cluster-crash detection).
        if server_log_path:
            try:
                guard = await asyncio.to_thread(
                    execute_log_grep_step,
                    f"recover-guard-{idx:02d}",
                    server_log_path,
                    RECOVER_MODE_PATTERN,
                    case_started_unix,
                )
                if guard.matches and guard.matches > 0:
                    cluster_crashed_flag[0] = True
                    break
            except Exception as e:  # noqa: BLE001
                # The guard itself should not crash the case; just log.
                logger.warning("recover-mode guard failed: %s", e)

        if step_result.status is not StepStatus.PASS:
            # First non-pass step in this group breaks the group, but other
            # groups keep going (§5.3.3 + asyncio.gather semantics).
            break
    return results


def _group_by_session(steps: list[dict[str, Any]]) -> list[list[tuple[int, dict[str, Any]]]]:
    """Group steps by `on:` session name preserving original indices.

    Steps with no `on:` (or `on: null`) share one implicit group keyed
    None — they all run sequentially together.
    """
    groups: dict[Any, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for idx, step in enumerate(steps):
        key = step.get("on") or None
        groups[key].append((idx, step))
    # Stable ordering by first-appearance — preserves YAML author intent
    # when groups are reported.
    seen: dict[Any, int] = {}
    for key in groups:
        if key not in seen:
            seen[key] = len(seen)
    return [groups[k] for k in sorted(groups.keys(), key=lambda k: seen[k])]


# ---------------------------------------------------------------------------
# case runner
# ---------------------------------------------------------------------------


async def run_case(
    case: dict[str, Any],
    run_id: int,
    *,
    artifacts_root: Path,
    jinja_context: dict[str, Any],
    dut_hosts: set[str],
    sql_pool: SqlSessionPool | None = None,
    server_log_path: str | None = None,
) -> CaseExecutionResult:
    """Run one case: setup -> steps (grouped concurrently by `on:`) -> teardown.

    Never raises (R9). Drivers fold their own exceptions; orchestrator
    folds anything else (jinja, dispatch, file IO).
    """
    case_id = str(case.get("id") or "unknown")
    t0 = time.monotonic()
    case_started_unix = time.time()
    setup_results: list[StepResult] = []
    teardown_results: list[StepResult] = []
    step_results: list[StepResult] = []
    case_status: StepStatus = StepStatus.PASS
    case_error: str | None = None
    cluster_crashed_flag = [False]

    # Resolve server.log path (case-level field > jinja_context fallback).
    resolved_server_log = (
        server_log_path or case.get("server_log_path") or jinja_context.get("server_log_path")
    )

    # Artifacts directory.
    case_artifacts_dir = Path(artifacts_root) / str(run_id) / case_id
    try:
        case_artifacts_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("could not create artifacts dir %s: %s", case_artifacts_dir, e)

    # Reset session-level state on every persistent sql connection BEFORE
    # this case's setup runs. Without this, non-LOCAL `SET` GUCs / temp
    # tables / prepared statements from a previous case bleed into this
    # case's session and silently corrupt behavior (dogfood 2026-05-26:
    # bug-0011/0012 SET work_mem='256kB' + enable_seqscan=off persisted
    # into the persistent AsyncConnection and broke xs-zombodb at the
    # suite tail). discard_all() swallows per-connection errors with
    # logger.warning, so we don't need a try/except here.
    if sql_pool is not None:
        await sql_pool.discard_all()

    setup_steps: list[dict[str, Any]] = list(case.get("setup") or [])
    main_steps: list[dict[str, Any]] = list(case.get("steps") or [])
    teardown_steps: list[dict[str, Any]] = list(case.get("teardown") or [])

    # --- setup (sequential, single implicit group) ---
    setup_failed = False
    for idx, step in enumerate(setup_steps):
        sr = await _execute_one_step(
            step,
            idx,
            jinja_context=jinja_context,
            dut_hosts=dut_hosts,
            sql_pool=sql_pool,
            case_artifacts_dir=case_artifacts_dir,
            case_started_unix=case_started_unix,
        )
        setup_results.append(sr)
        if sr.status is not StepStatus.PASS:
            setup_failed = True
            case_status = StepStatus.ERROR
            case_error = f"setup step {sr.step_id!r} failed: {sr.status.value}"
            break

    # --- main steps (grouped by `on:`, groups run concurrently) ---
    if not setup_failed and main_steps:
        groups = _group_by_session(main_steps)
        group_results = await asyncio.gather(
            *(
                _run_group(
                    g,
                    jinja_context=jinja_context,
                    dut_hosts=dut_hosts,
                    sql_pool=sql_pool,
                    case_artifacts_dir=case_artifacts_dir,
                    case_started_unix=case_started_unix,
                    cluster_crashed_flag=cluster_crashed_flag,
                    server_log_path=resolved_server_log,
                )
                for g in groups
            ),
            return_exceptions=False,
        )
        # Flatten + sort back to original step order so downstream UI sees
        # steps in YAML order.
        flat: list[tuple[int, StepResult]] = []
        # Build index of step_id -> idx for sort ordering (relies on step_id).
        # But step_id may not be unique; safest is to recover idx via the
        # _step_id default scheme. Each group preserves idx in the indexed
        # tuple so we'd have to thread it through. Simpler: store indices.
        # We already preserved order within group; just concat in group
        # order (group order = YAML appearance order of session names).
        for grp_res in group_results:
            for sr in grp_res:
                flat.append((0, sr))  # idx not needed for output ordering
        step_results = [sr for _, sr in flat]

        # Compute case status from main steps.
        if cluster_crashed_flag[0]:
            case_status = StepStatus.ERROR
            case_error = (
                f"cluster crashed (server.log matched {RECOVER_MODE_PATTERN!r}); "
                "remaining steps aborted"
            )
        else:
            non_pass = [sr for sr in step_results if sr.status is not StepStatus.PASS]
            if any(sr.status is StepStatus.ERROR for sr in non_pass):
                case_status = StepStatus.ERROR
            elif non_pass:
                case_status = StepStatus.FAIL
            # else: still PASS

    # --- teardown (always runs, best-effort; failures DO NOT change case_status) ---
    for idx, step in enumerate(teardown_steps):
        try:
            tr = await _execute_one_step(
                step,
                idx,
                jinja_context=jinja_context,
                dut_hosts=dut_hosts,
                sql_pool=sql_pool,
                case_artifacts_dir=case_artifacts_dir,
                case_started_unix=case_started_unix,
            )
        except Exception as e:  # noqa: BLE001 — defensive; should already be folded
            tr = _make_error_result(
                f"teardown-{idx:02d}",
                "unknown",
                datetime.now(UTC).isoformat(),
                time.monotonic(),
                f"teardown unexpected exception: {type(e).__name__}: {e}",
            )
        teardown_results.append(tr)
        if tr.status is not StepStatus.PASS:
            logger.warning(
                "teardown step %s failed but case_status preserved: %s",
                tr.step_id,
                tr.status.value,
            )

    # --- expect_detail summary (lines of "<step_id>.<key>: <detail>") ---
    detail_lines: list[str] = []
    for sr in step_results:
        for key, passed, detail in sr.assertions:
            if not passed:
                detail_lines.append(f"{sr.step_id}.{key}: {detail}")
    expect_detail = "\n".join(detail_lines)

    duration_ms = int((time.monotonic() - t0) * 1000)
    return CaseExecutionResult(
        case_id=case_id,
        status=case_status,
        duration_ms=duration_ms,
        step_results=step_results,
        setup_results=setup_results,
        teardown_results=teardown_results,
        skip_reason=None,
        expect_detail=expect_detail,
        cluster_crashed=cluster_crashed_flag[0],
        error=case_error,
        artifacts_dir=str(case_artifacts_dir),
    )


# ---------------------------------------------------------------------------
# suite runner
# ---------------------------------------------------------------------------


SessionFactory = Callable[[], AbstractContextManager[Any]]


def _sort_destructive_last(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable sort: non-destructive first, destructive last (§5.3.3)."""
    return sorted(cases, key=lambda c: bool(c.get("destructive", False)))


def _skip_rule_active(rule: dict[str, Any], today: date) -> bool:
    """A skip rule is active if `until_date` is absent OR is >= today.
    `until_version` filtering is left to the caller (we don't know the
    target version here)."""
    until = rule.get("until_date")
    if until is None:
        return True
    if isinstance(until, str):
        try:
            until_dt = date.fromisoformat(until)
        except ValueError:
            return True
    elif isinstance(until, date):
        until_dt = until
    else:
        return True
    return until_dt >= today


def _matching_skip_rule(
    case_id: str,
    skip_list: list[dict[str, Any]],
) -> dict[str, Any] | None:
    today = date.today()
    for rule in skip_list:
        if rule.get("case_id") != case_id:
            continue
        if _skip_rule_active(rule, today):
            return rule
    return None


async def run_suite(
    cases: list[dict[str, Any]],
    *,
    run_id: int,
    artifacts_root: Path,
    jinja_context: dict[str, Any],
    dut_hosts: set[str],
    session_factory: SessionFactory,
    sql_pool: SqlSessionPool | None = None,
    server_log_path: str | None = None,
    skip_list: list[dict[str, Any]] | None = None,
    insert_case_result_fn: Callable[..., Any] | None = None,
) -> SuiteSummary:
    """Run a list of cases.

    `session_factory`: a context-manager-yielding callable (e.g.
    `sqlite_store.get_session`) used to persist each CaseResult row.
    `insert_case_result_fn`: optional override of the persistence helper
    (defaults to `sqlite_store.insert_case_result`); injected so tests
    can avoid a real DB.

    Returns a SuiteSummary with counts + per-case list. Never raises;
    case-level exceptions are folded to status='error' (R9 at suite scope).
    """
    # Defer the real import — keeps the orchestrator unit-testable without
    # a live SQLAlchemy engine when insert_case_result_fn is provided.
    if insert_case_result_fn is None:
        from app.storage.sqlite_store import insert_case_result as _icr

        insert_case_result_fn = _icr

    skip_list = skip_list or []
    ordered = _sort_destructive_last(cases)

    case_results: list[CaseExecutionResult] = []
    passed = failed = errored = skipped = 0

    for case in ordered:
        case_id = str(case.get("id") or "unknown")

        # Skip-list check before any work.
        rule = _matching_skip_rule(case_id, skip_list)
        if rule is not None:
            cer = CaseExecutionResult(
                case_id=case_id,
                status=StepStatus.SKIP,
                duration_ms=0,
                skip_reason=str(rule.get("reason") or "skip-list entry"),
            )
            _persist_case(
                session_factory, insert_case_result_fn, run_id, cer, _coerce_status_for_db(cer)
            )
            from app.runner import event_broker  # local — see comment in main loop

            event_broker.publish_case_done(
                run_id=run_id,
                case_id=cer.case_id,
                status=_coerce_status_for_db(cer),
                duration_ms=cer.duration_ms,
                error=None,
            )
            case_results.append(cer)
            skipped += 1
            continue

        try:
            cer = await run_case(
                case,
                run_id,
                artifacts_root=artifacts_root,
                jinja_context=jinja_context,
                dut_hosts=dut_hosts,
                sql_pool=sql_pool,
                server_log_path=server_log_path,
            )
        except Exception as e:  # noqa: BLE001 — R9 at suite scope
            logger.exception("case-level exception for %s — folding to error", case_id)
            cer = CaseExecutionResult(
                case_id=case_id,
                status=StepStatus.ERROR,
                duration_ms=0,
                error=f"case-level exception: {type(e).__name__}: {e}",
            )

        _persist_case(
            session_factory, insert_case_result_fn, run_id, cer, _coerce_status_for_db(cer)
        )
        case_results.append(cer)

        # M6-1: publish SSE event for case completion (best-effort, no-op
        # if no SSE subscriber). Decoupled via event_broker module so
        # orchestrator doesn't depend on FastAPI.
        from app.runner import event_broker  # local import — avoid cycle in unit tests

        event_broker.publish_case_done(
            run_id=run_id,
            case_id=cer.case_id,
            status=_coerce_status_for_db(cer),
            duration_ms=cer.duration_ms,
            error=cer.error,
        )

        if cer.status is StepStatus.PASS:
            passed += 1
        elif cer.status is StepStatus.FAIL:
            failed += 1
        elif cer.status is StepStatus.ERROR:
            errored += 1
        elif cer.status is StepStatus.SKIP:
            skipped += 1

    return SuiteSummary(
        total=len(ordered),
        passed=passed,
        failed=failed,
        errored=errored,
        skipped=skipped,
        case_results=case_results,
    )


def _coerce_status_for_db(cer: CaseExecutionResult) -> str:
    """StepStatus enum -> plain string for the CaseResult.status column."""
    return cer.status.value


def _persist_case(
    session_factory: SessionFactory,
    insert_case_result_fn: Callable[..., Any],
    run_id: int,
    cer: CaseExecutionResult,
    status_str: str,
) -> None:
    """Persist a CaseResult row. Persistence failure is logged but does
    NOT change the in-memory result or counters (R9 at suite scope)."""
    try:
        with session_factory() as session:
            insert_case_result_fn(
                session,
                run_id=run_id,
                case_id=cer.case_id,
                status=status_str,
                duration_ms=cer.duration_ms,
                skip_reason=cer.skip_reason,
                expect_detail=cer.expect_detail or None,
                artifacts_path=cer.artifacts_dir,
            )
    except Exception as e:  # noqa: BLE001
        logger.exception("persisting CaseResult for %s failed: %s", cer.case_id, e)


# Keep the awaitable-typed helper exposed so type-checkers know it's intended.
__all__ = [
    "CaseExecutionResult",
    "SuiteSummary",
    "run_case",
    "run_suite",
    "RECOVER_MODE_PATTERN",
    "DEFAULT_TIMEOUTS_MS",
]
