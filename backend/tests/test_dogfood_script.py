"""Tests for backend/scripts/run_m1_dogfood.py (M1-11).

These tests cover the normalizer (load + normalize), the DSN map
builder, the markdown report renderer, and an end-to-end `main()`
invocation against a real case YAML with a fake (no-network) SQL pool.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app.runner.types import StepResult, StepStatus
from scripts import run_m1_dogfood
from scripts.run_m1_dogfood import (
    build_dsn_map,
    load_cases,
    main,
    normalize_case,
    render_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / "cases" / "bug-regression"


# ---------------------------------------------------------------------------
# normalize_case: setup as list[str]
# ---------------------------------------------------------------------------


def test_normalize_case_setup_list_str() -> None:
    raw = {
        "id": "lg-x",
        "category": "bug_regression",
        "status": "open",
        "defaults": {"database": "postgres"},
        "setup": ["DROP TABLE IF EXISTS x", "CREATE TABLE x (i int)"],
        "steps": [{"kind": "sql", "sql": "SELECT 1"}],
        "teardown": ["DROP TABLE IF EXISTS x"],
    }
    out = normalize_case(raw)
    assert isinstance(out["setup"], list)
    assert len(out["setup"]) == 2
    assert out["setup"][0] == {
        "id": "setup-00",
        "kind": "sql",
        "sql": "DROP TABLE IF EXISTS x",
        "on": "default:postgres",
    }
    assert out["setup"][1]["id"] == "setup-01"
    assert out["setup"][1]["kind"] == "sql"
    assert out["setup"][1]["sql"] == "CREATE TABLE x (i int)"
    # teardown the same shape
    assert out["teardown"][0]["id"] == "teardown-00"
    assert out["teardown"][0]["kind"] == "sql"
    # category / destructive default
    assert out["category"] == "bug_regression"
    assert out["destructive"] is False


# ---------------------------------------------------------------------------
# normalize_case: step field aliases (name → id, kind, sql)
# ---------------------------------------------------------------------------


def test_normalize_case_step_field_aliases() -> None:
    raw = {
        "id": "lg-x",
        "defaults": {"database": "postgres"},
        "steps": [{"name": "foo", "kind": "sql", "sql": "SELECT 1"}],
    }
    out = normalize_case(raw)
    assert len(out["steps"]) == 1
    step = out["steps"][0]
    assert step["id"] == "foo"  # name → id
    assert step["kind"] == "sql"
    assert step["sql"] == "SELECT 1"
    # `on:` defaults to the case's defaults.database so SqlSessionPool can route.
    assert step["on"] == "default:postgres"


def test_normalize_case_step_driver_alias_accepted() -> None:
    """Either kind: or driver: should populate the normalized kind."""
    raw = {
        "id": "lg-x",
        "defaults": {"database": "postgres"},
        "steps": [{"id": "s1", "driver": "sql", "sql": "SELECT 1"}],
    }
    out = normalize_case(raw)
    assert out["steps"][0]["kind"] == "sql"


def test_normalize_case_step_invalid_kind_raises() -> None:
    raw = {
        "id": "lg-x",
        "steps": [{"id": "s1", "kind": "unknown-kind", "sql": "SELECT 1"}],
    }
    with pytest.raises(ValueError, match="invalid kind"):
        normalize_case(raw)


def test_normalize_case_step_missing_kind_raises() -> None:
    raw = {
        "id": "lg-x",
        "steps": [{"id": "s1", "sql": "SELECT 1"}],
    }
    with pytest.raises(ValueError, match="missing kind"):
        normalize_case(raw)


def test_normalize_case_sql_step_missing_sql_raises() -> None:
    raw = {
        "id": "lg-x",
        "steps": [{"id": "s1", "kind": "sql"}],
    }
    with pytest.raises(ValueError, match="missing sql"):
        normalize_case(raw)


def test_normalize_case_shell_step_missing_cmd_raises() -> None:
    raw = {
        "id": "lg-x",
        "steps": [{"id": "s1", "kind": "shell"}],
    }
    with pytest.raises(ValueError, match="missing cmd"):
        normalize_case(raw)


def test_normalize_case_setup_unsupported_type_raises() -> None:
    raw = {
        "id": "lg-x",
        "setup": [123],  # not str or dict
        "steps": [{"id": "s1", "kind": "sql", "sql": "SELECT 1"}],
    }
    with pytest.raises(ValueError, match="setup\\[0\\]"):
        normalize_case(raw)


def test_normalize_case_setup_dict_entry_normalized() -> None:
    """A dict-shaped setup entry (already structured) should still be
    normalized through the per-step path."""
    raw = {
        "id": "lg-x",
        "setup": [{"kind": "sql", "sql": "SET x=1"}],
        "steps": [{"id": "s1", "kind": "sql", "sql": "SELECT 1"}],
    }
    out = normalize_case(raw)
    assert out["setup"][0]["id"] == "setup-00"
    assert out["setup"][0]["kind"] == "sql"


# ---------------------------------------------------------------------------
# normalize_case: per-step database override → on becomes default:<db>
# ---------------------------------------------------------------------------


def test_normalize_case_per_step_database() -> None:
    raw = {
        "id": "lg-x",
        "defaults": {"database": "postgres"},
        "steps": [
            {"id": "s1", "kind": "sql", "database": "mydb", "sql": "SELECT 1"},
        ],
    }
    out = normalize_case(raw)
    assert out["steps"][0]["on"] == "default:mydb"

    # And the DSN map should include a default:mydb DSN that ends with /mydb.
    dsn_map = build_dsn_map(
        [out],
        pghost="hostX",
        pgport=5432,
        pguser="gpadmin",
        pgdatabase="postgres",
    )
    assert "default:mydb" in dsn_map
    assert dsn_map["default:mydb"].endswith("/mydb")
    assert "default:postgres" in dsn_map
    assert dsn_map["default:postgres"].endswith("/postgres")


# ---------------------------------------------------------------------------
# load_cases: real fixture lg-bug-0001
# ---------------------------------------------------------------------------


def test_load_cases_real_fixtures() -> None:
    """Loads the real lg-bug-0001 YAML and asserts the normalized output
    is orchestrator-compatible (setup/steps/teardown are lists of dicts,
    each step has a `kind` field)."""
    cases = load_cases(CASES_DIR, only_ids={"lg-bug-0001-hashjoin-right-table"})
    assert len(cases) == 1
    case = cases[0]

    assert case["id"] == "lg-bug-0001-hashjoin-right-table"
    assert isinstance(case["setup"], list)
    assert isinstance(case["steps"], list)
    assert isinstance(case["teardown"], list)
    assert all(isinstance(s, dict) and "kind" in s for s in case["setup"])
    assert all(isinstance(s, dict) and "kind" in s for s in case["steps"])
    assert all(isinstance(s, dict) and "kind" in s for s in case["teardown"])
    # lg-bug-0001 has 4 setup statements (3 strings + 1 multi-statement block)
    assert len(case["setup"]) >= 3
    # the main step is sql kind with plan_contains assertion in expect
    assert case["steps"][0]["kind"] == "sql"
    assert "expect" in case["steps"][0]


def test_load_cases_loads_all_five() -> None:
    cases = load_cases(CASES_DIR)
    ids = [c["id"] for c in cases]
    assert "lg-bug-0001-hashjoin-right-table" in ids
    assert "lg-bug-0002-array-unnest-crash" in ids
    assert "lg-bug-0003-count-no-statistics" in ids
    assert "lg-bug-0004-ctas-rowcount-zero" in ids
    assert "lg-bug-0005-lc-ctype-upper" in ids


def test_load_cases_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_cases(tmp_path / "does-not-exist")


def test_load_cases_only_ids_filter(tmp_path: Path) -> None:
    # Build a tiny cases dir with two yamls.
    d = tmp_path / "cases"
    d.mkdir()
    (d / "a.yaml").write_text(
        "id: case-a\ncategory: bug_regression\nsteps:\n"
        "  - id: s1\n    kind: sql\n    sql: SELECT 1\n",
        encoding="utf-8",
    )
    (d / "b.yaml").write_text(
        "id: case-b\ncategory: bug_regression\nsteps:\n"
        "  - id: s1\n    kind: sql\n    sql: SELECT 1\n",
        encoding="utf-8",
    )
    cases = load_cases(d, only_ids={"case-a"})
    assert [c["id"] for c in cases] == ["case-a"]


# ---------------------------------------------------------------------------
# build_dsn_map: aggregates distinct sessions
# ---------------------------------------------------------------------------


def test_build_dsn_map_includes_default_and_per_db() -> None:
    cases = [
        {
            "id": "c1",
            "setup": [],
            "steps": [
                {"id": "s1", "kind": "sql", "on": "default:postgres", "sql": "x"},
                {"id": "s2", "kind": "sql", "on": "default:mydb", "sql": "y"},
            ],
            "teardown": [],
        },
    ]
    dsn_map = build_dsn_map(
        cases, pghost="h1", pgport=5432, pguser="gpadmin", pgdatabase="postgres"
    )
    assert "default" in dsn_map  # implicit fallback
    assert "default:postgres" in dsn_map
    assert "default:mydb" in dsn_map
    assert dsn_map["default:mydb"] == "postgresql://gpadmin@h1:5432/mydb"
    assert dsn_map["default"] == "postgresql://gpadmin@h1:5432/postgres"


# ---------------------------------------------------------------------------
# render_report: summary counts + per-case sections
# ---------------------------------------------------------------------------


def _make_step_result(step_id: str, status: StepStatus = StepStatus.PASS) -> StepResult:
    now = datetime.utcnow().isoformat()
    return StepResult(
        status=status,
        step_id=step_id,
        driver="sql",
        started_at=now,
        ended_at=now,
        duration_ms=10,
    )


def test_report_render_summary_counts(tmp_path: Path) -> None:
    from app.runner.orchestrator import CaseExecutionResult

    s1 = _make_step_result("s1", StepStatus.PASS)
    s1.assertions = [("scalar", True, "expected scalar == 1, got 1")]

    s2 = _make_step_result("s2", StepStatus.FAIL)
    s2.assertions = [("scalar", False, "expected scalar == 1, got None")]

    cer_pass = CaseExecutionResult(
        case_id="lg-bug-0001",
        status=StepStatus.PASS,
        duration_ms=100,
        step_results=[s1],
    )
    cer_fail = CaseExecutionResult(
        case_id="lg-bug-0002",
        status=StepStatus.FAIL,
        duration_ms=200,
        step_results=[s2],
    )
    cer_err = CaseExecutionResult(
        case_id="lg-bug-0003",
        status=StepStatus.ERROR,
        duration_ms=50,
        error="connection refused",
    )

    results = [
        ({"id": "lg-bug-0001", "title": "t1", "status": "open"}, cer_pass),
        ({"id": "lg-bug-0002", "title": "t2", "status": "open"}, cer_fail),
        ({"id": "lg-bug-0003", "title": "t3", "status": "open"}, cer_err),
    ]
    md = render_report(
        results,
        pghost="synxdb-0001",
        pgport=5432,
        pgdatabase="postgres",
        cases_dir=Path("cases/bug-regression"),
        artifacts_root=Path("artifacts/m1-dogfood"),
        timestamp="2026-05-24-1200",
        run_id=1,
    )
    # header
    assert "# M1 dogfood — bug-regression cases on synxdb-0001 (2026-05-24-1200)" in md
    # summary table
    assert "|   3   |  1   |  1   |   1   |  0   |" in md
    # per-case sections
    assert "### lg-bug-0001 — PASS" in md
    assert "### lg-bug-0002 — FAIL" in md
    assert "### lg-bug-0003 — ERROR" in md
    # BUG state inference
    assert "upstream-fixed" in md  # lg-bug-0001
    assert "BUG still present" in md  # lg-bug-0002
    assert "cluster/env issue" in md  # lg-bug-0003
    # case-level error rendered
    assert "Error (case-level): connection refused" in md
    # assertion detail rendered
    assert "s1.scalar: pass" in md
    assert "s2.scalar: fail" in md


def test_report_render_empty_results() -> None:
    md = render_report(
        [],
        pghost="x",
        pgport=5432,
        pgdatabase="postgres",
        cases_dir=Path("cases/bug-regression"),
        artifacts_root=Path("artifacts/m1-dogfood"),
        timestamp="2026-05-24-0000",
        run_id=1,
    )
    assert "No cases ran" in md
    assert "|   0   |  0   |  0   |   0   |  0   |" in md


def test_report_render_cluster_crashed_marker() -> None:
    from app.runner.orchestrator import CaseExecutionResult

    cer = CaseExecutionResult(
        case_id="lg-bug-XX",
        status=StepStatus.ERROR,
        duration_ms=100,
        cluster_crashed=True,
        error="cluster crashed",
    )
    md = render_report(
        [({"id": "lg-bug-XX", "title": "x", "status": "open"}, cer)],
        pghost="h",
        pgport=5432,
        pgdatabase="postgres",
        cases_dir=Path("cases/bug-regression"),
        artifacts_root=Path("artifacts/m1-dogfood"),
        timestamp="t",
        run_id=1,
    )
    assert "CLUSTER CRASHED" in md


# ---------------------------------------------------------------------------
# end-to-end main() with a fake pool (no network)
# ---------------------------------------------------------------------------


class _FakePool:
    """Stand-in for SqlSessionPool that records the DSN map and does
    nothing else. main() doesn't actually call .acquire() because we
    also monkeypatch the sql driver."""

    def __init__(self, dsn_map: dict[str, str]) -> None:
        self.dsn_map = dsn_map
        self.closed = False
        self.discard_calls = 0

    async def close_all(self) -> None:
        self.closed = True

    async def discard_all(self) -> None:
        # orchestrator invokes this once per case to reset session state
        # (dogfood 2026-05-26 zombodb regression fix). No-op for the fake;
        # we count calls for any test that wants to assert.
        self.discard_calls += 1


async def test_e2e_with_mock_pool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The most important test: main() loads a real case YAML, builds
    a dsn map, runs the orchestrator with a fake SQL driver, writes
    artifacts + a markdown report. Verifies wiring end-to-end without
    a live cluster."""

    # Monkey-patch the orchestrator's sql driver dispatcher so we don't
    # actually need a Postgres connection. The orchestrator imports
    # execute_sql_step at module load, so we patch the binding inside
    # orchestrator's namespace.
    from app.runner import orchestrator as orch

    async def fake_sql(*, pool: Any, step_id: str, session: str, sql: str, timeout_ms: Any) -> Any:
        # Return a PASS step result so the case passes. Populate plan_text /
        # scalar / stdout with values that satisfy every assertion the
        # case YAMLs declare (plan_contains, scalar_ge, not_contains, ...).
        now = datetime.utcnow().isoformat()
        return StepResult(
            status=StepStatus.PASS,
            step_id=step_id,
            driver="sql",
            started_at=now,
            ended_at=now,
            duration_ms=1,
            stdout="ok",
            stderr="",
            scalar=0,  # so lg-bug-0003 expect: scalar: 0 passes
            plan_text="Hash Join on tmp_test02",  # so lg-bug-0001 plan_contains passes
        )

    monkeypatch.setattr(orch, "execute_sql_step", fake_sql)

    # Also patch log_grep so case-0002 doesn't try to read a real log file.
    def fake_log_grep(step_id: str, log_path: str, pattern: str, started_unix: float) -> StepResult:
        now = datetime.utcnow().isoformat()
        return StepResult(
            status=StepStatus.PASS,
            step_id=step_id,
            driver="log_grep",
            started_at=now,
            ended_at=now,
            duration_ms=1,
            matches=0,
        )

    monkeypatch.setattr(orch, "execute_log_grep_step", fake_log_grep)

    report_path = tmp_path / "report.md"
    artifacts_root = tmp_path / "artifacts"

    rc = await main(
        argv=[
            "--cases-dir",
            str(CASES_DIR),
            "--pghost",
            "fake-host",
            "--pgport",
            "5432",
            "--pguser",
            "gpadmin",
            "--pgdatabase",
            "postgres",
            "--artifacts-root",
            str(artifacts_root),
            "--report-path",
            str(report_path),
            "--case-id",
            "lg-bug-0001-hashjoin-right-table",
        ],
        pool_factory=_FakePool,
    )

    assert rc == 0
    assert report_path.exists()
    md = report_path.read_text(encoding="utf-8")
    assert "lg-bug-0001-hashjoin-right-table" in md
    # one case ran — summary table has exactly one total row.
    # (We don't assert pass=1 because the case YAML's
    #  `plan_contains: ["Hash", "tmp_test02"]` is a list, and the assertions
    #  module's _plan_contains evaluator expects a string. That mismatch is
    #  a real bug in the assertions module that the dogfood is supposed to
    #  surface; the SCRIPT's job is "load + normalize + run + report", and
    #  that's exactly what we're testing here.)
    assert "## Summary" in md
    assert "| total | pass | fail | error | skip |" in md
    # artifacts dir is created by the orchestrator at run_case time
    assert (artifacts_root / "1" / "lg-bug-0001-hashjoin-right-table").is_dir()


