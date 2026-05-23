"""Table-driven tests for expect-clause evaluators (design.md §5)."""

from __future__ import annotations

import pytest

from app.runner.assertions import (
    EVALUATORS,
    UnknownExpectKey,
    _duration_lt_ms,
    _exit_code,
    _matches,
    _matches_ge,
    _matches_lt,
    _not_contains,
    _plan_contains,
    _plan_contains_any,
    _regex,
    _row_count,
    _rows_affected,
    _scalar_eq,
    _scalar_ge,
    _scalar_gt,
    _scalar_le,
    _scalar_lt,
    _scalar_ne,
    _stdout_contains,
    evaluate,
)

# -- one pass + one fail per evaluator --
PASS_CASES = [
    ("exit_code", 0, 0),
    ("scalar", "kache", "kache"),
    ("scalar_eq", 5, 5),
    ("scalar_ne", "a", "b"),
    ("scalar_ge", 10, 1),
    ("scalar_le", 1, 10),
    ("scalar_gt", 10, 1),
    ("scalar_lt", 1, 10),
    ("row_count", 42, 42),
    ("rows_affected", 1, 1),
    ("plan_contains", "Hash Join on tmp_test02", "tmp_test02"),
    ("plan_contains", "Hash Join on tmp_test02", ["Hash", "tmp_test02"]),
    ("plan_contains_any", "Seq Scan", ["Index", "Seq"]),
    ("stdout_contains", "hello world", "world"),
    ("not_contains", "ok status", "ERROR"),
    ("regex", "abc-123-def", r"\d+"),
    ("matches", 0, 0),
    ("matches_lt", 1, 5),
    ("matches_ge", 5, 1),
    ("duration_lt_ms", 100, 30000),
]


FAIL_CASES = [
    ("exit_code", 1, 0),
    ("scalar", "kache", "other"),
    ("scalar_eq", 5, 6),
    ("scalar_ne", "same", "same"),
    ("scalar_ge", 1, 10),
    ("scalar_le", 10, 1),
    ("scalar_gt", 1, 1),
    ("scalar_lt", 10, 1),
    ("row_count", 41, 42),
    ("rows_affected", 0, 1),
    ("plan_contains", "Seq Scan", "Hash Join"),
    ("plan_contains", "Seq Scan on foo", ["Hash", "tmp_test02"]),
    ("plan_contains_any", "Nested Loop", ["Index", "Seq"]),
    ("stdout_contains", "hello", "world"),
    ("not_contains", "ERROR found", "ERROR"),
    ("regex", "abc", r"\d+"),
    ("matches", 3, 0),
    ("matches_lt", 5, 1),
    ("matches_ge", 1, 5),
    ("duration_lt_ms", 30000, 100),
]


@pytest.mark.parametrize(("key", "actual", "expected"), PASS_CASES)
def test_pass_cases(key: str, actual: object, expected: object) -> None:
    passed, detail = evaluate(key, actual, expected)
    assert passed is True, f"{key}: expected pass, got fail with detail={detail!r}"
    # Detail must mention both sides for diagnostics.
    assert detail, f"{key}: detail must be non-empty"


@pytest.mark.parametrize(("key", "actual", "expected"), FAIL_CASES)
def test_fail_cases(key: str, actual: object, expected: object) -> None:
    passed, detail = evaluate(key, actual, expected)
    assert passed is False, f"{key}: expected fail, got pass with detail={detail!r}"
    assert detail, f"{key}: detail must be non-empty"


# -- dispatcher / alias / type-loose contract --


def test_unknown_expect_key_raises() -> None:
    with pytest.raises(UnknownExpectKey):
        evaluate("nonexistent_key", 1, 1)


def test_scalar_alias_is_scalar_eq() -> None:
    # design.md §4.1: `expect.scalar` with no suffix == scalar_eq.
    assert EVALUATORS["scalar"] is EVALUATORS["scalar_eq"]


def test_scalar_eq_is_type_loose() -> None:
    # YAML may yield int 5, SQL may yield "5" or Decimal("5"); both must match.
    passed, _ = _scalar_eq("5", 5)
    assert passed is True


# -- None-handling per evaluator (all branches that gate on actual is None) --


@pytest.mark.parametrize(
    "func",
    [
        _exit_code,
        _scalar_eq,
        _scalar_ne,
        _scalar_ge,
        _scalar_le,
        _scalar_gt,
        _scalar_lt,
        _row_count,
        _rows_affected,
        _plan_contains,
        _stdout_contains,
        _not_contains,
        _regex,
        _matches,
        _matches_lt,
        _matches_ge,
        _duration_lt_ms,
    ],
)
def test_none_actual_fails(func) -> None:
    passed, detail = func(None, 5)
    assert passed is False
    assert "actual is None" in detail


