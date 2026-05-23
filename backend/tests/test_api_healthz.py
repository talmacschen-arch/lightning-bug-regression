"""Tests for GET /healthz (M1-10 / design.md §5.2)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.storage import sqlite_store
from app.storage.models import Base


@pytest.fixture
def client_with_db(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Bind an in-memory SQLite to the storage module before the request,
    bypassing the FastAPI lifespan (which would try to open a file-backed
    URL from `get_database_url`)."""
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
    # Neutralize the lifespan so it doesn't replace our in-memory engine
    # with one built from get_database_url() (default points at ./data/runs.db).
    monkeypatch.setattr(sqlite_store, "init_engine", lambda url: None)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_healthz_returns_200_with_db_ok(client_with_db: TestClient) -> None:
    """With the engine wired, GET /healthz must report db: 'ok'."""
    resp = client_with_db.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}


def test_healthz_reports_db_fail_when_engine_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the storage engine is not initialized, the endpoint must still
    return 200 (it's the liveness probe) but with `db: 'fail'`."""
    monkeypatch.setattr(sqlite_store, "_engine", None, raising=False)
    monkeypatch.setattr(sqlite_store, "_SessionLocal", None, raising=False)
    # Neutralize the lifespan; otherwise it would re-init the engine from
    # the default sqlite:///./data/runs.db URL.
    monkeypatch.setattr(sqlite_store, "init_engine", lambda url: None)
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "fail"
