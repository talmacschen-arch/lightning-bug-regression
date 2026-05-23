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
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            pass
        return _err(step_id, started, t0, f"asyncio.TimeoutError (after {timeout_ms}ms)")
    except Exception as e:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
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
