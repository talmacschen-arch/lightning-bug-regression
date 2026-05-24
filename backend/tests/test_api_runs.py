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


# ---------------------------------------------------------------------------
# M6-1 SSE stream — GET /runs/{run_id}/stream
# ---------------------------------------------------------------------------


def _parse_sse(body: str) -> list[dict[str, Any]]:
    """Parse SSE body into list of JSON-decoded events. Ignores comments."""
    events: list[dict[str, Any]] = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk or chunk.startswith(":"):
            continue
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


def test_stream_404_for_unknown_run(client: TestClient) -> None:
    """Streaming an unknown run emits a synthetic `error` event then closes."""
    resp = client.get("/runs/999999/stream")
    assert resp.status_code == 200  # SSE always 200 even on logical error
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "not found" in events[0]["message"]


def test_stream_emits_snapshot_plus_synthetic_terminal_for_finished_run(
    client: TestClient,
) -> None:
    """Subscriber arriving after run already done sees snapshot + synthetic
    run_done so it knows to stop and refetch final state."""
    resp = client.post("/runs", json={"triggered_by": "alice@example.com"})
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    _wait_for_run_terminal(client, run_id)

    sse = client.get(f"/runs/{run_id}/stream")
    assert sse.status_code == 200
    events = _parse_sse(sse.text)
    types = [e["type"] for e in events]
    assert types[0] == "snapshot"
    assert events[0]["status"] == "done"
    assert events[0]["total"] == 1
    assert types[-1] == "run_done"
    assert events[-1].get("synthetic") is True


def test_stream_sets_anti_buffer_headers(client: TestClient) -> None:
    resp = client.post("/runs", json={"triggered_by": "x"})
    run_id = resp.json()["run_id"]
    _wait_for_run_terminal(client, run_id)
    sse = client.get(f"/runs/{run_id}/stream")
    assert sse.headers["cache-control"] == "no-cache"
    assert sse.headers["x-accel-buffering"] == "no"


# ---------------------------------------------------------------------------
# M6-2 artifacts list + download
# ---------------------------------------------------------------------------


def _seed_run_with_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, str, Path]:
    """Create a run + case_result + artifacts dir on disk.

    Returns (run_id, case_id, artifacts_dir).
    """
    started = datetime.utcnow()
    case_id = "lg-bug-fake-art-0001"
    artifacts_dir = tmp_path / "1" / case_id
    artifacts_dir.mkdir(parents=True)
    # Realistic per-step layout written by orchestrator
    (artifacts_dir / "step-00-setup-create-table.stdout.txt").write_text("CREATE TABLE\n")
    (artifacts_dir / "step-00-setup-create-table.stderr.txt").write_text("")
    (artifacts_dir / "step-01-select-rows.stdout.txt").write_text(" id\n----\n  1\n  2\n")
    # other-format file (not matching pattern)
    (artifacts_dir / "summary.json").write_text('{"ok": true}')

    with sqlite_store.get_session() as sess:
        run = sqlite_store.create_run(sess, started_at=started)
        run_id = run.id
        sqlite_store.finish_run(
            sess,
            run_id,
            status="done",
            finished_at=datetime.utcnow(),
            total=1,
            passed=1,
            failed=0,
            skipped=0,
        )
        sqlite_store.insert_case_result(
            sess,
            run_id=run_id,
            case_id=case_id,
            status="pass",
            duration_ms=100,
            artifacts_path=str(artifacts_dir),
        )
    return run_id, case_id, artifacts_dir


