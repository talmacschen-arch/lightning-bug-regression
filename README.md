# lightning-bug-regression

**HashData Lightning 升级后回归测试 + 周边 extension 集成测试 + 外部系统集成测试。**

每次 lightning / synxdb 升级后，本工具一键回归三类用例集合：

1. **`bug_regression`** —— 历史 BUG 的复现 / 修复验证（来源主要是飞书「LG 历史 BUG」章节）。
2. **`extension`** —— 周边 extension 的安装 + 基础功能 + 关键边界（pgvector / postgis / pgcrypto 等；研发侧测试因周边环境不充分而覆盖度不够）。
3. **`external_systems`** —— 外部系统依赖测试（datalake_fdw / hive_connector / PXF / zombodb 等需要外部服务可达）。

三类用例**共用**同一份 runner、schema、UI；通过 `category` 字段（DB 表驱动可扩展）区分，统计 / 看板 / Run 子集按 category 拆分。

> 状态：**M0 ~ M6 全部交付 + post-M6 UX 迭代 wave 1+2 + 简易用户登录模块 + Release 流程文档 + target_versions registry + run.errored / error verdict / 进度条 / case 隔离 / 时区 root fix / Admin Bearer 迁移 + external_systems status 双轴语义改造**（design.md v1.21，2026-05-27）。Released: [**v0.19.0**](https://github.com/talmacschen-arch/lightning-bug-regression/releases/tag/v0.19.0) (2026-05-26)。

---

## 功能概览（M0~M6 + 用户登录已交付）

### Web UI（`http://localhost:5173/`）

| 页面 | 用途 |
|---|---|
| `/login` | 单用户登录（初始 admin/admin）；token 存 localStorage；?next= 支持深链跳转 |
| `/dashboard` | KPI 看板 — 各 category case 数 + 各 category status breakdown + Recent runs (pass/fail/running/aborted 派生) + Recent activity + Quick actions + "Compare last 2 runs →" 快捷链 |
| `/cases` | 按 category tab 列 case + 顶部 "+ New Case" CTA + status badge / tags / latest-run |
| `/cases/:id` | YAML 高亮 + 4-tuple 叙事 + Recent runs 区块（跨页 link 到 /runs/:id） |
| `/cases/new` | 双入口编辑器（Tab A 描述生成 = M7 stub / Tab B 粘 YAML）→ Validate → Try → Save 三段闸门 + PR auto-merge |
| `/runs` | 列 run + FilterBar（verdict chips + since + q 搜 version/triggered_by）+ "Includes case:" CaseIdCombobox 服务端过滤 (`?case_id=X` URL 持久化) |
| `/runs/new` | 多选 case + target_version **下拉**（v1.19，源自 `/admin/target-versions` active 列表）+ 触发 POST /runs；支持 `?category=X&status=Y` URL preset（Dashboard quick-action 走这） |
| `/runs/:id` | Run 实时进度 — SSE EventSource 推送 + 每 case 行 ▸ Artifacts 折叠（每 step stdout/stderr 下载） |
| `/runs/diff?a=X&b=Y` | 两 run 并排 diff，分类 = pass→fail / fail→pass / new_case / removed_case / duration_jump (>1.5×) |
| `/admin` | Skip list / External services / Delete case / Target Versions / Change password 五入口 |
| `/admin/skip-list` | 暂时禁用某 case CRUD — case_id 用 shadcn Combobox 选（防 typo），支持 until_date 自动过期 |
| `/admin/external-services` | `external/<svc>.yml` read-only 浏览（YAML 内容 + size + mtime + inline parse_error）|
| `/admin/cases` | 永久删 case（YAML 文件从磁盘删，case_results 历史保留），confirm dialog 引导用 Skip list 暂时禁用 |
| `/admin/target-versions` | v1.19 — 维护 `Trigger New Run → Target version` 下拉 catalog（seed `SynxDB-4.5.0-build130`）；inline edit / active 软删 / at-most-one default / 硬删 refuses-if-referenced（？force=true 跳过；historical run.target_version Text 列保留 stale 字符串无 FK）|
| `/admin/change-password` | 修改当前用户密码（3 字段表单 + 前端校验 + 成功后 1.5s reload）|

### 用户登录（v1.17 新增）

- **单用户**: 始终只有 `admin` 用户，初始密码 `admin/admin`
- **Bearer token**: `secrets.token_urlsafe(32)` 不透明 token，sha256 后存 DB（dump 不可即时 replay）
- **永久 token**: 不过期，logout 才失效；多设备 OK（每次登录独立 token）
- **首次登录**: 顶部红条 "请改密码" 提醒，可忽略；改完后自动消失（password_changed_at 字段控制）
- **替换 ADMIN_PASSWORD env** (M6-4): 旧 `X-Admin-Password` header 模式已删除
- **密码哈希**: bcrypt 工业标准
- **路由保护**: 前端 `<RequireAuth>` 检查 localStorage token；apiFetch 自动加 `Authorization: Bearer`；401 自动 clear + redirect `/login`

### CLI / Skill

- **`add-test-case`** Claude Code Skill — 4 入口（飞书 url / 自然描述 / `ext:<name>` / `xs:<name>`）→ canonical YAML 草稿 → 复制粘 `/cases/new` 走 web 闭环

### Runner 能力

- **SQL driver** (psycopg3, NOTICE 捕获, statement_timeout 双保险)
- **Shell driver** (asyncio subprocess, R9 异常折叠, kill+wait 防 zombie)
- **Log grep driver** (regex on server.log, since case start)
- **Jinja 模板渲染** — case YAML 引用 `{{ external.<svc>.<field> }}` 自动注入
- **External deps 注入** — `external_deps: [hive, hdfs]` → 自动 load `external/hive.yml` + `external/hdfs.yml`
- **DUT 连接抽象** — `external/dut.yml` 取代 `PGHOST/PGPORT/...` env var（旧 env var 仍 fallback）

### Skip list 自动过期

- 加 `until_date: 2026-12-31` → 该日期当天及之前生效，过期自动恢复跑
- 不填 = 永久 skip 直到手动删

---

## 设计文档

**[design.md](./design.md)** 是本项目**唯一权威设计文档**（v1.16，3400+ 行）。涵盖：

| 章节 | 内容 |
|---|---|
| §0 / §0.1 | 版本历史（v0.1 ~ v1.16）+ Topic Index（跨章节导航） |
| §1~§2 | 背景 / 目标 / 范围（三类测试门类、In/Out scope） |
| §3 | 总体架构 + 集群访问约定（mdw / std / sdw1+sdw2 / `external/dut.yml`） |
| §4 | 数据模型：YAML schema + SQLite 五张表 + §4.5 case_categories 元数据表（plug-and-play 扩门类） |
| §5 | 后端设计：API / 执行引擎 / LLM 解析 / `add-test-case` skill |
| §6 | 前端设计：双入口 `/cases/new` + Validate → Try → Save 三段闸门 |
| §7 | PR 流程 + GitHub 仓库配置 |
| §8 | 多 agent 开发协作（8 个 agent） |
| §9 | 项目结构 |
| §10 | 部署与运维（SQLite + 配置分层） |
| §11 | 开放问题汇总（Q1~Q33） |
| §12 | Roadmap — M0~M6 done，M4c external_systems 1 例 done + 后续按需，M7 LLM 接入低优 backlog |
| §13 | 各 sprint 实战回顾 + plan：§13.4 M1 / §13.6 M2 / §13.7 M3a / §13.8 M3b / §13.9 M4 / §13.10 M4c / §13.11 M5 / §13.12 M6 plan / §13.14 M6 retro（含 wave 1 + wave 2 post-iter） |
| §14 | 风险预警与反模式（R1~R32，吸收 preflight + 4 sprint 实战教训） |
| §15 | 自动协作运转模型：foreman verify loop + GitHub auto-merge |
| §16 | 测试门类 super-section（v1.11） |
| §17 | `add-test-case` Skill super-section（v1.11） |
| §18 | Milestones index（按 M 视角导航） |

读 design 时**永远从 §0 版本历史 + §0.1 Topic Index 入手**——每个版本号一行简述本轮关键决策。

---

## 仓库布局

```
.
├── README.md
├── LICENSE                     # Apache-2.0
├── design.md                   # 权威设计文档（v1.16，3400+ 行）
├── external/                   # 外部系统配置（git-tracked，runtime 注入 Jinja）
│   ├── dut.yml                 # DUT (system under test) 连接 + ssh 路由
│   └── elasticsearch.yml       # zombodb case 用
├── .claude/
│   ├── agents/                 # 8 个 Claude Code subagent 定义
│   ├── skills/
│   │   ├── add-test-case/      # YAML 草稿 generator skill
│   │   └── report-status/      # 定时汇报 skill
│   └── scripts/
│       └── check_agent_dispatch.sh
├── cases/
│   ├── bug-regression/         # BUG 回归用例 YAML
│   ├── extension/              # extension 集成测试用例 YAML
│   └── external-systems/       # 外部系统集成测试用例 YAML
├── backend/                    # Python + FastAPI + SQLite
│   ├── app/
│   │   ├── api/                # /cases / /runs / /admin endpoints
│   │   ├── runner/             # SQL / shell / log_grep driver + jinja + external_deps_loader
│   │   └── storage/            # SQLAlchemy + Alembic
│   └── tests/                  # 396+ pytest
├── frontend/                   # React + TS + Vite + shadcn/ui + cmdk
│   ├── src/
│   │   ├── routes/             # /dashboard / /cases / /runs / /admin pages
│   │   ├── components/         # Layout / FilterBar / CaseIdCombobox / ui/*
│   │   ├── lib/                # useFilters hook / runVerdict / skillFence
│   │   └── api/                # OpenAPI codegen client
│   └── ... (204+ vitest)
├── docs/
│   ├── plans/                  # M<n>.md sprint 清单（历史，foreman 路径用）
│   ├── status/                 # foreman state + 定时报告
│   ├── foreman-runs/           # dispatch-foreman.sh wrapper output
│   └── m<N>-dogfood-*.md       # 各 milestone dogfood 报告
├── scripts/
│   ├── dispatch-foreman.sh     # foreman 包装（§14 R25 mitigation）
│   ├── install-cron.sh         # OS crontab 注册 report-status
│   └── cron-report-status.sh   # cron wrapper（proxy + GH_TOKEN + --permission-mode）
└── .github/
    └── workflows/
        └── ci-gate.yml         # 聚合 backend / frontend / agents / docs lint + test
```

---

## 首次安装（fresh clone bootstrap）

**前置**: Python 3.11+ / Node 20+ / npm / git。集群侧 SynxDB 见 §3.1 (design.md)。

最简：

```bash
git clone https://github.com/talmacschen-arch/lightning-bug-regression.git
cd lightning-bug-regression
bash scripts/bootstrap.sh
```

`scripts/bootstrap.sh` 做 3 件事，idempotent 可重跑：
1. **backend venv** — `python3 -m venv backend/.venv` + `.venv/bin/pip install -e ".[dev]"`
2. **DB schema + seed admin** — `alembic upgrade head` 建 7 个 SQLite 表 + 插入 `admin/admin` 用户
3. **frontend deps** — `cd frontend && npm ci`

如果只想跑某一步，对应手动:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
DATABASE_URL=sqlite:///$(pwd)/data/runs.db .venv/bin/alembic upgrade head

cd ../frontend
npm ci
```

### 验证安装成功

```bash
# backend
cd backend
.venv/bin/python -m pytest -q                              # 期望: 420 passed

# frontend
cd ../frontend
npm run lint && npx tsc --noEmit && npx vitest run         # 期望: vitest 244+ passed
```

---

## 日常启动

每次开发会话起 backend + frontend。**首次安装跑完才适用**（venv / DB / node_modules 都存在）。`bootstrap.sh` 重跑也安全 — 已有的不动。

backend 启动需要以下 env 显式注入 uvicorn process（裸 `uvicorn app.main:app` 起不来 — §14 R27）：

```bash
# 终端 1: backend (从 repo root)
cd backend
REPO_ROOT="$(cd .. && pwd)"
nohup env \
  CASES_ROOT="$REPO_ROOT/cases" \
  EXTERNAL_DEPS_DIR="$REPO_ROOT/external" \
  ARTIFACTS_ROOT="$REPO_ROOT/artifacts" \
  DATABASE_URL="sqlite:///$(pwd)/data/runs.db" \
  PGHOST=127.0.0.1 PGPORT=5432 PGUSER=gpadmin PGDATABASE=gpadmin \
  GH_TOKEN="$(sed -n 's|https://[^:]*:\([^@]*\)@github.com.*|\1|p' ~/.git-credentials | head -1)" \
  LBR_REPO_ROOT="$REPO_ROOT" \
  ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop asyncio \
  > /tmp/uvicorn.log 2>&1 &
# `--loop asyncio` 强制走 stdlib asyncio 而非默认 uvloop。dogfood 2026-05-26：
# uvloop 的 subprocess.communicate() 在某些 detach-child 命令上（如
# `pxf cluster restart` 触发 PXF JVM 重启）不返回，让 shell step 撞
# asyncio.wait_for timeout。stdlib asyncio 没这个问题。

# 终端 2: frontend vite dev (从 repo root)
cd frontend
nohup npm run dev -- --host 127.0.0.1 --port 5173 > /tmp/vite.log 2>&1 &
```

env vars 说明:

| env | 作用 | 必需性 |
|---|---|---|
| `CASES_ROOT` | `/cases` API 扫盘根目录 | **必须**（默认 `Path("cases")` 相对路径，cwd 偶然性大，§14 R27） |
| `EXTERNAL_DEPS_DIR` | `external/<svc>.yml` 文件目录 | 推荐（默认 `external` 相对路径；用绝对路径避 cwd 问题） |
| `ARTIFACTS_ROOT` | 每 run 的 step stdout/stderr 落盘根目录 | 推荐（默认 `artifacts`） |
| `DATABASE_URL` | SQLite DB 路径 | **必须**（默认相对，同上） |
| `PGHOST` / `PGPORT` / `PGUSER` / `PGDATABASE` | psycopg → 集群 PG 连接 | 可选（被 `external/dut.yml` per-field 覆盖；都不设走默认 `127.0.0.1/gpadmin/gpadmin`） |
| `GH_TOKEN` | `/cases/submit` endpoint 内部 `gh pr create` / `gh pr merge --auto --squash` | **`/cases/new` 必须** |
| `LBR_REPO_ROOT` | `/cases/submit` `subprocess.run(cwd=...)` 显式 repo root | 推荐 |
| `ANTHROPIC_API_KEY` | `POST /cases/generate-draft` (§5.4 / §13.13 M7) 调 Anthropic SDK 真生成 YAML 草稿。缺失时该 endpoint 返 503，不影响其它路径 | **`/cases/new` 入口 A（"从描述生成"）必须**；skill 路径 + Tab B 粘贴不需要 |

> `ADMIN_PASSWORD` env (M6-4 PR #115 落地的) 在 v1.17 已**删除** — 现走用户登录模块 (`/auth/login` admin/admin → Bearer token)，env var 形式无法接入新 auth 流程。

**笔记本访问**（VM 无 GUI / 浏览器）:

```bash
ssh -L 5173:127.0.0.1:5173 -L 8000:127.0.0.1:8000 root@<vm-ip>
# 留隧道开着，浏览器开 http://localhost:5173/
```

### 忘记 admin 密码？

单用户 tool 没有邮件重置流程。重置密码 = backend CLI 直改 DB:

```bash
cd backend
DATABASE_URL=sqlite:///$(pwd)/data/runs.db .venv/bin/python -c "
from app.api.auth import hash_password
from app.storage import sqlite_store
from app.storage.models import User
from sqlalchemy import select

# init engine (matches uvicorn startup path)
sqlite_store.init_engine('sqlite:///$(pwd)/data/runs.db')

with sqlite_store.get_session() as sess:
    user = sess.scalar(select(User).where(User.username == 'admin'))
    if user is None:
        print('no admin user — backend startup auto-seeds; check DB path')
    else:
        user.password_hash = hash_password('admin')
        user.password_changed_at = None
        sess.commit()
        print('admin password reset to: admin')
"
```

重新登录用 `admin/admin` → 红条提醒再改一次。

---

## 多 agent 自动协作（M5+ 后 fallback 路径）

**当前现实**：M6 + post-M6 wave 1/2 共 ~16 PR 为 user-driven 手写（带 Claude Code 协作但非 foreman 自动 dispatch），证明 R-stabilized 的代码库上 user-driven 显著比 foreman 快。**但 2026-05-28 起 foreman 自动 dispatch 路径已被真实功能 sprint 验证可用**：`m6-run-experience-deepening`（6 PR #189~#194）是**首个全程走 foreman 自动流水线**的功能 wave（非 user-driven），6/6 merged、`r25_violation=False`、reviewer 当真闸门抓 3 个真 bug（见下 Review 流水线 + design.md v1.24）。

**foreman 自动 dispatch 路径仍然可用**（§15），作为大批量 sprint 的 fallback：

1. 你（人类）在终端启动一次 `claude` session 跑 `/foreman <sprint>`
2. **foreman**（opus）进入 verify loop（10 round / 2h budget），dispatch 7 个 specialist
3. specialist 改代码 → 起分支 → 开 PR → `gh pr merge --auto --squash` → 立即退出
4. CI 全绿 → GitHub 自动 squash merge
5. **reporter**（OS crontab @ 12:00 / 20:00）独立 fire，写 `docs/status/<ts>.md`
6. 你查 `docs/status/` 目录看进度 + 处理 needs-human 决策项

### Review 流水线（v1.22）

**新流程**（2026-05-28）：

- **specialist 开 PR 时不自武装 auto-merge**，返回 `open-awaiting-review` 状态
- **foreman 派 reviewer**（merge 前置闸门）→ 跑 §14 + 6 域审查
- **reviewer APPROVE** → foreman 武装 `gh pr merge --auto --squash`
- **reviewer REQUEST_CHANGES** → foreman 派 fix，重新审查；REJECT 则停止
- **CI 全绿** → GitHub 自动 squash merge 到 main
- **merge 后 foreman 派 smoke-runner**（前台同步，见下 v1.23 更正）→ 跑 `scripts/smoke.sh` 用 known-good case 验证工具链健康；NO-GO → foreman 核对 git show --stat 清单后自动开 revert PR + escalate
- **内置 `/review` 和 `/ultrareview`** 由用户**手动**调，不进自动流水线

**v1.23 更正**：smoke-runner 由 foreman 在 merge 后**前台同步**(synchronous)派发，而**非**后台 (`run_in_background`)。原因：foreman 跑在 `claude --print` 一次性进程里，终态门若背景化会 orphan 子 agent 且丢失 final JSON，前台同步保证 GO/NO-GO 在同一轮被消费。详见 design.md §15.1 hard rule 5 + v1.23 changelog。

**v1.24 验证（2026-05-28）**：上述全流水线首次在真实多 PR 功能 sprint（`m6-run-experience-deepening`，6 PR）上端到端跑通——specialist un-armed PR → reviewer 前置闸门（3 次 REQUEST_CHANGES 各抓真 bug：errorCache 双渲染 / 踩坏既有 e2e 契约 testid / §14 R30 stale-branch）→ APPROVE 武装 → ci-gate → 前台 smoke 逐 item 6 次全 GO。wrapper 对账 `foreman_exit_code=0` / `foreman_returned_final_json=True` / `r25_violation=False`。教训：**串行 worktree 不天然免冲突**（分支早于上一 PR 合入时切出会夹带已合并 commits，靠 reviewer R30 兜住）。详见 design.md v1.24 + docs/plans/review-pipeline-completion.md §5.6。

### Agent 模型矩阵

- **opus**：pm-designer / foreman / **backend-fixer**
- **sonnet**：frontend-fixer / reviewer
- **haiku**：doc-writer / smoke-runner / reporter
- **opus-4-7 (永久钉)**：`add-test-case` skill（§17.8 / PR #85 lint enforced）

### Hard rules (§14 R29~R32 落地)

- **R29** reviewer SKIP-disclosure + TENTATIVE_APPROVE verdict
- **R30** specialist ≤1 novel mechanism per PR
- **R31** foreman heartbeat mandatory + ci-gate FAILURE = stop
- **R32** playwright artifact upload on CI failure

---

## Release（打 tag + GitHub Release）

Canonical 步骤详 design.md §13.16。简版:

```bash
# 1. 状态 sanity
git checkout main && git pull
git status                                                  # 期望: working tree clean
cd backend && .venv/bin/python -m pytest -q                 # 期望: 420+ passed
cd ../frontend && npx tsc --noEmit && npm run lint && npx vitest run

# 2. 版本号 + tag (与 design.md 内部版本对齐 / 单人 tool 用 0.x semver)
git tag -a v0.17.0 -m "M0~M6 + 用户登录模块 — design.md v1.17"
git push origin v0.17.0

# 3. release notes (从 design.md §0 changelog + §18 milestones index 抽精华)
#    例: 见 design.md §13.16 模板
cat > /tmp/RELEASE_NOTES_v0.17.0.md <<'EOF'
## v0.17.0 — 用户登录模块上线
- M0~M6 全套（runner / web / Admin / external_deps / dogfood）
- 用户登录: admin/admin + bcrypt + Bearer token + 红条提醒
详 design.md §0 changelog + §18 milestones index
EOF

# 4. GitHub release
GH_TOKEN=... gh release create v0.17.0 \
  --title "v0.17.0 — M0~M6 + 用户登录" \
  --notes-file /tmp/RELEASE_NOTES_v0.17.0.md \
  --target main
```

后续 release 走同样的 6 步，把 `v0.17.0` 替换成新版本号。

---

## License

Apache License 2.0 — 见 [LICENSE](./LICENSE)。
