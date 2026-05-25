"""Tests for /admin/target-versions CRUD (design.md §4.6, v1.18+).

The target_versions registry backs the frontend "Trigger New Run -> Target
version" dropdown. Backend does NOT validate runs.target_version against
this catalog (POST /runs stays permissive); this suite asserts the user
decisions baked into the API:

  - Seed row ``SynxDB-4.5.0-build130`` exists after fresh migration.
  - GET ``?active=true`` filters to is_active=1 rows.
  - POST rejects empty name (400), duplicate name (409).
  - POST/PATCH with is_default=true clears is_default on other rows.
  - PATCH supports partial updates and 404s on unknown id.
  - DELETE refuses (409 + ``run_count``) when runs reference the name;
    ``?force=true`` overrides.
  - All mutating endpoints require Bearer auth (401 otherwise).
  - List ordering: ``display_order ASC, name ASC``.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.storage import sqlite_store
from app.storage.models import Base, CaseCategory, TargetVersion


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """In-memory DB + seeded admin user + seeded categories + the initial
    target_version row that the migration would create.

    Replicates the seed behaviour of migration 0004 because
    ``Base.metadata.create_all()`` makes the table but doesn't run the
    INSERT — without this manual seed the GET test would see an empty list.
    """
    from app.api.auth import seed_admin_if_missing

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

    # Seed initial target_version (matches migration 0004 SQL).
    with SessionLocal() as sess:
        sess.add(
            TargetVersion(
                name="SynxDB-4.5.0-build130",
                display_order=100,
                is_active=True,
                is_default=True,
            )
        )
        # Seed at least one category so the rest of /admin doesn't get
        # surprised — not strictly needed for these tests but matches
        # the existing test_api_admin fixture.
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
        sess.commit()

    seed_admin_if_missing()

    with TestClient(app) as c:
        login = c.post("/auth/login", json={"username": "admin", "password": "admin"})
        assert login.status_code == 200, f"seeded admin login failed: {login.json()}"
        token = login.json()["token"]
        c.auth_headers = {"Authorization": f"Bearer {token}"}  # type: ignore[attr-defined]
        yield c

    Base.metadata.drop_all(engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# GET /admin/target-versions
# ---------------------------------------------------------------------------


def test_get_returns_seeded_synxdb_row(client: TestClient) -> None:
    """Fresh fixture has the migration-seeded SynxDB row."""
    resp = client.get("/admin/target-versions")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    only = body[0]
    assert only["name"] == "SynxDB-4.5.0-build130"
    assert only["display_order"] == 100
    assert only["is_active"] is True
    assert only["is_default"] is True
    assert only["notes"] is None
    # Shape check — must include id + created_at
    assert isinstance(only["id"], int)
    assert "created_at" in only


def test_get_active_only_filter(client: TestClient) -> None:
    """``?active=true`` excludes is_active=0 rows."""
    # Add an inactive row directly via the store helper
    with sqlite_store.get_session() as sess:
        sqlite_store.add_target_version(
            sess,
            name="SynxDB-3.0-legacy",
            display_order=200,
            is_active=False,
            is_default=False,
        )

    # Default GET returns both
    all_rows = client.get("/admin/target-versions").json()
    names = [r["name"] for r in all_rows]
    assert set(names) == {"SynxDB-4.5.0-build130", "SynxDB-3.0-legacy"}

    # ?active=true filters
    active_rows = client.get("/admin/target-versions?active=true").json()
    assert [r["name"] for r in active_rows] == ["SynxDB-4.5.0-build130"]


def test_get_ordering_by_display_order_then_name(client: TestClient) -> None:
    """``ORDER BY display_order ASC, name ASC``."""
    with sqlite_store.get_session() as sess:
        sqlite_store.add_target_version(sess, name="zz-tail", display_order=50, is_active=True)
        sqlite_store.add_target_version(sess, name="aa-head", display_order=50, is_active=True)
        sqlite_store.add_target_version(sess, name="mm-mid", display_order=10, is_active=True)

    rows = client.get("/admin/target-versions").json()
    names = [r["name"] for r in rows]
    # display_order: 10 (mm-mid) < 50 (aa-head, zz-tail tied) < 100 (seed)
    # within order=50, name ASC: aa-head before zz-tail
    assert names == ["mm-mid", "aa-head", "zz-tail", "SynxDB-4.5.0-build130"]


# ---------------------------------------------------------------------------
# POST /admin/target-versions
# ---------------------------------------------------------------------------


def test_post_creates_and_persists(client: TestClient) -> None:
    resp = client.post(
        "/admin/target-versions",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={
            "name": "SynxDB-4.6.0-build1",
            "display_order": 90,
            "is_active": True,
            "is_default": False,
            "notes": "next minor",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "SynxDB-4.6.0-build1"
    assert body["display_order"] == 90
    assert body["is_active"] is True
    assert body["is_default"] is False
    assert body["notes"] == "next minor"
    assert isinstance(body["id"], int)
    # ISO datetime parseable
    datetime.fromisoformat(body["created_at"])

    # GET should now include it (no auth needed for GET)
    listing = client.get("/admin/target-versions").json()
    names = {r["name"] for r in listing}
    assert "SynxDB-4.6.0-build1" in names


def test_post_empty_name_returns_400(client: TestClient) -> None:
    for blank in ("", "   ", "\t\n"):
        resp = client.post(
            "/admin/target-versions",
            headers=client.auth_headers,  # type: ignore[attr-defined]
            json={"name": blank},
        )
        assert resp.status_code == 400, f"expected 400 for name={blank!r}"


def test_post_duplicate_name_returns_409(client: TestClient) -> None:
    # The seed row already uses "SynxDB-4.5.0-build130"
    resp = client.post(
        "/admin/target-versions",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"name": "SynxDB-4.5.0-build130"},
    )
    assert resp.status_code == 409


def test_post_with_is_default_clears_other_defaults(client: TestClient) -> None:
    """Setting a new row's is_default=true MUST clear the previous default."""
    # Seed already has SynxDB-4.5.0-build130 as is_default
    resp = client.post(
        "/admin/target-versions",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"name": "SynxDB-5.0-dev", "is_default": True},
    )
    assert resp.status_code == 201

    listing = client.get("/admin/target-versions").json()
    defaults = [r for r in listing if r["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "SynxDB-5.0-dev"


def test_post_without_is_default_preserves_existing_default(client: TestClient) -> None:
    """is_default defaults to false and must not flip the existing default."""
    resp = client.post(
        "/admin/target-versions",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"name": "SynxDB-experiment"},
    )
    assert resp.status_code == 201
    listing = client.get("/admin/target-versions").json()
    defaults = [r for r in listing if r["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "SynxDB-4.5.0-build130"


# ---------------------------------------------------------------------------
# PATCH /admin/target-versions/{vid}
# ---------------------------------------------------------------------------


def _seed_id(client: TestClient) -> int:
    """Return the id of the seeded SynxDB row."""
    rows = client.get("/admin/target-versions").json()
    return next(r for r in rows if r["name"] == "SynxDB-4.5.0-build130")["id"]


def test_patch_partial_update_notes_only(client: TestClient) -> None:
    vid = _seed_id(client)
    resp = client.patch(
        f"/admin/target-versions/{vid}",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"notes": "GA build"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["notes"] == "GA build"
    # Other fields untouched
    assert body["name"] == "SynxDB-4.5.0-build130"
    assert body["display_order"] == 100
    assert body["is_default"] is True


def test_patch_unknown_id_returns_404(client: TestClient) -> None:
    resp = client.patch(
        "/admin/target-versions/999999",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"notes": "n/a"},
    )
    assert resp.status_code == 404


def test_patch_empty_name_returns_400(client: TestClient) -> None:
    vid = _seed_id(client)
    resp = client.patch(
        f"/admin/target-versions/{vid}",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"name": "   "},
    )
    assert resp.status_code == 400


def test_patch_name_conflict_returns_409(client: TestClient) -> None:
    # Add a second row, then try to rename it to the seed's name
    create = client.post(
        "/admin/target-versions",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"name": "SynxDB-temp"},
    )
    new_id = create.json()["id"]
    resp = client.patch(
        f"/admin/target-versions/{new_id}",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"name": "SynxDB-4.5.0-build130"},
    )
    assert resp.status_code == 409


