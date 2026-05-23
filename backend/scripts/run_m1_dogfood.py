"""M1 dogfood runner — drive the orchestrator against the 5 real
bug-regression cases on a live cluster (synxdb-0001) and emit a markdown
report.

Why this script exists (and not just the API): the 5 case YAMLs under
`cases/bug-regression/*.yaml` follow design.md §4.1 shape (setup /
teardown as `list[str]`, `kind:` step type, `defaults.database`,
`category: bug_regression` with underscore, per-step `database:`
override). The M1-2 yaml_loader implemented a stricter, different schema
(id / on / driver / run, `bug-regression` with dash, no `list[str]`
setup) and rejects all 5 real cases as written. The M1-9 orchestrator
itself is permissive enough on step shape — it accepts `kind:` or
`driver:`, defaults `on:` to "default", and reads `sql:` / `cmd:` /
`run:` — but its setup / teardown loops call `_execute_one_step(step,
...)` expecting `step` to be a dict; passing a raw string would crash.

So this script is a thin normalizer that side-steps yaml_loader for the
dogfood. Proper fix (re-aligning yaml_loader with §4.1) is deferred to a
future M2 ticket.

Usage::

    uv run python -m backend.scripts.run_m1_dogfood \\
        --cases-dir cases/bug-regression \\
        --pghost synxdb-0001 \\
        --pgport 5432 \\
        --pguser gpadmin \\
        --pgdatabase postgres \\
        --artifacts-root artifacts/m1-dogfood \\
        --report-path docs/m1-dogfood-<auto-timestamp>.md \\
        [--case-id lg-bug-0001-hashjoin-right-table]

PGPASSWORD env or ~/.pgpass picks up the password — psycopg honors both.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.runner.case_normalizer import normalize_case  # re-export for tests
from app.runner.dsn_builder import build_dsn_map  # re-export for tests
from app.runner.orchestrator import CaseExecutionResult, run_case
from app.runner.sql_driver import SqlSessionPool
from app.runner.types import StepStatus

logger = logging.getLogger("m1_dogfood")

# `normalize_case` + `_VALID_KINDS` moved to app.runner.case_normalizer
# (M2 dogfood followup, 2026-05-24) so the API path
# (api/runs.py::_load_cases_from_disk) shares the same normalizer —
# previously the API path skipped normalization and crashed at
# orchestrator's `_step_id` because raw `setup: list[str]` items are
# strings, not dicts. Dual-code-path divergence (design.md §14 R26 候选).
# Re-exported here so existing test_dogfood_script.py imports keep working.


# ---------------------------------------------------------------------------
# case loading
# ---------------------------------------------------------------------------


def load_cases(cases_dir: Path, only_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Scan `cases_dir/*.yaml`, yaml.safe_load each, return list of
    normalized case dicts. If `only_ids` is provided, filter to only
    those case IDs. Filename order is sorted for deterministic output."""
    if not cases_dir.is_dir():
        raise FileNotFoundError(f"cases dir not found: {cases_dir}")
    out: list[dict[str, Any]] = []
    for path in sorted(cases_dir.glob("*.yaml")):
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, dict):
            logger.warning("skipping %s: top-level YAML is not a mapping", path)
            continue
        normalized = normalize_case(raw)
        if only_ids is not None and normalized.get("id") not in only_ids:
            continue
        out.append(normalized)
    return out


# `build_dsn_map` moved to app.runner.dsn_builder (M2 dogfood followup,
# 2026-05-24) so the API path shares the same DSN logic — previously the
# API path didn't build any DSN map, so orchestrator ran with sql_pool=None
# and every SQL step errored. Re-exported here for test_dogfood_script.py.

# ---------------------------------------------------------------------------
# report rendering
# ---------------------------------------------------------------------------