async def test_e2e_pass_path_with_synthetic_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sanity-check the pass path with a hand-crafted YAML whose assertions
    only depend on scalar/not_contains — both single-string evaluators that
    are robust to our fake driver's outputs."""
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "synthetic.yaml").write_text(
        "id: synthetic-pass\n"
        "category: bug_regression\n"
        "status: open\n"
        "defaults:\n"
        "  database: postgres\n"
        "setup:\n"
        "  - SELECT 0\n"
        "steps:\n"
        "  - id: s1\n"
        "    kind: sql\n"
        "    sql: SELECT 1\n"
        "    expect:\n"
        "      scalar: 1\n"
        "teardown:\n"
        "  - SELECT 0\n",
        encoding="utf-8",
    )

    from app.runner import orchestrator as orch

    async def fake_sql(*, pool: Any, step_id: str, session: str, sql: str, timeout_ms: Any) -> Any:
        now = datetime.utcnow().isoformat()
        return StepResult(
            status=StepStatus.PASS,
            step_id=step_id,
            driver="sql",
            started_at=now,
            ended_at=now,
            duration_ms=1,
            scalar=1,
        )

    monkeypatch.setattr(orch, "execute_sql_step", fake_sql)

    report_path = tmp_path / "r.md"
    rc = await main(
        argv=[
            "--cases-dir",
            str(cases_dir),
            "--report-path",
            str(report_path),
            "--artifacts-root",
            str(tmp_path / "a"),
            "--pghost",
            "fake",
        ],
        pool_factory=_FakePool,
    )
    assert rc == 0
    md = report_path.read_text(encoding="utf-8")
    assert "|   1   |  1   |  0   |   0   |  0   |" in md
    assert "synthetic-pass" in md
    assert "PASS" in md
    assert "upstream-fixed" in md  # status=open + run=pass


