# M6 运行体验深化（Run Experience Deepening）

> 范畴：归并入既有 **M6** 里程碑（M6-1 SSE / M6-2 artifacts / M6-4 auth 之后的体验补齐
> wave）。**不更新 design.md**——本文件是该 wave 的独立设计稿，落地后由各 PR 描述回链。
> 作者起草：2026-05-28。

四个特性，均为已交付页面上的"体验补齐"，不引入新页面、不引入图表库（沿用 Dashboard
"无 chart library，纯数字 + 色块"的既有取舍）。

| 子项 | 特性 | 后端改动 | 工作量 |
|---|---|---|---|
| **M6-D1** | Run 详情页一键重跑（全部 / 仅失败） | 无 | 小 |
| **M6-D2** | Artifact stdout/stderr 内联查看（不必下载） | 无 | 小 |
| **M6-D3** | Case 详情页 per-case 状态时间线 / 跨版本趋势（**定：做到 Tier2**） | 加 1 字段 | 中 |
| **M6-D4** | Cases 页搜索框（复用后端 `q`）+ tag 过滤 | 无 | 小 |

落地建议顺序：**D2 → D1 → D4 → D3**（D2/D4 最独立，D1 要改两个页面，D3 含可选后端）。

---

## M6-D1 — Run 详情页一键重跑（#2）

### 动机
回归场景最高频的动作：改完一个 bug，只重跑上次挂掉的那几条 case。当前 `/runs/:id` 是纯
只读结果页，重跑只能手动回 `/runs/new` 逐个勾选。

### 现状约束
`RunNewPage` 已支持 URL preset，但仅认 `?category=X&status=Y`（见 `RunNewPage.tsx:43-66`
的 `presetKey` 一次性应用机制），**不认显式 case_id 列表**。`POST /runs` 的 body 本身就接
`case_ids: string[]`（`CreateRunRequest`），所以重跑 = 预选 + 复用现有提交路径，无需后端。

### 方案

**A. `/runs/:id` 加两个按钮（`RunDetailPage.tsx` 头部）**
- `Re-run all` → 跳 `/runs/new?case_ids=<run 内全部 case_id, 逗号分隔>&from_run=<id>&target_version=<run.target_version>`
- `Re-run failed` → 同上，但 `case_ids` 只取 `case_results` 里 `status ∈ {fail, error}` 的；
  当失败数为 0 时 `disabled`。
- 两个 case_id 集合从 `run.case_results` 现场算（页面已有该数据，零额外请求）。
- `target_version` 从 `run.target_version` 带过去作为预选（见 B 的回填规则）。
- testid：`btn-rerun-all`、`btn-rerun-failed`。

**B. `RunNewPage` 扩 `?case_ids=` 预选通道**
- 新读 `searchParams.get('case_ids')`，按逗号 split。
- 并入既有一次性 preset 机制：`case_ids` 存在时**优先于** `category/status`（显式列表覆盖
  过滤式），其余复用 `appliedPresetKey` 防重入逻辑。
- **关键边界（对齐 CLAUDE.md "失败要说出来"）**：URL 里的 case_id 可能已被删除（case YAML 已
  从磁盘删，但历史 run 仍引用它）。应用预选时必须与"当前磁盘上真实存在的 case 集合"
  （`allCases.map(c => c.id)`）取交集；落选的 id **不**塞进 `selected`（否则 checkbox 不渲染
  却仍被提交），并在 preset banner 上提示 `N case(s) from Run #X no longer exist — skipped`。
- `target_version`：带过来的值若在 active 版本下拉里存在则预选；不存在（版本已软删/改名）则
  回退到默认值并提示，**不**静默用一个不在列表里的值。
- banner 文案随来源切换：来自 `from_run` 时显示 `Re-run from Run #X: N cases`。

### 测试要点（验证 wiring，非浅层）
- `Re-run failed`：构造一个含 pass/fail/error/skip 的 run，断言跳转 URL 的 `case_ids` 精确等于
  fail+error 两类的 id 集合（不多不少）——这是 "covers fail/error" 的 claim，必须 assert。
