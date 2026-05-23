"""Tests for app.runner.orchestrator (M1-9).

Strategy: mock the three drivers (sql / shell / log_grep) so tests
exercise orchestration wiring (grouping, breaking on fail, teardown,
assertions, R9 fold-don't-bubble, destructive ordering, skip-list,
artifacts, recover-mode guard) without spinning up psycopg or
subprocesses. The drivers themselves are tested in their own modules.

Each test maps to a design.md section in its docstring so reviewer can
cross-check coverage:
  - happy path                 → §5.3 (基本 step 顺序执行)
  - first-fail break + teardown→ §5.3.3 (第一个非 pass step break；teardown 始终跑)
  - R9 step exception folded   → §5.3.3 / §14 R9
  - multi-session concurrency  → §5.3 (不同 on: session 并发)
  - destructive ordering       → §5.3.3 (destructive=true 排最后)
  - setup failure → teardown   → §5.3.3 (setup 失败仍跑 teardown)
  - assertions integration     → §5 expect schema → assertions.py
  - cluster_crashed guard      → §5.3 (recover mode 强制中止)
  - skip-list                  → §5 / §4.2 case_skip_list
  - artifacts on disk          → §5.3 artifacts/<run_id>/<case_id>/
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.runner import orchestrator
from app.runner.orchestrator import (
    CaseExecutionResult,
    SuiteSummary,
    run_case,
    run_suite,
)
from app.runner.types import StepResult, StepStatus

# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


def _make_step_result(
    step_id: str,
    *,
    status: StepStatus = StepStatus.PASS,
    driver: str = "sql",
    stdout: str = "",
    stderr: str = "",
    row_count: int | None = None,
    exit_code: int | None = None,
    matches: int | None = None,
    error: str | None = None,
) -> StepResult:
    now = datetime.utcnow().isoformat()
    return StepResult(
        status=status,
        step_id=step_id,
        driver=driver,
        started_at=now,
        ended_at=now,
        duration_ms=1,
        stdout=stdout,
        stderr=stderr,
        row_count=row_count,
        exit_code=exit_code,
        matches=matches,
        error=error,
    )


@contextmanager
def _noop_session() -> Any:
    yield MagicMock()


def _noop_session_factory():
    return _noop_session()


def _noop_insert(*args: Any, **kwargs: Any) -> None:
    return None


# ---------------------------------------------------------------------------
# happy path: single sql step PASS
# ---------------------------------------------------------------------------


async def test_happy_path_single_sql_step_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Maps to §5.3: simplest case — one step, dispatch + PASS verdict."""

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        return _make_step_result(step_id, status=StepStatus.PASS, stdout="ok")

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    case = {
        "id": "lg-bug-0001",
        "steps": [
            {"id": "s1", "kind": "sql", "on": "primary", "sql": "select 1"},
        ],
    }
    result = await run_case(
        case,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),  # presence-only; fake_sql ignores it
    )
    assert result.status is StepStatus.PASS
    assert len(result.step_results) == 1
    assert result.step_results[0].status is StepStatus.PASS
    assert result.cluster_crashed is False


# ---------------------------------------------------------------------------
# first-fail break + teardown still runs
# ---------------------------------------------------------------------------


