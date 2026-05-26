"""Test that `alembic upgrade head` produces the expected schema + seed.

Each test runs a fresh `alembic upgrade head` against a tmp SQLite file. We
verify:

  * all 5 business tables + alembic_version exist
  * uniq_runs_running enforces "at most one row with status='running'"
  * case_results.run_id FK declares runs(id)
  * case_categories is seeded with bug_regression + extension
  * status_whitelist values are valid JSON arrays
  * downgrade() is reversible
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run_alembic(cwd: Path, args: list[str], env_extra: dict[str, str]) -> None:
    # Invoke via `python -m alembic` so we don't depend on the alembic console
    # script being on PATH inside the test subprocess (the venv bin/ usually
    # isn't on PATH unless the venv is activated).
    env = {**os.environ, **env_extra}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def fresh_db_url(tmp_path: Path) -> str:
    """Upgrade an empty SQLite file to head; return its URL."""
    db_file = tmp_path / "test.db"
    url = f"sqlite:///{db_file}"
    _run_alembic(BACKEND_DIR, ["upgrade", "head"], {"DATABASE_URL": url})
    return url


def test_all_five_tables_plus_alembic_version_exist(fresh_db_url: str) -> None:
    engine = create_engine(fresh_db_url)
    insp = inspect(engine)
    # v1.17 adds 2 auth tables (users, auth_tokens) on top of the
    # original 5 business tables. v1.18 adds target_versions (§4.6).
    expected = {
        "runs",
        "case_results",
        "case_skip_list",
        "system_settings",
        "case_categories",
        "users",
        "auth_tokens",
        "target_versions",
        "alembic_version",
    }
    assert set(insp.get_table_names()) == expected


def test_uniq_runs_running_enforced(fresh_db_url: str) -> None:
    engine = create_engine(fresh_db_url)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO runs (started_at, status) VALUES (CURRENT_TIMESTAMP, 'running')")
        )
    # Second 'running' row must fail.
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text("INSERT INTO runs (started_at, status) VALUES (CURRENT_TIMESTAMP, 'running')")
        )
    # But multiple non-running rows are fine.
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO runs (started_at, status) VALUES (CURRENT_TIMESTAMP, 'done')")
        )
        conn.execute(
            text("INSERT INTO runs (started_at, status) VALUES (CURRENT_TIMESTAMP, 'aborted')")
        )


def test_case_results_run_id_fk_declared(fresh_db_url: str) -> None:
    engine = create_engine(fresh_db_url)
    insp = inspect(engine)
    fks = insp.get_foreign_keys("case_results")
    assert len(fks) == 1
    assert fks[0]["referred_table"] == "runs"
    assert fks[0]["referred_columns"] == ["id"]
    assert fks[0]["constrained_columns"] == ["run_id"]


def test_case_results_indexes(fresh_db_url: str) -> None:
    engine = create_engine(fresh_db_url)
    insp = inspect(engine)
    names = {idx["name"] for idx in insp.get_indexes("case_results")}
    assert "idx_case_results_run" in names
    assert "idx_case_results_case" in names


def test_case_categories_seeded(fresh_db_url: str) -> None:
    engine = create_engine(fresh_db_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT name, id_prefix, dir_path, default_status, display_order, is_active "
                "FROM case_categories ORDER BY display_order"
            )
        ).fetchall()
    assert len(rows) == 3
    bug, ext, xs = rows
    assert bug.name == "bug_regression"
    assert bug.id_prefix == "lg-bug-"
    assert bug.dir_path == "bug-regression"
    assert bug.default_status == "open"
    assert bug.display_order == 10
    assert bug.is_active in (1, True)
    assert ext.name == "extension"
    assert ext.id_prefix == "lg-ext-"
    assert ext.dir_path == "extension"
    assert ext.default_status == "stable"
    assert ext.display_order == 20
    assert xs.name == "external_systems"
    assert xs.id_prefix == "lg-xs-"
    assert xs.dir_path == "external-systems"
    assert xs.default_status == "open"
    assert xs.display_order == 30
    assert xs.is_active in (1, True)


def test_status_whitelist_is_valid_json_array(fresh_db_url: str) -> None:
    engine = create_engine(fresh_db_url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name, status_whitelist FROM case_categories")).fetchall()
    by_name = {r.name: json.loads(r.status_whitelist) for r in rows}
    assert by_name["bug_regression"] == ["open", "fixed", "wontfix", "stub"]
    assert by_name["extension"] == ["stable", "experimental", "deprecated", "stub"]
    assert by_name["external_systems"] == ["open", "fixed", "wontfix", "stub", "awaiting_env"]


def test_id_prefix_and_dir_path_are_unique(fresh_db_url: str) -> None:
    engine = create_engine(fresh_db_url)
    insp = inspect(engine)
    unique_cols = {tuple(c["column_names"]) for c in insp.get_unique_constraints("case_categories")}
    # SQLite reports UNIQUE columns; both id_prefix and dir_path should be there.
    flat = {col for cols in unique_cols for col in cols}
    assert "id_prefix" in flat
    assert "dir_path" in flat


def test_target_versions_seeded_with_synxdb_default(fresh_db_url: str) -> None:
    """Migration 0004 seeds one row (SynxDB-4.5.0-build130 as default)."""
    engine = create_engine(fresh_db_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT name, display_order, is_active, is_default FROM target_versions ORDER BY id"
            )
        ).fetchall()
    assert len(rows) == 1
    only = rows[0]
    assert only.name == "SynxDB-4.5.0-build130"
    assert only.display_order == 100
    assert only.is_active in (1, True)
    assert only.is_default in (1, True)


def test_downgrade_then_upgrade_round_trip(tmp_path: Path) -> None:
    db_file = tmp_path / "rt.db"
    url = f"sqlite:///{db_file}"
    env_extra = {"DATABASE_URL": url}
    _run_alembic(BACKEND_DIR, ["upgrade", "head"], env_extra)
    _run_alembic(BACKEND_DIR, ["downgrade", "base"], env_extra)
    engine = create_engine(url)
    insp = inspect(engine)
    # Only alembic_version remains after downgrade to base.
    assert set(insp.get_table_names()) == {"alembic_version"}
    _run_alembic(BACKEND_DIR, ["upgrade", "head"], env_extra)
    insp = inspect(create_engine(url))
    assert "case_categories" in insp.get_table_names()


def test_0005_adds_errored_column_to_runs(fresh_db_url: str) -> None:
    """alembic 0005: `runs` table gains an `errored INTEGER NULL` column.

    The column lives next to `passed/failed/skipped` and mirrors their
    `Integer NULL` shape — NOT `NOT NULL DEFAULT 0` — so half-baked rows
    that never finished aggregation keep the same "never-aggregated"
    NULL signal as the other three counters.
    """
    engine = create_engine(fresh_db_url)
    insp = inspect(engine)
    cols = {c["name"]: c for c in insp.get_columns("runs")}
    assert "errored" in cols, "alembic 0005 didn't add runs.errored"
    # Integer + nullable. SQLAlchemy reports the dialect-native type;
    # we just need Integer-ness + nullability.
    assert cols["errored"]["nullable"] is True
    type_str = str(cols["errored"]["type"]).upper()
    assert "INT" in type_str, f"errored column type unexpected: {type_str}"


def test_0005_downgrade_drops_errored_column(tmp_path: Path) -> None:
    """Downgrade 0005 -> 0004 removes `errored` cleanly. Tests the
    batch_alter_table drop_column path on SQLite."""
    db_file = tmp_path / "rt0005.db"
    url = f"sqlite:///{db_file}"
    env_extra = {"DATABASE_URL": url}
    _run_alembic(BACKEND_DIR, ["upgrade", "head"], env_extra)
    # Confirm errored exists at head
    insp = inspect(create_engine(url))
    assert "errored" in {c["name"] for c in insp.get_columns("runs")}
    # Downgrade one step
    _run_alembic(BACKEND_DIR, ["downgrade", "0004"], env_extra)
    insp = inspect(create_engine(url))
    cols = {c["name"] for c in insp.get_columns("runs")}
    assert "errored" not in cols
    # passed/failed/skipped should still exist (we only dropped errored)
    assert {"passed", "failed", "skipped"}.issubset(cols)
    # And re-upgrading restores the column
    _run_alembic(BACKEND_DIR, ["upgrade", "head"], env_extra)
    insp = inspect(create_engine(url))
    assert "errored" in {c["name"] for c in insp.get_columns("runs")}


def test_0005_backfills_errored_from_case_results(tmp_path: Path) -> None:
    """Regression for the dogfood incident 2026-05-26: pre-existing runs
    rows must get their `errored` count populated from `case_results` at
    upgrade time so historical runs render correctly in the UI.

    Seed: stop at revision 0004, insert a runs row with total set + a
    handful of case_results (2 error + 1 pass), then upgrade to 0005 and
    assert errored == 2. Also insert a half-baked row (total NULL) and
    assert its errored stays NULL (the 'aggregation never finished'
    signal — don't lie about it).
    """
    db_file = tmp_path / "backfill.db"
    url = f"sqlite:///{db_file}"
    env_extra = {"DATABASE_URL": url}

    # Stop at 0004 so the errored column doesn't exist yet.
    _run_alembic(BACKEND_DIR, ["upgrade", "0004"], env_extra)

    engine = create_engine(url)
    with engine.begin() as conn:
        # Row A: aggregated (total NOT NULL), 2 errors + 1 pass.
        conn.execute(
            text(
                "INSERT INTO runs (id, started_at, status, total, passed, failed, skipped) "
                "VALUES (1, CURRENT_TIMESTAMP, 'done', 3, 1, 0, 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO case_results (run_id, case_id, status) VALUES "
                "(1, 'a-1', 'pass'), (1, 'a-2', 'error'), (1, 'a-3', 'error')"
            )
        )
        # Row B: half-baked (total NULL). Has 1 errored case_result. Backfill
        # should NOT touch it (preserve 'aggregation never finished' signal).
        conn.execute(
            text(
                "INSERT INTO runs (id, started_at, status) VALUES (2, CURRENT_TIMESTAMP, 'aborted')"
            )
        )
        conn.execute(
            text("INSERT INTO case_results (run_id, case_id, status) VALUES (2, 'b-1', 'error')")
        )
        # Row C: aggregated, all pass — backfill should set errored=0
        # (not NULL), so the row shape is internally consistent.
        conn.execute(
            text(
                "INSERT INTO runs (id, started_at, status, total, passed, failed, skipped) "
                "VALUES (3, CURRENT_TIMESTAMP, 'done', 2, 2, 0, 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO case_results (run_id, case_id, status) VALUES "
                "(3, 'c-1', 'pass'), (3, 'c-2', 'pass')"
            )
        )

    # Now upgrade to 0005 — backfill runs.
    _run_alembic(BACKEND_DIR, ["upgrade", "0005"], env_extra)

    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, total, errored FROM runs ORDER BY id")).fetchall()
    by_id = {r.id: r for r in rows}
    assert by_id[1].errored == 2, "row 1: 2 case_results.status='error' should backfill to 2"
    assert by_id[2].errored is None, "row 2: half-baked (total NULL) must NOT be backfilled"
    assert by_id[3].errored == 0, "row 3: aggregated with no errors should be 0 (not NULL)"