- 失败数为 0 → 按钮 disabled。
- RunNew 收到含 1 个已删除 id 的 `case_ids` → 该 id 不在 `selected`、banner 提示 skipped、
  Trigger 按钮计数只算存活 case。
- 带 stale `target_version` → 回退默认 + 提示。

---

## M6-D2 — Artifact 内联日志查看（#4）

### 动机
排查一个失败 case 时，当前 `/runs/:id` 的 Artifacts 折叠里每个文件只有 **Download** 链接
（`RunDetailPage.tsx:137-144`）。triage 要把 stdout/stderr 一个个下下来再用编辑器打开，很慢。

### 现状约束（已核实，对方案有实质影响）
下载端点 `GET /runs/{id}/cases/{case_id}/artifacts/{filename}`（`runs.py:667`）返回
`media_type="text/plain; charset=utf-8"`，但带 `Content-Disposition: attachment`。
**`attachment` 只影响浏览器导航/`<a download>` 的下载行为；`fetch().then(r => r.text())`
完全忽略它**——所以内联读取无需任何后端改动，直接 fetch 同一个 URL 取文本即可。
该端点当前无鉴权（与现有 Download 用裸 `fetch` 一致）。

### 方案（`RunDetailPage.tsx` 的 `CaseArtifacts` 组件内）
- 每个 artifact 行在 `Download` 旁加 `View` 按钮，toggle 一段内联 `<pre>`。
- 懒加载：首次展开才 `fetch(downloadUrl).then(r => r.text())`，结果按 `filename` 缓存进组件
  state（`Map<filename, string>`），重复展开不重复请求。loading / error 各有状态。
- 渲染：等宽字体、`whitespace-pre`、`max-h-96 overflow-auto` 滚动框。
- **大文件保护**：artifact 列表已带 `size_bytes`。阈值（建议 **512 KB**）以上不自动内联，显示
  `Large file (X) — Download instead`，避免把多 MB 的 stdout 一次性塞进 DOM 卡死页面。
  （runner 的 stderr_preview 截断只在 TryResponse 里；落盘 artifact 是全量文件，必须设阈值。）
- testid：`artifact-view-<caseId>-<filename>`、`artifact-content-<caseId>-<filename>`、
  `artifact-view-loading-*`、`artifact-view-error-*`、`artifact-too-large-*`。

### 未来兼容性备注
若后续给 artifact 端点加鉴权，裸 `fetch` 会 401。届时需要给 `apiFetch` 加一个返回 `text()`
的变体（现在它写死 `res.json()`）。本期不做，仅记录。

### 测试要点
- 点 View → 渲染文件文本；再点折叠；再展开**不**触发第二次 fetch（断言 fetch 调用次数）。
- fetch 失败 → 显示 error，不影响 Download 链接仍可用。
- `size_bytes > 512KB` → 不渲染内联、显示 "Download instead"。

---

## M6-D3 — Case 历史时间线 / 跨版本趋势（#5）

### 动机
回归工具最该有、目前却没有的视图：一条历史 BUG case 在最近 N 次运行 / 哪个版本上
**回潮（regression）** 了。当前 `/cases/:id` 只有一个 "Recent runs" 纯列表
（`CaseDetailPage.tsx:25-119`）。

### 现状约束（已核实）
- 数据源 `GET /cases/:id/recent-runs` 已存在，返回 `CaseRecentRunOut`：
  `run_id / run_status / started_at / finished_at / case_status / duration_ms`。
- **缺 `target_version`**——所以"跨版本"维度严格说后端要补一个字段。因此分两层。

### Tier 1（纯前端，本期主交付）— 回归 sparkline
- 在 Recent runs 卡片**上方**加一个 `CaseTimeline` 卡片：把最近 N 次的 `case_status` 渲染成一排
  色块（oldest→newest），`pass=绿 / fail=红 / skip=灰 / error=橙`，色彩映射数据驱动、不硬编码
  category（遵 §14 R4b 风格）。
