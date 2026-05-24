"""Tests for GET /admin/categories (M1-10 / design.md §4.5)."""

from __future__ import annotations

import json

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
    """Spin a fresh in-memory DB + seed the two §4.5 categories so the
    endpoint has something to return. Mirrors the seed inserts in
    alembic migration 0001."""
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
                description="历史 BUG 用例",
                id_prefix="lg-bug-",
                dir_path="bug-regression",
                status_whitelist=json.dumps(["open", "fixed", "wontfix", "stub"]),
                default_status="open",
                display_order=10,
                is_active=True,
            )
        )
        sess.add(
            CaseCategory(
                name="extension",
                display_name="Extension 集成测试",
                description="Extension 验证",
                id_prefix="lg-ext-",
                dir_path="extension",
                status_whitelist=json.dumps(["stable", "experimental", "deprecated", "stub"]),
                default_status="stable",
                display_order=20,
                is_active=True,
            )
        )
        sess.commit()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(engine)
    engine.dispose()


def test_categories_returns_both_seeded_rows_with_parsed_whitelist(
    client: TestClient,
) -> None:
    """Both seeded rows should be returned in display_order ASC, with
    status_whitelist decoded into a JSON list (not a raw string)."""
    resp = client.get("/admin/categories")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2
    # display_order ASC -> bug_regression (10) first, extension (20) second.
    assert body[0]["name"] == "bug_regression"
    assert body[1]["name"] == "extension"

    # status_whitelist must be a list, not a JSON-encoded string.
    assert isinstance(body[0]["status_whitelist"], list)
    assert body[0]["status_whitelist"] == ["open", "fixed", "wontfix", "stub"]
    assert body[1]["status_whitelist"] == [
        "stable",
        "experimental",
        "deprecated",
        "stub",
    ]

    # spot-check required fields
    assert body[0]["id_prefix"] == "lg-bug-"
    assert body[0]["dir_path"] == "bug-regression"
    assert body[0]["default_status"] == "open"


def test_categories_filters_out_inactive_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Insert a third row with `is_active=0`; the endpoint must hide it."""
    with sqlite_store.get_session() as sess:
        sess.add(
            CaseCategory(
                name="legacy_perf",
                display_name="legacy perf",
                description=None,
                id_prefix="lg-perf-",
                dir_path="perf-regression",
                status_whitelist=json.dumps(["open"]),
                default_status="open",
                display_order=99,
                is_active=False,
            )
        )

    resp = client.get("/admin/categories")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "legacy_perf" not in names
    assert set(names) == {"bug_regression", "extension"}


def test_categories_with_malformed_whitelist_returns_empty_list(
    client: TestClient,
) -> None:
    """If a row's status_whitelist is not valid JSON, the endpoint must
    not crash — it should surface an empty list so the admin UI can
    visibly flag the row."""
    with sqlite_store.get_session() as sess:
        sess.add(
            CaseCategory(
                name="broken_cat",
                display_name="broken",
                description=None,
                id_prefix="lg-broken-",
                dir_path="broken",
                status_whitelist="not-json",
                default_status="open",
                display_order=50,
                is_active=True,
            )
        )

    resp = client.get("/admin/categories")
    assert resp.status_code == 200
    broken = next(c for c in resp.json() if c["name"] == "broken_cat")
    assert broken["status_whitelist"] == []


# ---------------------------------------------------------------------------
# M6-4 skip-list CRUD
# ---------------------------------------------------------------------------


def test_skip_list_empty_returns_empty_array(client: TestClient) -> None:
    resp = client.get("/admin/skip-list")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_skip_list_entry_round_trip(client: TestClient) -> None:
    resp = client.post(
        "/admin/skip-list",
        json={
            "case_id": "lg-bug-9999-flaky",
            "reason": "intermittent on 4.5.0 — needs ≥10 rounds (R28)",
            "applies_to_version": "SynxDB-4.5.0-build130",
            "upstream_issue": "https://example/issue/42",
            "until_date": "2026-12-31",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["case_id"] == "lg-bug-9999-flaky"
    assert body["reason"].startswith("intermittent on 4.5.0")
    assert body["applies_to_version"] == "SynxDB-4.5.0-build130"
    assert body["until_date"] == "2026-12-31"
    assert isinstance(body["id"], int)

    # GET should return the row
    listing = client.get("/admin/skip-list").json()
    assert len(listing) == 1
    assert listing[0]["id"] == body["id"]


def test_create_skip_list_entry_rejects_blank_required_fields(
    client: TestClient,
) -> None:
    resp = client.post(
        "/admin/skip-list",
        json={"case_id": "  ", "reason": "x"},
    )
    assert resp.status_code == 400
    resp = client.post(
        "/admin/skip-list",
        json={"case_id": "y", "reason": ""},
    )
    assert resp.status_code == 400


def test_delete_skip_list_entry(client: TestClient) -> None:
    resp = client.post(
        "/admin/skip-list",
        json={"case_id": "lg-bug-X", "reason": "test"},
    )
    eid = resp.json()["id"]
    del_resp = client.delete(f"/admin/skip-list/{eid}")
    assert del_resp.status_code == 204
    # GET shows it's gone
    assert client.get("/admin/skip-list").json() == []


def test_delete_skip_list_404_for_unknown_id(client: TestClient) -> None:
    resp = client.delete("/admin/skip-list/999999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /admin/settings endpoints removed 2026-05-25 — see admin.py for rationale.
# dut_hosts moved to external/dut.yml; jinja_context + server_log_path had
# zero real consumers in 15 case YAMLs. Tests below cover the regression:
# the endpoints must now 404, ensuring frontend doesn't still try to call
# them after the refactor.
# ---------------------------------------------------------------------------


def test_settings_list_endpoint_removed(client: TestClient) -> None:
    resp = client.get("/admin/settings")
    assert resp.status_code == 404


def test_settings_put_endpoint_removed(client: TestClient) -> None:
    resp = client.put("/admin/settings/jinja_context", json={"value": {"x": 1}})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# X-Admin-Password auth guard (M6-4; still active for skip-list mutations)
# ---------------------------------------------------------------------------


def test_no_auth_required_when_admin_password_env_unset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dev-mode: env unset → mutating endpoints work without header."""
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    resp = client.post(
        "/admin/skip-list",
        json={"case_id": "lg-bug-dev", "reason": "no auth in dev"},
    )
    assert resp.status_code == 201


def test_mutation_blocked_without_password_when_env_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-pw-2026")
    resp = client.post(
        "/admin/skip-list",
        json={"case_id": "lg-bug-blocked", "reason": "no header"},
    )
    assert resp.status_code == 401


def test_mutation_allowed_with_correct_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-pw-2026")
    resp = client.post(
        "/admin/skip-list",
        headers={"X-Admin-Password": "secret-pw-2026"},
        json={"case_id": "lg-bug-ok", "reason": "with header"},
    )
    assert resp.status_code == 201


def test_get_endpoints_remain_open_with_admin_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GETs should still work without password (read-only access OK)."""
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-pw-2026")
    assert client.get("/admin/skip-list").status_code == 200
    assert client.get("/admin/categories").status_code == 200
