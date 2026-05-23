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
