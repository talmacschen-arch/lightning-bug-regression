# lightning-bug-regression

**HashData Lightning 升级后回归测试 + 周边 extension 集成测试。**

每次 lightning / synxdb 升级后，本工具一键回归两类用例集合：

1. **`bug_regression`** —— 历史 BUG 的复现 / 修复验证（来源主要是飞书「LG 历史 BUG」章节）。
2. **`extension`** —— 周边 extension 的安装 + 基础功能 + 关键边界（pgvector / postgis / pgcrypto 等；研发侧测试因周边环境不充分而覆盖度不够）。

两类用例**共用**同一份 runner、schema、UI；通过 `category` 字段（DB 表驱动可扩展）区分，统计 / 看板 / Run 子集按 category 拆分。

> 状态：**M0 项目骨架阶段**。详见 [`design.md`](./design.md)（v1.3，1800+ 行）。

---

## 设计文档

**[design.md](./design.md)** 是本项目**唯一权威设计文档**。涵盖：

| 章节 | 内容 |
|------|------|
| §1~§2 | 背景 / 目标 / 范围（两类测试门类、In/Out scope） |
| §3 | 总体架构 + 集群访问约定（mdw / gpadmin / cluster_topology） |
| §4 | 数据模型：YAML schema + SQLite 五张表（runs / case_results / case_skip_list / system_settings / case_categories） |
| §5 | 后端设计：API / 执行引擎 / LLM 解析 / Claude Code Skill `add-test-case` |
| §6 | 前端设计：双入口 `/cases/new` + Validate → Try → Save 三段闸门 |
| §7 | PR 流程 + GitHub 仓库配置 |
| §8 | 多 agent 开发协作（8 个 agent） |
| §9 | 项目结构 |
| §10 | 部署与运维（SQLite + 三层配置） |
| §11 | 开放问题汇总（Q1~Q32） |
| §12~§13 | Roadmap + M0 启动前自检 + M0~M5 计划 |
| §14 | 风险预警与反模式（R1~R21，吸收 preflight 教训） |
| §15 | **自动协作运转模型**：foreman verify loop + GitHub auto-merge + cron 12:00/20:00 定时汇报 |

读 design 时**永远从版本历史**（§0）入手——每个版本号一行简述本轮关键决策。

---

## 仓库布局

```
.
├── README.md
├── LICENSE                   # Apache-2.0
├── design.md                 # 权威设计文档
├── .claude/
│   ├── agents/               # 8 个 Claude Code subagent 定义
│   ├── skills/
│   │   ├── add-test-case/    # YAML 草稿 generator skill
│   │   └── report-status/    # 定时汇报 skill
│   └── scripts/
│       └── check_agent_dispatch.sh
├── cases/
│   ├── bug-regression/       # BUG 回归用例 YAML
│   ├── extension/            # extension 集成测试用例 YAML
│   └── SCHEMA.md
├── backend/                  # Python + FastAPI
├── frontend/                 # React + TS + Vite
├── docs/
│   ├── plans/                # M<n>.md sprint 清单（foreman 读这里）
│   └── status/               # foreman state + 定时报告
├── scripts/
└── .github/
    └── workflows/
```

---

## 开发模式

**多 agent 自动协作，人类无需常驻**（§15）：

1. 你（人类）在终端启动一次 `claude` session 跑 `/foreman <sprint>`
2. **foreman**（opus）进入 verify loop（10 round / 2h budget），dispatch 7 个 specialist
3. specialist 改代码 → 起分支 → 开 PR → `gh pr merge --auto --squash` → 立即退出
4. CI 全绿 → GitHub 自动 squash merge
5. **reporter**（OS crontab @ 12:00 / 20:00）独立 fire，写 `docs/status/<ts>.md`
6. 你查 `docs/status/` 目录看进度 + 处理 needs-human 决策项

### Agent 模型矩阵

- **opus**：pm-designer / foreman / **backend-fixer**
- **sonnet**：frontend-fixer / reviewer
- **haiku**：doc-writer / smoke-runner / reporter

---

## 起本机 dev 服务（M3a `/cases/new` dogfood 用）

backend + frontend 一起跑通 web 录入闭环（Validate → Try → Save 真开 PR + auto-merge）需要以下 env 显式注入 uvicorn process。**裸 `uvicorn app.main:app` 起不来 / 起来不能 Save**——M3a-10 dogfood 教训（design.md §14 R27 余波 + §13.7 M3a-3 spec）。

```bash
# 终端 1: backend (从 repo root)
cd backend
nohup env \
  CASES_ROOT="$(cd .. && pwd)/cases" \
  DATABASE_URL="sqlite:///$(pwd)/data/runs.db" \
  PGHOST=127.0.0.1 PGPORT=5432 PGUSER=gpadmin PGDATABASE=postgres \
  GH_TOKEN="$(sed -n 's|https://[^:]*:\([^@]*\)@github.com.*|\1|p' ~/.git-credentials | head -1)" \
  LBR_REPO_ROOT="$(cd .. && pwd)" \
  ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  > /tmp/uvicorn.log 2>&1 &

# 终端 2: frontend vite dev (从 repo root)
cd frontend
nohup npm run dev -- --host 127.0.0.1 --port 5173 > /tmp/vite.log 2>&1 &
```

env vars 说明:

| env | 作用 | 必需性 |
|---|---|---|
| `CASES_ROOT` | `/cases` API 扫盘根目录 | **必须**（默认 `Path("cases")` 相对路径，cwd 偶然性大，§14 R27） |
| `DATABASE_URL` | SQLite DB 路径 | **必须**（默认相对，同上） |
| `PGHOST` / `PGPORT` / `PGUSER` / `PGDATABASE` | psycopg → 集群 PG 连接 | **必须**（默认 `127.0.0.1/gpadmin/postgres` 对齐 §3.1，pg_hba `trust` 不需密码） |
| `GH_TOKEN` | `/cases/submit` endpoint 内部 `gh pr create` / `gh pr merge --auto --squash` | **M3a-3 必须**（缺则 Save 在 gh 那步报 auth fail） |
| `LBR_REPO_ROOT` | `/cases/submit` 的 `subprocess.run(cwd=...)` 显式 repo root | **M3a-3 必须**（默认通过 `__file__` 推 4 级父目录；显式 env 更可靠） |

**笔记本访问**（VM 无 GUI / 浏览器）:

```bash
ssh -L 5173:127.0.0.1:5173 -L 8000:127.0.0.1:8000 root@<vm-ip>
# 留隧道开着，浏览器开 http://localhost:5173/
```

---

## License

Apache License 2.0 — 见 [LICENSE](./LICENSE)。
