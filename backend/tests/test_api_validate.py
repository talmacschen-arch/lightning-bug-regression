"""Tests for POST /cases/validate (design.md §13.7 M3a-1 / §14 R26).

The endpoint MUST visibly delegate to two modules:
  * ``app.storage.yaml_loader.load_case`` — §4.1 schema checks
  * ``app.runner.case_normalizer.normalize_case`` — step-kind / required
    field checks the schema layer permits

These tests exercise both delegation paths plus the pre-loader YAML-syntax
+ top-level-mapping checks the endpoint itself handles.
"""

from __future__ import annotations

import json
import textwrap

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.storage import sqlite_store
from app.storage.models import Base, CaseCategory


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """In-memory DB seeded with the §4.5 ``bug_regression`` category so
    ``load_case`` has a whitelist to validate against."""
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
                id_prefix="bug-",
                dir_path="bug-regression",
                status_whitelist=json.dumps(["open", "fixed", "wontfix", "stub"]),
                default_status="open",
                display_order=10,
                is_active=True,
            )
        )
        sess.commit()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# minimal valid YAML factory
# ---------------------------------------------------------------------------


def _minimal_valid_yaml() -> str:
    """A YAML that satisfies both the §4.1 schema (yaml_loader) AND the
    normalizer's VALID_KINDS check.

    Kept inline (not loaded from cases/) so the test stays hermetic — a
    real on-disk case rewrite shouldn't break this test.
    """
    return textwrap.dedent(
        """\
        id: bug-9999-test-validate
        category: bug_regression
        title: validate endpoint smoke
        description: minimal valid case for /cases/validate test
        procedure: run one trivial sql
        expected: returns 1
        status: open
        steps:
          - name: trivial
            kind: sql
            sql: SELECT 1
        """
    )


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_validate_happy_path(client: TestClient) -> None:
    """A YAML that satisfies both schema + normalizer → ok=true, errors=[]."""
    resp = client.post("/cases/validate", json={"yaml": _minimal_valid_yaml()})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ok": True, "errors": []}


# ---------------------------------------------------------------------------
# pre-loader (endpoint-level) checks
# ---------------------------------------------------------------------------


def test_validate_yaml_syntax_error(client: TestClient) -> None:
    """Malformed YAML (multiple colons) → where='yaml_syntax'."""
    resp = client.post("/cases/validate", json={"yaml": "foo: : :"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert len(body["errors"]) >= 1
    assert body["errors"][0]["where"] == "yaml_syntax"
    # reason should carry the underlying yaml error description
    assert body["errors"][0]["reason"]


def test_validate_top_level_not_a_mapping(client: TestClient) -> None:
    """A YAML list at the top level → where='top-level'."""
    resp = client.post("/cases/validate", json={"yaml": "- one\n- two\n"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert len(body["errors"]) == 1
    assert body["errors"][0]["where"] == "top-level"
    assert "mapping" in body["errors"][0]["reason"].lower()


# ---------------------------------------------------------------------------
# yaml_loader (schema) delegation
# ---------------------------------------------------------------------------


def test_validate_schema_violation_missing_id(client: TestClient) -> None:
    """Schema check (yaml_loader.load_case) catches missing required field.

    The endpoint MUST delegate to yaml_loader; an inline duplicate of the
    required-field list would be a §14 R26 violation.
    """
    bad = textwrap.dedent(
        """\
        category: bug_regression
        title: missing id
        description: d
        procedure: p
        expected: e
        steps:
          - name: s
            kind: sql
            sql: SELECT 1
        """
    )
    resp = client.post("/cases/validate", json={"yaml": bad})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert len(body["errors"]) >= 1
    # where should mention the missing field ("id"); the exact format is the
    # yaml_loader's "<key>" convention.
    found = body["errors"][0]
    assert "id" in found["where"] or "id" in found["reason"]


# ---------------------------------------------------------------------------
# case_normalizer delegation
# ---------------------------------------------------------------------------


def test_validate_normalize_violation_unknown_step_kind(client: TestClient) -> None:
    """A step whose `kind` is in yaml_loader._VALID_DRIVERS but NOT in
    case_normalizer.VALID_KINDS must surface as where='normalize'.

    ``restart_db`` is the wedge: yaml_loader accepts it (it's in
    _VALID_DRIVERS), but the normalizer's VALID_KINDS only allows
    {sql, shell, log_grep}. This proves the endpoint actually runs
    normalize_case (§14 R26 delegation), not just yaml_loader.
    """
    yaml_with_unknown_kind = textwrap.dedent(
        """\
        id: bug-9999-test-normalize
        category: bug_regression
        title: triggers normalize-stage rejection
        description: passes schema but normalize_case rejects restart_db kind
        procedure: p
        expected: e
        status: open
        steps:
          - name: bad-kind
            kind: restart_db
            run: noop
        """
    )
    resp = client.post("/cases/validate", json={"yaml": yaml_with_unknown_kind})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert len(body["errors"]) >= 1
    assert body["errors"][0]["where"] == "normalize"
    # The normalizer's message mentions the invalid kind.
    assert "restart_db" in body["errors"][0]["reason"] or "kind" in body["errors"][0]["reason"]


# ---------------------------------------------------------------------------
# response shape sanity
# ---------------------------------------------------------------------------


def test_validate_response_shape_pydantic(client: TestClient) -> None:
    """Every error entry must be {where: str, reason: str}; ok must be bool."""
    resp = client.post("/cases/validate", json={"yaml": "foo: : :"})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["ok"], bool)
    assert isinstance(body["errors"], list)
    for err in body["errors"]:
        assert set(err.keys()) == {"where", "reason"}
        assert isinstance(err["where"], str)
        assert isinstance(err["reason"], str)
