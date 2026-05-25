"""Tests for GET /admin/categories (M1-10 / design.md §4.5)."""

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


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """In-memory DB + seeded categories + seeded admin user (v1.17).

    `c.auth_headers` is attached: `{Authorization: Bearer <token>}` —
    use on all mutation requests (skip-list POST/DELETE, delete-case,
    etc.). GETs don't need the header.
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

    seed_admin_if_missing()

    with TestClient(app) as c:
        login = c.post("/auth/login", json={"username": "admin", "password": "admin"})
        assert login.status_code == 200, f"seeded admin login failed: {login.json()}"
        token = login.json()["token"]
        c.auth_headers = {"Authorization": f"Bearer {token}"}  # type: ignore[attr-defined]
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
        headers=client.auth_headers,  # type: ignore[attr-defined]
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

    # GET should return the row (GETs don't require auth)
    listing = client.get("/admin/skip-list").json()
    assert len(listing) == 1
    assert listing[0]["id"] == body["id"]


def test_create_skip_list_entry_rejects_blank_required_fields(
    client: TestClient,
) -> None:
    resp = client.post(
        "/admin/skip-list",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"case_id": "  ", "reason": "x"},
    )
    assert resp.status_code == 400
    resp = client.post(
        "/admin/skip-list",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"case_id": "y", "reason": ""},
    )
    assert resp.status_code == 400


def test_delete_skip_list_entry(client: TestClient) -> None:
    resp = client.post(
        "/admin/skip-list",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"case_id": "lg-bug-X", "reason": "test"},
    )
    eid = resp.json()["id"]
    del_resp = client.delete(
        f"/admin/skip-list/{eid}",
        headers=client.auth_headers,  # type: ignore[attr-defined]
    )
    assert del_resp.status_code == 204
    # GET shows it's gone
    assert client.get("/admin/skip-list").json() == []


def test_delete_skip_list_404_for_unknown_id(client: TestClient) -> None:
    resp = client.delete(
        "/admin/skip-list/999999",
        headers=client.auth_headers,  # type: ignore[attr-defined]
    )
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
# Bearer-token auth gate (v1.17+ replaces M6-4 X-Admin-Password env pattern)
# ---------------------------------------------------------------------------


def test_mutation_without_bearer_token_401(client: TestClient) -> None:
    """No Authorization header → mutating endpoint returns 401."""
    resp = client.post(
        "/admin/skip-list",
        json={"case_id": "lg-bug-no-auth", "reason": "no header"},
    )
    assert resp.status_code == 401


def test_mutation_with_invalid_bearer_token_401(client: TestClient) -> None:
    resp = client.post(
        "/admin/skip-list",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={"case_id": "lg-bug-bad-token", "reason": "bad token"},
    )
    assert resp.status_code == 401


def test_mutation_with_valid_bearer_token_201(client: TestClient) -> None:
    """Sanity: the fixture-seeded admin user's token works on mutations."""
    resp = client.post(
        "/admin/skip-list",
        headers=client.auth_headers,  # type: ignore[attr-defined]
        json={"case_id": "lg-bug-with-token", "reason": "with bearer"},
    )
    assert resp.status_code == 201


def test_get_endpoints_remain_open_without_token(client: TestClient) -> None:
    """GETs are open — no Authorization header required."""
    assert client.get("/admin/skip-list").status_code == 200
    assert client.get("/admin/categories").status_code == 200


# ---------------------------------------------------------------------------
# /admin/external-services — read-only browser (v1.15+)
# ---------------------------------------------------------------------------


def test_external_services_empty_when_dir_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing EXTERNAL_DEPS_DIR → empty list, no error."""
    monkeypatch.setenv("EXTERNAL_DEPS_DIR", str(tmp_path / "does-not-exist"))
    resp = client.get("/admin/external-services")
    assert resp.status_code == 200
    assert resp.json() == []


def test_external_services_lists_yml_files_with_content(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each .yml file in the dir appears with name/filename/size/mtime/content."""
    ext_dir = tmp_path / "external"
    ext_dir.mkdir()
    (ext_dir / "elasticsearch.yml").write_text(
        "host: 192.168.195.203\nport: 9200\n", encoding="utf-8"
    )
    (ext_dir / "dut.yml").write_text(
        "host: 127.0.0.1\nport: 5432\nuser: gpadmin\ndatabase: gpadmin\n",
        encoding="utf-8",
    )
    # non-YAML file should be ignored
    (ext_dir / "README.md").write_text("# external services", encoding="utf-8")
    monkeypatch.setenv("EXTERNAL_DEPS_DIR", str(ext_dir))

    resp = client.get("/admin/external-services")
    assert resp.status_code == 200
    items = resp.json()
    names = {i["name"] for i in items}
    assert names == {"dut", "elasticsearch"}

    by_name = {i["name"]: i for i in items}
    es = by_name["elasticsearch"]
    assert es["filename"] == "elasticsearch.yml"
    assert es["size_bytes"] > 0
    assert "host: 192.168.195.203" in es["content"]
    assert "modified_at" in es
    assert es["parse_error"] is None