- 每个色块：hover tooltip 显示 `Run #X · <相对时间> · <duration>`，点击跳 `/runs/X`。
- 卡片头部一行汇总：`最近 N 次：a pass / b fail / c skip` + `上次失败：Run #X（Yd ago）`（无失败
  则省略），让"在回潮吗"一眼可读。
- **共用一次请求**：把 recent-runs 的 fetch 从 `CaseRecentRuns` 上提到 `CaseDetailPage`，同时喂给
  `CaseTimeline`（sparkline）和 `CaseRecentRuns`（列表），避免同端点请求两次。
- **顺带修时区 bug**：`CaseDetailPage.tsx:15-16` 的 `formatRelative` 用 `new Date(dateStr)` 直解
  后端 naive-UTC 时间串，会有 ~8h 偏移（UTC+8）。RunDetailPage 已修（`:194-197` 的
  "无 tz 后缀则补 'Z'" 逻辑）。本期把那段抽成共享 helper（如 `lib/time.ts` 的 `parseUtc()`），
  Timeline / RecentRuns 一起用，消除偏移。
- testid：`case-timeline`、`case-timeline-cell-<run_id>`、`case-timeline-summary`。

### Tier 2（**已定纳入本期**，加版本维度）— 需后端 1 个字段
> 决策 2026-05-28：D3 做到 Tier2。Tier1 仍先落地（前端独立 PR），Tier2 在其上叠加（含一个 backend PR）。
- 后端：`CaseRecentRunOut` 增 `target_version: str | None`；`sqlite_store.list_recent_runs_for_case`
  的 SELECT 把 `runs.target_version` 一起带出（join 已在，纯加列；遵 §14 R26 不写内联 SQL，改在
  storage 层）。默认 `limit` 可从 10 提到 ~20 以覆盖多版本。
- 前端：色块 tooltip 加版本号；并可加一个 "按版本 pass 率" 迷你表（`v4.5.0: 3/3 · v4.6.0: 2/3`），
  直接回答"哪个版本开始挂"。
- 建议：Tier 1 先落地见效，Tier 2 视是否真的要按版本归并再排。

### 测试要点
- 给定 case_status 序列 → 色块颜色与顺序正确（oldest→newest）。
- 汇总计数与"上次失败"指向正确的 run。
- 时区：一个 naive-UTC 串经 `parseUtc` 后相对时间正确（回归 ~8h 偏移）。

---

## M6-D4 — Cases 页搜索 + tag 过滤（#6）

### 动机
`/cases` 目前只有 category tab（`CasesPage.tsx`），case 多了找不到。

### 现状约束（已核实）
后端 `GET /cases?q=` **已支持**（`cases.py:296,331`）：大小写不敏感子串，匹配
`id / title / description / tags`（description 不在 `CaseSummary` 里，所以这部分前端无法自己
复刻——**搜索走服务端**才完整）。

### 方案（`CasesPage.tsx`）
- 顶部加搜索输入框（debounce ~300ms）。`q` 变化时**带 `?q=` 重新请求当前 active category**
  （`q` 也参与缓存 key，使现有"已加载则不重取"的 `fetchCasesForCategory` 在 q 变化时失效重取）。
- `q` 同步进 URL（`?q=`，可分享、支持后退），与 `RunsPage` 的 FilterBar / `lib/useFilters` URL-sync
  风格一致——优先复用 `useFilters`，不另造一套（遵 CLAUDE.md "遇到冲突不要平均 / 项目约定优先"）。
- **tag 过滤**：tags 已在 `CaseSummary` 里，做**客户端**过滤即可——把当前 tab 已加载 case 的 tag 收
  成一排可点 chip，选中后在已渲染列表上按 tag 过滤（多选 = OR）。与服务端 `q` 叠加（q 先收窄、
  tag 再筛）。
- 空结果态：`No cases match "<q>"`（+ 选中的 tag）。
- testid：`cases-search-input`、`cases-tag-filter-<tag>`、`cases-search-empty`。

