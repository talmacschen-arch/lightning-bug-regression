"""Async shell driver (design.md §5, §14 R9).

Local subprocess only (M1 scope). Remote ssh wrapping happens at Jinja
template render time — caller is expected to pass an already-rendered
command string like `ssh -o ... gpadmin@sdw1 'gpstate -s'`. M1-8
jinja_render.decide_ssh_user owns the ssh prefix decision; this driver
just shells out.

R9: NEVER raise. asyncio.TimeoutError, OSError, FileNotFoundError —
all wrapped into StepResult(status=ERROR).
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from datetime import UTC, datetime

from app.runner.types import StepResult, StepStatus


async def execute_shell_step(
    step_id: str,
    command: str,
    timeout_ms: int | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> StepResult:
    """Run `command` via /bin/sh -c. Returns StepResult always.

    - status PASS iff exit_code == 0 and no timeout.
    - status FAIL iff process ran cleanly but exit_code != 0
      (subtle: distinguishes 'ran but failed' from 'driver couldn't run').
    - status ERROR iff timed out, OS error, or unable to spawn.
    """
    started = _iso_now()
    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    except (OSError, FileNotFoundError) as e:
        return _err(step_id, started, t0, f"spawn failed: {type(e).__name__}: {e}")

    try:
        if timeout_ms is not None and timeout_ms > 0:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_ms / 1000.0
            )
        else:
            stdout_b, stderr_b = await proc.communicate()
    except TimeoutError:
        await _force_kill_and_reap(proc)
        return _err(step_id, started, t0, f"asyncio.TimeoutError (after {timeout_ms}ms)")
    except Exception as e:
        await _force_kill_and_reap(proc)
        return _err(step_id, started, t0, f"{type(e).__name__}: {e}")

    duration_ms = int((time.monotonic() - t0) * 1000)
    exit_code = proc.returncode if proc.returncode is not None else -1
    status = StepStatus.PASS if exit_code == 0 else StepStatus.FAIL
    return StepResult(
        status=status,
        step_id=step_id,
        driver="shell",
        started_at=started,
        ended_at=_iso_now(),
        duration_ms=duration_ms,
        stdout=stdout_b.decode("utf-8", errors="replace"),
        stderr=stderr_b.decode("utf-8", errors="replace"),
        exit_code=exit_code,
    )


async def _force_kill_and_reap(proc: asyncio.subprocess.Process) -> None:
    """Kill subprocess + bound the cleanup wait.

    Belt-and-suspenders rationale (observed on Ubuntu CI 2026-05-23, M1
    shell_driver PR #8 — duration_ms came back as ~5001ms for a `sleep 5`
    with 100ms timeout, suggesting proc.kill() via the asyncio transport
    was swallowed silently after wait_for cancelled communicate(), and
    proc.wait() then patiently waited for the subprocess's natural
    termination):

      1. proc.kill() — the high-level asyncio method (may be no-op if
         transport state went sideways during cancellation).
      2. os.kill(pid, SIGKILL) — direct syscall, bypasses transport state.
      3. asyncio.wait_for(proc.wait(), timeout=1.0) — even with SIGKILL
         sent, asyncio transport finalization can hang on cancelled-
         communicate pipe state; bound it. If we time out here, the
         subprocess is already SIGKILL'd at the kernel level and will
         be reaped by init/Python's child reaper eventually — we just
         stop blocking the caller.
    """
    pid = proc.pid
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass
    if pid is not None:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=1.0)
    except (TimeoutError, Exception):
        pass


def _iso_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _err(step_id: str, started: str, t0: float, msg: str) -> StepResult:
    return StepResult(
        status=StepStatus.ERROR,
        step_id=step_id,
        driver="shell",
        started_at=started,
        ended_at=_iso_now(),
        duration_ms=int((time.monotonic() - t0) * 1000),
        error=msg,
    )
