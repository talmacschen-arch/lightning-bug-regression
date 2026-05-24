# M3b sprint — Skill 录入路径（`.claude/skills/add-test-case`）

foreman 入口文件（design.md §13.0-E）。M3b = 第二条录入路径，面向**在终端里用 Claude Code 写录入的开发者**（不开浏览器、不离开命令行）。skill 生成 YAML → 用户复制粘贴到 M3a `/cases/new` Tab B 入口 → 汇入同一个 Validate → Try → Save 闸门。

权威设计：`design.md`
- §5.5 整章（10 子节）—— skill 设计权威源头，本 sprint 几乎是把这章落成可执行的 SKILL.md
  - §5.5.1 设计原则（6 条铁律）
  - §5.5.2 4 个输入模式（A 飞书 / B 本地 sql / C 自然语言 / D extension）
  - §5.5.3 7 步工作流
  - §5.5.4 6 个对齐问题（首题 category 从 API 拉）
  - §5.5.5 场景特化追问（通用 6 类 + extension 13 类）
  - §5.5.6 canonical 字段顺序
  - §5.5.7 11 项 cross-check
  - §5.5.8 输出格式 + footer
  - §5.5.9 不做的事
  - §5.5.10 落地
- §13.8（M3b 子步骤计划，本 sprint 的来源）
- §4.5（case_categories 元数据表 — M3b-4 6 题对齐首题选项来源）
- §14 R4b（不硬编码 category）+ R26（dual code path）

§14 预付教训 — 写 skill markdown / backend endpoint 时回看：
- **R4b**（绝禁硬编码 category）：M3b-4 6 题对齐的首题"category"选项 + status_whitelist + id_prefix + dir_path **全部从 `GET /admin/categories` 拉表**，skill markdown 里**禁止**出现 `if category == "bug_regression"` / `if category == "extension"` 字面分支。未来加门类时 skill 不需要改一行。
- **R26**（dual code path）：skill 输出 YAML → M3a `/cases/validate` 校验 → **同一份** yaml_loader。skill 自身**不实现** schema 校验逻辑（避免再造一份），让 frontend Validate 做唯一权威。skill 只在 §5.5.7 做 11 项 cross-check (style + canonical 排序 + 命名前缀)，不做 schema 完整性校验。
- **§5.5.1 generator-only 铁律**（极重要）：skill **禁止** Write 工具 / git add/commit/push / POST /cases/submit / 触发集群运行。**唯一输出 = stdout 上一段 YAML**（带 `─── BEGIN YAML ───` / `─── END YAML ───` 围栏 + 3 行 footer 引导用户去 `/cases/new` 入口 B）。
- **R24**（specialist 本地 ci-gate triplet）：每个 backend PR commit 前 `ruff check + ruff format --check + pytest -q`；skill markdown PR 跑 `.claude/scripts/check_agent_dispatch.sh` 或类似 lint（如不存在，本 sprint 加一个 skill-lint 脚本作 M3b-9）。
- **R25**（foreman 走 wrapper）：dispatch foreman 一律 `scripts/dispatch-foreman.sh`。

reviewer 必须按 §14 cross-reference + §5.5.1 铁律逐项核对。

## 任务列表（按依赖图 + 优先级）

### Sprint M3b-backend — 2 个 grounding endpoint（可并行）

- [ ] M3b-1 `GET /admin/step-kinds` endpoint：`backend/app/api/admin.py` 加新路由，返回 `[{kind: "sql", description: "...", required_fields: [...], optional_fields: [...]}, {kind: "shell", ...}, {kind: "log_grep", ...}]`。**唯一权威**——skill §5.5.7 cross-check 1 项强校验 step kind 是否在此 list。**§14 R26 强约束**：source-of-truth 必须是 backend 已有的 step kind 注册表（如果有），如果没有，本 PR 加一份 `backend/app/runner/step_kinds.py` 数据文件 + endpoint 读它 + orchestrator 也读它统一（避免双源不一致）。配测试 `test_api_admin_step_kinds.py` 验返回结构 + 列表非空
- [ ] M3b-2 `GET /cases?q=<topic>&category=<name>` 查重增强：M1-10 已有 `?category=` 过滤（实测可用），本步加 `?q=` 全文搜索（在 case YAML 的 `id` / `title` / `description` 子串包含，case-insensitive；skill §5.5.3 step 2 fetch 用）。返回简表 `[{id, title, status, tags, category}]`。修 `backend/app/api/cases.py` 现有 list 端点。配测试 `test_api_cases_query.py` 覆盖：`?q=hashjoin` 匹配 lg-bug-0001 / `?q=foo` 不匹配任何 / `?q=optimizer&category=bug_regression` 组合过滤

