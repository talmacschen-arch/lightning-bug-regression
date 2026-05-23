"""Log directory grep driver (design.md §5).

Scans files under log_path (directory) whose mtime falls in
[started_at, ended_at] window. For each file, reads line-by-line
and counts regex matches. Returns StepResult with:
  matches    = total match count across all in-window files
  stdout     = first up-to-MAX_SAMPLE_LINES matching lines (one per line)
  artifacts  = list of file paths that contributed at least one match

R9: catches FileNotFoundError, PermissionError, UnicodeDecodeError, etc.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from pathlib import Path

from app.runner.types import StepResult, StepStatus

MAX_SAMPLE_LINES = 50


def execute_log_grep_step(
    step_id: str,
    log_path: str,
    pattern: str,
    started_at_unix: float,
    ended_at_unix: float | None = None,
    recursive: bool = True,
) -> StepResult:
    """Synchronous (fs I/O is local; orchestrator wraps in thread if needed).

    - log_path: directory to scan.
    - pattern: Python regex (re.search, multi-line=False).
    - started_at_unix / ended_at_unix: file mtime window (inclusive). If
      ended_at_unix is None, treat as "now".
    """
    started_iso = _iso_now()
    t0 = time.monotonic()
    sample: list[str] = []
    matched_files: list[str] = []
    total = 0

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return _err(step_id, started_iso, t0, f"invalid regex: {e}")

    end = ended_at_unix if ended_at_unix is not None else time.time()
    root = Path(log_path)
    if not root.exists():
        return _err(step_id, started_iso, t0, f"log_path does not exist: {log_path}")
    if not root.is_dir():
        return _err(step_id, started_iso, t0, f"log_path is not a directory: {log_path}")

    try:
        files = root.rglob("*") if recursive else root.iterdir()
        for fp in files:
            try:
                if not fp.is_file():
                    continue
                st = fp.stat()
                if st.st_mtime < started_at_unix or st.st_mtime > end:
                    continue
                file_hits = 0
                with fp.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if regex.search(line):
                            total += 1
                            file_hits += 1
                            if len(sample) < MAX_SAMPLE_LINES:
                                sample.append(f"{fp}: {line.rstrip()}")
                if file_hits > 0:
                    matched_files.append(str(fp))
            except (PermissionError, OSError):
                # skip unreadable file; do NOT error the whole step
                continue
    except Exception as e:
        return _err(step_id, started_iso, t0, f"scan failed: {type(e).__name__}: {e}")

    duration_ms = int((time.monotonic() - t0) * 1000)
    # grep "ran cleanly" — orchestrator decides pass/fail via expect.matches
    return StepResult(
        status=StepStatus.PASS,
        step_id=step_id,
        driver="log_grep",
        started_at=started_iso,
        ended_at=_iso_now(),
        duration_ms=duration_ms,
        stdout="\n".join(sample),
        matches=total,
        artifacts=matched_files,
    )


def _iso_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _err(step_id: str, started: str, t0: float, msg: str) -> StepResult:
    return StepResult(
        status=StepStatus.ERROR,
        step_id=step_id,
        driver="log_grep",
        started_at=started,
        ended_at=_iso_now(),
        duration_ms=int((time.monotonic() - t0) * 1000),
        error=msg,
    )
