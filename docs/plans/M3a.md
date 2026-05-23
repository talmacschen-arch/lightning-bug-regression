# M3a sprint — Web 录入路径

foreman 入口文件（design.md §13.0-E）。M3a = `/cases/new` 双入口编辑器 + Validate → Try → Save 三段闸门 + LLM 描述路径 stub + `/cases/submit` 真 PR 流程。

权威设计：`design.md`
- §6.1（前端路由）+ §6.2 关键交互（三段闸门）+ §6.4 R1~R7 前端强约束
- §13.7（M3a 子步骤计划，本 sprint 的来源）
- §5.4（描述 → YAML 路径概念）
- §14 R26 / R27（M3a 触发：endpoint 必须复用模块 / 路径配置显式）

§14 预付教训 — 写代码 + reviewer cross-reference 必看：
- **R2**（contract test）：M3a-8 必有 Playwright contract test `page.route("**/api/cases/submit", ...)` + `postDataJSON()` 断言 body shape，**禁止**只断 button 渲染
- **R4b**（不硬编码 category）：编辑器若有 category 下拉，必须从 `GET /admin/categories` 拉
- **R6**（data-testid）：编辑器 / 三个 button / Validate / Try / Save 全 data-testid
- **R7**（ErrorBoundary）：M2-4 已建，M3a-4 编辑器挂载到 root layout 下，不要破坏外层 wrap
- **R26**（dual code path）：M3a-1 `/cases/validate` 必须复用 `yaml_loader.parse + case_normalizer.normalize_case`；M3a-2 `/cases/try` 必须复用 `dsn_builder + SqlSessionPool` + 与 POST /runs 同一份 orchestrator 调用代码（只是 store 不写 DB）。**禁止 inline 一份新校验 / 新调度逻辑**
- **R27**（路径配置）：M3a-3 `git push` 操作的 cwd 与 `CASES_ROOT` 配置必须 explicit，不能依赖 uvicorn 启动时偶然 cwd
- **R24**（specialist 本地 ci-gate triplet）：每个 PR commit 前必须真跑 `tsc + lint + vitest + ruff + pytest`（前端/后端按改动范围），脑内推断"应该绿"不算
- **R25**（foreman 走 wrapper）：dispatch foreman 一律 `scripts/dispatch-foreman.sh`

reviewer 必须按 §14 cross-reference + §6.4 8 条逐项核对（详 `.claude/agents/reviewer.md` step 5）。

## 任务列表（按依赖图 + 优先级）

### Sprint M3a-backend — 3 个 endpoint（可并行）