### Sprint M3b-skill-write — SKILL.md 主体（顺序写，单 PR / 或拆 2~3 个 PR）

- [ ] M3b-3 `.claude/skills/add-test-case/SKILL.md` 骨架 + frontmatter：write 该文件，frontmatter 含 `name: add-test-case` / `description: 生成历史 BUG 复现 / extension 集成测试用例 YAML，generator-only` / `model: opus`（不用 sonnet，理由：skill 输出需要严谨结构 + canonical 排序，§5.5 spec 强）。骨架按 §5.5.3 7 步工作流：(1) Read 2-3 相似已有 case YAML / (2) Fetch 4 grounding endpoints / (3) 分析输入推导默认 / (4) 6 题对齐 / (5) 场景特化追问 / (6) Canonical 顺序起草 + cross-check / (7) 打印 BEGIN/END。复制 §5.5.1 6 条铁律 verbatim 进骨架顶部。**禁止** Write / git / submit / 跑集群
- [ ] M3b-4 §5.5.4 6 题对齐 + §5.5.3 自动推导规则：把 6 题（category / id / title / applies_to.versions / status / severity）以 markdown step-by-step 编入 SKILL.md。**关键**：首题 category 选项 + 后续 5 题的默认（id_prefix / default_status / status_whitelist）**从 `GET /admin/categories` 拉表后缓存查表**，skill 文本里**绝禁** `if category == "bug_regression"`（§14 R4b）。自动推导规则（slug / title / status / severity）按 §5.5.3 中段 "自动推导规则" 表 verbatim 编入
- [ ] M3b-5 §5.5.5 通用场景特化追问 6 类：concurrent / crash / mydb / GUC / plan / 性能 — 各按 design.md §5.5.5 通用组表 verbatim 编入。每命中 1 类加 1 题，命中则按 "影响" 列加对应字段
- [ ] M3b-6 §5.5.5 extension category-tagged 13 类场景追问：CREATE EXTENSION / pgvector / postgis / pgcrypto / FDW / 过程语言 / shared_preload / 服务端配置 / kinit / 远端 CLI / warmup / DO $$ FDW 等 13 类，**仅当 category=extension 才跑这组检测**（§5.5.5 末说明）。skill markdown 用条件 markdown 而非硬编码 if（如 "如果用户选 extension category，本节生效"），保留 design.md §13.3 "扩门类 5 步法" 在 skill 场景注册表加新组的扩展性
- [ ] M3b-7 §5.5.6 canonical 字段顺序 + §5.5.7 11 项 cross-check：把 §5.5.6 整段 YAML 模板复制进 SKILL.md（保留 `# 命中并发场景时填...` 等行内注释作引导）；11 项 cross-check 写成 self-check 清单，skill 在打印 BEGIN/END 前**必须**逐项过一遍。任一未过 → 修正重试，不打印
- [ ] M3b-8 §5.5.8 输出格式 + footer：`─── BEGIN YAML ───` ... `─── END YAML ───` 围栏 + 3 行 footer 引导 user 去 `/cases/new` 入口 B（footer 引用 M3a 实测路径，前后端起服务命令见 README "起本机 dev 服务" 章节）。**M3a 已 done**，footer 可直接说 "粘到 http://localhost:5173/cases/new Tab B"

### Sprint M3b-skill-lint — 单测 + lint（可与 skill-write 并行，依赖 M3b-3 骨架先写）

- [ ] M3b-9 skill 自检 lint script：`.claude/scripts/check_skill_add_test_case.sh`（或 Python `.py`）—— 读 `.claude/skills/add-test-case/SKILL.md`，断言：
  - frontmatter 含 `name / description / model: opus`
  - 6 条铁律 (§5.5.1) verbatim 出现
  - 6 题对齐含 `从 /admin/categories 拉` 字样（防止 R4b 反模式）
  - canonical 顺序 verbatim 出现
  - 11 项 cross-check 清单完整
  - 输出格式 BEGIN/END 围栏 + footer 段落都在
  - **禁词扫**：`if category == "bug_regression"` / `category == "extension"` / `os.system` / `subprocess` / `Write` / `git add` 任何出现就 fail（§5.5.1 铁律 + R4b）
  - 加进 `.github/workflows/ci-gate.yml` 的 `agents` block（path filter `.claude/skills/add-test-case/**`）

