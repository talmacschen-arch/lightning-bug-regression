"""Tests for POST /cases/submit + Try-pass cache (design.md §13.7 M3a-3 + M3a-3.5).

Covers:
  * Three-gate enforcement: missing/stale Try-pass cache → 400.
  * Re-validation: invalid YAML at submit time → 400 even with cache hit.
  * DRY-RUN happy path: writes file to disk, returns fake PR, makes NO
    subprocess calls.
  * Live happy path: mocks ``subprocess.run`` so it doesn't actually push;
    asserts every git/gh call carries ``cwd=str(repo_root)`` (§14 R27
    contract — repo_root resolved from ``LBR_REPO_ROOT`` env or
    ``__file__``-anchored default, never cwd-implicit).
  * Subprocess failure: ``CalledProcessError`` on ``git push`` → 500 with
    the stderr surfaced.
  * Cache freshness helper unit tests covering miss / fresh / stale.

These tests directly seed ``app.state.try_pass_cache[hash] = now`` rather
than going through ``POST /cases/try`` because that endpoint does not yet
exist (M3a-2 will add it and add its own "passing Try writes to cache"
test there). The cache helper + dict are exercised end-to-end via submit.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.cases import _resolve_repo_root, _try_cache_is_fresh
from app.main import app
from app.storage import sqlite_store
from app.storage.models import Base, CaseCategory

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _minimal_valid_yaml() -> str:
    """Mirror of test_api_validate.py — a YAML that passes both the §4.1
    schema (yaml_loader) and the normalizer's VALID_KINDS check."""
    return textwrap.dedent(
        """\
        id: lg-bug-9999-test-submit
        category: bug_regression
        title: submit endpoint smoke
        description: minimal valid case for /cases/submit test
        procedure: run one trivial sql
        expected: returns 1
        status: open
        steps:
          - name: trivial
            kind: sql
            sql: SELECT 1
        """
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """In-memory DB seeded with bug_regression + extension categories,
    CASES_ROOT pointed at a hermetic tmp_path so disk writes don't touch
    the repo's real cases/ tree."""
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, class_=Session
    )
    monkeypatch.setattr(sqlite_store, "_engine", engine, raising=False)
    monkeypatch.setattr(sqlite_store, "_SessionLocal", SessionLocal, raising=False)
    monkeypatch.setattr(sqlite_store, "init_engine", lambda url: None)

    with SessionLocal() as sess:
        sess.add(
            CaseCategory(
                name="bug_regression",
                display_name="BUG 回归",
                description=None,
                id_prefix="lg-bug-",
                dir_path="bug-regression",
                status_whitelist=json.dumps(["open", "fixed", "wontfix", "stub"]),
                default_status="open",
                display_order=10,
                is_active=True,
            )
        )
        sess.commit()

    monkeypatch.setenv("CASES_ROOT", str(tmp_path))
    # By default LBR_REPO_ROOT points at tmp_path so file_relative_to_repo_root
    # math doesn't refuse the write. Tests that need the real default unset it.
    monkeypatch.setenv("LBR_REPO_ROOT", str(tmp_path))

    # Reset the cache between tests — app.state persists across TestClient
    # invocations within a session.
    app.state.try_pass_cache.clear()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(engine)
    engine.dispose()


def _seed_cache(yaml_text: str, *, age: timedelta = timedelta(seconds=0)) -> str:
    """Compute the YAML's sha256 and seed app.state.try_pass_cache with a
    timestamp that is `age` old. Returns the hash so the test can assert
    against it."""
    h = hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()
    app.state.try_pass_cache[h] = datetime.now(UTC) - age
    return h


# ---------------------------------------------------------------------------
# _try_cache_is_fresh helper (unit) — the gate primitive
# ---------------------------------------------------------------------------


def test_cache_miss_is_not_fresh() -> None:
    cache: dict[str, datetime] = {}
    assert _try_cache_is_fresh(cache, "deadbeef") is False


def test_cache_recent_entry_is_fresh() -> None:
    cache = {"abc": datetime.now(UTC) - timedelta(minutes=5)}
    assert _try_cache_is_fresh(cache, "abc") is True


def test_cache_stale_entry_is_not_fresh() -> None:
    cache = {"abc": datetime.now(UTC) - timedelta(hours=2)}
    assert _try_cache_is_fresh(cache, "abc") is False


def test_cache_custom_max_age() -> None:
    cache = {"abc": datetime.now(UTC) - timedelta(minutes=10)}
    assert _try_cache_is_fresh(cache, "abc", max_age=timedelta(minutes=5)) is False
    assert _try_cache_is_fresh(cache, "abc", max_age=timedelta(minutes=15)) is True


def test_cache_naive_datetime_treated_as_utc() -> None:
    """Belt-and-suspenders: a misuser storing a naive datetime should still
    yield a sane (not crash) result. Not a documented API but worth covering
    so a future refactor doesn't quietly start raising TypeError."""
    cache = {"abc": datetime.utcnow() - timedelta(minutes=5)}  # naive
    assert _try_cache_is_fresh(cache, "abc") is True


