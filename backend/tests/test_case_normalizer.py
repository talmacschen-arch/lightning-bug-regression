"""Tests for app.runner.case_normalizer — shared by dogfood + API path.

Background: M2 dogfood (2026-05-24) revealed API path crashed on real
case YAMLs because it skipped the normalizer that the dogfood script
had inlined. This module consolidates the normalizer; both paths now
import from here.

Tests cover only the normalizer itself; integration tests for the API
path live in test_api.py, and dogfood script integration lives in
test_dogfood_script.py.
"""

from __future__ import annotations

import pytest

from app.runner.case_normalizer import (
    VALID_KINDS,
    normalize_case,
)


class TestNormalizeSetupTeardown:
    """`setup: list[str]` MUST be wrapped — this is the M2-revealed bug."""

    def test_string_setup_becomes_sql_dict(self):
        raw = {
            "id": "lg-bug-X",
            "defaults": {"database": "mydb"},
            "setup": ["DROP TABLE IF EXISTS t1"],
            "steps": [{"kind": "sql", "sql": "SELECT 1"}],
        }
        out = normalize_case(raw)
        assert out["setup"] == [
            {
                "id": "setup-00",
                "kind": "sql",
                "sql": "DROP TABLE IF EXISTS t1",
                "on": "default:mydb",
            }
        ]

    def test_string_teardown_becomes_sql_dict(self):
        raw = {
            "id": "x",
            "defaults": {"database": "mydb"},
            "teardown": ["DROP TABLE foo", "DROP TABLE bar"],
            "steps": [{"kind": "sql", "sql": "select 1"}],
        }
        out = normalize_case(raw)
        assert len(out["teardown"]) == 2
        assert out["teardown"][0]["id"] == "teardown-00"
        assert out["teardown"][1]["id"] == "teardown-01"
        assert all(t["kind"] == "sql" for t in out["teardown"])

    def test_psql_string_routes_to_shell_kind(self):
        # `psql ...` strings can't run inside autocommit psycopg sessions
        # (CREATE/DROP DATABASE, CREATE EXTENSION etc.) — route to shell.
        raw = {
            "id": "x",
            "setup": ["su - gpadmin -c \"psql -c 'CREATE EXTENSION pgvector'\""],
            "steps": [{"kind": "sql", "sql": "select 1"}],
        }
        out = normalize_case(raw)
        assert out["setup"][0]["kind"] == "shell"
        assert "psql " in out["setup"][0]["cmd"]

    def test_dict_setup_passes_through_normalize_step(self):
        raw = {
            "id": "x",
            "setup": [{"kind": "shell", "cmd": "echo hi"}],
            "steps": [{"kind": "sql", "sql": "select 1"}],
        }
        out = normalize_case(raw)
        assert out["setup"][0]["kind"] == "shell"
        assert out["setup"][0]["id"] == "setup-00"

    def test_empty_setup_and_teardown_become_empty_lists(self):
        raw = {"id": "x", "steps": [{"kind": "sql", "sql": "select 1"}]}
        out = normalize_case(raw)
        assert out["setup"] == []
        assert out["teardown"] == []

    def test_setup_invalid_type_raises(self):
        raw = {
            "id": "x",
            "setup": [123],  # int — neither str nor dict
            "steps": [],
        }
        with pytest.raises(ValueError, match="setup\\[0\\] must be a string or dict"):
            normalize_case(raw)


class TestNormalizeStep:
    def test_step_gets_id_from_name_or_index(self):
        raw = {
            "id": "x",
            "steps": [
                {"name": "run-query", "kind": "sql", "sql": "select 1"},
                {"kind": "sql", "sql": "select 2"},  # no id/name → step-NN
            ],
        }
        out = normalize_case(raw)
        assert out["steps"][0]["id"] == "run-query"
        assert out["steps"][1]["id"] == "step-01"

    def test_step_driver_alias_normalized_to_kind(self):
        raw = {
            "id": "x",
            "steps": [{"id": "s", "driver": "sql", "sql": "select 1"}],
        }
        out = normalize_case(raw)
        assert out["steps"][0]["kind"] == "sql"

    def test_step_missing_kind_raises(self):
        raw = {"id": "x", "steps": [{"id": "s", "sql": "select 1"}]}
        with pytest.raises(ValueError, match="missing kind"):
            normalize_case(raw)

    def test_step_invalid_kind_raises(self):
        raw = {"id": "x", "steps": [{"id": "s", "kind": "no-such-kind"}]}
        with pytest.raises(ValueError, match="invalid kind"):
            normalize_case(raw)

    def test_per_step_database_overrides_on(self):
        raw = {
            "id": "x",
            "defaults": {"database": "main"},
            "steps": [
                {"id": "s1", "kind": "sql", "sql": "select 1", "database": "other"},
                {"id": "s2", "kind": "sql", "sql": "select 2"},  # uses default
            ],
        }
        out = normalize_case(raw)
        assert out["steps"][0]["on"] == "default:other"
        assert out["steps"][1]["on"] == "default:main"

    def test_sql_step_missing_sql_or_run_raises(self):
        raw = {"id": "x", "steps": [{"id": "s", "kind": "sql"}]}
        with pytest.raises(ValueError, match="sql step .* missing sql/run"):
            normalize_case(raw)

    def test_shell_step_missing_cmd_or_run_raises(self):
        raw = {"id": "x", "steps": [{"id": "s", "kind": "shell"}]}
        with pytest.raises(ValueError, match="shell step .* missing cmd/run"):
            normalize_case(raw)

    def test_string_step_in_steps_list_raises(self):
        # `steps` items must be dicts (only setup/teardown allow strings).
        raw = {"id": "x", "steps": ["select 1"]}
        with pytest.raises(ValueError, match="steps\\[0\\] must be a dict"):
            normalize_case(raw)


class TestNormalizeCaseTopLevel:
    def test_default_database_fallback_is_postgres(self):
        raw = {"id": "x", "steps": [{"id": "s", "kind": "sql", "sql": "select 1"}]}
        out = normalize_case(raw)
        assert out["steps"][0]["on"] == "default:postgres"

    def test_destructive_coerced_to_bool(self):
        raw = {"id": "x", "destructive": "yes", "steps": []}
        out = normalize_case(raw)
        assert out["destructive"] is True

    def test_real_lg_bug_0001_shape_does_not_crash(self):
        # Mini reproduction of the actual lg-bug-0001 YAML — proves
        # `setup: list[str]` no longer breaks the orchestrator path.
        raw = {
            "id": "lg-bug-0001-hashjoin-right-table",
            "category": "bug_regression",
            "status": "open",
            "defaults": {"database": "postgres"},
            "setup": [
                "DROP TABLE IF EXISTS tmp_test01",
                "DROP TABLE IF EXISTS tmp_test02",
                "CREATE TABLE tmp_test01 (a int)",
            ],
            "steps": [
                {
                    "id": "explain-hashjoin",
                    "kind": "sql",
                    "sql": "EXPLAIN SELECT * FROM tmp_test01",
                }
            ],
            "teardown": [
                "DROP TABLE IF EXISTS tmp_test01",
                "DROP TABLE IF EXISTS tmp_test02",
            ],
        }
        out = normalize_case(raw)
        assert all(isinstance(s, dict) for s in out["setup"])
        assert all(isinstance(s, dict) for s in out["teardown"])
        assert all(isinstance(s, dict) for s in out["steps"])
        # The bug: M2 dogfood saw .get("id") crash because items were str.
        # Now every step is a dict and has an id.
        for s in out["setup"] + out["teardown"] + out["steps"]:
            assert "id" in s
            assert s["kind"] in VALID_KINDS