### Sprint M3b-dogfood — 人类终端跑一次（依赖 M3a 已 done + skill 全写完）

- [x] M3b-10 dogfood smoke：2026-05-24 13:40 (UTC+8) programmatic 跑完 (skill 经 `claude --print` subprocess → /tmp/m3b-yaml.txt → POST /cases/{validate,try,submit} 三段闸门 → PR #68 真 merge → 新 case `cases/extension/lg-ext-pgvector-ivfflat-basic.yaml` 在 main 上 + via API /cases?category=extension 可见)。skill 输出 97 行 YAML，2 main steps via /cases/try 真在 synxdb-0001 上跑 PASS (CREATE IVFFlat 7ms + EXPLAIN 1ms 断言走索引)。**暴露 1 个 backend bug** (assertions.py `_not_contains`/`_stdout_contains` 不接受 list 形式 → 已修 PR #67)。详 `docs/m3b-dogfood-2026-05-24-1340.md`

## 关键依赖图

```
M3b-1 (step-kinds endpoint) ∥ M3b-2 (cases?q= 增强)   ← 2 backend，可并行
                ↓ (M3b-3 之前 endpoints 至少 stub)
M3b-3 (SKILL.md 骨架) → M3b-4 (6题) → M3b-5 (通用追问) → M3b-6 (ext 追问) → M3b-7 (canonical + cross-check) → M3b-8 (输出格式)
                ↓
M3b-9 (skill lint)         ← 可与 M3b-3~8 部分并行；M3b-3 骨架写完后即可起 lint
                ↓
M3b-10 (human dogfood, needs_human; 依赖 M3a + skill 全部 done)
```

## 完成定义

- M3b-1 ~ M3b-9 全 [x] + ci-gate 全绿（backend + agents 都触发；新 skill-lint script 跑过）+ 每个 PR reviewer §14 R cross-reference 无 REQUEST_CHANGES（重点 R4b / R26 / §5.5.1 铁律）
- M3b-10 dogfood：用户终端跑 `/add-test-case ext:pgvector` 拿到合规 YAML（§4.1 schema + §5.5.6 canonical 顺序通过 lint），粘到 `/cases/new` 入口 B 走通 Validate → Try → Save，新 case 真 merge 到 main
- foreman 把前 9 项推完即 status=done + needs_human entry "M3b-10 等用户终端 + 浏览器手动"

## 失控防护

按 design.md §15.4 + foreman.md hard rules。本 sprint 特别注意：
- **skill markdown 本身大段（§5.5 全章约 200 行 YAML/markdown）**：拆 M3b-3 ~ M3b-8 6 个 PR 各 50 行左右；若 specialist 想 bundle，foreman 允许但要求 reviewer 仔细 cross-check
- **§14 R4b enforcement 高发**：skill 写 6 题对齐时 specialist 倾向硬编码 `[bug_regression, extension]` 字面列表，**dispatch prompt 显式列**："首题选项从 API 拉，不在 markdown 写死"
- **§5.5.1 generator-only 铁律高发**：sonnet 模型容易 scope creep 在 skill 里加 `Write` / `git` 操作（"为了方便用户"），**强禁**——M3b-3 specialist 必须 model=opus，且 reviewer 扫到任何副作用工具调用 → REQUEST_CHANGES
- **R24 footgun**：backend specialist (M3b-1/M3b-2) 必须真跑 `ruff check + ruff format --check + pytest`；skill markdown PR 必须真跑 M3b-9 lint script（如已存在）才 commit
- 10 round / 2h budget → BUDGET-EXHAUSTED；M3b backend 部分小（2 个 endpoint），skill 部分主要工作量在 markdown 抄写 §5.5 + 加 lint；budget 应充裕
- M3b-10 dogfood **强烈推荐模式 D `ext:pgvector`**（不依赖飞书 doc 准备）；若用户偏好模式 A `<feishu-url>` 也行，user 提供 url