async def test_first_fail_step_breaks_subsequent_and_runs_teardown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Maps to §5.3.3: first non-pass step breaks further steps in its
    group; teardown still runs best-effort."""

    call_log: list[str] = []

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        call_log.append(step_id)
        if step_id == "s1":
            return _make_step_result(step_id, status=StepStatus.FAIL)
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    case = {
        "id": "lg-bug-0002",
        "steps": [
            {"id": "s1", "kind": "sql", "on": "primary", "sql": "select 1"},
            {"id": "s2", "kind": "sql", "on": "primary", "sql": "select 2"},
            {"id": "s3", "kind": "sql", "on": "primary", "sql": "select 3"},
        ],
        "teardown": [
            {"id": "t1", "kind": "sql", "on": "primary", "sql": "drop temp"},
        ],
    }
    result = await run_case(
        case,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),
    )
    # s2 and s3 must NOT have been called.
    assert call_log == ["s1", "t1"]
    assert result.status is StepStatus.FAIL
    assert len(result.step_results) == 1  # broke after s1
    assert len(result.teardown_results) == 1
    assert result.teardown_results[0].status is StepStatus.PASS


# ---------------------------------------------------------------------------
# step exception → status=ERROR (R9 fold-don't-bubble)
# ---------------------------------------------------------------------------


async def test_driver_exception_is_folded_to_error_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Maps to §5.3.3 / §14 R9: a driver raising must NOT crash the case;
    the step gets status=error and the next case continues."""

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        raise RuntimeError("psycopg connection refused")

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    case = {
        "id": "lg-bug-0003",
        "steps": [{"id": "s1", "kind": "sql", "on": "primary", "sql": "select 1"}],
    }
    result = await run_case(
        case,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),
    )
    assert result.status is StepStatus.ERROR
    assert result.step_results[0].status is StepStatus.ERROR
    assert result.step_results[0].error is not None
    assert "RuntimeError" in result.step_results[0].error
    assert "psycopg connection refused" in result.step_results[0].error


# ---------------------------------------------------------------------------
# multi-session concurrency: 2 sessions × 2 steps each — wall ≈ max(group)
# ---------------------------------------------------------------------------


async def test_multi_session_steps_run_concurrently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Maps to §5.3: different `on:` session names run in parallel via
    asyncio.gather; total wall time ≈ max(group_wall) not sum."""

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        # Each step sleeps 0.10s (fast enough to keep test snappy)
        await asyncio.sleep(0.10)
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    # session A has 2 sequential steps; session B has 2 sequential steps;
    # A and B run concurrently. Sequential per-group cost = 0.20s each;
    # concurrent total ≈ 0.20s (not 0.40s).
    case = {
        "id": "lg-bug-0004",
        "steps": [
            {"id": "a1", "kind": "sql", "on": "A", "sql": "select 1"},
            {"id": "b1", "kind": "sql", "on": "B", "sql": "select 2"},
            {"id": "a2", "kind": "sql", "on": "A", "sql": "select 3"},
            {"id": "b2", "kind": "sql", "on": "B", "sql": "select 4"},
        ],
    }
    t0 = asyncio.get_event_loop().time()
    result = await run_case(
        case,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),
    )
    elapsed = asyncio.get_event_loop().time() - t0

    assert result.status is StepStatus.PASS
    assert len(result.step_results) == 4
    # Strict-ish bound: if it had serialized, elapsed ≥ 0.40s; if concurrent
    # we expect ≤ ~0.30s (0.20s real work + scheduling slack). Pick 0.30
    # as a safety threshold robust against CI noise.
    assert elapsed < 0.30, f"expected concurrent execution, got elapsed={elapsed:.3f}s"


# ---------------------------------------------------------------------------
# destructive ordering at suite level
# ---------------------------------------------------------------------------


async def test_destructive_cases_run_last(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Maps to §5.3.3: destructive=true cases sort to the end of the
    suite. Order in input: A=destructive, B=not, C=destructive, D=not.
    Expected execution order: B, D, A, C (stable sort, non-destructive first)."""

    executed_order: list[str] = []

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    # Wrap run_case to record case_id in order.
    real_run_case = orchestrator.run_case

    async def tracking_run_case(case, run_id, **kw):
        executed_order.append(case["id"])
        return await real_run_case(case, run_id, **kw)

    monkeypatch.setattr(orchestrator, "run_case", tracking_run_case)

    cases = [
        {"id": "A", "destructive": True, "steps": _one_sql_step("A1")},
        {"id": "B", "destructive": False, "steps": _one_sql_step("B1")},
        {"id": "C", "destructive": True, "steps": _one_sql_step("C1")},
        {"id": "D", "destructive": False, "steps": _one_sql_step("D1")},
    ]
    summary = await run_suite(
        cases,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        session_factory=_noop_session_factory,
        sql_pool=MagicMock(),
        insert_case_result_fn=_noop_insert,
    )
    assert executed_order == ["B", "D", "A", "C"]
    assert summary.passed == 4


