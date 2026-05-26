"""Tests for backend tz-aware UTC datetime contract.

Background (dogfood 2026-05-26): a just-triggered run showed "8h ago" on a
UTC+8 client because backend wrote `datetime.utcnow()` (naive) to SQLite,
SQLAlchemy round-trip dropped tzinfo even when written tz-aware, and
Pydantic v2 serialized the naive datetime without a tz suffix. Frontend
shims (PR #168 formatRelative, PR #169 RunProgressBar ETA) treated naive
ISO as UTC via regex — works but accumulates as tech debt.

This suite is the canonical backend root fix:

  Layer A — every write is tz-aware UTC: assert by reading after a write,
            confirming the datetime is unambiguous (the API response carries
            the tz suffix).

  Layer B — `as_utc` helper re-attaches UTC tzinfo at storage→response
            boundary. Unit-tested directly here for None / naive / aware
            cases.

  Layer C — API contract: GET /runs/{id} and GET /admin/target-versions
            both serialize datetime fields with explicit `+00:00` suffix.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import runs as runs_api
from app.main import app
from app.runner.orchestrator import SuiteSummary
from app.storage import sqlite_store
from app.storage.models import Base, CaseCategory, TargetVersion
from app.utils.time import as_utc

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CASES_DIR = REPO_ROOT / "cases"


# ---------------------------------------------------------------------------
# Layer B — `as_utc` unit tests
# ---------------------------------------------------------------------------


def test_as_utc_none_passthrough() -> None:
    """None in → None out (preserves the optional-field convention)."""
    assert as_utc(None) is None


def test_as_utc_naive_gets_utc_tzinfo_attached() -> None:
    """Naive datetime is treated as UTC (matches our write policy: every
    write goes through datetime.now(UTC), so any naive datetime read from
    DB is UTC)."""
    naive = datetime(2026, 5, 26, 3, 47, 11, 314501)
    assert naive.tzinfo is None  # sanity
    out = as_utc(naive)
    assert out is not None
    assert out.tzinfo is UTC
    # Wall-clock components preserved — we only attach tzinfo, never shift.
    assert out.year == 2026
    assert out.month == 5
    assert out.day == 26
    assert out.hour == 3
    assert out.minute == 47
    assert out.second == 11
    assert out.microsecond == 314501


def test_as_utc_aware_pass_through_unchanged() -> None:
    """Already-aware datetime is idempotent — safe to call twice in a chain."""
    aware = datetime(2026, 5, 26, 3, 47, 11, tzinfo=UTC)
    out = as_utc(aware)
    assert out is aware  # same object; no copy needed


def test_as_utc_isoformat_emits_offset_suffix() -> None:
    """End-to-end: isoformat() on the result MUST carry `+00:00`. This is
    what Pydantic v2 emits for tz-aware datetime fields, and what frontend
    relies on to disambiguate."""
    naive = datetime(2026, 5, 26, 3, 47, 11)
    out = as_utc(naive)
    assert out is not None
    iso = out.isoformat()
    assert iso.endswith("+00:00"), f"expected +00:00 suffix, got {iso!r}"


# ---------------------------------------------------------------------------
# Shared fixture: in-memory DB + seeded admin + fast fake orchestrator
# (mirrors test_api_runs / test_admin_target_versions fixtures).
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.api.auth import seed_admin_if_missing

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
                display_name="BUG",
                description=None,
                id_prefix="lg-bug-",
                dir_path="bug-regression",
                status_whitelist=json.dumps(["open"]),
                default_status="open",
                display_order=10,
                is_active=True,
            )
        )
        sess.add(
            TargetVersion(
                name="SynxDB-4.5.0-build130",
                display_order=100,
                is_active=True,
                is_default=True,
            )
        )
        sess.commit()

    monkeypatch.setenv("CASES_ROOT", str(REAL_CASES_DIR))

    async def fake_run_suite(
        cases: list[dict[str, Any]],
        *,
        run_id: int,
        artifacts_root: Path,
        jinja_context: dict[str, Any],
        dut_hosts: set[str],
        session_factory: Any,
        sql_pool: Any = None,
        server_log_path: str | None = None,
        skip_list: list[dict[str, Any]] | None = None,
        insert_case_result_fn: Any = None,
    ) -> SuiteSummary:
        return SuiteSummary(total=0, passed=0, failed=0, errored=0, skipped=0)

    monkeypatch.setattr(runs_api.orchestrator, "run_suite", fake_run_suite)

    seed_admin_if_missing()

    with TestClient(app) as c:
        login = c.post("/auth/login", json={"username": "admin", "password": "admin"})
        assert login.status_code == 200
        token = login.json()["token"]
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c

    Base.metadata.drop_all(engine)
    engine.dispose()


def _wait_for_run_terminal(
    client: TestClient, run_id: int, timeout_s: float = 3.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200
        last = resp.json()
        if last["status"] != "running":
            return last
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} stuck running after {timeout_s}s: {last}")


# ---------------------------------------------------------------------------
# Layer C — API contract: datetime fields serialize with `+00:00` suffix
# ---------------------------------------------------------------------------


def _assert_iso_tz_aware(value: str, field_name: str) -> None:
    """Assert the ISO string carries an explicit tz suffix (+00:00 or Z).

    Without this, browsers parse the string as local time and clocks skew
    by the client's offset (UTC+8 -> "8h ago" for a just-finished run).
    """
    assert isinstance(value, str), f"{field_name} not a string: {value!r}"
    # Pydantic v2 emits `+00:00` for tz-aware UTC datetimes; we don't accept
    # bare ISO without tz info (that's the regression class this PR fixes).
    has_offset = value.endswith("+00:00") or value.endswith("Z") or "+" in value[10:]
    assert has_offset, (
        f"{field_name} must carry an explicit tz suffix, got {value!r}; "
        "naive ISO is the regression class this PR fixes"
    )


def test_get_runs_serializes_started_at_tz_aware(client: TestClient) -> None:
    """GET /runs returns started_at with `+00:00` (regression: was bare ISO)."""
    resp = client.post("/runs", json={})
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    _wait_for_run_terminal(client, run_id)

    rows = client.get("/runs").json()
    assert len(rows) >= 1
    row = next(r for r in rows if r["id"] == run_id)
    _assert_iso_tz_aware(row["started_at"], "/runs[].started_at")
    if row.get("finished_at"):
        _assert_iso_tz_aware(row["finished_at"], "/runs[].finished_at")


def test_get_run_detail_serializes_datetimes_tz_aware(client: TestClient) -> None:
    """GET /runs/{id} returns started_at + finished_at both tz-aware."""
    resp = client.post("/runs", json={})
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    final = _wait_for_run_terminal(client, run_id)

    _assert_iso_tz_aware(final["started_at"], "/runs/{id}.started_at")
    _assert_iso_tz_aware(final["finished_at"], "/runs/{id}.finished_at")


def test_post_runs_response_started_at_tz_aware(client: TestClient) -> None:
    """POST /runs response's `started_at` field is tz-aware (the value is
    minted in-process, never round-tripped through SQLite — so this guards
    against regressing the Layer A migration `utcnow → now(UTC)`)."""
    resp = client.post("/runs", json={})
    assert resp.status_code == 202
    body = resp.json()
    _assert_iso_tz_aware(body["started_at"], "POST /runs.started_at")


def test_admin_target_versions_created_at_tz_aware(client: TestClient) -> None:
    """GET /admin/target-versions returns created_at with explicit tz suffix.

    `created_at` is set by the SQLAlchemy column default (UTC via
    `datetime.now(UTC)` in the model) and round-tripped through SQLite —
    this is exactly the path that drops tzinfo without `as_utc()`.
    """
    rows = client.get("/admin/target-versions").json()
    assert len(rows) >= 1
    _assert_iso_tz_aware(rows[0]["created_at"], "/admin/target-versions[].created_at")


# ---------------------------------------------------------------------------
# Layer A regression guard — confirm no datetime.utcnow callsite remains
# ---------------------------------------------------------------------------


def test_no_datetime_utcnow_in_app_source() -> None:
    """Guard against accidental reintroduction. `datetime.utcnow()` is
    deprecated in Python 3.12 and is the root cause of the naive-ISO
    regression class fixed by this PR."""
    app_root = Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []
    for py in app_root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "datetime.utcnow(" in text:
            offenders.append(str(py.relative_to(app_root)))
    assert not offenders, f"datetime.utcnow() found in: {offenders}; use datetime.now(UTC) instead"