def render_report(
    results: list[tuple[dict[str, Any], CaseExecutionResult]],
    *,
    pghost: str,
    pgport: int,
    pgdatabase: str,
    cases_dir: Path,
    artifacts_root: Path,
    timestamp: str,
    run_id: int,
) -> str:
    """Build the markdown report. `results` is a list of (case_dict,
    CaseExecutionResult) pairs in execution order."""
    total = len(results)
    counts = {"pass": 0, "fail": 0, "error": 0, "skip": 0}
    for _, cer in results:
        counts[cer.status.value] = counts.get(cer.status.value, 0) + 1

    lines: list[str] = []
    lines.append(f"# M1 dogfood — bug-regression cases on {pghost} ({timestamp})\n")
    lines.append(f"- Cluster: {pghost}:{pgport} (db={pgdatabase})")
    lines.append("- Runner: backend/scripts/run_m1_dogfood.py")
    lines.append(f"- Cases dir: {cases_dir}/")
    lines.append(f"- Artifacts: {artifacts_root}/{run_id}/<case_id>/\n")
    lines.append("## Summary\n")
    lines.append("| total | pass | fail | error | skip |")
    lines.append("|-------|------|------|-------|------|")
    lines.append(
        f"|   {total}   |  {counts['pass']}   |  {counts['fail']}   |"
        f"   {counts['error']}   |  {counts['skip']}   |\n"
    )

    lines.append("## Per-case results\n")
    for case_dict, cer in results:
        yaml_status = case_dict.get("status", "unknown")
        case_id = cer.case_id
        run_status = cer.status.value
        title = case_dict.get("title", "")
        lines.append(f"### {case_id} — {run_status.upper()}\n")
        if title:
            lines.append(f"- Title: {title}")
        lines.append(f"- Status (from runner): {run_status}")
        lines.append(f"- YAML status: {yaml_status}")
        lines.append(f"- **Inferred BUG state**: {_infer_bug_state(yaml_status, run_status)}")
        lines.append(f"- Duration: {cer.duration_ms} ms")
        lines.append(f"- Artifacts: {artifacts_root}/{run_id}/{case_id}/")

        # Per-step assertions (only emit a non-empty block if there are any)
        assertion_lines: list[str] = []
        for sr in cer.step_results:
            for key, passed, detail in sr.assertions:
                verdict = "pass" if passed else "fail"
                assertion_lines.append(f"    - {sr.step_id}.{key}: {verdict} — {detail}")
        if assertion_lines:
            lines.append("- Assertions:")
            lines.extend(assertion_lines)
        else:
            lines.append("- Assertions: (none recorded)")

        setup_pass = sum(1 for sr in cer.setup_results if sr.status is StepStatus.PASS)
        setup_fail = len(cer.setup_results) - setup_pass
        teardown_pass = sum(1 for sr in cer.teardown_results if sr.status is StepStatus.PASS)
        teardown_fail = len(cer.teardown_results) - teardown_pass
        lines.append(f"- Setup results: {setup_pass} pass / {setup_fail} fail")
        lines.append(f"- Teardown results: {teardown_pass} pass / {teardown_fail} fail")
        if cer.error:
            lines.append(f"- Error (case-level): {cer.error}")
        if cer.cluster_crashed:
            lines.append("- **CLUSTER CRASHED** (recover-mode pattern matched)")
        lines.append("")  # blank line between cases

    lines.append("## Overall verdict\n")
    lines.append(_overall_verdict(counts, total))
    return "\n".join(lines) + "\n"


def _infer_bug_state(yaml_status: str, run_status: str) -> str:
    """Match the spec's matrix.

    status=open + run pass  → BUG appears fixed upstream (candidate
                              to update YAML status:fixed)
    status=open + run fail  → BUG still present (expected)
    status=open + run error → cluster/env issue, do not conclude
    """
    if yaml_status == "open":
        if run_status == "pass":
            return (
                "upstream-fixed (BUG no longer reproduces — candidate "
                'to update YAML status to "fixed")'
            )
        if run_status == "fail":
            return "BUG still present (expected if not yet upstream-fixed)"
        if run_status == "error":
            return "cluster/env issue, investigate (do NOT conclude about BUG state)"
        if run_status == "skip":
            return "skipped (no signal about BUG state)"
    if yaml_status == "fixed":
        if run_status == "pass":
            return "regression-clean (BUG remains fixed)"
        if run_status == "fail":
            return "regression-broken (BUG returned — investigate)"
    return f"unknown (yaml_status={yaml_status}, run_status={run_status})"