def _one_sql_step(step_id: str) -> list[dict[str, Any]]:
    return [{"id": step_id, "kind": "sql", "on": "primary", "sql": "select 1"}]


# ---------------------------------------------------------------------------
# setup failure → steps[] skipped, teardown still runs
# ---------------------------------------------------------------------------


async def test_setup_failure_skips_steps_but_runs_teardown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Maps to §5.3.3: setup failure → case status=error, main steps[]
    are NOT executed, but teardown still runs best-effort."""

    call_log: list[str] = []

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        call_log.append(step_id)
        if step_id == "setup1":
            return _make_step_result(step_id, status=StepStatus.FAIL)
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    case = {
        "id": "lg-bug-0005",
        "setup": [
            {"id": "setup1", "kind": "sql", "on": "primary", "sql": "create temp"},
        ],
        "steps": [
            {"id": "main1", "kind": "sql", "on": "primary", "sql": "select 1"},
        ],
        "teardown": [
            {"id": "td1", "kind": "sql", "on": "primary", "sql": "drop temp"},
        ],
    }
    result = await run_case(
        case,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),
    )
    # main1 must NOT have been called; setup1 + td1 yes.
    assert "main1" not in call_log
    assert "setup1" in call_log
    assert "td1" in call_log
    assert result.status is StepStatus.ERROR
    assert len(result.step_results) == 0  # main steps[] skipped
    assert len(result.teardown_results) == 1
    assert result.teardown_results[0].status is StepStatus.PASS


# ---------------------------------------------------------------------------
# assertions integration: PASS evaluator vs FAIL evaluator
# ---------------------------------------------------------------------------


async def test_assertion_pass_downgrade_to_fail_when_expect_mismatches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Maps to §5 expect schema: PASS step downgrades to FAIL when its
    expect: row_count != actual row_count. Verifies the wiring from
    StepResult.row_count → assertions.evaluate(row_count, ...)."""

    async def fake_sql_row_count(*, pool, step_id, session, sql, timeout_ms):
        return _make_step_result(step_id, status=StepStatus.PASS, row_count=5)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql_row_count)

    # 1. expect matches → PASS preserved.
    case_pass = {
        "id": "lg-bug-0006a",
        "steps": [
            {
                "id": "s1",
                "kind": "sql",
                "on": "primary",
                "sql": "select * from t",
                "expect": {"row_count": 5},
            }
        ],
    }
    result_pass = await run_case(
        case_pass,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),
    )
    assert result_pass.status is StepStatus.PASS
    assert result_pass.step_results[0].assertions == [
        ("row_count", True, "expected row_count == 5, got 5")
    ]

    # 2. expect mismatches → downgrade PASS → FAIL.
    case_fail = {
        "id": "lg-bug-0006b",
        "steps": [
            {
                "id": "s1",
                "kind": "sql",
                "on": "primary",
                "sql": "select * from t",
                "expect": {"row_count": 6},
            }
        ],
    }
    result_fail = await run_case(
        case_fail,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),
    )
    assert result_fail.status is StepStatus.FAIL
    assert result_fail.step_results[0].status is StepStatus.FAIL
    # assertion record contains the mismatch detail
    assert any(not passed for (_k, passed, _d) in result_fail.step_results[0].assertions)
    # case-level expect_detail summary line exists
    assert "s1.row_count" in result_fail.expect_detail


