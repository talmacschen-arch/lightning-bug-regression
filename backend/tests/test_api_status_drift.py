"""Wiring tests for GET /cases/status-drift.

铁律2：不是自 seed 后单测 classify，而是驱动完整链路——扫盘拿 YAML status +
查 DB 拿 verdict + classify + response counts——断言每种漂移在真实 wiring 下
都被算到。四个 fixture case 各命中一类漂移。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.storage import sqlite_store
from app.storage.models import Base, CaseCategory

# 每个 case → 每个 run 的 verdict（run 顺序 = 旧→新，即 run1, run2, run3）。
# newest(run3) 决定 REGRESSION/EXPECTED 判定。
CASE_VERDICTS = {
    "bug-t-reg": ("fixed", ["pass", "pass", "fail"]),   # fixed 但最新 fail → REGRESSION
    "bug-t-cand": ("open", ["pass", "pass", "pass"]),   # open 连续 3 pass → CANDIDATE
    "bug-t-exp": ("open", ["fail", "fail", "fail"]),    # open 仍 fail → EXPECTED
    "bug-t-ok": ("fixed", ["pass", "pass", "pass"]),    # fixed 仍 pass → OK
    "bug-t-wontfix": ("wontfix", ["skip", "skip", "skip"]),  # 不在 BUG 修复轴 → 应被排除
}


def _write_case(cases_dir: Path, case_id: str, status: str) -> None:
    # 最小但能过 §4.1 strict 校验的 case（_summary_from_raw 跑 load_case；
    # 不合规会被判 status='invalid' 从而排除，测不到漂移 wiring）。
    (cases_dir / f"{case_id}.yaml").write_text(
        f"""id: {case_id}
category: bug_regression
status: {status}
title: t {case_id}
description: d
procedure: p
expected: e
steps:
  - name: s
    kind: sql
    sql: "SELECT 1"
    expect:
      scalar: 1
""",
        encoding="utf-8",
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # 1) 临时 cases 目录 + bug-regression 子目录 + 5 个最小 YAML
    cases_dir = tmp_path / "cases" / "bug-regression"
    cases_dir.mkdir(parents=True)
    for cid, (status, _) in CASE_VERDICTS.items():
        _write_case(cases_dir, cid, status)
    monkeypatch.setenv("CASES_ROOT", str(tmp_path / "cases"))

    # 2) in-memory DB + patch engine
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, class_=Session
    )
    monkeypatch.setattr(sqlite_store, "_engine", engine, raising=False)
    monkeypatch.setattr(sqlite_store, "_SessionLocal", SessionLocal, raising=False)
    monkeypatch.setattr(sqlite_store, "init_engine", lambda url: None)

    with SessionLocal() as sess:
        sess.add(CaseCategory(
            name="bug_regression", display_name="BUG", description=None,
            id_prefix="bug-", dir_path="bug-regression",
            status_whitelist=json.dumps(["open", "fixed", "wontfix", "stub"]),
            default_status="open", display_order=10, is_active=True,
        ))
        sess.commit()
        # 3) seed 3 个 done run（run1..run3，旧→新），每 run 给每个 case 一条 verdict
        for i in range(3):
            run = sqlite_store.create_run(
                sess, started_at=datetime(2026, 1, 1 + i, tzinfo=UTC),
                target_version="BUILD-777", total=len(CASE_VERDICTS),
            )
            for cid, (_status, verdicts) in CASE_VERDICTS.items():
                sqlite_store.insert_case_result(
                    sess, run_id=run.id, case_id=cid, status=verdicts[i]
                )
            sqlite_store.finish_run(
                sess, run.id, status="done",
                finished_at=datetime(2026, 1, 1 + i, tzinfo=UTC),
            )
        sess.commit()

    return TestClient(app)


def test_status_drift_classifies_every_case_via_full_wiring(client: TestClient):
    r = client.get("/cases/status-drift", params={"rounds": 3})
    assert r.status_code == 200
    d = r.json()

    assert d["rounds"] == 3
    assert d["latest_target"] == "BUILD-777"
    # run_ids newest-first
    assert d["run_ids"] == sorted(d["run_ids"], reverse=True)
    assert len(d["run_ids"]) == 3

    drift_by_id = {it["id"]: it["drift"] for it in d["items"]}
    # wontfix 不在 BUG 修复轴上 → 必须被排除
    assert "bug-t-wontfix" not in drift_by_id
    # 四类漂移各自命中（这才证明 wiring 真跑到分类，而非 unit 自 seed）
    assert drift_by_id["bug-t-reg"] == "REGRESSION"
    assert drift_by_id["bug-t-cand"] == "CANDIDATE"
    assert drift_by_id["bug-t-exp"] == "EXPECTED"
    assert drift_by_id["bug-t-ok"] == "OK"

    assert d["regression_count"] == 1
    assert d["candidate_count"] == 1


def test_candidate_suggestion_carries_latest_target(client: TestClient):
    d = client.get("/cases/status-drift", params={"rounds": 3}).json()
    cand = next(it for it in d["items"] if it["id"] == "bug-t-cand")
    assert cand["suggestion"] is not None
    assert "BUILD-777" in cand["suggestion"]  # 回填建议带上验证 build
    assert cand["verdicts"] == ["pass", "pass", "pass"]


def test_regression_ranked_before_ok(client: TestClient):
    items = client.get("/cases/status-drift", params={"rounds": 3}).json()["items"]
    ids = [it["id"] for it in items]
    assert ids.index("bug-t-reg") < ids.index("bug-t-ok")


def test_thin_evidence_when_rounds_exceeds_history(client: TestClient):
    # 阈值 5 但只有 3 次 run：连续 pass 的 open case 采样不足 → THIN-EVIDENCE，不升 CANDIDATE
    d = client.get("/cases/status-drift", params={"rounds": 5}).json()
    drift_by_id = {it["id"]: it["drift"] for it in d["items"]}
    assert drift_by_id["bug-t-cand"] == "THIN-EVIDENCE"
    assert d["candidate_count"] == 0
