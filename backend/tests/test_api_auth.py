"""Tests for /auth/* endpoints (v1.17 single-user login)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import hash_password, seed_admin_if_missing
from app.main import app
from app.storage import sqlite_store
from app.storage.models import AuthToken, Base, User


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """In-memory DB with seeded admin/admin user."""
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

    seed_admin_if_missing()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(engine)
    engine.dispose()


def test_seed_admin_is_idempotent(client: TestClient) -> None:
    """Calling seed_admin_if_missing twice doesn't create duplicate users."""
    seed_admin_if_missing()
    seed_admin_if_missing()
    with sqlite_store.get_session() as sess:
        users = list(sess.scalars(select(User)).all())
        assert len(users) == 1
        assert users[0].username == "admin"
        assert users[0].password_changed_at is None


def test_login_happy_path(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "admin"
    assert body["must_change_password"] is True
    assert isinstance(body["token"], str) and len(body["token"]) >= 30


def test_login_wrong_password_401(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user_401(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"username": "alice", "password": "x"})
    assert resp.status_code == 401


def test_login_empty_creds_401(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"username": "", "password": ""})
    assert resp.status_code == 401


def test_login_token_persisted_as_hash(client: TestClient) -> None:
    """The raw token returned to client should NOT appear in DB; only sha256."""
    resp = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    token = resp.json()["token"]
    with sqlite_store.get_session() as sess:
        rows = list(sess.scalars(select(AuthToken)).all())
        assert len(rows) == 1
        # The stored token_hash MUST differ from the raw token
        assert rows[0].token_hash != token
        assert len(rows[0].token_hash) == 64  # sha256 hex


def test_me_with_valid_token(client: TestClient) -> None:
    login = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    token = login.json()["token"]
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"username": "admin", "must_change_password": True}


def test_me_without_token_401(client: TestClient) -> None:
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_with_invalid_token_401(client: TestClient) -> None:
    resp = client.get("/auth/me", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_me_with_malformed_header_401(client: TestClient) -> None:
    # Missing "Bearer "
    resp = client.get("/auth/me", headers={"Authorization": "just-a-token"})
    assert resp.status_code == 401


def test_logout_invalidates_token(client: TestClient) -> None:
    login = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    token = login.json()["token"]
    # Token works before logout
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    # Logout
    resp = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 204
    # Token no longer works
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_logout_without_header_still_204(client: TestClient) -> None:
    """Logout is idempotent — even without a token, returns 204."""
    resp = client.post("/auth/logout")
    assert resp.status_code == 204


def test_change_password_round_trip(client: TestClient) -> None:
    login = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    token = login.json()["token"]

    resp = client.post(
        "/auth/change-password",
        json={"current_password": "admin", "new_password": "newpass123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204

    # Old password no longer works
    bad = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert bad.status_code == 401

    # New password works + must_change_password now False
    new = client.post("/auth/login", json={"username": "admin", "password": "newpass123"})
    assert new.status_code == 200
    assert new.json()["must_change_password"] is False


def test_change_password_wrong_current_401(client: TestClient) -> None:
    login = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    token = login.json()["token"]
    resp = client.post(
        "/auth/change-password",
        json={"current_password": "wrong", "new_password": "newpass123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


def test_change_password_too_short_400(client: TestClient) -> None:
    login = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    token = login.json()["token"]
    resp = client.post(
        "/auth/change-password",
        json={"current_password": "admin", "new_password": "abc"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_change_password_same_as_current_400(client: TestClient) -> None:
    login = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    token = login.json()["token"]
    resp = client.post(
        "/auth/change-password",
        json={"current_password": "admin", "new_password": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_change_password_without_token_401(client: TestClient) -> None:
    resp = client.post(
        "/auth/change-password",
        json={"current_password": "admin", "new_password": "newpass123"},
    )
    assert resp.status_code == 401


def test_multiple_logins_create_multiple_tokens(client: TestClient) -> None:
    """Multi-device login: same user can have multiple tokens, each independent."""
    r1 = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    r2 = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    t1, t2 = r1.json()["token"], r2.json()["token"]
    assert t1 != t2
    # Both work
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {t1}"}).status_code == 200
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {t2}"}).status_code == 200
    # Logging out t1 doesn't affect t2
    client.post("/auth/logout", headers={"Authorization": f"Bearer {t1}"})
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {t1}"}).status_code == 401
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {t2}"}).status_code == 200


def test_password_hash_uses_bcrypt(client: TestClient) -> None:
    """Sanity: stored hash starts with bcrypt prefix `$2b$` (not plaintext)."""
    with sqlite_store.get_session() as sess:
        user = sess.scalar(select(User))
        assert user is not None
        assert user.password_hash.startswith("$2b$")


def test_hash_password_round_trip() -> None:
    """Helper-level: hash + verify (no DB)."""
    from app.api.auth import verify_password

    h = hash_password("my-strong-password")
    assert verify_password("my-strong-password", h)
    assert not verify_password("wrong", h)