async def test_assertions_accept_yaml_loader_list_form(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Spec/loader compat: expect: as a list of single-key mappings
    (yaml_loader output) must work identically to the dict form."""

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        return _make_step_result(step_id, status=StepStatus.PASS, row_count=3)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    case = {
        "id": "lg-bug-0006c",
        "steps": [
            {
                "id": "s1",
                "kind": "sql",
                "on": "primary",
                "sql": "select * from t",
                "expect": [{"row_count": 3}],
            }
        ],
    }
    result = await run_case(
        case,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),
    )
    assert result.status is StepStatus.PASS
    assert result.step_results[0].assertions[0][0] == "row_count"


# ---------------------------------------------------------------------------
# cluster_crashed guard (recover mode in server.log)
# ---------------------------------------------------------------------------


async def test_recover_mode_guard_aborts_case_and_marks_cluster_crashed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Maps to §5.3: orchestrator polls server.log after each step; if
    'the database system is in recover mode' is found, abort remaining
    steps and set cluster_crashed=True, case status=error."""

    call_log: list[str] = []

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        call_log.append(step_id)
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    # First guard call returns 0 matches, second returns 1 — so step s1
    # passes, the guard after s1 (the SECOND call into the guard,
    # because tests above don't exercise it) returns 1 → abort before s2.
    guard_calls = {"n": 0}

    def fake_log_grep(step_id, log_path, pattern, started_at_unix, *args, **kwargs):
        guard_calls["n"] += 1
        matches = 1 if guard_calls["n"] >= 1 else 0
        sr = _make_step_result(step_id, status=StepStatus.PASS, driver="log_grep")
        sr.matches = matches
        return sr

    monkeypatch.setattr(orchestrator, "execute_log_grep_step", fake_log_grep)

    # Create a fake server.log file so the resolved path is truthy.
    server_log = tmp_path / "server.log"
    server_log.write_text("dummy\n")

    case = {
        "id": "lg-bug-0007",
        "steps": [
            {"id": "s1", "kind": "sql", "on": "primary", "sql": "select 1"},
            {"id": "s2", "kind": "sql", "on": "primary", "sql": "select 2"},
        ],
    }
    result = await run_case(
        case,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),
        server_log_path=str(server_log),
    )
    # s1 ran; s2 did NOT (guard fired after s1).
    assert call_log == ["s1"]
    assert result.cluster_crashed is True
    assert result.status is StepStatus.ERROR


# ---------------------------------------------------------------------------
# skip-list integration
# ---------------------------------------------------------------------------


async def test_skip_list_skips_case_without_executing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Maps to §4.2 case_skip_list: an active rule for a case_id makes
    run_suite mark that case status=skip with the rule's reason, and
    NOT call run_case at all."""

    call_log: list[str] = []

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        call_log.append(step_id)
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    cases = [
        {"id": "A", "steps": _one_sql_step("a1")},
        {"id": "B", "steps": _one_sql_step("b1")},
    ]
    skip_list = [
        {"case_id": "B", "reason": "upstream bug not fixed yet"},
    ]
    summary = await run_suite(
        cases,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        session_factory=_noop_session_factory,
        sql_pool=MagicMock(),
        skip_list=skip_list,
        insert_case_result_fn=_noop_insert,
    )
    assert call_log == ["a1"]  # B never ran
    assert summary.passed == 1
    assert summary.skipped == 1
    skipped_results = [c for c in summary.case_results if c.status is StepStatus.SKIP]
    assert len(skipped_results) == 1
    assert skipped_results[0].case_id == "B"
    assert skipped_results[0].skip_reason == "upstream bug not fixed yet"


async def test_skip_list_expired_rule_does_not_skip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Skip rule with `until_date` in the past must NOT activate."""

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    cases = [{"id": "A", "steps": _one_sql_step("a1")}]
    skip_list = [{"case_id": "A", "reason": "old", "until_date": "2000-01-01"}]
    summary = await run_suite(
        cases,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        session_factory=_noop_session_factory,
        sql_pool=MagicMock(),
        skip_list=skip_list,
        insert_case_result_fn=_noop_insert,
    )
    assert summary.passed == 1
    assert summary.skipped == 0


# ---------------------------------------------------------------------------
# artifacts written to disk
# ---------------------------------------------------------------------------


