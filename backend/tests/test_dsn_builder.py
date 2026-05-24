"""Tests for app.runner.dsn_builder — shared by dogfood + API path.

Background: M2 dogfood (2026-05-24) revealed POST /runs ran orchestrator
with sql_pool=None because the API path never built a DSN map. This
module + its test exist so both code paths build DSNs the same way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.runner.dsn_builder import (
    build_dsn_map,
    dsn_map_from_env,
    dsn_map_from_external_or_env,
)

# Minimal normalized case shapes — matches what case_normalizer.normalize_case
# produces (every step has an `on:` session-name field).


def _case_with_sessions(*session_names: str) -> dict:
    return {
        "id": "test-case",
        "setup": [],
        "teardown": [],
        "steps": [
            {"id": f"s{i:02d}", "kind": "sql", "sql": "select 1", "on": sn}
            for i, sn in enumerate(session_names)
        ],
    }


class TestBuildDsnMap:
    def test_default_sessions_always_present(self):
        # Even with no cases, `default` + `default:<pgdatabase>` exist —
        # a case that hit normalize_case with no `on:` lands on `default:postgres`,
        # but a non-normalized one might keep bare `default`.
        m = build_dsn_map([], pghost="h", pgport=5432, pguser="u", pgdatabase="db")
        assert m == {
            "default": "postgresql://u@h:5432/db",
            "default:db": "postgresql://u@h:5432/db",
        }

    def test_step_on_session_collected(self):
        cases = [_case_with_sessions("default:postgres", "default:other_db")]
        m = build_dsn_map(cases, pghost="h", pgport=5432, pguser="u", pgdatabase="postgres")
        assert m["default:postgres"] == "postgresql://u@h:5432/postgres"
        assert m["default:other_db"] == "postgresql://u@h:5432/other_db"

    def test_setup_and_teardown_on_session_collected(self):
        case = {
            "id": "x",
            "setup": [{"kind": "sql", "sql": "select 1", "on": "default:setup_db"}],
            "steps": [],
            "teardown": [{"kind": "sql", "sql": "select 2", "on": "default:teardown_db"}],
        }
        m = build_dsn_map([case], pghost="h", pgport=5432, pguser="u", pgdatabase="postgres")
        assert "default:setup_db" in m
        assert "default:teardown_db" in m
        assert m["default:setup_db"].endswith("/setup_db")
        assert m["default:teardown_db"].endswith("/teardown_db")

    def test_custom_session_name_fallback(self):
        # A session name that doesn't follow `default:<db>` shape should
        # fall back to pgdatabase DSN — not crash, not omit.
        cases = [_case_with_sessions("custom-session")]
        m = build_dsn_map(cases, pghost="h", pgport=5432, pguser="u", pgdatabase="postgres")
        assert m["custom-session"] == "postgresql://u@h:5432/postgres"

    def test_multiple_cases_dsn_aggregation(self):
        cases = [
            _case_with_sessions("default:db1"),
            _case_with_sessions("default:db2", "default:db1"),
        ]
        m = build_dsn_map(cases, pghost="h", pgport=5432, pguser="u", pgdatabase="postgres")
        # 4 keys: default, default:postgres, default:db1, default:db2
        assert len(m) == 4
        assert "default:db1" in m
        assert "default:db2" in m


class TestDsnMapFromEnv:
    def test_uses_libpq_env_vars(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PGHOST", "myhost")
        monkeypatch.setenv("PGPORT", "5433")
        monkeypatch.setenv("PGUSER", "myuser")
        monkeypatch.setenv("PGDATABASE", "mydb")

        m = dsn_map_from_env([])
        assert m["default"] == "postgresql://myuser@myhost:5433/mydb"

    def test_defaults_match_section_3_1_convention(self, monkeypatch: pytest.MonkeyPatch):
        # §3.1: API server runs on mdw; psycopg connects to localhost via
        # `trust` over TCP as `gpadmin` to the `gpadmin` database (owner-home
        # db on Synxdb/Cloudberry — user 2026-05-24 decision, was `postgres`).
        for k in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE"):
            monkeypatch.delenv(k, raising=False)
        m = dsn_map_from_env([])
        assert m["default"] == "postgresql://gpadmin@127.0.0.1:5432/gpadmin"

    def test_pgport_parsed_as_int(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PGPORT", "5555")
        m = dsn_map_from_env([])
        assert ":5555/" in m["default"]


class TestDsnMapFromExternalOrEnv:
    """Post-Settings removal (2026-05-25): DUT connection moved to
    external/dut.yml. Loader picks file > env > module default per field."""

    def test_reads_external_dut_yml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        ext_dir = tmp_path / "external"
        ext_dir.mkdir()
        (ext_dir / "dut.yml").write_text(
            "host: file-host\nport: 6543\nuser: fileuser\ndatabase: filedb\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("EXTERNAL_DEPS_DIR", str(ext_dir))
        # Clear env so we don't accidentally hide the file path
        for k in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE"):
            monkeypatch.delenv(k, raising=False)
        m = dsn_map_from_external_or_env([])
        assert m["default"] == "postgresql://fileuser@file-host:6543/filedb"

    def test_falls_back_to_env_when_file_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        ext_dir = tmp_path / "external"
        ext_dir.mkdir()
        # No dut.yml file
        monkeypatch.setenv("EXTERNAL_DEPS_DIR", str(ext_dir))
        monkeypatch.setenv("PGHOST", "envhost")
        monkeypatch.setenv("PGPORT", "5432")
        monkeypatch.setenv("PGUSER", "envuser")
        monkeypatch.setenv("PGDATABASE", "envdb")
        m = dsn_map_from_external_or_env([])
        assert m["default"] == "postgresql://envuser@envhost:5432/envdb"

    def test_partial_file_falls_through_to_env_per_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """If external/dut.yml has only `host`, port/user/db fall through to env."""
        ext_dir = tmp_path / "external"
        ext_dir.mkdir()
        (ext_dir / "dut.yml").write_text("host: only-host\n", encoding="utf-8")
        monkeypatch.setenv("EXTERNAL_DEPS_DIR", str(ext_dir))
        monkeypatch.setenv("PGUSER", "envuser")
        monkeypatch.setenv("PGDATABASE", "envdb")
        monkeypatch.delenv("PGPORT", raising=False)
        m = dsn_map_from_external_or_env([])
        # host from file, user/db from env, port from default (5432)
        assert m["default"] == "postgresql://envuser@only-host:5432/envdb"

    def test_uses_module_default_when_neither_file_nor_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("EXTERNAL_DEPS_DIR", str(tmp_path / "nope"))
        for k in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE"):
            monkeypatch.delenv(k, raising=False)
        m = dsn_map_from_external_or_env([])
        assert m["default"] == "postgresql://gpadmin@127.0.0.1:5432/gpadmin"