def test_patch_set_is_default_clears_other_defaults(client: TestClient) -> None:
    """Promote a non-default row to default; the old default flips false."""
    # Add a second row not-default
    create = client.post(
        "/admin/target-versions",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"name": "SynxDB-promote-me", "is_default": False},
    )
    new_id = create.json()["id"]

    # PATCH it to be default
    resp = client.patch(
        f"/admin/target-versions/{new_id}",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"is_default": True},
    )
    assert resp.status_code == 200
    assert resp.json()["is_default"] is True

    # Listing: only one row should have is_default=true
    listing = client.get("/admin/target-versions").json()
    defaults = [r for r in listing if r["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "SynxDB-promote-me"


# ---------------------------------------------------------------------------
# DELETE /admin/target-versions/{vid}
# ---------------------------------------------------------------------------


def test_delete_unreferenced_returns_204(client: TestClient) -> None:
    create = client.post(
        "/admin/target-versions",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"name": "to-be-deleted"},
    )
    vid = create.json()["id"]

    resp = client.delete(
        f"/admin/target-versions/{vid}",
        headers=client.auth_headers,  # type: ignore[attr-defined]
    )
    assert resp.status_code == 204

    # Listing no longer has it
    names = {r["name"] for r in client.get("/admin/target-versions").json()}
    assert "to-be-deleted" not in names


def test_delete_referenced_returns_409_with_run_count(client: TestClient) -> None:
    """If any run row has runs.target_version = <name>, refuse with 409."""
    # Insert a run row that references the seed version's name directly
    # (POST /runs is permissive — we go around it for test isolation).
    with sqlite_store.get_session() as sess:
        sess.execute(
            text(
                "INSERT INTO runs (started_at, status, target_version) "
                "VALUES (CURRENT_TIMESTAMP, 'done', 'SynxDB-4.5.0-build130')"
            )
        )
        sess.execute(
            text(
                "INSERT INTO runs (started_at, status, target_version) "
                "VALUES (CURRENT_TIMESTAMP, 'done', 'SynxDB-4.5.0-build130')"
            )
        )
        sess.commit()

    vid = _seed_id(client)
    resp = client.delete(
        f"/admin/target-versions/{vid}",
        headers=client.auth_headers,  # type: ignore[attr-defined]
    )
    assert resp.status_code == 409
    body = resp.json()
    # FastAPI wraps the detail dict; body["detail"] is the dict we sent
    detail = body["detail"]
    assert detail["run_count"] == 2
    assert "force=true" in detail["detail"]


def test_delete_referenced_with_force_proceeds(client: TestClient) -> None:
    with sqlite_store.get_session() as sess:
        sess.execute(
            text(
                "INSERT INTO runs (started_at, status, target_version) "
                "VALUES (CURRENT_TIMESTAMP, 'done', 'SynxDB-4.5.0-build130')"
            )
        )
        sess.commit()

    vid = _seed_id(client)
    resp = client.delete(
        f"/admin/target-versions/{vid}?force=true",
        headers=client.auth_headers,  # type: ignore[attr-defined]
    )
    assert resp.status_code == 204

    # Row is gone, but the historical run row is preserved (free-text column)
    names = {r["name"] for r in client.get("/admin/target-versions").json()}
    assert "SynxDB-4.5.0-build130" not in names
    with sqlite_store.get_session() as sess:
        result = sess.execute(
            text("SELECT COUNT(*) FROM runs WHERE target_version = 'SynxDB-4.5.0-build130'")
        ).scalar()
        assert result == 1, "force-delete must not touch historical runs"


def test_delete_unknown_id_returns_404(client: TestClient) -> None:
    resp = client.delete(
        "/admin/target-versions/999999",
        headers=client.auth_headers,  # type: ignore[attr-defined]
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth gate (matches existing skip-list pattern)
# ---------------------------------------------------------------------------


def test_get_open_without_auth(client: TestClient) -> None:
    """GET requires no Authorization header (matches /admin/categories)."""
    resp = client.get("/admin/target-versions")
    assert resp.status_code == 200


def test_post_without_auth_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/admin/target-versions",
        json={"name": "no-auth"},
    )
    assert resp.status_code == 401


def test_patch_without_auth_returns_401(client: TestClient) -> None:
    vid = _seed_id(client)
    resp = client.patch(f"/admin/target-versions/{vid}", json={"notes": "x"})
    assert resp.status_code == 401


def test_delete_without_auth_returns_401(client: TestClient) -> None:
    vid = _seed_id(client)
    resp = client.delete(f"/admin/target-versions/{vid}")
    assert resp.status_code == 401