def test_external_services_surfaces_parse_error_in_body(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A malformed YAML must not 500 — surface error in row's `parse_error`."""
    ext_dir = tmp_path / "external"
    ext_dir.mkdir()
    (ext_dir / "broken.yml").write_text("- a\n- b\n", encoding="utf-8")  # list, not dict
    (ext_dir / "invalid.yml").write_text("this: [unclosed", encoding="utf-8")
    (ext_dir / "ok.yml").write_text("host: 10.0.0.1\n", encoding="utf-8")
    monkeypatch.setenv("EXTERNAL_DEPS_DIR", str(ext_dir))

    resp = client.get("/admin/external-services")
    assert resp.status_code == 200
    items = {i["name"]: i for i in resp.json()}

    assert items["broken"]["parse_error"] is not None
    assert "mapping" in items["broken"]["parse_error"]
    assert items["invalid"]["parse_error"] is not None
    assert "parse error" in items["invalid"]["parse_error"].lower()
    assert items["ok"]["parse_error"] is None


def test_external_services_accepts_both_yml_and_yaml_extensions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ext_dir = tmp_path / "external"
    ext_dir.mkdir()
    (ext_dir / "a.yml").write_text("host: x\n", encoding="utf-8")
    (ext_dir / "b.yaml").write_text("host: y\n", encoding="utf-8")
    monkeypatch.setenv("EXTERNAL_DEPS_DIR", str(ext_dir))
    items = client.get("/admin/external-services").json()
    names = {i["name"] for i in items}
    assert names == {"a", "b"}


# ---------------------------------------------------------------------------
# DELETE /admin/cases/{case_id} (v1.16+)
# ---------------------------------------------------------------------------


def _seed_test_case_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Set up a fake cases/ root with one category dir + 1 case YAML."""
    cases_root = tmp_path / "cases"
    cat_dir = cases_root / "bug-regression"
    cat_dir.mkdir(parents=True)
    case_yaml = cat_dir / "lg-bug-test-delete.yaml"
    case_yaml.write_text(
        "id: lg-bug-test-delete\n"
        "category: bug_regression\n"
        "status: open\n"
        "title: dummy\n"
        "defaults: {database: gpadmin}\n"
        "steps:\n  - {id: s1, kind: shell, cmd: 'echo ok'}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CASES_ROOT", str(cases_root))
    return case_yaml


def test_delete_case_removes_yaml_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case_yaml = _seed_test_case_dir(monkeypatch, tmp_path)
    assert case_yaml.exists()

    resp = client.delete(
        "/admin/cases/lg-bug-test-delete",
        headers=client.auth_headers,  # type: ignore[attr-defined]
    )
    assert resp.status_code == 204
    assert not case_yaml.exists()


def test_delete_case_404_when_not_found(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_test_case_dir(monkeypatch, tmp_path)
    resp = client.delete(
        "/admin/cases/lg-bug-not-real",
        headers=client.auth_headers,  # type: ignore[attr-defined]
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_delete_case_path_traversal_attempt_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """case_id with .. or path separator can't escape — iter_case_files
    only yields files inside category dirs, so a `..` case_id has no
    matching file = 404 (route param doesn't even allow raw `/`)."""
    _seed_test_case_dir(monkeypatch, tmp_path)
    resp = client.delete(
        "/admin/cases/..%2Fevil",
        headers=client.auth_headers,  # type: ignore[attr-defined]
    )
    assert resp.status_code in (404, 400)


def test_delete_case_preserves_case_results_history(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Historical case_results rows must NOT be touched by case delete —
    that's the whole point: delete the definition, keep the audit trail."""
    case_yaml = _seed_test_case_dir(monkeypatch, tmp_path)

    # Seed a fake run + case_result referencing the case_id
    from datetime import datetime as _dt

    with sqlite_store.get_session() as sess:
        run = sqlite_store.create_run(sess, started_at=_dt.utcnow())
        sqlite_store.finish_run(
            sess,
            run.id,
            status="done",
            finished_at=_dt.utcnow(),
            total=1,
            passed=1,
            failed=0,
            skipped=0,
        )
        sqlite_store.insert_case_result(
            sess,
            run_id=run.id,
            case_id="lg-bug-test-delete",
            status="pass",
            duration_ms=42,
        )
        run_id = run.id

    resp = client.delete(
        "/admin/cases/lg-bug-test-delete",
        headers=client.auth_headers,  # type: ignore[attr-defined]
    )
    assert resp.status_code == 204
    assert not case_yaml.exists()

    # case_results row still there
    with sqlite_store.get_session() as sess:
        rows = sqlite_store.list_case_results(sess, run_id)
        assert len(rows) == 1
        assert rows[0].case_id == "lg-bug-test-delete"


def test_delete_case_requires_bearer_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_test_case_dir(monkeypatch, tmp_path)

    # Without Authorization header → 401
    resp = client.delete("/admin/cases/lg-bug-test-delete")
    assert resp.status_code == 401

    # With valid Bearer token → 204
    resp = client.delete(
        "/admin/cases/lg-bug-test-delete",
        headers=client.auth_headers,  # type: ignore[attr-defined]
    )
    assert resp.status_code == 204
