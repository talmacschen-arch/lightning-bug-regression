"""Tests for GET /cases ``?q=`` filter (M3b-2 / design.md §5.5.3 step 2).

The ``q`` substring filter must match against id, title, description, AND
tags so the ``.claude/skills/add-test-case`` skill can surface
near-duplicate cases regardless of which field the author phrased the
domain words in.

Each test seeds a tmp cases root + an in-memory sqlite DB with the
required categories, then walks the public endpoint. Fixture cases are
deliberately *not* schema-valid against §4.1 (they omit ``procedure`` /
``expected`` / ``steps``) so the endpoint surfaces them with
``status='invalid'`` — the list endpoint never drops invalid files
(``test_api_cases.test_list_does_not_500_on_invalid_yaml_file``), and
the q filter operates on the salvaged fields all the same.
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


def _write_case(cat_dir: Path, case_id: str, **fields: object) -> Path:
    """Write a minimal-but-realistic case YAML for q-filter testing.

    The file ends up at ``<cat_dir>/<case_id>.yaml``. Fields default to
    benign values; tests override ``title`` / ``description`` / ``tags``
    to set the haystack content they care about.
    """
    doc: dict[str, object] = {
        "id": case_id,
        "category": fields.pop("category", "bug_regression"),
        "title": fields.pop("title", "untitled"),
        "status": fields.pop("status", "open"),
        "destructive": fields.pop("destructive", False),
        "description": fields.pop("description", ""),
    }
    tags = fields.pop("tags", None)
    if tags is not None:
        doc["tags"] = tags
    doc.update(fields)

    path = cat_dir / f"{case_id}.yaml"
    # Hand-rolled YAML so description multi-line stays readable and we
    # don't pull in pyyaml's dump quoting heuristics in the test.
    lines = [f"id: {doc['id']}"]
    lines.append(f"category: {doc['category']}")
    lines.append(f"title: {json.dumps(doc['title'])}")
    lines.append(f"status: {doc['status']}")
    lines.append(f"destructive: {str(doc['destructive']).lower()}")
    if tags is not None:
        lines.append(f"tags: {json.dumps(tags)}")
    # description as a JSON-encoded scalar — quotes any embedded newlines/colons.
    lines.append(f"description: {json.dumps(doc['description'])}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def client_with_seeded_cases(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """Build an in-memory DB + tmp cases root, then drop a curated set of
    fixture YAMLs designed to exercise each q-filter haystack field
    independently.

    Layout:

        <tmp>/cases/bug-regression/
            lg-bug-0001-hashjoin-foo.yaml      # matches via id substring
            lg-bug-0002-ndv-optimizer.yaml     # matches via title substring
            lg-bug-0003-uniqueword.yaml        # matches via description
            lg-bug-0004-concurrent-tagged.yaml # matches via tags
        <tmp>/cases/extension/
            lg-ext-0001-optimizer-ext.yaml     # used by combined-filter test
    """
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

    cases_root = tmp_path / "cases"
    bug_dir = cases_root / "bug-regression"
    ext_dir = cases_root / "extension"
    bug_dir.mkdir(parents=True)
    ext_dir.mkdir(parents=True)

    # 1) id-only match.
    _write_case(
        bug_dir,
        "lg-bug-0001-hashjoin-foo",
        title="Some unrelated heading",
        description="An ordinary description without the keyword.",
        tags=["misc"],
    )
    # 2) title-only match (case-insensitive — title has mixed case).
    _write_case(
        bug_dir,
        "lg-bug-0002-ndv-blowup",
        title="Optimizer NDV blow-up on partitioned tables",
        description="Unrelated narrative here.",
        tags=["planner"],
    )
    # 3) description-only match (the new behavior — keyword nowhere else).
    _write_case(
        bug_dir,
        "lg-bug-0003-uniqueword",
        title="Plain title",
        description="This case investigates a quirky-needle-phrase in the runtime path.",
        tags=["misc"],
    )
    # 4) tag-only match.
    _write_case(
        bug_dir,
        "lg-bug-0004-tagged",
        title="Plain title",
        description="Plain description with no keywords.",
        tags=["concurrent-update", "isolation"],
    )
    # 5) null/missing description — must not 500 the endpoint.
    _write_case(
        bug_dir,
        "lg-bug-0005-no-description",
        title="Plain title",
        description="",
        tags=["misc"],
    )
    # 6) Extension category — used by the combined-filter test to ensure
    #    ?category= still narrows the result set even when ?q= would match.
    _write_case(
        ext_dir,
        "lg-ext-0001-optimizer-ext",
        category="extension",
        status="stable",
        title="Optimizer extension entry point",
        description="Unrelated narrative.",
        tags=["planner"],
    )

    monkeypatch.setenv("CASES_ROOT", str(cases_root))
    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(engine)
    engine.dispose()


def _ids(body: list[dict[str, object]]) -> set[str]:
    return {str(c["id"]) for c in body}


def test_q_matches_id_substring(client_with_seeded_cases: TestClient) -> None:
    """?q=hashjoin must match a case whose id contains 'hashjoin' even if
    the title doesn't (regression guard for the id-haystack behavior that
    existed before M3b-2)."""
    resp = client_with_seeded_cases.get("/cases?q=hashjoin")
    assert resp.status_code == 200
    body = resp.json()
    ids = _ids(body)
    assert "lg-bug-0001-hashjoin-foo" in ids
    # No other fixture has "hashjoin" anywhere.
    assert len(ids) == 1, f"unexpected matches: {ids}"


def test_q_matches_title_substring(client_with_seeded_cases: TestClient) -> None:
    """?q=optimizer must be case-insensitive and match the bug case whose
    title contains 'Optimizer' (capital O). The extension case also has
    'Optimizer' in its title so we assert membership rather than equality."""
    resp = client_with_seeded_cases.get("/cases?q=optimizer")
    assert resp.status_code == 200
    ids = _ids(resp.json())
    assert "lg-bug-0002-ndv-blowup" in ids


def test_q_matches_description_substring(client_with_seeded_cases: TestClient) -> None:
    """?q=quirky-needle-phrase must match a case where the keyword is
    ONLY in the description — this is the new M3b-2 behavior. The test
    fails on the old code path that searched id+title only."""
    resp = client_with_seeded_cases.get("/cases?q=quirky-needle-phrase")
    assert resp.status_code == 200
    body = resp.json()
    ids = _ids(body)
    assert ids == {"lg-bug-0003-uniqueword"}, f"description match failed: {ids}"
    # Defensive: confirm description is NOT exposed on the summary payload
    # (out-of-scope decision: keep list response lean for the dropdown).
    assert "description" not in body[0]


def test_q_matches_tag(client_with_seeded_cases: TestClient) -> None:
    """?q=concurrent must match a case whose tag is 'concurrent-update'
    even when neither id nor title contains 'concurrent' (substring on
    joined tags). This is also new M3b-2 behavior."""
    resp = client_with_seeded_cases.get("/cases?q=concurrent")
    assert resp.status_code == 200
    ids = _ids(resp.json())
    assert "lg-bug-0004-tagged" in ids
    # Ensure we didn't accidentally also match anyone else (no other
    # fixture has 'concurrent' anywhere).
    assert ids == {"lg-bug-0004-tagged"}


def test_q_no_match_returns_empty(client_with_seeded_cases: TestClient) -> None:
    """?q=zzz-nonexistent must return [] — never 500, never fall back to
    'return everything'. Also implicitly exercises the missing/empty
    description path (lg-bug-0005-no-description must not raise)."""
    resp = client_with_seeded_cases.get("/cases?q=zzz-nonexistent")
    assert resp.status_code == 200
    assert resp.json() == []


def test_q_combined_with_category(client_with_seeded_cases: TestClient) -> None:
    """?q=optimizer&category=bug_regression must drop the extension-category
    'optimizer-ext' case even though its title would otherwise match.
    The category filter and the q filter compose as AND."""
    resp = client_with_seeded_cases.get("/cases?q=optimizer&category=bug_regression")
    assert resp.status_code == 200
    ids = _ids(resp.json())
    assert "lg-bug-0002-ndv-blowup" in ids
    assert "lg-ext-0001-optimizer-ext" not in ids
    # Every returned id must be from the bug_regression category.
    for c in resp.json():
        assert c["id"].startswith("lg-bug-"), f"non-bug case leaked through: {c['id']}"
