"""Tests for GET /cases + GET /cases/{id} (M1-10 / design.md §4.5).

CASES_ROOT is pointed at the real `cases/` directory in the repo so the
list endpoint walks the 5 bug-regression fixtures. The yaml_loader's
strict §4.1 schema does not yet model the richer (kind/name/setup/
teardown) shape that the existing fixtures use, so each fixture comes
back with status='invalid' but is NOT dropped — the endpoint must still
surface them so the UI can show what needs fixing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.storage import sqlite_store
from app.storage.models import Base, CaseCategory

# repo_root = backend/ -> .. (i.e. lightning-bug-regression/)
REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CASES_DIR = REPO_ROOT / "cases"


@pytest.fixture
def client_with_real_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """In-memory DB seeded with the two §4.5 categories + CASES_ROOT
    pointed at the repo's real `cases/` directory."""
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
                display_name="Extension",
                description=None,
                id_prefix="lg-ext-",
                dir_path="extension",
                status_whitelist=json.dumps(["stable", "experimental", "deprecated", "stub"]),
                default_status="stable",
                display_order=20,
                is_active=True,
            )
        )
        sess.commit()

    monkeypatch.setenv("CASES_ROOT", str(REAL_CASES_DIR))
    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(engine)
    engine.dispose()


def test_list_returns_all_five_bug_regression_cases(
    client_with_real_cases: TestClient,
) -> None:
    """The 5 real M1-original fixtures under `cases/bug-regression/` must
    all show up in the list (even though strict §4.1 validation rejects
    their richer schema; per spec we include them with status='invalid').

    M3a-10 dogfood added 2 more cases (`lg-bug-0006-m3a-dogfood-smoke{,2}`),
    so the test asserts the 5 originals are a **subset** rather than an
    equality — new cases (added via M3a `/cases/submit` web flow or future
    M4a feishu imports) must not break this test."""
    resp = client_with_real_cases.get("/cases")
    assert resp.status_code == 200
    body = resp.json()
    ids = {c["id"] for c in body}
    expected_subset = {
        "lg-bug-0001-hashjoin-right-table",
        "lg-bug-0002-array-unnest-crash",
        "lg-bug-0003-count-no-statistics",
        "lg-bug-0004-ctas-rowcount-zero",
        "lg-bug-0005-lc-ctype-upper",
    }
    assert expected_subset.issubset(ids), f"missing original cases: {expected_subset - ids}"


def test_list_filtered_by_category_bug_regression(
    client_with_real_cases: TestClient,
) -> None:
    """`?category=bug_regression` narrows the scan to just that dir.

    The 5 M1 originals must be present; any extras from M3a-10 dogfood /
    future M4a imports under the same dir are also allowed."""
    resp = client_with_real_cases.get("/cases?category=bug_regression")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 5
    for c in body:
        assert c["id"].startswith("lg-bug-")


def test_list_search_returns_hashjoin_case_only(
    client_with_real_cases: TestClient,
) -> None:
    """Substring search against id+title matches lg-bug-0001 alone."""
    resp = client_with_real_cases.get("/cases?q=hashjoin")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == "lg-bug-0001-hashjoin-right-table"


def test_list_search_case_insensitive(
    client_with_real_cases: TestClient,
) -> None:
    """`q` must be case-insensitive (id is lowercase but title isn't always)."""
    resp = client_with_real_cases.get("/cases?q=HASHJOIN")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_case_returns_raw_yaml_and_parsed_fields(
    client_with_real_cases: TestClient,
) -> None:
    """GET /cases/{id} must return both raw text (yaml_raw) and parsed
    fields so the editor can show the source while UI controls show
    structured metadata."""
    resp = client_with_real_cases.get("/cases/lg-bug-0001-hashjoin-right-table")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "lg-bug-0001-hashjoin-right-table"
    # Raw text must be non-empty and contain the case's id.
    assert "lg-bug-0001-hashjoin-right-table" in body["yaml_raw"]
    # Parsed dict must be present and carry the same id.
    assert body["parsed"] is not None
    assert body["parsed"]["id"] == "lg-bug-0001-hashjoin-right-table"
    # Title surfaces even though strict validation rejects this case.
    assert body["title"]
    assert body["category"] == "bug_regression"


def test_get_case_404_on_unknown_id(
    client_with_real_cases: TestClient,
) -> None:
    """Unknown case_id → 404 (NOT 500)."""
    resp = client_with_real_cases.get("/cases/lg-bug-9999-does-not-exist")
    assert resp.status_code == 404


def test_list_does_not_500_on_invalid_yaml_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Drop a malformed YAML in a tmp cases root + point CASES_ROOT at it.
    The endpoint must include the file as `status='invalid'`, never 500."""
    # Build the same in-memory DB + categories.
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
                display_name="BUG",
                description=None,
                id_prefix="lg-bug-",
                dir_path="bug-regression",
                status_whitelist=json.dumps(["open"]),
                default_status="open",
                display_order=10,
                is_active=True,
            )
        )
        sess.commit()

    # tmp cases root layout: <tmp>/bug-regression/bad.yaml
    cases_root = tmp_path / "cases"
    cat_dir = cases_root / "bug-regression"
    cat_dir.mkdir(parents=True)
    # Deliberately broken YAML (unclosed bracket).
    bad_file = cat_dir / "bad.yaml"
    bad_file.write_text("id: bad\nthis is: [unclosed list\n", encoding="utf-8")

    monkeypatch.setenv("CASES_ROOT", str(cases_root))

    with TestClient(app) as client:
        resp = client.get("/cases")
        assert resp.status_code == 200
        body = resp.json()
        # Exactly one entry, status=invalid, error populated.
        assert len(body) == 1
        assert body[0]["status"] == "invalid"
        assert body[0]["error"] is not None
        assert body[0]["id"] == "bad"  # falls back to filename stem


def test_list_empty_when_no_categories_directories_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A clean repo with no on-disk dirs must return [], not 500."""
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
                display_name="BUG",
                description=None,
                id_prefix="lg-bug-",
                dir_path="bug-regression",
                status_whitelist=json.dumps(["open"]),
                default_status="open",
                display_order=10,
                is_active=True,
            )
        )
        sess.commit()

    monkeypatch.setenv("CASES_ROOT", str(tmp_path))  # no bug-regression subdir
    with TestClient(app) as client:
        resp = client.get("/cases")
        assert resp.status_code == 200
        assert resp.json() == []