async def test_artifacts_written_to_disk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Maps to §5.3 artifacts/<run_id>/<case_id>/: each step's stdout
    and stderr are persisted as files."""

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        return _make_step_result(
            step_id,
            status=StepStatus.PASS,
            stdout="hello stdout",
            stderr="warn stderr",
        )

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    case = {
        "id": "lg-bug-0008",
        "steps": [
            {"id": "s1", "kind": "sql", "on": "primary", "sql": "select 1"},
        ],
    }
    result = await run_case(
        case,
        run_id=42,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),
    )
    case_dir = tmp_path / "42" / "lg-bug-0008"
    assert case_dir.is_dir()
    stdout_file = case_dir / "step-00-s1.stdout.txt"
    stderr_file = case_dir / "step-00-s1.stderr.txt"
    assert stdout_file.exists()
    assert stderr_file.exists()
    assert "hello stdout" in stdout_file.read_text()
    assert "warn stderr" in stderr_file.read_text()
    # artifacts_dir in the result points at the case directory
    assert result.artifacts_dir is not None
    assert Path(result.artifacts_dir) == case_dir
    # the StepResult.artifacts list contains the paths
    assert any("step-00-s1.stdout.txt" in p for p in result.step_results[0].artifacts)


# ---------------------------------------------------------------------------
# unknown step kind → error (NOT crash)
# ---------------------------------------------------------------------------


async def test_unknown_step_kind_produces_error_result(tmp_path: Path) -> None:
    """An unrecognized `kind:` value must surface as a step error, not
    propagate as an exception (R9)."""
    case = {
        "id": "lg-bug-0009",
        "steps": [{"id": "s1", "kind": "playwright", "on": "primary", "run": "x"}],
    }
    result = await run_case(
        case,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),
    )
    assert result.status is StepStatus.ERROR
    assert "unknown step kind" in (result.step_results[0].error or "")


# ---------------------------------------------------------------------------
# Jinja undefined variable → step error (StrictUndefined; §5.3.1 / R13)
# ---------------------------------------------------------------------------


async def test_jinja_undefined_variable_yields_step_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Maps to §5.3.1: StrictUndefined templates raise → orchestrator
    folds to step error WITHOUT calling the driver."""

    driver_called = {"v": False}

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        driver_called["v"] = True
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    case = {
        "id": "lg-bug-0010",
        "steps": [
            {
                "id": "s1",
                "kind": "sql",
                "on": "primary",
                "sql": "select '{{ external.kafka.host }}'",
            }
        ],
    }
    result = await run_case(
        case,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},  # no `external` defined
        dut_hosts=set(),
        sql_pool=MagicMock(),
    )
    assert driver_called["v"] is False
    assert result.status is StepStatus.ERROR
    assert "template error" in (result.step_results[0].error or "")


# ---------------------------------------------------------------------------
# decide_ssh_user — R13: host ∈ dut_hosts → gpadmin; else → root
# ---------------------------------------------------------------------------


async def test_ssh_user_decision_threads_into_render_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Maps to §5.3.2 / §14 R13: when a step has a `host:` field, the
    rendered ssh_user variable should be available in the cmd template.
    """

    captured_cmds: list[str] = []

    async def fake_shell(*, step_id, command, timeout_ms, cwd=None, env=None):
        captured_cmds.append(command)
        return _make_step_result(step_id, driver="shell", exit_code=0)

    monkeypatch.setattr(orchestrator, "execute_shell_step", fake_shell)

    case = {
        "id": "lg-bug-0011",
        "steps": [
            {
                "id": "dut_step",
                "kind": "shell",
                "host": "sdw1",  # in dut_hosts
                "cmd": "ssh {{ ssh_user }}@{{ host }} 'gpstate -s'",
            },
            {
                "id": "ext_step",
                "kind": "shell",
                "host": "hive.example.com",  # NOT in dut_hosts
                "cmd": "ssh {{ ssh_user }}@{{ host }} 'beeline -u jdbc:...'",
            },
        ],
    }
    result = await run_case(
        case,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts={"sdw1", "synxdb-0001"},
    )
    # Surface any error message so debug is easy if this regresses.
    for sr in result.step_results:
        assert sr.error is None, f"step {sr.step_id} had error: {sr.error}"
    assert len(captured_cmds) == 2
    assert "ssh gpadmin@sdw1" in captured_cmds[0]
    assert "ssh root@hive.example.com" in captured_cmds[1]


# ---------------------------------------------------------------------------
# suite-level R9: case-level exception folded
# ---------------------------------------------------------------------------


async def test_case_level_exception_in_suite_continues_to_next(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Maps to §5.3.3 / §14 R9: a case-level crash (not step-level) must
    NOT abort the suite. The crashed case gets status=error; the next
    case runs."""

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    # Patch run_case (within the orchestrator namespace) to raise on
    # case A, work normally on case B.
    real_run_case = orchestrator.run_case

    async def flaky_run_case(case, run_id, **kw):
        if case["id"] == "A":
            raise RuntimeError("simulated case-level crash")
        return await real_run_case(case, run_id, **kw)

    monkeypatch.setattr(orchestrator, "run_case", flaky_run_case)

    cases = [
        {"id": "A", "steps": _one_sql_step("a1")},
        {"id": "B", "steps": _one_sql_step("b1")},
    ]
    summary = await run_suite(
        cases,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        session_factory=_noop_session_factory,
        sql_pool=MagicMock(),
        insert_case_result_fn=_noop_insert,
    )
    assert summary.passed == 1
    assert summary.errored == 1
    statuses = {c.case_id: c.status for c in summary.case_results}
    assert statuses["A"] is StepStatus.ERROR
    assert statuses["B"] is StepStatus.PASS


