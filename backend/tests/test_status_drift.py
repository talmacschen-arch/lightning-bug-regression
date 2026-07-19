"""Unit tests for the drift classifier (app/utils/status_drift.py).

These pin the判定阈值 — the易错的核心. Each test states the业务意图:
如果阈值/分支逻辑错了，对应 test 必挂。
"""
from __future__ import annotations

from app.utils import status_drift as sd


def test_bugfix_axis_is_exactly_open_and_fixed():
    # wontfix / stub / extension 成熟度轴的值都不该参与对账
    assert sd.BUGFIX_AXIS == frozenset({"open", "fixed"})


def test_fixed_with_fail_is_regression():
    assert sd.classify("fixed", ["fail", "pass", "pass"], 3)[0] == sd.REGRESSION


def test_fixed_with_error_is_regression():
    assert sd.classify("fixed", ["error"], 3)[0] == sd.REGRESSION


def test_fixed_all_pass_is_ok():
    assert sd.classify("fixed", ["pass", "pass"], 3)[0] == sd.OK


def test_fixed_all_skip_is_no_data():
    assert sd.classify("fixed", ["skip", "skip"], 3)[0] == sd.NO_DATA


def test_open_consecutive_pass_meets_threshold_is_candidate():
    assert sd.classify("open", ["pass", "pass", "pass"], 3)[0] == sd.CANDIDATE


def test_open_pass_below_threshold_is_thin_evidence():
    # 只 2 次 pass，阈值 3 → 采样不足，绝不能升 CANDIDATE（bug-0009 假阳性教训）
    assert sd.classify("open", ["pass", "pass"], 3)[0] == sd.THIN_EVIDENCE


def test_open_with_fail_is_expected():
    assert sd.classify("open", ["fail", "pass"], 3)[0] == sd.EXPECTED


def test_open_all_skip_is_no_data():
    assert sd.classify("open", ["skip"], 3)[0] == sd.NO_DATA


def test_skip_does_not_count_toward_pass_threshold():
    # 2 pass + 1 skip，阈值 3：skip 不计入，有效 pass 只 2 次 → THIN，非 CANDIDATE
    assert sd.classify("open", ["pass", "skip", "pass"], 3)[0] == sd.THIN_EVIDENCE


def test_rounds_one_promotes_single_pass_to_candidate():
    assert sd.classify("open", ["pass"], 1)[0] == sd.CANDIDATE


def test_drift_order_ranks_regression_first_ok_last():
    assert sd.DRIFT_ORDER[0] == sd.REGRESSION
    assert sd.DRIFT_ORDER[-1] == sd.OK


def test_actionable_is_the_three_needs_attention_categories():
    assert sd.ACTIONABLE == frozenset({sd.REGRESSION, sd.CANDIDATE, sd.THIN_EVIDENCE})
