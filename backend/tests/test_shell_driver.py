"""Tests for app.runner.shell_driver (design.md §5, §14 R9).

Integration-style — exercises the real asyncio subprocess machinery
against /bin/sh, no mocking. These confirm that:
  * exit 0 → PASS, captured stdout
  * exit !=0 → FAIL (ran cleanly, just non-zero), exit_code preserved
  * stderr is captured independently
  * timeout → ERROR, process is actually killed (duration well under
    the underlying command's natural runtime)
  * unspawnable command (bad cwd) → ERROR, error message names the
    OS exception type
  * env passthrough works
  * non-UTF8 bytes don't crash decode (errors='replace')
"""

from __future__ import annotations

import os

import pytest

from app.runner.shell_driver import execute_shell_step
from app.runner.types import StepStatus


@pytest.mark.asyncio
async def test_happy_path_echo() -> None:
    r = await execute_shell_step("s1", "echo hello")
    assert r.status is StepStatus.PASS
    assert r.exit_code == 0
    assert "hello" in r.stdout
    assert r.driver == "shell"
    assert r.step_id == "s1"
    assert r.error is None


@pytest.mark.asyncio
async def test_non_zero_exit_is_fail_not_error() -> None:
    # `exit 7` runs under /bin/sh -c — process executes cleanly and just
    # returns code 7. That's FAIL (the step ran, the step failed), not
    # ERROR (the driver couldn't run the step).
    r = await execute_shell_step("s2", "exit 7")
    assert r.status is StepStatus.FAIL
    assert r.exit_code == 7
    assert r.error is None


@pytest.mark.asyncio
async def test_stderr_capture() -> None:
    r = await execute_shell_step("s3", "echo err 1>&2 ; exit 0")
    assert r.status is StepStatus.PASS
    assert r.exit_code == 0
    assert "err" in r.stderr
    # stdout should be empty (we redirected the echo to stderr).
    assert r.stdout.strip() == ""


@pytest.mark.asyncio
async def test_timeout_folds_to_error_and_kills_process() -> None:
    r = await execute_shell_step("s4", "sleep 5", timeout_ms=100)
    assert r.status is StepStatus.ERROR
    assert r.error is not None
    assert "TimeoutError" in r.error
    # Sanity: we must have killed the sleep(5). Allow generous slack
    # for slow CI but stay well under the 5000ms natural runtime.
    assert r.duration_ms < 2000, f"duration_ms={r.duration_ms} suggests kill didn't fire"


@pytest.mark.asyncio
async def test_spawn_failure_with_bad_cwd_is_error() -> None:
    r = await execute_shell_step(
        "s5",
        "echo never-runs",
        cwd="/definitely/does/not/exist/lightning-bug-xyz",
    )
    assert r.status is StepStatus.ERROR
    assert r.error is not None
    # Driver labels spawn failures explicitly so post-run triage can tell
    # 'process ran and crashed' from 'we never got a process'.
    assert "spawn failed" in r.error
    assert ("FileNotFoundError" in r.error) or ("OSError" in r.error)


@pytest.mark.asyncio
async def test_env_passthrough() -> None:
    # /bin/sh on most distros needs PATH (etc.) from os.environ; passing
    # only {"FOO": "bar"} would strip the shell's own runtime env. Real
    # callers merge with os.environ — mirror that here.
    env = {**os.environ, "FOO": "bar"}
    r = await execute_shell_step("s6", "echo $FOO", env=env)
    assert r.status is StepStatus.PASS
    assert "bar" in r.stdout


@pytest.mark.asyncio
async def test_non_utf8_stdout_does_not_crash() -> None:
    # Emit raw 0xff 0xfe (invalid UTF-8) via python so the test doesn't
    # depend on /bin/sh's printf hex-escape behaviour — dash (Ubuntu's
    # default /bin/sh) doesn't expand \xHH, only bash does. CI runners
    # use dash; previous `printf '\xff\xfe'` left literal \xff\xfe bytes
    # on stdout and broke this assertion (M1 PR #8 forensic).
    # The driver must decode with errors='replace' so the orchestrator
    # (which only sees the StepResult, never raw bytes) doesn't blow up.
    cmd = "python3 -c 'import sys; sys.stdout.buffer.write(bytes([255, 254]))'"
    r = await execute_shell_step("s7", cmd)
    assert r.status is StepStatus.PASS
    assert r.exit_code == 0
    # U+FFFD REPLACEMENT CHARACTER — what utf-8 'replace' emits for
    # each invalid byte.
    assert "�" in r.stdout