def test_list_artifacts_returns_classified_files(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, case_id, _ = _seed_run_with_artifacts(tmp_path, monkeypatch)
    resp = client.get(f"/runs/{run_id}/cases/{case_id}/artifacts")
    assert resp.status_code == 200
    items = resp.json()
    by_name = {it["filename"]: it for it in items}
    assert "step-00-setup-create-table.stdout.txt" in by_name
    assert by_name["step-00-setup-create-table.stdout.txt"]["kind"] == "stdout"
    assert by_name["step-00-setup-create-table.stdout.txt"]["step_idx"] == 0
    assert by_name["step-00-setup-create-table.stdout.txt"]["step_id"] == "setup-create-table"
    assert by_name["step-01-select-rows.stdout.txt"]["step_idx"] == 1
    # other-format files still appear, classified as 'other'
    assert by_name["summary.json"]["kind"] == "other"
    assert by_name["summary.json"]["step_idx"] is None


def test_list_artifacts_404_for_unknown_run(client: TestClient) -> None:
    resp = client.get("/runs/999999/cases/x/artifacts")
    assert resp.status_code == 404


def test_list_artifacts_404_for_unknown_case(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, _case_id, _ = _seed_run_with_artifacts(tmp_path, monkeypatch)
    resp = client.get(f"/runs/{run_id}/cases/nope/artifacts")
    assert resp.status_code == 404


def test_download_artifact_returns_file(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, case_id, _ = _seed_run_with_artifacts(tmp_path, monkeypatch)
    resp = client.get(f"/runs/{run_id}/cases/{case_id}/artifacts/step-01-select-rows.stdout.txt")
    assert resp.status_code == 200
    assert resp.text == " id\n----\n  1\n  2\n"
    assert "attachment" in resp.headers["content-disposition"]
    assert "step-01-select-rows.stdout.txt" in resp.headers["content-disposition"]


def test_download_artifact_rejects_path_traversal(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, case_id, artifacts_dir = _seed_run_with_artifacts(tmp_path, monkeypatch)
    # Make a sensitive file outside the artifacts dir
    outside = artifacts_dir.parent.parent / "secret.txt"
    outside.write_text("PWNED")

    # 1. literal `..` in URL path is normalized by URL parser, but
    #    we still pass through validate logic.
    resp = client.get(f"/runs/{run_id}/cases/{case_id}/artifacts/..%2Fsecret.txt")
    # Either 400 (validation) or 404 (file not present in this dir).
    assert resp.status_code in (400, 404)

    # 2. /-containing filenames blocked at validate layer
    # Use httpx raw request to bypass URL normalization (pass embedded ..).
    # Easier: monkey-patched name with separator → backend must reject.
    # FastAPI path param doesn't accept `/` so the route won't match;
    # but `\\` should be rejected by our validator.
    resp = client.get(f"/runs/{run_id}/cases/{case_id}/artifacts/..%5Csecret.txt")
    assert resp.status_code in (400, 404)


def test_download_artifact_404_for_missing_file(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, case_id, _ = _seed_run_with_artifacts(tmp_path, monkeypatch)
    resp = client.get(f"/runs/{run_id}/cases/{case_id}/artifacts/no-such.txt")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# M6-5 external_deps runtime injection
# ---------------------------------------------------------------------------


def test_execute_run_injects_external_context_from_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ensure _execute_run loads external/<svc>.yml for each svc in
    union(case.external_deps) and merges under jinja_context['external'].

    We don't need to actually run a case end-to-end — just verify the
    orchestrator receives a jinja_context with the right shape.
    """
    # Set up external/ dir
    ext_dir = tmp_path / "external"
    ext_dir.mkdir()
    (ext_dir / "elasticsearch.yml").write_text("host: 10.0.0.5\nport: 9200\n", encoding="utf-8")
    monkeypatch.setenv("EXTERNAL_DEPS_DIR", str(ext_dir))

    # Spy on orchestrator.run_suite
    from app.api import runs as runs_api
    from app.runner.orchestrator import SuiteSummary

    captured: dict[str, Any] = {}

    async def fake_run_suite(cases, *, jinja_context, **kwargs):
        captured["jinja_context"] = jinja_context
        return SuiteSummary(total=0, passed=0, failed=0, errored=0, skipped=0)

    monkeypatch.setattr(runs_api.orchestrator, "run_suite", fake_run_suite)

    # Call _execute_run directly with a case that declares external_deps
    cases = [
        {"id": "lg-xs-test", "external_deps": ["elasticsearch"]},
    ]
    import asyncio

    # _execute_run needs a real DB session because it calls finish_run +
    # publishes; reuse the client fixture's setup pattern.
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

    with SessionLocal() as sess:
        run = sqlite_store.create_run(sess, started_at=datetime.utcnow())
        run_id = run.id

    asyncio.run(
        runs_api._execute_run(
            run_id=run_id,
            cases=cases,
            artifacts_root=tmp_path / "artifacts",
            jinja_context={"coordinator": {"host": "syn0001"}},
            dut_hosts=set(),
        )
    )

    jc = captured["jinja_context"]
    # original coordinator key preserved
    assert jc["coordinator"]["host"] == "syn0001"
    # external block injected
    assert "external" in jc
    assert jc["external"]["elasticsearch"]["host"] == "10.0.0.5"
    assert jc["external"]["elasticsearch"]["port"] == 9200

    engine.dispose()


def test_execute_run_external_override_via_user_context_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If system_settings.jinja_context already provides external.<svc>,
    user-supplied values should override the file-loaded defaults so a
    dev can hot-patch a target host without editing external/<svc>.yml."""
    ext_dir = tmp_path / "external"
    ext_dir.mkdir()
    (ext_dir / "es.yml").write_text("host: from-file\n", encoding="utf-8")
    monkeypatch.setenv("EXTERNAL_DEPS_DIR", str(ext_dir))

    from app.api import runs as runs_api
    from app.runner.orchestrator import SuiteSummary

    captured: dict[str, Any] = {}

    async def fake_run_suite(cases, *, jinja_context, **kwargs):
        captured["jinja_context"] = jinja_context
        return SuiteSummary(total=0, passed=0, failed=0, errored=0, skipped=0)

    monkeypatch.setattr(runs_api.orchestrator, "run_suite", fake_run_suite)

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

    with SessionLocal() as sess:
        run = sqlite_store.create_run(sess, started_at=datetime.utcnow())
        run_id = run.id

    import asyncio

    asyncio.run(
        runs_api._execute_run(
            run_id=run_id,
            cases=[{"id": "x", "external_deps": ["es"]}],
            artifacts_root=tmp_path / "artifacts",
            jinja_context={
                "external": {"es": {"host": "user-override"}},
            },
            dut_hosts=set(),
        )
    )
    assert captured["jinja_context"]["external"]["es"]["host"] == "user-override"
    engine.dispose()
