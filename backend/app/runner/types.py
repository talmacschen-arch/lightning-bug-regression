"""Shared runner types (design.md §5, §14 R9).

StepResult is the unified return shape for every step driver
(sql_driver / shell_driver / log_grep_driver). The orchestrator
folds a list of StepResult into a CaseResult and never sees
raw driver exceptions — drivers must catch and convert to
StepResult(status=ERROR) per §14 R9.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class StepStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIP = "skip"


@dataclass
class StepResult:
    """Result of executing one step in a case.

    status:      pass/fail/error/skip
    step_id:     opaque identifier from YAML (str)
    driver:      "sql" | "shell" | "log_grep" | ...
    started_at:  ISO8601
    ended_at:    ISO8601
    duration_ms: monotonic wall-clock ms
    stdout:      driver stdout (sql: rendered query result text; shell: stdout)
    stderr:      driver stderr (sql: NOTICE/WARNING stream; shell: stderr)
    exit_code:   shell-driver only; None elsewhere
    scalar:      sql-driver first row first col; None elsewhere
    row_count:   sql-driver last result set row count; None elsewhere
    rows_affected: sql-driver UPDATE/DELETE/INSERT count; None elsewhere
    matches:     log-grep match count; None elsewhere
    plan_text:   EXPLAIN plan text (sql-driver explain steps); None elsewhere
    assertions:  list of (expect_key, passed, detail) tuples populated by
                 orchestrator after assertions.py runs
    error:       human-readable error message when status=ERROR (R9 fold-don't-bubble)
    artifacts:   driver-collected sample lines / files (paths or short strings)
    """

    status: StepStatus
    step_id: str
    driver: str
    started_at: str
    ended_at: str
    duration_ms: int
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    scalar: Any = None
    row_count: int | None = None
    rows_affected: int | None = None
    matches: int | None = None
    plan_text: str | None = None
    assertions: list[tuple[str, bool, str]] = field(default_factory=list)
    error: str | None = None
    artifacts: list[str] = field(default_factory=list)


class StepError(Exception):
    """Raised inside a driver only when the driver cannot produce a StepResult
    (e.g. malformed step config caught pre-execution). Orchestrator catches
    and converts to StepResult(status=ERROR). Drivers must NOT raise StepError
    for runtime failures — those return StepResult(status=ERROR) directly per R9.
    """