async def test_main_no_matching_cases_returns_zero(tmp_path: Path) -> None:
    """If --case-id filters out everything, main() should log a warning
    and return 0 (not crash, not raise)."""
    rc = await main(
        argv=[
            "--cases-dir",
            str(CASES_DIR),
            "--report-path",
            str(tmp_path / "r.md"),
            "--artifacts-root",
            str(tmp_path / "a"),
            "--case-id",
            "no-such-case",
        ],
        pool_factory=_FakePool,
    )
    assert rc == 0


async def test_main_missing_cases_dir_returns_one(tmp_path: Path) -> None:
    rc = await main(
        argv=[
            "--cases-dir",
            str(tmp_path / "nope"),
            "--report-path",
            str(tmp_path / "r.md"),
            "--artifacts-root",
            str(tmp_path / "a"),
        ],
        pool_factory=_FakePool,
    )
    assert rc == 1


# ---------------------------------------------------------------------------
# _auto_timestamp shape sanity
# ---------------------------------------------------------------------------


def test_auto_timestamp_format() -> None:
    ts = run_m1_dogfood._auto_timestamp()
    # Should be 4-digit year, 2-digit month/day/hour/minute, dash-separated.
    parts = ts.split("-")
    assert len(parts) == 4
    assert len(parts[0]) == 4
    assert len(parts[1]) == 2
    assert len(parts[2]) == 2
    assert len(parts[3]) == 4  # HHMM
    # parses
    datetime.strptime(ts, "%Y-%m-%d-%H%M")