### 测试要点
- 输 q → 断言 `/cases` 带 `?q=` 重新请求、列表更新、URL 含 `?q=`。
- 切 category 时 q 保持生效。
- tag chip 多选 = OR 过滤，且与 q 叠加。

---

## 跨项约定（四项通用）
- 不加图表库 / 不加新依赖（沿用 Dashboard 取舍）。
- 状态颜色一律数据驱动，不对 status/category 字符串硬编码（§14 R4b）。
- 涉后端（仅 D3 Tier2）：查询走 storage 层，禁内联 SQL（§14 R26）。
- 测试验证 wiring 与业务意图，不写"返回非空"式浅层测试（CLAUDE.md §7 / §2）；凡 claim "覆盖
  fail/error / 多版本" 必须 assert 每种情形真的走到。
- 全部纯前端项无后端依赖，可独立开 PR、独立合入。

---

## Sprint 任务清单（foreman 消费；sprint-label = `m6-run-experience-deepening`）

> 设计细节见上文各 `## M6-Dx` 节，specialist 实现时**回读对应节**。foreman 串行派发（一项
> merge + smoke GO 后再开下一项），故下方 RunDetailPage / CaseDetailPage 的跨项文件冲突由
> "每个新 worktree 都从更新后的 main 切" 天然规避，**不要并行派**。顺序即优先级：自上而下。
>
> **跨项硬约束**（务必按此序）：
> - D3T2-backend 必须在 D3T1 之后（tooltip 叠在 timeline 上）。
> - D3T2-frontend 必须在 D3T2-backend **merge 之后**（前端要先 `npm run gen:types` 才拿到
>   `CaseRecentRunOut.target_version` 类型）。
> - D3T2 是 backend + frontend **两个 PR**（单个 specialist 类型不能同时碰前后端），不可合一。

- [ ] **m6d2-artifact-inline-view**（frontend-fixer）: 见 §M6-D2。`RunDetailPage.tsx` 的
      `CaseArtifacts` 组件内，每个 artifact 行加 `View` 按钮 toggle 内联 `<pre>`；首展开才
      `fetch(downloadUrl).then(r=>r.text())`，按 filename 缓存进组件 state（不重复请求）；
      `size_bytes > 512KB` 不内联、显示 "Download instead"；loading/error 各有态。
      testid：`artifact-view-<caseId>-<filename>` / `artifact-content-*` / `artifact-view-loading-*` /
      `artifact-view-error-*` / `artifact-too-large-*`。**零后端改动**。
      测试断言：重复展开**不**触发第二次 fetch（断调用次数）；fetch 失败显示 error 且 Download 仍可用；
      >512KB 不渲染内联。Out of scope：不碰后端、不给 artifact 端点加鉴权、不动 Download 链接。

- [ ] **m6d1-rerun**（frontend-fixer）: 见 §M6-D1。①`RunDetailPage.tsx` 头部加 `Re-run all` /
      `Re-run failed` 两按钮，case_id 集合从 `run.case_results` 现场算，failed 集合取 `status∈{fail,error}`，
      失败数 0 时 `Re-run failed` disabled；跳 `/runs/new?case_ids=...&from_run=<id>&target_version=<run.target_version>`。
      ②`RunNewPage.tsx` 扩 `?case_ids=` 预选通道，并入既有 `appliedPresetKey` 一次性机制，`case_ids`
      存在时优先于 `category/status`；**与磁盘真实存在的 case 取交集**，落选 id 不进 `selected` 且 banner
      提示 `N case(s) from Run #X no longer exist — skipped`；stale `target_version` 回退默认 + 提示，不静默用。
      testid：`btn-rerun-all` / `btn-rerun-failed`。**零后端改动**。
      测试断言：跳转 URL 的 `case_ids` 精确 == fail+error 集合（不多不少，这是 covers-fail/error 的 claim）；
      0 失败 → disabled；含 1 个已删除 id → 不在 selected + banner skipped + Trigger 计数只算存活；stale 版本 → 回退默认 + 提示。