def test_plan_contains_any_none_fails() -> None:
    passed, detail = _plan_contains_any(None, ["Hash Join"])
    assert passed is False
    assert "actual is None" in detail


def test_scalar_ge_none_specifically() -> None:
    # Explicit per spec.
    passed, detail = _scalar_ge(actual=None, expected=5)
    assert passed is False
    assert "actual is None" in detail


# -- regex / not_contains / plan_contains_any focused cases per dispatch spec --


def test_regex_with_dot_wildcard() -> None:
    passed, _ = _regex("hello world", "wo.ld")
    assert passed is True


def test_not_contains_pass_and_fail() -> None:
    passed, _ = _not_contains("ok", "err")
    assert passed is True
    passed, _ = _not_contains("err", "err")
    assert passed is False


def test_plan_contains_any_match_in_concatenated_text() -> None:
    passed, _ = _plan_contains_any("Hash Join nested loop", ["Merge Join", "Hash Join"])
    assert passed is True


# -- plan_contains list[str] shape (design.md §4.1 line 285) --


def test_plan_contains_list_all_present() -> None:
    # All substrings present => PASS.
    passed, detail = _plan_contains("Hash Join on tmp_test02", ["Hash", "tmp_test02"])
    assert passed is True
    assert "Hash" in detail and "tmp_test02" in detail


def test_plan_contains_list_some_missing() -> None:
    # Subset present => FAIL, detail names the missing items.
    passed, detail = _plan_contains("Hash Join on something_else", ["Hash", "tmp_test02"])
    assert passed is False
    assert "missing" in detail
    assert "tmp_test02" in detail
    # Items that DID match should not appear in missing list.
    # We check via the literal repr of the missing list.
    assert "['tmp_test02']" in detail


def test_plan_contains_list_none_present() -> None:
    # No substrings present => FAIL, both listed as missing.
    passed, detail = _plan_contains("Seq Scan on foo", ["Hash", "tmp_test02"])
    assert passed is False
    assert "missing" in detail
    assert "Hash" in detail
    assert "tmp_test02" in detail


def test_plan_contains_list_empty() -> None:
    # Edge case: empty list. Decision: PASS vacuously — no constraint declared
    # means nothing to check (consistent with "all of [] are present" being true).
    passed, _ = _plan_contains("anything goes", [])
    assert passed is True


def test_plan_contains_str_back_compat_pass() -> None:
    # Existing str-form still works (back-compat).
    passed, _ = _plan_contains("Hash Join on tmp_test02", "tmp_test02")
    assert passed is True


def test_plan_contains_str_back_compat_fail() -> None:
    passed, detail = _plan_contains("Seq Scan", "Hash Join")
    assert passed is False
    assert "Hash Join" in detail


# -- numeric comparators: non-numeric inputs return False with explanatory detail --


@pytest.mark.parametrize(
    "func",
    [_scalar_ge, _scalar_le, _scalar_gt, _scalar_lt],
)
def test_scalar_numeric_non_numeric_actual(func) -> None:
    passed, detail = func("not-a-number", 5)
    assert passed is False
    assert "not numeric" in detail


@pytest.mark.parametrize(
    "func",
    [_scalar_ge, _scalar_le, _scalar_gt, _scalar_lt],
)
def test_scalar_numeric_non_numeric_expected(func) -> None:
    passed, detail = func(5, "not-a-number")
    assert passed is False
    assert "not numeric" in detail


# -- regex: invalid pattern path --


def test_regex_invalid_pattern_fails_gracefully() -> None:
    passed, detail = _regex("hello", "[unclosed")
    assert passed is False
    assert "invalid regex" in detail


# -- registry shape sanity --


def test_registry_covers_all_19_keys() -> None:
    expected_keys = {
        "exit_code",
        "scalar",
        "scalar_eq",
        "scalar_ne",
        "scalar_ge",
        "scalar_le",
        "scalar_gt",
        "scalar_lt",
        "row_count",
        "rows_affected",
        "plan_contains",
        "plan_contains_any",
        "stdout_contains",
        "not_contains",
        "regex",
        "matches",
        "matches_lt",
        "matches_ge",
        "duration_lt_ms",
    }
    assert set(EVALUATORS.keys()) == expected_keys


# -- detail format: must include both expected and actual for pass and fail --


def test_detail_includes_expected_and_actual_on_fail() -> None:
    _, detail = _exit_code(1, 0)
    assert "0" in detail and "1" in detail


def test_detail_includes_expected_and_actual_on_pass() -> None:
    _, detail = _exit_code(0, 0)
    assert "0" in detail