# ---------------------------------------------------------------------------
# teardown failure does NOT change case status
# ---------------------------------------------------------------------------


async def test_teardown_failure_does_not_change_case_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Maps to §5.3.3: teardown failure → log + continue; case status
    must remain whatever the main steps resolved to."""

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        if step_id == "td":
            return _make_step_result(step_id, status=StepStatus.FAIL)
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    case = {
        "id": "lg-bug-0012",
        "steps": [{"id": "s1", "kind": "sql", "on": "primary", "sql": "x"}],
        "teardown": [{"id": "td", "kind": "sql", "on": "primary", "sql": "y"}],
    }
    result = await run_case(
        case,
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),
    )
    assert result.status is StepStatus.PASS
    assert result.teardown_results[0].status is StepStatus.FAIL


# ---------------------------------------------------------------------------
# persistence wiring sanity: insert_case_result_fn called once per case
# ---------------------------------------------------------------------------


async def test_suite_persists_one_row_per_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """run_suite must call insert_case_result_fn exactly once per case
    (including skipped ones)."""

    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)

    inserted: list[dict[str, Any]] = []

    def capture_insert(session, **kw):
        inserted.append(kw)

    cases = [
        {"id": "A", "steps": _one_sql_step("a1")},
        {"id": "B", "steps": _one_sql_step("b1")},
        {"id": "C", "steps": _one_sql_step("c1")},
    ]
    skip_list = [{"case_id": "C", "reason": "stub"}]

    summary = await run_suite(
        cases,
        run_id=99,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        session_factory=_noop_session_factory,
        sql_pool=MagicMock(),
        skip_list=skip_list,
        insert_case_result_fn=capture_insert,
    )
    assert len(inserted) == 3
    ids = sorted(row["case_id"] for row in inserted)
    assert ids == ["A", "B", "C"]
    # status strings (not enum) for the DB column
    statuses = {row["case_id"]: row["status"] for row in inserted}
    assert statuses["A"] == "pass"
    assert statuses["B"] == "pass"
    assert statuses["C"] == "skip"
    assert summary.total == 3


# ---------------------------------------------------------------------------
# return type sanity
# ---------------------------------------------------------------------------


async def test_run_case_returns_case_execution_result_dataclass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)
    result = await run_case(
        {"id": "X", "steps": _one_sql_step("s1")},
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        sql_pool=MagicMock(),
    )
    assert isinstance(result, CaseExecutionResult)


async def test_run_suite_returns_suite_summary_dataclass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_sql(*, pool, step_id, session, sql, timeout_ms):
        return _make_step_result(step_id, status=StepStatus.PASS)

    monkeypatch.setattr(orchestrator, "execute_sql_step", fake_sql)
    summary = await run_suite(
        [{"id": "X", "steps": _one_sql_step("s1")}],
        run_id=1,
        artifacts_root=tmp_path,
        jinja_context={},
        dut_hosts=set(),
        session_factory=_noop_session_factory,
        sql_pool=MagicMock(),
        insert_case_result_fn=_noop_insert,
    )
    assert isinstance(summary, SuiteSummary)
    assert summary.total == 1
