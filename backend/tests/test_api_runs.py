"""Tests for POST /runs, GET /runs, GET /runs/{id} (M1-10 / design.md §5.2 / §4.2).

Strategy: in-memory SQLite + monkeypatch `orchestrator.run_suite` to a
fast canned coroutine so the FastAPI BackgroundTask completes near-
instantly. We then poll the runs table until status flips to 'done'
(or timeout, indicating something is wrong with the wiring).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
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
from app.storage.models import Base, CaseCategory

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CASES_DIR = REPO_ROOT / "cases"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """In-memory DB + seeded categories + fake (fast) orchestrator."""
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
        sess.commit()

    # Point at the real cases dir so POST /runs has something to load.
    monkeypatch.setenv("CASES_ROOT", str(REAL_CASES_DIR))

    # Replace orchestrator.run_suite with a fast canned coroutine. We
    # patch the symbol the runs router actually called on
    # (`runs_api.orchestrator.run_suite`) so the test doesn't depend on
    # how the import was structured.
    captured: dict[str, Any] = {"calls": []}

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
        captured["calls"].append({"run_id": run_id, "n_cases": len(cases)})
        # Insert one fake case_result so GET /runs/{id} can verify the
        # nested array is wired.
        from app.storage.sqlite_store import insert_case_result

        with session_factory() as sess:
            insert_case_result(
                sess,
                run_id=run_id,
                case_id="lg-bug-fake-0001",
                status="pass",
                duration_ms=42,
            )
        return SuiteSummary(total=1, passed=1, failed=0, errored=0, skipped=0)

    monkeypatch.setattr(runs_api.orchestrator, "run_suite", fake_run_suite)

    with TestClient(app) as c:
        c.captured = captured  # type: ignore[attr-defined]
        yield c

    Base.metadata.drop_all(engine)
    engine.dispose()


def _wait_for_run_terminal(
    client: TestClient, run_id: int, timeout_s: float = 3.0
) -> dict[str, Any]:
    """Poll GET /runs/{id} until status != 'running' or timeout."""
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200
        last = resp.json()
        if last["status"] != "running":
            return last
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} stuck in 'running' after {timeout_s}s: {last}")


# ---------------------------------------------------------------------------
# POST /runs
# ---------------------------------------------------------------------------


def test_create_run_happy_path_returns_202_and_runs_in_background(
    client: TestClient,
) -> None:
    """POST with empty body should kick off the orchestrator, return 202
    with `run_id` + Location header, and the background task should flip
    status to 'done' shortly after."""
    resp = client.post("/runs", json={"triggered_by": "alice@example.com"})
    assert resp.status_code == 202
    body = resp.json()
    assert "run_id" in body
    assert body["status"] == "running"
    assert body["location"] == f"/runs/{body['run_id']}"
    assert resp.headers["Location"] == body["location"]

    final = _wait_for_run_terminal(client, body["run_id"])
    assert final["status"] == "done"
    assert final["total"] == 1
    assert final["passed"] == 1
    # nested case_results array populated by the fake orchestrator.
    assert any(cr["case_id"] == "lg-bug-fake-0001" for cr in final["case_results"])


def test_create_run_with_explicit_case_ids_filters_load(client: TestClient) -> None:
    """When `case_ids` is provided, only those files should be loaded
    from disk and passed to run_suite. We verify by inspecting the
    captured cases count from the fake orchestrator."""
    resp = client.post(
        "/runs",
        json={"case_ids": ["lg-bug-0001-hashjoin-right-table"]},
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    _wait_for_run_terminal(client, run_id)

    captured = client.captured["calls"]  # type: ignore[attr-defined]
    assert len(captured) == 1
    assert captured[0]["run_id"] == run_id
    assert captured[0]["n_cases"] == 1


def test_create_run_409_when_another_is_active(client: TestClient) -> None:
    """Second POST /runs while the first is still 'running' must yield
    409 with `active_run_id`. We seed a 'running' run directly via the
    storage layer (bypassing POST) so we don't have to fight a hung
    background task during teardown."""
    started = datetime.utcnow()
    with sqlite_store.get_session() as sess:
        first = sqlite_store.create_run(sess, started_at=started)
        first_id = first.id

    # Now the partial-unique index makes any second POST → ActiveRunExists
    # → 409.
    resp = client.post("/runs", json={})
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"] == "another run is already active"
    assert body["active_run_id"] == first_id


# ---------------------------------------------------------------------------
# GET /runs
# ---------------------------------------------------------------------------


def test_list_runs_empty_returns_empty_array(client: TestClient) -> None:
    resp = client.get("/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_runs_returns_recent_runs_newest_first(client: TestClient) -> None:
    """After two completed runs, GET /runs returns both with id desc."""
    # First run — create + wait for completion (the fake orchestrator is
    # fast, so finish_run flips status off 'running' before we POST again).
    r1 = client.post("/runs", json={})
    assert r1.status_code == 202
    id1 = r1.json()["run_id"]
    _wait_for_run_terminal(client, id1)

    r2 = client.post("/runs", json={})
    assert r2.status_code == 202
    id2 = r2.json()["run_id"]
    _wait_for_run_terminal(client, id2)

    resp = client.get("/runs")
    assert resp.status_code == 200
    body = resp.json()
    ids = [r["id"] for r in body]
    # Newest first.
    assert ids[0] > ids[1]
    assert set(ids) == {id1, id2}


# ---------------------------------------------------------------------------
# GET /runs/{id}
# ---------------------------------------------------------------------------


def test_get_run_404_on_unknown_id(client: TestClient) -> None:
    resp = client.get("/runs/99999")
    assert resp.status_code == 404


def test_get_run_returns_run_with_case_results_array(client: TestClient) -> None:
    """After a run completes, GET /runs/{id} must return the nested
    case_results array (populated by the fake orchestrator)."""
    r = client.post("/runs", json={})
    run_id = r.json()["run_id"]
    final = _wait_for_run_terminal(client, run_id)
    assert final["id"] == run_id
    assert isinstance(final["case_results"], list)
    assert len(final["case_results"]) >= 1
    assert final["case_results"][0]["case_id"] == "lg-bug-fake-0001"
    assert final["case_results"][0]["status"] == "pass"
    assert final["case_results"][0]["duration_ms"] == 42


# ---------------------------------------------------------------------------
# helper coverage
# ---------------------------------------------------------------------------


def test_jinja_context_and_dut_hosts_read_from_system_settings(
    client: TestClient,
) -> None:
    """If system_settings has jinja_context + dut_hosts entries, the
    background task should propagate them to run_suite. We assert by
    setting the rows and checking the orchestrator received them."""
    captured_ctx: dict[str, Any] = {}

    async def capture_run_suite(
        cases: list[dict[str, Any]], *, run_id: int, **kwargs: Any
    ) -> SuiteSummary:
        captured_ctx["jinja_context"] = kwargs.get("jinja_context")
        captured_ctx["dut_hosts"] = kwargs.get("dut_hosts")
        return SuiteSummary(total=0, passed=0, failed=0, errored=0, skipped=0)

    # monkeypatch directly on the runs_api binding
    import pytest as _pytest

    mp = _pytest.MonkeyPatch()
    mp.setattr(runs_api.orchestrator, "run_suite", capture_run_suite)

    try:
        with sqlite_store.get_session() as sess:
            sqlite_store.set_setting(sess, "jinja_context", {"target_version": "2.3.0"})
            sqlite_store.set_setting(sess, "dut_hosts", {"hosts": ["mdw", "sdw1"]})

        r = client.post("/runs", json={})
        run_id = r.json()["run_id"]
        _wait_for_run_terminal(client, run_id)
    finally:
        mp.undo()

    assert captured_ctx["jinja_context"] == {"target_version": "2.3.0"}
    assert captured_ctx["dut_hosts"] == {"mdw", "sdw1"}


def test_background_task_marks_run_aborted_on_unexpected_exception(
    client: TestClient,
) -> None:
    """If `run_suite` raises something the orchestrator doesn't fold (e.g.
    a programmer bug bubbles up), the background task must still flip
    the run row to status='aborted'."""
    import pytest as _pytest

    mp = _pytest.MonkeyPatch()

    async def boom(*args: Any, **kwargs: Any) -> SuiteSummary:
        raise RuntimeError("simulated orchestrator failure")

    mp.setattr(runs_api.orchestrator, "run_suite", boom)
    try:
        r = client.post("/runs", json={})
        run_id = r.json()["run_id"]
        final = _wait_for_run_terminal(client, run_id)
    finally:
        mp.undo()

    assert final["status"] == "aborted"
    assert final["finished_at"] is not None


def test_artifacts_root_respects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tiny direct test of the helper — guards against silent drift in
    where artifacts are written."""
    monkeypatch.setenv("ARTIFACTS_ROOT", "/tmp/x-artifacts")
    assert str(runs_api._artifacts_root()) == "/tmp/x-artifacts"
    monkeypatch.delenv("ARTIFACTS_ROOT", raising=False)
    assert str(runs_api._artifacts_root()) == "artifacts"


def test_load_cases_from_disk_skips_unreadable_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A YAML that is syntactically broken should be skipped (logged),
    not crash the background task."""
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

    cases_root = tmp_path / "cases"
    cat_dir = cases_root / "bug-regression"
    cat_dir.mkdir(parents=True)
    (cat_dir / "broken.yaml").write_text("id: x\n: [unclosed\n", encoding="utf-8")
    (cat_dir / "good.yaml").write_text("id: y\ntitle: ok\n", encoding="utf-8")

    monkeypatch.setenv("CASES_ROOT", str(cases_root))

    with SessionLocal() as sess:
        cats = [
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
        ]
        for c in cats:
            sess.add(c)
        sess.commit()
        # call the helper directly using the active session's categories
        from app.api.cases import _load_categories

        active_cats = _load_categories()

    loaded = runs_api._load_cases_from_disk(None, active_cats)
    # broken.yaml skipped; good.yaml loaded
    assert len(loaded) == 1
    assert loaded[0]["id"] == "y"

    engine.dispose()
