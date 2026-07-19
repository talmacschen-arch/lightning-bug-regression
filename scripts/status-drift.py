#!/usr/bin/env python3
"""status-drift.py — 用最新测试结果对账 YAML 里手工维护的 `status` 字段。

背景（design.md §4.3 L388 + §14 R28 + §16.2）：
  case 的 `status`（open/fixed/wontfix/stub）是**手工元数据**，不参与判定，也
  不会因为某次跑绿就自动变。它和 runs.db 里每次 run 的 verdict（pass/fail/skip）
  是两条独立的轴。时间一长，`status` 会与实际 verdict 漂移——最典型的是 BUG
  早就修好、跑绿了，但 YAML 还停在 `open`（stale label）。

本脚本做的是**对账 + 提示**，不改任何文件。漂移分类与阈值判定复用后端的单一真源
  `backend/app/utils/status_drift.py`（§14 R26/铁律5：classify 不许两处实现），
  与 `GET /cases/status-drift` 前端卡片用的是同一份逻辑。

退出码：有 REGRESSION → 2；否则 → 0（CANDIDATE 只提示不改退出码）。
用法：
  python3 scripts/status-drift.py [--rounds N] [--db PATH] [--cases DIR] [--format md|text]
挂接：在 scripts/cron-report-status.sh 生成 rollup 时追加本脚本的 md 输出，或作为
  CI 的一个 informational step（REGRESSION 时 exit 2 可当 gate）。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import yaml


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


# 复用后端判定核心。脚本本就读 backend/data/runs.db，这里把 backend 加进
# sys.path 以 import 那份纯逻辑（classify / 常量 / ICON 全在那）。
sys.path.insert(0, str(repo_root() / "backend"))
from app.utils import status_drift  # noqa: E402


def load_case_status(cases_dir: Path) -> list[dict]:
    """扫盘读每个 case 的 id / status / 相对路径。用 safe_load 只取顶层字段。"""
    out: list[dict] = []
    for p in sorted(cases_dir.rglob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        cid = doc.get("id")
        status = doc.get("status")
        if not cid or not status:
            continue
        out.append({"id": cid, "status": status, "path": str(p.relative_to(repo_root()))})
    return out


def recent_verdicts(db: Path, rounds: int) -> tuple[list[int], dict[str, list[str]], str | None]:
    """返回 (最近 rounds 个 done run 的 id 列表[新→旧], {case_id: [verdict 新→旧]}, 最新 target_version)。"""
    con = sqlite3.connect(str(db))
    try:
        run_rows = con.execute(
            "SELECT id, target_version FROM runs WHERE status='done' ORDER BY id DESC LIMIT ?",
            (rounds,),
        ).fetchall()
        run_ids = [r[0] for r in run_rows]
        latest_target = run_rows[0][1] if run_rows else None
        verdicts: dict[str, list[str]] = {}
        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            rows = con.execute(
                f"SELECT run_id, case_id, status FROM case_results WHERE run_id IN ({placeholders})",
                run_ids,
            ).fetchall()
            by_case: dict[str, dict[int, str]] = {}
            for run_id, case_id, st in rows:
                by_case.setdefault(case_id, {})[run_id] = st
            for case_id, m in by_case.items():
                verdicts[case_id] = [m[rid] for rid in run_ids if rid in m]
        return run_ids, verdicts, latest_target
    finally:
        con.close()


def suggestion(drift: str, latest_target: str | None) -> str:
    if drift == status_drift.REGRESSION:
        return "查回归，勿盲目改 status"
    if drift == status_drift.CANDIDATE:
        return f"人核后 flip fixed + 回填 fixed_version={latest_target!r}"
    if drift == status_drift.THIN_EVIDENCE:
        return "多跑几次再看"
    return ""


def main() -> int:
    root = repo_root()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rounds", type=int, default=3, help="连续全 pass 认定 CANDIDATE 的 run 次数阈值（默认 3）")
    ap.add_argument("--db", type=Path, default=root / "backend" / "data" / "runs.db")
    ap.add_argument("--cases", type=Path, default=root / "cases")
    ap.add_argument("--format", choices=["md", "text"], default="md")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"error: db not found: {args.db}", file=sys.stderr)
        return 1

    cases = load_case_status(args.cases)
    run_ids, verdicts, latest_target = recent_verdicts(args.db, args.rounds)

    rows = []
    for c in cases:
        if c["status"] not in status_drift.BUGFIX_AXIS:
            continue  # wontfix/stub/stable/... 不在 BUG 修复轴上，跳过
        drift, why = status_drift.classify(c["status"], verdicts.get(c["id"], []), args.rounds)
        rows.append({**c, "drift": drift, "why": why})
    rows.sort(key=lambda r: (status_drift.DRIFT_ORDER.index(r["drift"]), r["id"]))

    actionable = [r for r in rows if r["drift"] in status_drift.ACTIONABLE]
    n_reg = sum(1 for r in rows if r["drift"] == status_drift.REGRESSION)
    n_cand = sum(1 for r in rows if r["drift"] == status_drift.CANDIDATE)

    if args.format == "md":
        print("## status 漂移对账")
        print()
        print(f"- 最近 run: {run_ids or '无'}（阈值 rounds={args.rounds}，最新 target={latest_target!r}）")
        print(f"- 需处理: 🔴 REGRESSION×{n_reg} · 🟢 CANDIDATE×{n_cand}")
        print()
        if not actionable:
            print("✅ 无漂移：所有 open/fixed 的 case 与最近测试结果一致。")
        else:
            print("| | case | 当前 status | 漂移 | 依据 | 建议 |")
            print("|---|---|---|---|---|---|")
            for r in actionable:
                icon = status_drift.ICON[r["drift"]]
                print(f"| {icon} | `{r['id']}` | {r['status']} | {r['drift']} | {r['why']} | {suggestion(r['drift'], latest_target)} |")
        print()
        print("> status flip 仍需人确认 + 走 PR；wontfix 永远手工。本脚本只对账不改文件。")
    else:
        for r in rows:
            icon = status_drift.ICON[r["drift"]]
            print(f"{icon} {r['drift']:13s} {r['id']:52s} status={r['status']:6s} {r['why']}")

    return 2 if n_reg else 0


if __name__ == "__main__":
    raise SystemExit(main())
