# M0-validate sprint — foreman dry-run

foreman 入口文件（design.md §13.0-E：固定位置 `docs/plans/<sprint-label>.md`，markdown `- [ ] <id> <description>` 待办列表，完成项改 `- [x]` 走 doc-only commit）。

**目的**：M0 step 9——首次让 foreman 跑一个 trivial sprint，验证 §15.1 verify loop / §15.2 GitHub auto-merge / §15.3 reporter 三件套全链路通；非测代码正确性，是测 foreman→specialist→PR→auto-merge→state.json 路径本身。

权威设计：`design.md` §13.1 step 9 + §15.1 (foreman) + §15.2.1 (specialist 5 步 PR 收口)。

## 任务列表

- [x] M0v-1 把 `README.md` 第 12 行的 "design.md（v1.3，1700+ 行）" 更新成对应当前 design.md 实际行数（用 `wc -l design.md` 取数；写作 "X+ 行" 形式以避免每次微改 design 都 stale），单 PR、auto-merge

## 完成定义

- foreman 把 M0v-1 标 `- [x]` 后 session 退出 `status=done`；
- `docs/status/foreman-state.json` 落地，schema 符合 design.md §15.1.3，`items_done[]` 含该 PR URL + `merged_at`；
- PR 实际 merged 到 main（不 squash 也行——`gh pr merge --auto --squash` 触发 GitHub squash-only）；
- 下一份 reporter 报告（手动或下次 cron fire）§2 列出该 PR。

## 失控防护

- 同症状 fail 2 次 → escalate（写 `needs_human[]`，foreman 退出）
- 10 round 或 2h budget → BUDGET-EXHAUSTED 退出
- 任何阻塞（doc-writer 找不到 README、git push 401、CI 永远 in_progress 等）写进 `last_failures[]`
