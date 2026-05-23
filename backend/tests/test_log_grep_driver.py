"""Tests for app.runner.log_grep_driver (M1-7).

Uses tmp_path + os.utime to control mtimes precisely so we can assert
the mtime-window filter behaves as designed (design.md §5).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.runner.log_grep_driver import MAX_SAMPLE_LINES, execute_log_grep_step
from app.runner.types import StepStatus


def _write(path: Path, content: str, mtime: float) -> None:
    path.write_text(content, encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_happy_path_window_filters_out_old_file(tmp_path: Path) -> None:
    started = 1_000_000.0
    ended = 2_000_000.0

    in_window = tmp_path / "in.log"
    out_of_window = tmp_path / "old.log"

    _write(
        in_window,
        "ERROR boom\nINFO ok\nERROR again\nWARN huh\nERROR third\n",
        mtime=1_500_000.0,
    )
    _write(out_of_window, "ERROR a\nERROR b\nERROR c\nERROR d\nERROR e\n", mtime=500_000.0)

    result = execute_log_grep_step(
        step_id="s1",
        log_path=str(tmp_path),
        pattern=r"ERROR",
        started_at_unix=started,
        ended_at_unix=ended,
    )

    assert result.status is StepStatus.PASS
    assert result.matches == 3
    assert result.artifacts == [str(in_window)]
    # stdout should contain 3 sample lines, each prefixed with file path
    assert result.stdout.count("\n") == 2  # 3 lines = 2 newlines
    assert "ERROR boom" in result.stdout
    assert "ERROR again" in result.stdout
    assert "ERROR third" in result.stdout
    # Out-of-window file content must not leak into stdout or artifacts
    assert str(out_of_window) not in result.stdout
    assert str(out_of_window) not in result.artifacts


def test_no_match_returns_zero_with_empty_stdout_and_artifacts(tmp_path: Path) -> None:
    fp = tmp_path / "quiet.log"
    _write(fp, "INFO all good\nDEBUG fine\n", mtime=1_500_000.0)

    result = execute_log_grep_step(
        step_id="s2",
        log_path=str(tmp_path),
        pattern=r"ERROR",
        started_at_unix=1_000_000.0,
        ended_at_unix=2_000_000.0,
    )

    assert result.status is StepStatus.PASS
    assert result.matches == 0
    assert result.stdout == ""
    assert result.artifacts == []


def test_invalid_regex_returns_error(tmp_path: Path) -> None:
    result = execute_log_grep_step(
        step_id="s3",
        log_path=str(tmp_path),
        pattern=r"[",
        started_at_unix=0.0,
        ended_at_unix=None,
    )

    assert result.status is StepStatus.ERROR
    assert result.error is not None
    assert "invalid regex" in result.error


def test_log_path_does_not_exist_returns_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    result = execute_log_grep_step(
        step_id="s4",
        log_path=str(missing),
        pattern=r"ERROR",
        started_at_unix=0.0,
        ended_at_unix=None,
    )

    assert result.status is StepStatus.ERROR
    assert result.error is not None
    assert "does not exist" in result.error


def test_log_path_is_a_file_returns_error(tmp_path: Path) -> None:
    f = tmp_path / "not-a-dir.log"
    f.write_text("ERROR\n", encoding="utf-8")

    result = execute_log_grep_step(
        step_id="s5",
        log_path=str(f),
        pattern=r"ERROR",
        started_at_unix=0.0,
        ended_at_unix=None,
    )

    assert result.status is StepStatus.ERROR
    assert result.error is not None
    assert "not a directory" in result.error


def test_non_utf8_content_does_not_crash(tmp_path: Path) -> None:
    fp = tmp_path / "binary.log"
    # bytes that are invalid UTF-8 mixed with searchable ASCII
    fp.write_bytes(b"ERROR start\n\xff\xfe\xfd not utf8\nERROR end\n")
    os.utime(fp, (1_500_000.0, 1_500_000.0))

    result = execute_log_grep_step(
        step_id="s6",
        log_path=str(tmp_path),
        pattern=r"ERROR",
        started_at_unix=1_000_000.0,
        ended_at_unix=2_000_000.0,
    )

    assert result.status is StepStatus.PASS
    # errors="replace" preserves the readable parts; both ERROR lines are intact ASCII
    assert result.matches == 2
    assert result.artifacts == [str(fp)]


def test_permission_error_on_one_file_skips_it(tmp_path: Path) -> None:
    readable = tmp_path / "ok.log"
    locked = tmp_path / "locked.log"

    _write(readable, "ERROR one\nERROR two\n", mtime=1_500_000.0)
    _write(locked, "ERROR hidden\n", mtime=1_500_000.0)

    # Skip on platforms / users where chmod 000 is still readable (e.g. running as root).
    if os.geteuid() == 0:
        pytest.skip("running as root; chmod 0o000 does not deny read")

    os.chmod(locked, 0o000)
    try:
        result = execute_log_grep_step(
            step_id="s7",
            log_path=str(tmp_path),
            pattern=r"ERROR",
            started_at_unix=1_000_000.0,
            ended_at_unix=2_000_000.0,
        )
    finally:
        # Restore mode so pytest's tmp_path cleanup can remove the file.
        os.chmod(locked, stat.S_IRUSR | stat.S_IWUSR)

    assert result.status is StepStatus.PASS
    assert result.matches == 2
    assert result.artifacts == [str(readable)]
    assert "ERROR hidden" not in result.stdout


def test_recursive_true_picks_up_subdir_file(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    fp = sub / "nested.log"
    _write(fp, "ERROR deep\n", mtime=1_500_000.0)

    result = execute_log_grep_step(
        step_id="s8",
        log_path=str(tmp_path),
        pattern=r"ERROR",
        started_at_unix=1_000_000.0,
        ended_at_unix=2_000_000.0,
        recursive=True,
    )

    assert result.status is StepStatus.PASS
    assert result.matches == 1
    assert result.artifacts == [str(fp)]


def test_recursive_false_skips_subdir_file(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    nested = sub / "nested.log"
    _write(nested, "ERROR deep\n", mtime=1_500_000.0)

    top = tmp_path / "top.log"
    _write(top, "ERROR top\n", mtime=1_500_000.0)

    result = execute_log_grep_step(
        step_id="s9",
        log_path=str(tmp_path),
        pattern=r"ERROR",
        started_at_unix=1_000_000.0,
        ended_at_unix=2_000_000.0,
        recursive=False,
    )

    assert result.status is StepStatus.PASS
    assert result.matches == 1
    assert result.artifacts == [str(top)]
    assert str(nested) not in result.artifacts


def test_max_sample_lines_cap(tmp_path: Path) -> None:
    fp = tmp_path / "noisy.log"
    lines = "\n".join(f"ERROR line {i}" for i in range(100)) + "\n"
    _write(fp, lines, mtime=1_500_000.0)

    result = execute_log_grep_step(
        step_id="s10",
        log_path=str(tmp_path),
        pattern=r"ERROR",
        started_at_unix=1_000_000.0,
        ended_at_unix=2_000_000.0,
    )

    assert result.status is StepStatus.PASS
    assert result.matches == 100
    # stdout is "\n".join of <= MAX_SAMPLE_LINES sample lines
    sample_lines = result.stdout.split("\n")
    assert len(sample_lines) == MAX_SAMPLE_LINES


def test_artifacts_only_contains_files_with_hits(tmp_path: Path) -> None:
    hit = tmp_path / "hit.log"
    miss = tmp_path / "miss.log"
    out_of_window = tmp_path / "old.log"

    _write(hit, "ERROR yes\n", mtime=1_500_000.0)
    _write(miss, "INFO nothing\n", mtime=1_500_000.0)
    _write(out_of_window, "ERROR but out of window\n", mtime=500_000.0)

    result = execute_log_grep_step(
        step_id="s11",
        log_path=str(tmp_path),
        pattern=r"ERROR",
        started_at_unix=1_000_000.0,
        ended_at_unix=2_000_000.0,
    )

    assert result.status is StepStatus.PASS
    assert result.matches == 1
    assert result.artifacts == [str(hit)]
    assert str(miss) not in result.artifacts
    assert str(out_of_window) not in result.artifacts


def test_ended_at_unix_none_treated_as_now(tmp_path: Path) -> None:
    import time as _time

    fp = tmp_path / "recent.log"
    # mtime "now" — should be within [started, now]
    _write(fp, "ERROR fresh\n", mtime=_time.time())

    result = execute_log_grep_step(
        step_id="s12",
        log_path=str(tmp_path),
        pattern=r"ERROR",
        started_at_unix=0.0,
        ended_at_unix=None,
    )

    assert result.status is StepStatus.PASS
    assert result.matches == 1
    assert result.artifacts == [str(fp)]