- [ ] **m6d4-cases-search**（frontend-fixer）: 见 §M6-D4。`CasesPage.tsx` 顶部加搜索框（debounce ~300ms），
      `q` 变化带 `?q=` 重请求当前 active category（q 参与缓存 key 使 `fetchCasesForCategory` 失效重取），
      `q` 同步进 URL；**优先复用 `lib/useFilters`** 做 URL-sync，不另造一套（CLAUDE.md §5）。tag 过滤走
      **客户端**（tags 已在 CaseSummary）：当前 tab 已加载 case 的 tag 收成 chip，多选=OR，与服务端 q 叠加；
      空态 `No cases match "<q>"`。testid：`cases-search-input` / `cases-tag-filter-<tag>` / `cases-search-empty`。
      **零后端改动**（后端 `?q=` 已支持，匹配 id/title/description/tags）。
      测试断言：输 q → `/cases` 带 `?q=` 重请求 + 列表更新 + URL 含 `?q=`；切 category 时 q 保持；tag 多选 OR 且与 q 叠加。

- [ ] **m6d3t1-case-timeline**（frontend-fixer）: 见 §M6-D3 Tier1。`CaseDetailPage.tsx` 在 Recent runs
      卡片上方加 `CaseTimeline` 卡片：最近 N 次 `case_status` 渲染成一排色块（oldest→newest，颜色数据驱动
      `pass/fail/skip/error`，§14 R4b）；每块 hover tooltip `Run #X·相对时间·duration`，点击跳 `/runs/X`；
      卡片头汇总 `a pass / b fail / c skip` + `上次失败 Run #X`。**把 recent-runs 的 fetch 从 `CaseRecentRuns`
      上提到 `CaseDetailPage`**，同喂 Timeline 与列表（一次请求）。**新建 `lib/time.ts` 的 `parseUtc()`**
      （抽 RunDetailPage:196-197 的「无 tz 后缀补 'Z'」逻辑），CaseDetailPage 的 Timeline/RecentRuns 一起用，
      修 `formatRelative` 的 ~8h UTC+8 偏移。testid：`case-timeline` / `case-timeline-cell-<run_id>` / `case-timeline-summary`。
      **零后端改动**。Out of scope：**本项不回改 `RunDetailPage.tsx`**（避免与 m6d1/m6d2 的 RunDetailPage 链冲突）——
      RunDetailPage 改用 `parseUtc` 留作后续清理，标出不在本项。测试断言：给定 case_status 序列 → 色块颜色/顺序正确；
      汇总计数与"上次失败"指向正确 run；naive-UTC 串经 `parseUtc` 相对时间正确（回归 8h 偏移）。

- [ ] **m6d3t2-backend-version-field**（backend-fixer）: 见 §M6-D3 Tier2。`CaseRecentRunOut`
      （`cases.py:89`）增 `target_version: str | None = None`；recent-runs 端点 mapping 处直接读
      `run.target_version`（`list_recent_runs_for_case` 已返回完整 `(CaseResult, Run)` 元组，**SQL/storage 层
      无需改**，比设计稿说的更省）。`limit` 可从 10 提到 ~20 覆盖多版本。**仅后端 + 该端点测试**，不碰前端。
      测试断言：构造一个 run 带某 target_version → recent-runs 响应该 case 的行 `target_version` 等于该值；
      null 版本的 run → 字段为 null 不报错。

- [ ] **m6d3t2-frontend-version-dim**（frontend-fixer，**依赖上一项 merge**）: 见 §M6-D3 Tier2。先 `npm run gen:types`
      拿到新 `target_version` 类型。`CaseTimeline` 色块 tooltip 加版本号；加 "按版本 pass 率" 迷你表
      （如 `v4.5.0: 3/3 · v4.6.0: 2/3`），数据驱动归并版本。**零后端改动**（消费上一项的字段）。
      测试断言：给定带 target_version 的 recent-runs → tooltip 含版本号；按版本归并计数正确（多版本各自 pass/total）。