- [x] M3a-1 `POST /cases/validate` endpoint：`backend/app/api/cases.py` 加 `class ValidateRequest(BaseModel): yaml: str` + `class ValidateResponse(BaseModel): ok: bool, errors: list[dict[str, str]]`。endpoint body：先 `yaml.safe_load` → 复用 `yaml_loader.parse` 校验 schema → 复用 `case_normalizer.normalize_case` 校验 step kind / 必填字段。失败收集到 errors list 返回。**§14 R26 强约束**：直接 import `yaml_loader` 和 `case_normalizer`，禁止 copy-paste 校验逻辑。配测试 `test_api_validate.py` 覆盖 happy path + 多种 yaml error
- [x] M3a-2 `POST /cases/try` endpoint：`backend/app/api/cases.py` 加 `class TryRequest(BaseModel): yaml: str` + `class TryResponse(BaseModel): step_results: list[StepResultOut]`。body：parse + normalize → 起 `SqlSessionPool(dsn_map_from_env([case]))` (复用 M2 hotfix #2 `dsn_builder.py`) → 调 `orchestrator.run_case` 一次（**不调** run_suite，只跑这一个 case，避免污染 DB）→ 收集 step results 返回。**§14 R26 强约束**：复用 `orchestrator.run_case` + `dsn_builder` 模块，禁止重写一份 dispatcher。artifacts 用临时目录（`tempfile.mkdtemp`），返回前删。配测试 `test_api_try.py` 用 fake sql pool 验 happy + error path
- [x] M3a-3 `POST /cases/submit` endpoint：`backend/app/api/cases.py` 加 `class SubmitRequest(BaseModel): yaml: str, case_id: str, branch_name: str` + `class SubmitResponse(BaseModel): pr_url: str, pr_number: int, branch: str`。body：先调 internal validate（reject 不通过的）→ session-scoped check "本 yaml hash 是否最近 Try 过且过"（reject 未 Try 的，§6.2 闸门）→ `cases_root / category / case_id.yaml` 写文件 → `subprocess.run(["git", "checkout", "-b", branch], cwd=repo_root)` → `git add cases/<file>` + `git commit` + `git push -u origin HEAD` → `gh pr create` + `gh pr merge --auto --squash`。**§14 R27 强约束**：repo_root 通过 env `LBR_REPO_ROOT` 配（默认从 `__file__` 推 3 级 parent），cwd 显式。配测试 `test_api_submit.py` 用 mock subprocess（不真打 git/gh）
- [x] M3a-3.5 **session-scoped Try cache**（M3a-2 / M3a-3 配套）：在 FastAPI app state（`app.state.try_pass_cache: dict[str, datetime]`，key = yaml content sha256，value = pass timestamp）记录每次 Try pass 的 yaml hash + ts。M3a-3 submit 时检查 hash 是否在 cache 且 ts < 1 小时前；不在 → 拒绝 + 提示"必须先 Try 通过"。这是 §6.2 三段闸门 backend 端的强校验

### Sprint M3a-frontend-skeleton — 编辑器骨架（依赖 M3a-1/2/3 stub）

- [ ] M3a-4 `/cases/new` editor page 骨架：`frontend/src/routes/CaseNewPage.tsx`。布局：上方 Tab（A/B 入口）+ 中间 textarea（plain，先不 monaco，后期 M5 升级）+ 下方 3 按钮（Validate / Try / Save） + 右侧 step result panel。`data-testid` 全标（§14 R6）。`App.tsx` 加 `<Route path="/cases/new" element={<CaseNewPage />} />`，导航栏加链接

### Sprint M3a-frontend-flow — 双入口 + 三段闸门（依赖 M3a-4）

- [ ] M3a-5 入口 A「从描述生成」**stub**：Tab A 下放 textarea + "生成 YAML 草稿" 按钮。**v1 stub**：click 后弹 toast `"M3a-5 not yet wired — 请用 skill 路径（/add-test-case）或 Tab B 粘贴"`，**不实际调 LLM**。规避 LLM 接入复杂度阻塞主流程；M5 或单独 followup 再做真 LLM。data-testid `tab-entry-a` / `btn-generate-stub`
- [ ] M3a-6 入口 B「粘贴 YAML」：Tab B 下 textarea 直接接受 YAML。粘贴时若检测到 `─── BEGIN YAML ───` / `─── END YAML ───` 围栏（skill 输出格式），自动剥离围栏 + footer + 把内部 YAML 填到主 editor。data-testid `tab-entry-b` / `textarea-paste`
- [ ] M3a-7 Validate → Try → Save 三段闸门 UI 状态机：组件 state `{validate_ok: bool, try_ok: bool, try_step_results: list}`。Validate 按钮永远 enabled；Try 按钮在 validate_ok=true 之前置灰；Save 按钮在 try_ok=true 之前置灰 + hover tooltip `"必须先 Try 一次并通过"`（§6.4 强约束 6）。Validate 失败显示 errors 列表；Try 失败显示 per-step status + stderr 预览前 500 char。Save 成功跳转 `/cases/:id`（新 id）或显示 PR URL 链接

### Sprint M3a-frontend-tests-and-polish — 测试 + polling（可并行）

- [ ] M3a-8 Playwright contract test for `/cases/submit`：`frontend/e2e/cases-submit-contract.spec.ts`。`page.route("**/api/cases/submit", route => { const body = route.request().postDataJSON(); expect(body).toMatchObject({yaml: expect.any(String), case_id: expect.any(String), branch_name: expect.any(String)}); route.fulfill({status: 200, body: JSON.stringify({pr_url: "https://example/pr/1", pr_number: 1, branch: "..."}); })`。**§14 R2 强约束**：必须断言 body shape，不只断 button 渲染。complete the full Validate→Try→Save flow in this e2e (mock 全 3 endpoint)
- [ ] M3a-9 Try mode polling for live step results（实时反馈）：M3a-2 backend 同步返结果（case 跑完才返），前端用 setInterval `(POST /cases/try/status/<try_id>` 风格的 polling 让 UI 看起来有进度感即可。**v1 简化**：if backend M3a-2 直接同步返完整结果（case 通常 < 30s），UI 显示 "Trying… (12s)" spinner + 完成后 batch 展示 step results。SSE 推到 M5

### Sprint M3a-dogfood — 人类浏览器手动验

- [ ] M3a-10 dogfood smoke：前后端起好（dev server），用户在浏览器 `/cases/new`：(1) 走 Tab B 入口，粘贴一份 stub YAML（例：`lg-bug-0006-test-m3a-flow` 简单 SQL `select 1` + expect.scalar=1）；(2) Validate → 通过；(3) Try → 通过；(4) Save → 真开 PR + auto-merge fired → 看到 PR URL；(5) 刷新 `/cases` → 看新 case 出现。产 `docs/m3a-dogfood-<ts>.md` 报告。**M3a-10 等用户手动**

## 关键依赖图

```
M3a-1 (validate) ∥ M3a-2 (try) ∥ M3a-3 (submit) ∥ M3a-3.5 (try cache)   ← 4 backend 可并行
                ↓
M3a-4 (editor page skeleton)
                ↓
M3a-5 (entry A stub) ∥ M3a-6 (entry B) ∥ M3a-7 (3-gate state machine)   ← 3 路并行
                ↓
M3a-8 (contract test) ∥ M3a-9 (polling Try)                              ← 2 路并行
                ↓
M3a-10 (human dogfood, needs_human)
```

## 完成定义

- M3a-1 ~ M3a-9 全 [x] + ci-gate 全绿（backend + frontend block 都触发）+ 每个 PR reviewer §14 cross-reference 无 REQUEST_CHANGES（重点 R2 / R26 / R27）
- M3a-10 dogfood：用户能在浏览器从空白 textarea 起步，粘贴一份 stub YAML → Validate → Try → Save → 看到真 PR auto-merge → 刷新 `/cases` 看到新 case
- foreman 把前 9 项推完 status=done + 写 needs_human "M3a-10 等用户浏览器手动验"

## 失控防护

按 design.md §15.4 + foreman.md hard rules。本 sprint 特别注意：
- **M3a-3 真打 git/gh 高风险**：specialist 测试时**禁止**直接 push 到生产 repo（用 `LBR_GITHUB_DRY_RUN=1` env flag 让 endpoint 跑到 push 前就返 fake PR URL，单测用 mock subprocess）。foreman dispatch prompt 必须明列这条
- **同期 parallel PR 改 cases.py / package.json 高发**（M2 学到的）：M3a-1/2/3/3.5 都改 `backend/app/api/cases.py`，每 PR 都会冲突。**dispatch prompt 显式提醒预算每 PR 一次 rebase**
- **R24 footgun**：前端 specialist 必须真跑 `npx tsc --noEmit + npm run lint + npx vitest run`；后端必须 `ruff check + ruff format --check + pytest -q`
- 10 round / 2h budget → BUDGET-EXHAUSTED 退出，下次接力
- 阻塞类（gh CLI auth 失效 / git push 401 / 集群挂）写 needs_human 不重试
- **M3a-5 LLM 接入**：specialist 若 enthusiastic 想真接 LLM API（OpenAI / Claude / Anthropic），**foreman 必须挡**——v1 留 stub 是用户决策，不许 scope creep
