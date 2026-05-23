"""Expect-clause evaluators (design.md §5 expect schema).

Each evaluator: (actual: Any, expected: Any) -> tuple[bool, str].
The orchestrator picks the evaluator by expect key and supplies actual
from StepResult fields per this mapping:

   expect_key            actual_source
   ----------            -------------
   exit_code             step.exit_code (shell only)
   scalar / scalar_eq    step.scalar    (sql)
   scalar_ne             step.scalar
   scalar_ge             step.scalar
   scalar_le             step.scalar
   scalar_gt             step.scalar
   scalar_lt             step.scalar
   row_count             step.row_count (sql)
   rows_affected         step.rows_affected (sql)
   plan_contains         step.plan_text (sql EXPLAIN)
   plan_contains_any     step.plan_text
   stdout_contains       step.stdout
   not_contains          step.stdout
   regex                 step.stdout
   matches               step.matches (log_grep)
   matches_lt            step.matches
   matches_ge            step.matches
   duration_lt_ms        step.duration_ms

For 'scalar' (no suffix) and 'scalar_eq', behave identically: pass iff
actual == expected (string-coerce both sides for type-loose match).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any


def _exit_code(actual: int | None, expected: int) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected exit_code == {expected}, got None (actual is None)"
    passed = actual == expected
    return passed, f"expected exit_code == {expected}, got {actual}"


def _scalar_eq(actual: Any, expected: Any) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected scalar == {expected!r}, got None (actual is None)"
    # Loose type comparison: YAML int vs SQL Decimal vs str all coerce via str().
    passed = str(actual) == str(expected)
    return passed, f"expected scalar == {expected!r}, got {actual!r}"


def _scalar_ne(actual: Any, expected: Any) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected scalar != {expected!r}, got None (actual is None)"
    passed = str(actual) != str(expected)
    return passed, f"expected scalar != {expected!r}, got {actual!r}"


def _coerce_floats(actual: Any, expected: Any) -> tuple[float, float] | str:
    """Coerce both sides to float; return error string on failure."""
    try:
        a = float(actual)
    except (TypeError, ValueError):
        return f"actual {actual!r} not numeric"
    try:
        e = float(expected)
    except (TypeError, ValueError):
        return f"expected {expected!r} not numeric"
    return a, e


def _scalar_ge(actual: Any, expected: Any) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected scalar >= {expected!r}, got None (actual is None)"
    coerced = _coerce_floats(actual, expected)
    if isinstance(coerced, str):
        return False, f"expected scalar >= {expected!r}, got {actual!r} ({coerced})"
    a, e = coerced
    return a >= e, f"expected scalar >= {expected!r}, got {actual!r}"


def _scalar_le(actual: Any, expected: Any) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected scalar <= {expected!r}, got None (actual is None)"
    coerced = _coerce_floats(actual, expected)
    if isinstance(coerced, str):
        return False, f"expected scalar <= {expected!r}, got {actual!r} ({coerced})"
    a, e = coerced
    return a <= e, f"expected scalar <= {expected!r}, got {actual!r}"


def _scalar_gt(actual: Any, expected: Any) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected scalar > {expected!r}, got None (actual is None)"
    coerced = _coerce_floats(actual, expected)
    if isinstance(coerced, str):
        return False, f"expected scalar > {expected!r}, got {actual!r} ({coerced})"
    a, e = coerced
    return a > e, f"expected scalar > {expected!r}, got {actual!r}"


def _scalar_lt(actual: Any, expected: Any) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected scalar < {expected!r}, got None (actual is None)"
    coerced = _coerce_floats(actual, expected)
    if isinstance(coerced, str):
        return False, f"expected scalar < {expected!r}, got {actual!r} ({coerced})"
    a, e = coerced
    return a < e, f"expected scalar < {expected!r}, got {actual!r}"


def _row_count(actual: int | None, expected: int) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected row_count == {expected}, got None (actual is None)"
    passed = actual == expected
    return passed, f"expected row_count == {expected}, got {actual}"


def _rows_affected(actual: int | None, expected: int) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected rows_affected == {expected}, got None (actual is None)"
    passed = actual == expected
    return passed, f"expected rows_affected == {expected}, got {actual}"


def _plan_contains(actual: str | None, expected: str) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected plan to contain {expected!r}, got None (actual is None)"
    passed = expected in actual
    return passed, f"expected plan to contain {expected!r}, got plan_text={actual!r}"


def _plan_contains_any(actual: str | None, expected: list[str]) -> tuple[bool, str]:
    """Pass iff any string in expected list is a substring of actual."""
    if actual is None:
        return False, f"expected plan to contain any of {expected!r}, got None (actual is None)"
    passed = any(needle in actual for needle in expected)
    return passed, f"expected plan to contain any of {expected!r}, got plan_text={actual!r}"


def _stdout_contains(actual: str, expected: str) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected stdout to contain {expected!r}, got None (actual is None)"
    passed = expected in actual
    return passed, f"expected stdout to contain {expected!r}, got stdout={actual!r}"


def _not_contains(actual: str, expected: str) -> tuple[bool, str]:
    """Pass iff expected substring is NOT in actual."""
    if actual is None:
        return False, f"expected stdout to NOT contain {expected!r}, got None (actual is None)"
    passed = expected not in actual
    return passed, f"expected stdout to NOT contain {expected!r}, got stdout={actual!r}"


def _regex(actual: str, expected: str) -> tuple[bool, str]:
    """Pass iff re.search(expected, actual) is truthy."""
    if actual is None:
        return False, f"expected regex {expected!r} to match, got None (actual is None)"
    try:
        match = re.search(expected, actual)
    except re.error as exc:
        return False, f"invalid regex {expected!r}: {exc}"
    passed = match is not None
    return passed, f"expected regex {expected!r} to match, got stdout={actual!r}"


def _matches(actual: int | None, expected: int) -> tuple[bool, str]:
    """Exact integer equality on log-grep match count."""
    if actual is None:
        return False, f"expected matches == {expected}, got None (actual is None)"
    passed = actual == expected
    return passed, f"expected matches == {expected}, got {actual}"


def _matches_lt(actual: int | None, expected: int) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected matches < {expected}, got None (actual is None)"
    passed = actual < expected
    return passed, f"expected matches < {expected}, got {actual}"


def _matches_ge(actual: int | None, expected: int) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected matches >= {expected}, got None (actual is None)"
    passed = actual >= expected
    return passed, f"expected matches >= {expected}, got {actual}"


def _duration_lt_ms(actual: int, expected: int) -> tuple[bool, str]:
    if actual is None:
        return False, f"expected duration < {expected} ms, got None (actual is None)"
    passed = actual < expected
    return passed, f"expected duration < {expected} ms, got {actual} ms"


EVALUATORS: dict[str, Callable[[Any, Any], tuple[bool, str]]] = {
    "exit_code": _exit_code,
    "scalar": _scalar_eq,
    "scalar_eq": _scalar_eq,
    "scalar_ne": _scalar_ne,
    "scalar_ge": _scalar_ge,
    "scalar_le": _scalar_le,
    "scalar_gt": _scalar_gt,
    "scalar_lt": _scalar_lt,
    "row_count": _row_count,
    "rows_affected": _rows_affected,
    "plan_contains": _plan_contains,
    "plan_contains_any": _plan_contains_any,
    "stdout_contains": _stdout_contains,
    "not_contains": _not_contains,
    "regex": _regex,
    "matches": _matches,
    "matches_lt": _matches_lt,
    "matches_ge": _matches_ge,
    "duration_lt_ms": _duration_lt_ms,
}


class UnknownExpectKey(KeyError):
    """Raised when expect clause uses a key not in EVALUATORS."""


def evaluate(expect_key: str, actual: Any, expected: Any) -> tuple[bool, str]:
    """Dispatch single expect clause. Raises UnknownExpectKey if key not registered."""
    if expect_key not in EVALUATORS:
        raise UnknownExpectKey(f"unknown expect key: {expect_key!r} (known: {sorted(EVALUATORS)})")
    return EVALUATORS[expect_key](actual, expected)
