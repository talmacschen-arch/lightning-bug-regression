"""Smoke tests for app.runner.types (M1 prep).

Verifies that the shared StepResult / StepStatus / StepError contract
the parallel driver branches (M1-5/6/7) will depend on is importable
and has the expected shape.
"""

from __future__ import annotations

import pytest

from app.runner.types import StepError, StepResult, StepStatus


def test_step_status_is_str_enum() -> None:
    # StepStatus inherits from str so JSON-serializing a StepResult dict
    # (e.g. via dataclasses.asdict + json.dumps) does not need a custom
    # encoder for the status field.
    assert StepStatus.PASS == "pass"
    assert StepStatus.FAIL == "fail"
    assert StepStatus.ERROR == "error"
    assert StepStatus.SKIP == "skip"
    assert isinstance(StepStatus.PASS, str)


def test_step_result_minimal_construction_and_defaults() -> None:
    result = StepResult(
        status=StepStatus.PASS,
        step_id="step-1",
        driver="sql",
        started_at="2026-05-23T00:00:00Z",
        ended_at="2026-05-23T00:00:01Z",
        duration_ms=1000,
    )
    assert result.status is StepStatus.PASS
    assert result.step_id == "step-1"
    assert result.driver == "sql"
    # Defaults for optional fields — drivers that don't apply leave these untouched.
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.exit_code is None
    assert result.scalar is None
    assert result.row_count is None
    assert result.rows_affected is None
    assert result.matches is None
    assert result.plan_text is None
    assert result.assertions == []
    assert result.error is None
    assert result.artifacts == []


def test_step_result_default_collections_are_not_shared() -> None:
    # Guard against the classic mutable-default footgun: field(default_factory=list)
    # must give each instance a fresh list.
    a = StepResult(
        status=StepStatus.PASS,
        step_id="a",
        driver="sql",
        started_at="t0",
        ended_at="t1",
        duration_ms=1,
    )
    b = StepResult(
        status=StepStatus.PASS,
        step_id="b",
        driver="sql",
        started_at="t0",
        ended_at="t1",
        duration_ms=1,
    )
    a.assertions.append(("k", True, "ok"))
    a.artifacts.append("/tmp/x")
    assert b.assertions == []
    assert b.artifacts == []


def test_step_error_is_exception() -> None:
    assert issubclass(StepError, Exception)
    with pytest.raises(StepError):
        raise StepError("malformed step config")
