#!/usr/bin/env python3
"""status-drift.py — 用最新测试结果对账 YAML 里手工维护的 `status` 字段。

背景（design.md §4.3 L388 + §14 R28 + §16.2）：
  case 的 `status`（open/fixed/wontfix/stub）是**手工元数据**，不参与判定，也
  不会因为某次跑绿就自动变。它和 runs.db 里每次 run 的 verdict（pass/fail/skip）
  是两条独立的轴。时间一长，`status` 会与实际 verdict 漂移——最典型的是 BUG
  早就修好、跑绿了，但 YAML 还停在 `open`（stale label）。

本脚本做的是**对账 + 提示**，不改任何文件：
  - 🔴 REGRESSION   : status=fixed 但最近 N 次 run 里出现过 fail（修好的又坏了）
  - 🟢 CANDIDATE    : status=open 但最近 N 次 run **连续全 pass**（疑似已修，可 flip）
  - ⏳ THIN-EVIDENCE: status=open 且最近 pass 但采样不足 N 次（不建议 flip，防假阳性）
  - ✓  EXPECTED     : status=open 且最近仍 fail（BUG 仍复现，符合预期）
  - ⚪ NO-DATA      : 最近 run 里该 case 全是 skip / 没有记录

为什么用「连续 N 次 run 全 pass」而不是「最近一次 pass」：
  bug-0009 的教训（§14 R28）——间歇性 BUG 单次跑绿是假阳性。跨 run 的连续 pass
  是额外的稳健性闸门。注意这与 case **单次 run 内**的重复轮次（rounds，由 case
  YAML 自己控制，如 bug-0009 的 10 轮）是不同维度，二者叠加。

  CANDIDATE / REGRESSION 只是**给人看的建议**，flip status 仍需人确认 + 走 PR
  回填 fixed_version + 证据链。wontfix 永远是人的判定，本脚本不碰。

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

# status 语义按「BUG 修复轴」推导；只处理落在这条轴上的 status 值。
# extension 的 stable/experimental/... 是「成熟度轴」，不参与，自然被过滤掉。
BUGFIX_AXIS = {"open", "fixed"}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


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


def classify(status: str, verdicts: list[str], rounds: int) -> tuple[str, str]:
    """返回 (category, 说明)。verdicts 为该 case 最近若干 run 的 verdict（新→旧）。"""
    non_skip = [v for v in verdicts if v in ("pass", "fail", "error")]
    if status == "fixed":
        if any(v in ("fail", "error") for v in non_skip):
            return "REGRESSION", f"最近 {len(non_skip)} 次有 fail/error（修好的又坏了）"
        if non_skip:
            return "OK", "最近仍 pass，一致"
        return "NO-DATA", "最近 run 无有效 verdict（全 skip/无记录）"
    # status == open
    if not non_skip:
        return "NO-DATA", "最近 run 无有效 verdict（全 skip/无记录）"
    if all(v == "pass" for v in non_skip):
        if len(non_skip) >= rounds:
            return "CANDIDATE", f"最近连续 {len(non_skip)} 次全 pass（≥阈值 {rounds}，疑似已修）"
        return "THIN-EVIDENCE", f"最近 {len(non_skip)} 次 pass 但 < 阈值 {rounds}（采样不足，先别 flip）"
    return "EXPECTED", "最近仍 fail（BUG 仍复现，符合 open 预期）"


ORDER = ["REGRESSION", "CANDIDATE", "THIN-EVIDENCE", "NO-DATA", "EXPECTED", "OK"]
ICON = {
    "REGRESSION": "🔴", "CANDIDATE": "🟢", "THIN-EVIDENCE": "⏳",
    "NO-DATA": "⚪", "EXPECTED": "✓", "OK": "·",
}


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
        if c["status"] not in BUGFIX_AXIS:
            continue  # wontfix/stub/stable/... 不在 BUG 修复轴上，跳过
        cat, why = classify(c["status"], verdicts.get(c["id"], []), args.rounds)
        rows.append({**c, "drift": cat, "why": why})
    rows.sort(key=lambda r: (ORDER.index(r["drift"]), r["id"]))

    actionable = [r for r in rows if r["drift"] in ("REGRESSION", "CANDIDATE", "THIN-EVIDENCE")]
    n_reg = sum(1 for r in rows if r["drift"] == "REGRESSION")
    n_cand = sum(1 for r in rows if r["drift"] == "CANDIDATE")

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
                sug = {
                    "REGRESSION": "查回归，勿盲目改 status",
                    "CANDIDATE": f"人核后 flip fixed + 回填 fixed_version={latest_target!r}",
                    "THIN-EVIDENCE": "多跑几次再看",
                }[r["drift"]]
                print(f"| {ICON[r['drift']]} | `{r['id']}` | {r['status']} | {r['drift']} | {r['why']} | {sug} |")
        print()
        print("> status flip 仍需人确认 + 走 PR；wontfix 永远手工。本脚本只对账不改文件。")
    else:
        for r in rows:
            print(f"{ICON[r['drift']]} {r['drift']:13s} {r['id']:52s} status={r['status']:6s} {r['why']}")

    return 2 if n_reg else 0


if __name__ == "__main__":
    raise SystemExit(main())
