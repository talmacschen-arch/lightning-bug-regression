---
name: report-status
description: Generate the 12-hour rollup status report. Cron-fired by OS crontab via `claude --print "/report-status"`. Reads docs/status/foreman-state.json + git log + gh pr list; writes docs/status/<YYYY-MM-DD-HHMM>.md; commits doc-only and pushes to main. Write-scope is docs/status/ only — no code edits, no external messaging.
---

# /report-status skill

Authoritative spec: `design.md` §15.3 (cron 定时汇报). This file IS the spec —
the `reporter` agent uses these rules verbatim.

## Trigger model (§15.3.1, v1.3)

OS crontab (NOT Claude Code `CronCreate` — that path was abandoned in v1.3 after
implementation showed it's session-only + REPL-idle-gated, which fails under a
long-running foreman session):

```
0 12 * * * cd <repo> && /root/.local/bin/claude --print "/report-status" >> docs/status/cron.log 2>&1
0 0  * * * cd <repo> && /root/.local/bin/claude --print "/report-status" >> docs/status/cron.log 2>&1
```

Each fire = a fresh `claude` process running this skill non-interactively,
fully decoupled from any other claude session (including a running foreman).

## Hard rules

1. **Write-scope = `docs/status/` only.** No edits to `backend/`, `frontend/`,
   `cases/`, `design.md`, `docs/plans/`, `.claude/`, or anything else.
2. **No external messaging.** Feishu / Slack / email push were removed in v1.2.
   The report sits in the repo; the human reads it on their own cadence.
3. **All events go into the next report.** No immediate alerts. Even
   system-level breakage gets `🚨 SYSTEM_ALERT: <one-line>` at the top of
   the next regular report (§15.3.5) — not a separate channel.
4. **Doc-only direct push to main.** Status reports are append-only telemetry;
   skip the PR / review path. Use `git commit` + `git push origin main`. No
   `gh pr create` / `gh pr merge`. Never add a `Co-Authored-By: Claude`
   trailer (per global `~/.claude/CLAUDE.md`).
5. **Be honest about gaps.** If `foreman-state.json` is missing, the report
   says "foreman not running this period." If `git fetch` fails, the report
   still gets written — but with the SYSTEM_ALERT row prepended.

## Workflow (§15.3.2, 6 steps + commit)

```
1. Determine the time window.
   - `to:`   = now (in local timezone, ISO8601)
   - `from:` = previous report's `to:`  (read latest docs/status/*.md frontmatter)
               If no prior report exists, default to: now - 12 hours.

2. Read foreman-state.json.
   path: docs/status/foreman-state.json
   - present → parse: sprint_label / status / round / round_budget /
                       wall_budget_hours / items_done / item_in_progress /
                       items_remaining / needs_human[] / last_failures /
                       started_at / last_heartbeat
   - absent  → flag "foreman_status: not-running" in report frontmatter

3. Collect git activity in window.
   - Make sure local main is up-to-date:
       git fetch origin main          (← if this fails: SYSTEM_ALERT)
       git log --since="<from>" --oneline origin/main

4. Collect PR activity (gh; env GH_TOKEN extracted inline from
   ~/.git-credentials per project memory feedback-gh-token-auto).
   - Merged in window:
       gh pr list --search "merged:>=<from> repo:talmacschen-arch/lightning-bug-regression" \
         --state merged --json number,title,mergedAt
   - Open right now:
       gh pr list --repo talmacschen-arch/lightning-bug-regression --state open \
         --json number,title,state,statusCheckRollup,mergeable,isDraft

5. Surface needs_human[] from foreman-state.json directly into report §4
   (highest visibility) — one bullet per entry.

6. Render docs/status/<YYYY-MM-DD-HHMM>.md per §15.3.4 schema (frontmatter +
   8 sections, see "Report schema" below). Apply SYSTEM_ALERT rules if any
   trigger fired (see "SYSTEM_ALERT triggers" below).

7. Commit + push directly to main (doc-only, no PR):
       git add docs/status/<file>.md
       git commit -m "report: <YYYY-MM-DD HH:MM> rollup"
       git push origin main

8. Exit. No further work; no messaging.
```

## Report schema (§15.3.4 — fixed 8 sections, do not rename)