# ---------------------------------------------------------------------------
# /cases/submit — three-gate enforcement
# ---------------------------------------------------------------------------


def test_submit_rejects_when_no_cache_entry(client: TestClient) -> None:
    """No prior Try → 400 with the three-gate message. No subprocess calls,
    no file written."""
    resp = client.post(
        "/cases/submit",
        json={
            "yaml": _minimal_valid_yaml(),
            "case_id": "lg-bug-9999-test-submit",
            "branch_name": "case/lg-bug-9999-test-submit",
        },
    )
    assert resp.status_code == 400
    assert "must Try and pass" in resp.json()["detail"]


def test_submit_rejects_when_cache_entry_is_stale(client: TestClient) -> None:
    """Cache entry > 1 hour old → same 400, same message."""
    yaml_text = _minimal_valid_yaml()
    _seed_cache(yaml_text, age=timedelta(hours=2))
    resp = client.post(
        "/cases/submit",
        json={
            "yaml": yaml_text,
            "case_id": "lg-bug-9999-test-submit",
            "branch_name": "case/lg-bug-9999-test-submit",
        },
    )
    assert resp.status_code == 400
    assert "must Try and pass" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# /cases/submit — re-validation (defense in depth)
# ---------------------------------------------------------------------------


def test_submit_rejects_invalid_yaml_even_with_cache_hit(client: TestClient) -> None:
    """A malformed YAML with a (cheat-seeded) cache hit must still 400.

    This is the §14 R26-style invariant: submit MUST re-run the same
    validation pipeline /cases/validate runs (`_validate_yaml_text`). A
    cache hit alone is not a green light to write garbage to disk.
    """
    bad_yaml = "foo: : :\n"  # syntax error
    _seed_cache(bad_yaml)
    resp = client.post(
        "/cases/submit",
        json={
            "yaml": bad_yaml,
            "case_id": "lg-bug-9999-test-submit",
            "branch_name": "case/lg-bug-9999-test-submit",
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert "errors" in detail
    assert len(detail["errors"]) >= 1
    assert detail["errors"][0]["where"] == "yaml_syntax"


# ---------------------------------------------------------------------------
# /cases/submit — DRY-RUN happy path (writes file, no subprocess)
# ---------------------------------------------------------------------------


def test_submit_dry_run_writes_file_and_skips_subprocess(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """LBR_GITHUB_DRY_RUN=1: write the YAML to CASES_ROOT/<dir>/<id>.yaml,
    return a fake PR (pr_number=0, url contains "dryrun"), and prove no
    subprocess.run was invoked."""
    monkeypatch.setenv("LBR_GITHUB_DRY_RUN", "1")

    # Spy on subprocess.run — any call from submit_case fails the test.
    called: list[tuple[Any, ...]] = []

    def _no_subprocess(*args: Any, **kwargs: Any) -> None:
        called.append((args, kwargs))
        raise AssertionError("subprocess.run must NOT be called in DRY_RUN mode")

    monkeypatch.setattr("app.api.cases.subprocess.run", _no_subprocess)

    yaml_text = _minimal_valid_yaml()
    _seed_cache(yaml_text)

    resp = client.post(
        "/cases/submit",
        json={
            "yaml": yaml_text,
            "case_id": "lg-bug-9999-test-submit",
            "branch_name": "case/lg-bug-9999-test-submit",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pr_number"] == 0
    assert "dryrun" in body["pr_url"]
    assert body["branch"] == "case/lg-bug-9999-test-submit"
    assert called == []

    # File on disk, content round-trips byte-for-byte.
    expected_file = tmp_path / "bug-regression" / "lg-bug-9999-test-submit.yaml"
    assert expected_file.is_file()
    assert expected_file.read_text(encoding="utf-8") == yaml_text


# ---------------------------------------------------------------------------
# /cases/submit — unknown category → 400
# ---------------------------------------------------------------------------


def test_submit_rejects_unknown_category(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Category not in active case_categories → 400 (no hardcoded list —
    DB drives the whitelist per §14 R4b)."""
    monkeypatch.setenv("LBR_GITHUB_DRY_RUN", "1")
    yaml_text = _minimal_valid_yaml().replace(
        "category: bug_regression", "category: not_a_real_category"
    )
    _seed_cache(yaml_text)
    resp = client.post(
        "/cases/submit",
        json={
            "yaml": yaml_text,
            "case_id": "lg-bug-9999-test-submit",
            "branch_name": "case/lg-bug-9999-test-submit",
        },
    )
    # The validation layer rejects unknown categories first (it checks the
    # whitelist) → 400 with errors[] detail. If validation accepts a
    # category the loader doesn't enumerate, the post-validation check
    # would catch it instead. Either is correct behavior; both surface 400.
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /cases/submit — LIVE happy path (mock subprocess, assert R27 cwd contract)
# ---------------------------------------------------------------------------


def test_submit_live_path_mocks_subprocess_and_asserts_cwd(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Without DRY_RUN, the endpoint must drive 6 subprocess calls
    (checkout / add / commit / push / gh pr create / gh pr merge), each
    with cwd=str(repo_root). This is the §14 R27 contract test."""
    # Make sure DRY_RUN is unset.
    monkeypatch.delenv("LBR_GITHUB_DRY_RUN", raising=False)

    # Pin repo_root to tmp_path so file_relative math succeeds.
    monkeypatch.setenv("LBR_REPO_ROOT", str(tmp_path))
    expected_repo_root = str(tmp_path)

    calls: list[dict[str, Any]] = []

    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"argv": argv, "cwd": kwargs.get("cwd"), "kwargs": kwargs})
        # gh pr create must emit a parseable URL on stdout.
        stdout = ""
        if argv[:3] == ["gh", "pr", "create"]:
            stdout = "https://github.com/foo/bar/pull/42\n"
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("app.api.cases.subprocess.run", _fake_run)

    yaml_text = _minimal_valid_yaml()
    _seed_cache(yaml_text)

    resp = client.post(
        "/cases/submit",
        json={
            "yaml": yaml_text,
            "case_id": "lg-bug-9999-test-submit",
            "branch_name": "case/lg-bug-9999-test-submit",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pr_number"] == 42
    assert body["pr_url"] == "https://github.com/foo/bar/pull/42"
    assert body["branch"] == "case/lg-bug-9999-test-submit"

    # §14 R27 contract: every subprocess call MUST carry explicit cwd=repo_root.
    assert len(calls) == 6, f"expected 6 subprocess calls, got {len(calls)}: {calls}"
    for call in calls:
        assert call["cwd"] == expected_repo_root, (
            f"R27 violation: subprocess call {call['argv']} had cwd={call['cwd']!r}, "
            f"expected {expected_repo_root!r}"
        )

    # Verify the call sequence in order.
    argvs = [c["argv"] for c in calls]
    assert argvs[0][:2] == ["git", "checkout"]
    assert argvs[0][2] == "-b"
    assert argvs[0][3] == "case/lg-bug-9999-test-submit"
    assert argvs[1][:2] == ["git", "add"]
    assert argvs[2][:2] == ["git", "commit"]
    assert argvs[3][:4] == ["git", "push", "-u", "origin"]
    assert argvs[4][:3] == ["gh", "pr", "create"]
    assert argvs[5][:3] == ["gh", "pr", "merge"]
    assert "42" in argvs[5]
    assert "--auto" in argvs[5]
    assert "--squash" in argvs[5]


# ---------------------------------------------------------------------------
# /cases/submit — subprocess failure → 500 with stderr surfaced
# ---------------------------------------------------------------------------


def test_submit_subprocess_failure_returns_500(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """If `git push` raises CalledProcessError, the endpoint must 500 with
    a detail that names the failing step AND echoes the stderr — silent
    failure (returning success on a broken push) would break the §6.2
    contract that submit either pushes a PR or visibly fails."""
    monkeypatch.delenv("LBR_GITHUB_DRY_RUN", raising=False)
    monkeypatch.setenv("LBR_REPO_ROOT", str(tmp_path))

    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[:2] == ["git", "push"]:
            raise subprocess.CalledProcessError(
                returncode=128,
                cmd=argv,
                stderr="fatal: unable to access remote: 401 unauthorized",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.api.cases.subprocess.run", _fake_run)

    yaml_text = _minimal_valid_yaml()
    _seed_cache(yaml_text)

    resp = client.post(
        "/cases/submit",
        json={
            "yaml": yaml_text,
            "case_id": "lg-bug-9999-test-submit",
            "branch_name": "case/lg-bug-9999-test-submit",
        },
    )
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "git push" in detail
    assert "401" in detail


# ---------------------------------------------------------------------------
# _resolve_repo_root helper — env override + default
# ---------------------------------------------------------------------------


def test_resolve_repo_root_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LBR_REPO_ROOT", "/tmp/some-repo-root-override")
    assert _resolve_repo_root() == Path("/tmp/some-repo-root-override").resolve()


def test_resolve_repo_root_default_anchored_on_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the env var, the default is __file__-anchored 4 parents up.
    Concretely that lands on the repo root which contains `backend/` +
    `design.md` — §14 R27 anchoring on __file__ guarantees this works
    regardless of uvicorn's startup cwd."""
    monkeypatch.delenv("LBR_REPO_ROOT", raising=False)
    root = _resolve_repo_root()
    assert (root / "backend").is_dir(), f"expected backend/ under repo_root {root}"
    assert (root / "design.md").is_file(), f"expected design.md under repo_root {root}"
