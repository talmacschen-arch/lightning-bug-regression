"""Tests for GET /admin/step-kinds (M3b-1 / design.md §5.5.7).

The skill `.claude/skills/add-test-case` will hit this endpoint to learn
which step kinds + fields are legal. The contract is that the endpoint's
`kind` list is identical to `app.runner.case_normalizer.VALID_KINDS` —
single source of truth (§14 R26). These tests pin that contract so a
future contributor cannot silently re-introduce dual code paths.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.runner.step_kinds import STEP_KINDS, VALID_KIND_NAMES
from app.storage import sqlite_store
from app.storage.models import Base


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Spin a fresh in-memory DB and neutralize the lifespan engine init
    so the endpoint can be exercised without touching `data/runs.db`.

    The /admin/step-kinds endpoint itself doesn't touch the DB, but the
    FastAPI lifespan still runs and would otherwise pin a file-backed
    engine when TestClient enters its context manager.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(sqlite_store, "_engine", engine, raising=False)
    monkeypatch.setattr(
        sqlite_store,
        "_SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session),
        raising=False,
    )
    monkeypatch.setattr(sqlite_store, "init_engine", lambda url: None)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_step_kinds_returns_three(client: TestClient) -> None:
    """Endpoint returns exactly the kinds defined in STEP_KINDS, in order."""
    resp = client.get("/admin/step-kinds")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 3
    # Order must match the registry's declared order so the skill can
    # use positional references.
    assert [k["kind"] for k in body] == [m.kind for m in STEP_KINDS]
    assert [k["kind"] for k in body] == ["sql", "shell", "log_grep"]


def test_step_kinds_required_fields_non_empty(client: TestClient) -> None:
    """Every kind must declare at least one required field — a kind with
    no required fields would mean the skill can emit an empty step which
    the normalizer would reject anyway."""
    resp = client.get("/admin/step-kinds")
    assert resp.status_code == 200
    body = resp.json()
    for entry in body:
        assert isinstance(entry["required_fields"], list)
        assert len(entry["required_fields"]) >= 1, (
            f"kind {entry['kind']!r} has empty required_fields — skill cannot "
            f"emit a valid step of this kind"
        )
        # optional_fields must also be a list (may be empty in principle,
        # but currently every kind declares at least one — `expect`).
        assert isinstance(entry["optional_fields"], list)


def test_step_kinds_matches_normalizer_valid_kinds(client: TestClient) -> None:
    """Single-source-of-truth contract: the kinds the endpoint exposes
    are exactly the kinds the normalizer accepts. If this fails, a
    contributor has introduced a dual code path (§14 R26)."""
    resp = client.get("/admin/step-kinds")
    assert resp.status_code == 200
    body = resp.json()
    endpoint_kinds = {k["kind"] for k in body}
    assert endpoint_kinds == set(VALID_KIND_NAMES)


def test_step_kinds_description_non_empty(client: TestClient) -> None:
    """Every entry must have a non-empty description — the skill renders
    it into its prompt and an empty string would be visible noise."""
    resp = client.get("/admin/step-kinds")
    assert resp.status_code == 200
    for entry in resp.json():
        assert isinstance(entry["description"], str)
        assert entry["description"].strip(), f"kind {entry['kind']!r} has empty description"


def test_log_grep_required_fields_include_pattern_and_log_path(client: TestClient) -> None:
    """Regression guard: log_grep requires both `pattern` AND `log_path`.
    Driver consumes both; if either drops out of `required_fields` the
    skill will emit unrunnable cases."""
    resp = client.get("/admin/step-kinds")
    log_grep = next(k for k in resp.json() if k["kind"] == "log_grep")
    assert "pattern" in log_grep["required_fields"]
    assert "log_path" in log_grep["required_fields"]