```markdown
---
generated_at: <ISO8601 with TZ>
from: <ISO8601 with TZ>
to: <ISO8601 with TZ>
foreman_status: running | done | blocked-escalate | budget-exhausted | not-running
sprint: <foreman-state.sprint_label, or "none">
---

<!-- If any SYSTEM_ALERT trigger fired, prepend this single line BEFORE the H1: -->
<!-- 🚨 SYSTEM_ALERT: <one-line symptom — git fetch fail / report gap / gh auth fail / foreman hang> -->

# 进度报告 <YYYY-MM-DD HH:MM>

## 1. tl;dr（一句话）
<sprint label> 进度 <items_done>/<items_done+remaining> 项；foreman <status>（round <N>/<budget>）；**<needs_human count> 项需你决策**（见 §4）。

## 2. 本周期完成（12h 内 merged 的 PR）
- ✅ <item name> — PR #<n> (merged <HH:MM>)
- ...
（若无：写"暂无 merged PR"。）

## 3. 进行中（open PR）
- 🔄 <item name> — PR #<n> (open, CI <state>) — <auto-merge state>
- ...
（若无：写"暂无 open PR"。）

## 4. **需你决策**（⚠️ 不处理则 foreman 卡住）
- **[<needs_human[].kind>]** <needs_human[].summary>
  - 触发 item: <blocking_item>
  - 首次出现: <first_seen_at>，已重试 <attempt_count> 次
  - **怎么回复**：在 GitHub Discussion / Issue 留言，或直接编辑 docs/status/foreman-state.json 的 needs_human[] 把该项移除
（若无：写"暂无需决策项"。）

## 5. 阻塞项（agent 自己解不了的）
- <环境 / 凭据 / 外部数据 / 上游 issue 等>
（若无：写"暂无"。）

## 6. foreman session 状态
- session_id: <foreman-state.session_id>
- 启动: <started_at>
- round: <round> / <round_budget>
- 壁钟: <hours since started_at>h / <wall_budget_hours>h
- last_heartbeat: <last_heartbeat>（距今 <delta>）
- last_failures: <count> 项（最近一项 symptom_hash=<sha>, count=<n>）

## 7. 下周期计划（foreman 拟做）
<items_remaining 前 3~5 项，按优先级>
1. ...
2. ...
3. ...

## 8. 链接
- foreman state: docs/status/foreman-state.json
- 上一次报告: docs/status/<上一份 YYYY-MM-DD-HHMM>.md
- 本周期 git log（inline 5 行）：
  - <sha> <subject>
  - ...
```

## SYSTEM_ALERT triggers (§15.3.5)

Prepend a single `🚨 SYSTEM_ALERT: <one-line>` row before the H1 if **any** of
these fire. Continue rendering the rest of the report regardless — we never
silently bail.

| # | Trigger | One-line text |
|---|---------|---------------|
| 1 | `git fetch origin main` returns non-zero | `🚨 SYSTEM_ALERT: git fetch origin main failed — check network or repo permissions` |
| 2 | Previous report's `to:` > 13 hours ago (a cron fire was missed) | `🚨 SYSTEM_ALERT: previous report >13h old (gap at <prev-to>) — cron may not be firing` |
| 3 | `gh auth status` returns non-zero (or `gh` not available) | `🚨 SYSTEM_ALERT: gh CLI unauthenticated — GH_TOKEN may have expired or scope lost` |
| 4 | `foreman-state.json` exists with `status="running"` but `last_heartbeat` > 30 min stale | `🚨 SYSTEM_ALERT: foreman heartbeat stale (<delta>) while status=running — session may have hung` |

## What this skill does NOT do

- ❌ Edit code (`backend/`, `frontend/`, `cases/`, `.claude/agents/`, `.claude/skills/`).
- ❌ Edit `design.md` or `docs/plans/`.
- ❌ Dispatch other agents (no `Agent` / `Task` tool use).
- ❌ Open PRs (no `gh pr create` — direct push is the right path for telemetry).
- ❌ Send external messages (no Feishu / Slack / email — see v1.2 / Q31).
- ❌ Run code or tests on the cluster.
- ❌ Modify `foreman-state.json` (read-only; foreman owns writes).
- ❌ Wait / retry — if a tool call fails, capture into SYSTEM_ALERT and proceed.

## Tool palette (for the `reporter` agent invoking this skill)

- `Read` — for `docs/status/*.md` (find previous report's `to:`) and
  `docs/status/foreman-state.json`.
- `Bash` — for `git fetch / log`, `gh auth status / pr list`, `git add /
  commit / push`.
- `Glob` — to enumerate `docs/status/*.md` and find the newest.
- `Write` — only path `docs/status/<YYYY-MM-DD-HHMM>.md`.

## Implementation note (M0 → M1 boundary)

M0 step 7 (this commit) lands the **spec**. The `reporter` agent (.claude/
agents/reporter.md, M0 step 3 already landed) follows this spec. M0 step 8
will register the OS crontab entries so the skill actually fires on schedule.
M0 step 9 will run the first foreman dry-run to populate
`foreman-state.json`, after which the first cron report has real data to
render.

Until step 8/9 complete, `/report-status` can be invoked manually for
end-to-end smoke testing — it will simply note "foreman not running" /
"no prior reports" and write a near-empty but well-structured report.