def _overall_verdict(counts: dict[str, int], total: int) -> str:
    if total == 0:
        return "No cases ran. Nothing to verdict on."
    if counts.get("error", 0) == total:
        return (
            "All cases ERRORed — the runner+drivers did NOT prove they wire up "
            "to the cluster. Check connectivity, credentials, log paths, and "
            "session pool configuration before drawing conclusions about BUGs."
        )
    if counts.get("pass", 0) == total:
        return (
            "All cases PASSED — runner + drivers wire up correctly on the real "
            "cluster, and every BUG with status=open appears upstream-fixed. "
            'Consider promoting those YAML statuses to "fixed" in a follow-up.'
        )
    return (
        f"{counts.get('pass', 0)}/{total} cases passed. Runner + drivers wired up "
        "correctly enough to produce per-case verdicts; see per-case sections for "
        "details (BUG-still-present vs cluster/env errors vs upstream-fixed)."
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_m1_dogfood",
        description="Drive the M1 orchestrator against the 5 real bug-regression cases.",
    )
    parser.add_argument(
        "--cases-dir",
        type=Path,
        default=Path("cases/bug-regression"),
        help="Directory containing case *.yaml files (default: cases/bug-regression)",
    )
    parser.add_argument(
        "--pghost",
        default="synxdb-0001",
        help="Postgres / Cloudberry coordinator host (default: synxdb-0001)",
    )
    parser.add_argument("--pgport", type=int, default=5432, help="Coordinator port")
    parser.add_argument("--pguser", default="gpadmin", help="Postgres user")
    parser.add_argument(
        "--pgdatabase",
        default="postgres",
        help="Default Postgres database used when case has no per-step override",
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path("artifacts/m1-dogfood"),
        help="Root dir under which artifacts/<run_id>/<case_id>/ will be written",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="Markdown report output path (default: docs/m1-dogfood-<YYYY-MM-DD-HHMM>.md)",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=None,
        help=(
            "Optional: restrict to a specific case id; may be given multiple times. "
            "If omitted, all cases under --cases-dir run."
        ),
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=1,
        help="Run identifier used in artifacts path (default: 1)",
    )
    return parser.parse_args(argv)


def _auto_timestamp() -> str:
    """UTC YYYY-MM-DD-HHMM (no seconds, no tz suffix — short enough for filenames)."""
    return datetime.now(UTC).strftime("%Y-%m-%d-%H%M")


async def main(argv: list[str] | None = None, *, pool_factory: Any = None) -> int:
    """Async entry point. Returns process exit code (0 = run completed,
    1 = exception in driver loop). Note: a "fail" case verdict does NOT
    flip the exit code — operator wants the report regardless.

    `pool_factory` is a hook for tests: a callable
    `(dsn_map: dict[str, str]) -> SqlSessionPool`. Defaults to the real
    `SqlSessionPool(dsn_map)` constructor.
    """
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    timestamp = _auto_timestamp()
    report_path = args.report_path or Path(f"docs/m1-dogfood-{timestamp}.md")

    only_ids = set(args.case_id) if args.case_id else None
    try:
        cases = load_cases(args.cases_dir, only_ids=only_ids)
    except (FileNotFoundError, ValueError) as e:
        logger.error("failed to load cases: %s", e)
        return 1

    if not cases:
        logger.warning("no cases matched; nothing to do")
        return 0

    dsn_map = build_dsn_map(
        cases,
        pghost=args.pghost,
        pgport=args.pgport,
        pguser=args.pguser,
        pgdatabase=args.pgdatabase,
    )

    if pool_factory is None:
        pool = SqlSessionPool(dsn_map)
    else:
        pool = pool_factory(dsn_map)

    artifacts_root = Path(args.artifacts_root)
    results: list[tuple[dict[str, Any], CaseExecutionResult]] = []
    total = len(cases)
    try:
        for i, case in enumerate(cases, start=1):
            case_id = case.get("id", f"<unknown-{i}>")
            try:
                cer = await run_case(
                    case,
                    run_id=args.run_id,
                    artifacts_root=artifacts_root,
                    jinja_context={"coordinator": {"host": args.pghost}},
                    dut_hosts={args.pghost},
                    sql_pool=pool,
                )
            except Exception as e:  # noqa: BLE001 — R9 at script scope
                # orchestrator.run_case is supposed to fold, but we double-belt.
                logger.exception("case %s raised unexpectedly", case_id)
                cer = CaseExecutionResult(
                    case_id=case_id,
                    status=StepStatus.ERROR,
                    duration_ms=0,
                    error=f"main() caught {type(e).__name__}: {e}",
                )
            results.append((case, cer))
            print(
                f"[{i}/{total}] {case_id} ... {cer.status.value.upper()} "
                f"(duration_ms={cer.duration_ms})",
                file=sys.stderr,
            )
    finally:
        try:
            await pool.close_all()
        except Exception as e:  # noqa: BLE001
            logger.warning("pool.close_all() failed: %s", e)

    md = render_report(
        results,
        pghost=args.pghost,
        pgport=args.pgport,
        pgdatabase=args.pgdatabase,
        cases_dir=args.cases_dir,
        artifacts_root=artifacts_root,
        timestamp=timestamp,
        run_id=args.run_id,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(md, encoding="utf-8")
    logger.info("report written to %s", report_path)
    return 0


def _cli() -> None:
    """Synchronous CLI wrapper for `python -m backend.scripts.run_m1_dogfood`."""
    rc = asyncio.run(main())
    sys.exit(rc)


if __name__ == "__main__":
    _cli()
