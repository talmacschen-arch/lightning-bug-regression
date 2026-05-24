"""Unit tests for external_deps_loader (M6-5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.runner.external_deps_loader import (
    collect_external_deps,
    load_external_context,
)


def test_collect_external_deps_unions_dedupes_sorts():
    cases = [
        {"id": "c1", "external_deps": ["elasticsearch", "hive"]},
        {"id": "c2", "external_deps": ["hive"]},
        {"id": "c3", "external_deps": []},
        {"id": "c4"},  # no external_deps key
        {"id": "c5", "external_deps": ["zookeeper", "elasticsearch"]},
    ]
    assert collect_external_deps(cases) == ["elasticsearch", "hive", "zookeeper"]


def test_collect_external_deps_ignores_non_string_entries():
    """Defensive — case YAML schema validation guarantees strings, but
    don't crash if a downstream tool produces malformed data."""
    cases = [
        {"id": "c", "external_deps": ["ok", 42, None, "", "good"]},
    ]
    assert collect_external_deps(cases) == ["good", "ok"]


def test_collect_external_deps_empty_for_no_cases():
    assert collect_external_deps([]) == []


def test_load_external_context_reads_yaml(tmp_path: Path):
    (tmp_path / "elasticsearch.yml").write_text(
        "host: 192.168.195.203\nport: 9200\nextras:\n  api_key: K1\n",
        encoding="utf-8",
    )
    (tmp_path / "hive.yml").write_text(
        "host: hive-mdw\nport: 10000\nextras:\n  principal: hive/_HOST\n",
        encoding="utf-8",
    )

    ctx = load_external_context(["elasticsearch", "hive"], base_dir=tmp_path)
    assert set(ctx.keys()) == {"elasticsearch", "hive"}
    assert ctx["elasticsearch"]["host"] == "192.168.195.203"
    assert ctx["elasticsearch"]["port"] == 9200
    assert ctx["elasticsearch"]["extras"]["api_key"] == "K1"
    assert ctx["hive"]["extras"]["principal"] == "hive/_HOST"


def test_load_external_context_missing_file_skipped_not_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """A case YAML may reference a svc whose external/<svc>.yml hasn't
    been provisioned yet. We log + skip rather than raise — the case will
    fail later with a clean UndefinedError when its template references
    `external.<missing>.<key>`, which is a much clearer message."""
    (tmp_path / "good.yml").write_text("host: ok\n", encoding="utf-8")

    with caplog.at_level("WARNING"):
        ctx = load_external_context(["good", "missing"], base_dir=tmp_path)

    assert ctx == {"good": {"host": "ok"}}
    assert any("missing.yml not found" in r.message for r in caplog.records)


def test_load_external_context_non_dict_top_level_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """If external/<svc>.yml exists but parses to a list/scalar, log + skip."""
    (tmp_path / "broken.yml").write_text("- a\n- b\n", encoding="utf-8")
    with caplog.at_level("WARNING"):
        ctx = load_external_context(["broken"], base_dir=tmp_path)
    assert ctx == {}
    assert any("top-level must be a mapping" in r.message for r in caplog.records)


def test_load_external_context_invalid_yaml_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    (tmp_path / "bad.yml").write_text("this: [unclosed", encoding="utf-8")
    with caplog.at_level("WARNING"):
        ctx = load_external_context(["bad"], base_dir=tmp_path)
    assert ctx == {}
    assert any("failed to read" in r.message for r in caplog.records)


def test_load_external_context_missing_dir_returns_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    nonexistent = tmp_path / "nope"
    with caplog.at_level("WARNING"):
        ctx = load_external_context(["any"], base_dir=nonexistent)
    assert ctx == {}
    # Only warn when svc_names non-empty (no point spamming logs when
    # no case actually uses external_deps)
    assert any("does not exist" in r.message for r in caplog.records)


def test_load_external_context_missing_dir_no_warn_when_no_svcs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    nonexistent = tmp_path / "nope"
    with caplog.at_level("WARNING"):
        ctx = load_external_context([], base_dir=nonexistent)
    assert ctx == {}
    assert not any("does not exist" in r.message for r in caplog.records)


def test_load_external_context_honors_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When `base_dir` is not passed, EXTERNAL_DEPS_DIR env wins."""
    (tmp_path / "es.yml").write_text("host: env-host\n", encoding="utf-8")
    monkeypatch.setenv("EXTERNAL_DEPS_DIR", str(tmp_path))
    ctx = load_external_context(["es"])
    assert ctx["es"]["host"] == "env-host"
