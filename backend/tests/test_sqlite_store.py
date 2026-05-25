"""Tests for app.storage.sqlite_store (M1-3).

Strategy: each test gets a fresh in-memory SQLite (`sqlite:///:memory:`)
and creates the schema via `Base.metadata.create_all(engine)`. We don't
shell out to alembic in unit tests (the alembic round-trip is already
covered by `test_alembic_upgrade.py`); we *do* assert that the metadata
produces the same partial-unique index behaviour, so any future drift
between models and migration trips a test.

NOTE: in-memory SQLite engines are per-connection. We pin a single
StaticPool connection on the engine so `init_engine` + the contextmanager
share the same in-memory DB across calls within a test.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.storage import sqlite_store
from app.storage.models import Base, CaseSkipList


@pytest.fixture(autouse=True)
def fresh_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module-level engine/SessionLocal between tests + create schema
    on a shared in-memory DB."""
    # Build the engine ourselves (StaticPool keeps a single in-memory
    # connection alive so multiple sessions see the same data).
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    # Wire it into the module instead of calling init_engine (which would
    # build a fresh, separate engine that doesn't share the in-memory DB).
    from sqlalchemy.orm import Session, sessionmaker

    monkeypatch.setattr(sqlite_store, "_engine", engine, raising=False)
    monkeypatch.setattr(
        sqlite_store,
        "_SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session),
        raising=False,
    )
    yield
    Base.metadata.drop_all(engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# init_engine + get_session
# ---------------------------------------------------------------------------


def test_init_engine_is_required_before_get_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """If init_engine was never called, get_session must raise a clear error."""
    monkeypatch.setattr(sqlite_store, "_engine", None, raising=False)
    monkeypatch.setattr(sqlite_store, "_SessionLocal", None, raising=False)
    with pytest.raises(RuntimeError, match="not initialized"):
        with sqlite_store.get_session():
            pass


def test_init_engine_creates_tables_when_run_against_real_file(tmp_path) -> None:
    """init_engine itself doesn't run migrations; the dispatch contract is
    'call init once at startup'. We just sanity-check the engine works
    against a real SQLite file and that calling init_engine twice is
    idempotent (doesn't raise)."""
    db = tmp_path / "x.db"
    url = f"sqlite:///{db}"
    sqlite_store.init_engine(url)
    sqlite_store.init_engine(url)  # idempotent — should not raise
    assert sqlite_store._engine is not None


def test_get_session_commits_on_clean_exit() -> None:
    started = datetime(2026, 5, 1, 10, 0, 0)
    with sqlite_store.get_session() as sess:
        sqlite_store.create_run(sess, started_at=started, triggered_by="alice@example.com")

    # New session — the previous commit must be visible.
    with sqlite_store.get_session() as sess:
        runs = sqlite_store.list_runs(sess)
        assert len(runs) == 1
        assert runs[0].triggered_by == "alice@example.com"


def test_get_session_rolls_back_on_exception() -> None:
    started = datetime(2026, 5, 1, 10, 0, 0)

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with sqlite_store.get_session() as sess:
            sqlite_store.create_run(sess, started_at=started)
            raise Boom("kaboom")

    # The insert above must have been rolled back.
    with sqlite_store.get_session() as sess:
        assert sqlite_store.list_runs(sess) == []


# ---------------------------------------------------------------------------
# runs CRUD
# ---------------------------------------------------------------------------


def test_create_run_and_get_run_round_trip() -> None:
    started = datetime(2026, 5, 1, 10, 0, 0)
    with sqlite_store.get_session() as sess:
        run = sqlite_store.create_run(
            sess,
            started_at=started,
            triggered_by="alice@example.com",
            target_version="1.6.3",
        )
        run_id = run.id

    with sqlite_store.get_session() as sess:
        fetched = sqlite_store.get_run(sess, run_id)
        assert fetched is not None
        assert fetched.id == run_id
        assert fetched.status == "running"
        assert fetched.triggered_by == "alice@example.com"
        assert fetched.target_version == "1.6.3"
        assert fetched.started_at == started
        assert fetched.finished_at is None


def test_get_run_returns_none_for_missing_id() -> None:
    with sqlite_store.get_session() as sess:
        assert sqlite_store.get_run(sess, 99999) is None


def test_second_running_run_raises_active_run_exists() -> None:
    started = datetime(2026, 5, 1, 10, 0, 0)
    with sqlite_store.get_session() as sess:
        sqlite_store.create_run(sess, started_at=started)

    # Second create_run while the first is still 'running' must fail with
    # the typed exception (NOT a raw IntegrityError leaking out).
    with pytest.raises(sqlite_store.ActiveRunExists):
        with sqlite_store.get_session() as sess:
            sqlite_store.create_run(sess, started_at=started + timedelta(seconds=1))

    # And nothing was persisted by the failed call.
    with sqlite_store.get_session() as sess:
        assert len(sqlite_store.list_runs(sess)) == 1


def test_finish_run_then_create_again_succeeds() -> None:
    """After the first run is marked 'done', the partial-unique index
    no longer constrains a fresh 'running' insert."""
    started = datetime(2026, 5, 1, 10, 0, 0)
    with sqlite_store.get_session() as sess:
        first = sqlite_store.create_run(sess, started_at=started)
        first_id = first.id

    with sqlite_store.get_session() as sess:
        sqlite_store.finish_run(
            sess,
            first_id,
            status="done",
            finished_at=started + timedelta(minutes=5),
            total=3,
            passed=2,
            failed=1,
            skipped=0,
        )

    with sqlite_store.get_session() as sess:
        # Must succeed — no ActiveRunExists.
        sqlite_store.create_run(sess, started_at=started + timedelta(hours=1))

    with sqlite_store.get_session() as sess:
        runs = sqlite_store.list_runs(sess)
        assert len(runs) == 2
        statuses = {r.status for r in runs}
        assert statuses == {"done", "running"}
        finished = next(r for r in runs if r.status == "done")
        assert finished.total == 3
        assert finished.passed == 2
        assert finished.failed == 1


def test_finish_run_with_unknown_id_raises_value_error() -> None:
    with sqlite_store.get_session() as sess:
        with pytest.raises(ValueError, match="not found"):
            sqlite_store.finish_run(sess, 12345, status="done", finished_at=datetime(2026, 5, 1))


def test_finish_run_persists_errored_count() -> None:
    """alembic 0005: finish_run accepts `errored=` kwarg and stores it
    on the runs row. Without this column the error verdict was invisible
    at the run-summary level (dogfood 2026-05-26 run #25)."""
    started = datetime(2026, 5, 1, 10, 0, 0)
    with sqlite_store.get_session() as sess:
        run = sqlite_store.create_run(sess, started_at=started)
        run_id = run.id

    with sqlite_store.get_session() as sess:
        sqlite_store.finish_run(
            sess,
            run_id,
            status="done",
            finished_at=started + timedelta(minutes=1),
            total=4,
            passed=2,
            failed=0,
            skipped=1,
            errored=1,
        )

    with sqlite_store.get_session() as sess:
        row = sqlite_store.get_run(sess, run_id)
        assert row is not None
        assert row.total == 4
        assert row.passed == 2
        assert row.failed == 0
        assert row.skipped == 1
        assert row.errored == 1


def test_finish_run_without_errored_leaves_column_null() -> None:
    """Backwards-compat: callers that omit `errored=` (legacy callers,
    pre-0005 codepaths kept around for safety) leave the column NULL,
    matching the same convention as passed/failed/skipped."""
    started = datetime(2026, 5, 1, 10, 0, 0)
    with sqlite_store.get_session() as sess:
        run = sqlite_store.create_run(sess, started_at=started)
        run_id = run.id

    with sqlite_store.get_session() as sess:
        # No errored= kwarg
        sqlite_store.finish_run(
            sess,
            run_id,
            status="done",
            finished_at=started + timedelta(minutes=1),
            total=1,
            passed=1,
            failed=0,
            skipped=0,
        )

    with sqlite_store.get_session() as sess:
        row = sqlite_store.get_run(sess, run_id)
        assert row is not None
        assert row.errored is None


def test_list_runs_orders_newest_first_and_respects_limit() -> None:
    """list_runs must return id-desc order so the UI can show recent runs
    first, and must respect the `limit` kwarg."""
    started = datetime(2026, 5, 1, 10, 0, 0)
    # Insert 3 runs, finishing each before creating the next (otherwise
    # uniq_runs_running blocks us).
    with sqlite_store.get_session() as sess:
        a = sqlite_store.create_run(sess, started_at=started)
        sqlite_store.finish_run(sess, a.id, status="done", finished_at=started)
        b = sqlite_store.create_run(sess, started_at=started + timedelta(seconds=1))
        sqlite_store.finish_run(
            sess, b.id, status="done", finished_at=started + timedelta(seconds=2)
        )
        sqlite_store.create_run(sess, started_at=started + timedelta(seconds=3))

    with sqlite_store.get_session() as sess:
        runs = sqlite_store.list_runs(sess, limit=2)
        assert len(runs) == 2
        assert runs[0].id > runs[1].id


# ---------------------------------------------------------------------------
# case_results
# ---------------------------------------------------------------------------


def test_insert_case_result_and_list_round_trip() -> None:
    started = datetime(2026, 5, 1, 10, 0, 0)
    with sqlite_store.get_session() as sess:
        run = sqlite_store.create_run(sess, started_at=started)
        run_id = run.id

    with sqlite_store.get_session() as sess:
        sqlite_store.insert_case_result(
            sess,
            run_id=run_id,
            case_id="lg-bug-0001",
            status="pass",
            duration_ms=1234,
            stdout="hello",
            stderr=None,
            artifacts_path="/tmp/artifacts/1/lg-bug-0001",
        )
        sqlite_store.insert_case_result(
            sess,
            run_id=run_id,
            case_id="lg-bug-0002",
            status="fail",
            duration_ms=2000,
            expect_detail="step 2: scalar_eq expected 1 got 0",
        )

    with sqlite_store.get_session() as sess:
        rows = sqlite_store.list_case_results(sess, run_id)
        assert len(rows) == 2
        assert rows[0].case_id == "lg-bug-0001"
        assert rows[0].status == "pass"
        assert rows[0].duration_ms == 1234
        assert rows[0].artifacts_path == "/tmp/artifacts/1/lg-bug-0001"
        assert rows[1].case_id == "lg-bug-0002"
        assert rows[1].status == "fail"
        assert rows[1].expect_detail == "step 2: scalar_eq expected 1 got 0"


def test_list_case_results_filters_by_run_id() -> None:
    """Results from other runs must not leak into list_case_results."""
    started = datetime(2026, 5, 1, 10, 0, 0)
    with sqlite_store.get_session() as sess:
        run_a = sqlite_store.create_run(sess, started_at=started)
        sqlite_store.finish_run(sess, run_a.id, status="done", finished_at=started)
        run_b = sqlite_store.create_run(sess, started_at=started + timedelta(seconds=1))
        sqlite_store.insert_case_result(sess, run_id=run_a.id, case_id="c-A", status="pass")
        sqlite_store.insert_case_result(sess, run_id=run_b.id, case_id="c-B", status="pass")
        ra_id, rb_id = run_a.id, run_b.id

    with sqlite_store.get_session() as sess:
        assert [r.case_id for r in sqlite_store.list_case_results(sess, ra_id)] == ["c-A"]
        assert [r.case_id for r in sqlite_store.list_case_results(sess, rb_id)] == ["c-B"]


# ---------------------------------------------------------------------------
# case_skip_list
# ---------------------------------------------------------------------------


def test_get_skip_list_returns_inserted_rows() -> None:
    """We don't have a public create helper for skip-list rows in M1-3 (the
    admin UI / API is M1-10+); cover the read path by inserting via raw
    ORM and confirming get_skip_list returns them in id order."""
    with sqlite_store.get_session() as sess:
        sess.add(
            CaseSkipList(
                case_id="lg-bug-0099",
                reason="upstream bug not fixed; tracked LG-1234",
                upstream_issue="https://issues.example.com/LG-1234",
                created_by="ops@example.com",
            )
        )
        sess.add(
            CaseSkipList(
                case_id="lg-ext-0050",
                reason="extension stub; revisit Q3",
                created_by="ops@example.com",
            )
        )

    with sqlite_store.get_session() as sess:
        rows = sqlite_store.get_skip_list(sess)
        assert [r.case_id for r in rows] == ["lg-bug-0099", "lg-ext-0050"]
        assert rows[0].reason.startswith("upstream bug")
        # server_default CURRENT_TIMESTAMP populated created_at.
        assert rows[0].created_at is not None


# ---------------------------------------------------------------------------
# system_settings
# ---------------------------------------------------------------------------


def test_get_setting_returns_none_for_missing_key() -> None:
    with sqlite_store.get_session() as sess:
        assert sqlite_store.get_setting(sess, "nonexistent") is None


def test_set_setting_then_get_setting_round_trip() -> None:
    with sqlite_store.get_session() as sess:
        sqlite_store.set_setting(
            sess,
            "default_log_path",
            {"path": "/var/log/lightning"},
        )

    with sqlite_store.get_session() as sess:
        assert sqlite_store.get_setting(sess, "default_log_path") == {"path": "/var/log/lightning"}


def test_set_setting_upsert_overwrites_existing_row() -> None:
    """Calling set_setting twice on the same key must update the existing
    row, not raise PK collision, and the new value must replace the old."""
    with sqlite_store.get_session() as sess:
        sqlite_store.set_setting(sess, "claude_api_model", {"name": "opus-4"})
    with sqlite_store.get_session() as sess:
        sqlite_store.set_setting(sess, "claude_api_model", {"name": "opus-4.7"})

    with sqlite_store.get_session() as sess:
        val = sqlite_store.get_setting(sess, "claude_api_model")
        assert val == {"name": "opus-4.7"}

        # Exactly one row exists for the key.
        rows = sess.execute(
            text("SELECT COUNT(*) FROM system_settings WHERE key = :k"),
            {"k": "claude_api_model"},
        ).scalar_one()
        assert rows == 1


# ---------------------------------------------------------------------------
# schema parity guard: models vs alembic migration
# ---------------------------------------------------------------------------


def test_metadata_create_all_enforces_uniq_runs_running() -> None:
    """The whole point of declaring `uniq_runs_running` on the Run model
    is so test-time `Base.metadata.create_all(engine)` produces the same
    constraint behaviour as `alembic upgrade head`. If this test ever
    fails, the models drifted from the migration."""
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    idx_names = {idx["name"] for idx in insp.get_indexes("runs")}
    assert "uniq_runs_running" in idx_names

    # And it actually enforces the partial-unique semantics.
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO runs (started_at, status) VALUES (CURRENT_TIMESTAMP, 'running')")
        )
    with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                text("INSERT INTO runs (started_at, status) VALUES (CURRENT_TIMESTAMP, 'running')")
            )
    # Multiple non-running rows are fine.
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO runs (started_at, status) VALUES (CURRENT_TIMESTAMP, 'done')")
        )
        conn.execute(
            text("INSERT INTO runs (started_at, status) VALUES (CURRENT_TIMESTAMP, 'aborted')")
        )
    engine.dispose()
