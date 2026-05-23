# post_upgrade_test — 设计文档

> 当前版本: **v1.3**　状态: **M0 step 1 已完成（仓库已建，初始 commit 29b2507 已 push）。用户决策改 private——Wiki 因 GitHub Free + private 不可用自动禁用，其他 features 全保留**。

---

## 0. 版本历史

| 版本 | 日期 | 作者 | 变更摘要 |
|------|------|------|----------|
| v0.1 | 2026-05-23 | pm-designer (Claude) | 初稿。给出总体架构、YAML schema 草案、后端目录、前端路由、多 agent 协作流程、8 个待讨论项（Q1~Q8）。 |
| v0.2 | 2026-05-23 | pm-designer (Claude) | 收敛关键决策：**(a)** 测试语义改为"BUG 复现 = test FAIL，所有用例期望已修复行为"，`assert.kind` 删除 `should_fail`，简化为 3 种；**(b)** UI 锁定 Tailwind + shadcn/ui；**(c)** 仓库定名 `lightning-bug-regression`，托管在 `talmacschen-arch` 公开空间；**(d)** 多 agent 协作流程保持 §8 不调整。Q1（真实 BUG 样本）仍待用户贴出。 |
| v0.3 | 2026-05-23 | pm-designer (Claude) | 用飞书 9.1~9.5 五个真实 BUG 反推 schema，补 5 个能力：**(a)** `assert` 改为 list，可多断言叠加；**(b)** 新增 `query_output_matches` 断言（regex/contains 匹配 step 输出，覆盖 EXPLAIN 计划判定）；**(c)** `sql_returns` 的 `expect.value` 支持 `eq/ne/ge/le/gt/lt` 比较；**(d)** step / setup 支持 `database:` 字段覆盖默认连接；**(e)** 新增 `status: stub` 表示"已录入但缺复现脚本，run 时 skip"；**(f)** 元字段加 `issue_url`。Q1 关闭。 |
| v0.4 | 2026-05-23 | pm-designer (Claude) | M0 前置闸门收敛：**(a)** LICENSE 选 **Apache-2.0**；**(b)** GitHub 仓库 features 全开（Issues / Discussions / Wiki / Projects）；**(c)** 首批 5 个用例 `status` **全部先标 `open`**，待手动验证后再升级为 `fixed`（覆盖 v0.3 §13 "按飞书有无 fix 版本判断"的方案）；**(d)** 新增 Q10：澄清 §8 agent 角色 ≠ GitHub 账号角色，单 GitHub 账号既做 author 又做 merger 不阻塞。 |
| v0.5 | 2026-05-23 | pm-designer (Claude) | **结合 preflight 项目 5 周 1300 commits / 100+ MR 经验**重大重构。schema 层：**(a)** 断言下沉到 step 级 `expect: {...}`，移除 top-level `assert: list`（不再用 step 名字反向引用）；**(b)** 新增 `applies_to: {versions, exclude}` 结构化版本门控；**(c)** 新增 `preconditions:` / `external_deps:` 运行前 gate；**(d)** 新增 `sessions:` + step 级 `on:` 多会话原语，取代 `background: true`；**(e)** 新增 `kind: log_grep` step kind，吸收旧 `log_pattern` 断言；**(f)** timeout 默认值改 60s/300s/600s 三档，避免 sync-SSH 时代的 60s 陷阱。系统层：**(g)** 新增 `case_skip_list` DB 表，已知上游 issue 用表治理而非 YAML 改 `status`；**(h)** 新增 `system_settings` 表（Tier B 配置）+ Admin UI；**(i)** DB 唯一约束保证串行运行；**(j)** §14 新增"风险预警与反模式"章节，吸收 preflight 14 条避坑教训（contract 测试、ErrorBoundary、worktree isolation、MR-flow 等）。Q14~Q20 落账。 |
| v0.6 | 2026-05-23 | pm-designer (Claude) | 借鉴 preflight `.claude/skills/add-test-case/SKILL.md`（509 行）。**(a)** §2 范围把 "Claude Code skill" 从 Out 移到 In（generator-only 模式）；**(b)** 新增 §5.5 完整设计 `add-test-case` skill：generator-only 不写盘 / 5 题对齐 / 6 类场景特化追问（多 session / cluster crash / DB 切换 / GUC gate / EXPLAIN plan / 性能断言）/ canonical field 顺序 / live grounding API；**(c)** §5.2 新增 grounding 端点 `/admin/step-kinds` + 查重端点；**(d)** §6.1 `/cases/new` 改为双入口（描述生成 / 粘贴 YAML），两条路径汇入同一编辑器；**(e)** 引入 **Validate → Try → Save 三段式闸门**：提 PR 前**必须**触发一次"试跑"，未通过禁止提交，避免"yaml 没跑过先合并、下次启动才发现错"的回归。Q21/Q22 落账。 |
| v0.7 | 2026-05-23 | pm-designer (Claude) | 三点收敛：**(a)** §3 新增 3.1 "集群访问约定"，明确 Claude Code 节点 = mdw、`su - gpadmin` + psql 进集群、`gp_segment_configuration` 取拓扑、mdw → std/sdw* ssh 免密。这是 runner / smoke-runner 实现的硬前提，写进文档避免每次新会话重新对齐。**(b)** §7 新增 7.1 "GitHub 仓库保护规则约定"：Settings → Branches **不开** Require PR reviews，单账号 `talmacschen-arch` 既做 PR author 又做 merger；agent reviewer 输出是本人决策辅助、不挂 GitHub 身份字段；§11 Q10 同步细化。**(c)** schema 顶层引入 `category` 字段（`bug_regression` 默认 / `extension`），覆盖第二个测试门类——周边集成测试（pgvector / postgis / pgcrypto 等 extension 的研发侧测试因为周边环境不充分而不够覆盖）；`status` 词汇按 category 分语义（bug 用 open/fixed/wontfix/stub，extension 用 stable/experimental/deprecated/stub）；§9 目录改 `cases/bug-regression/` + `cases/extension/`；§5.5 skill 重命名 **`add-bug-case` → `add-test-case`** 并把 category 加为对齐题的第一题；§12 Roadmap 加 M4b extension 首批用例。Q10 细化 / Q23 / Q24 / Q25 落账。 |
| v0.8 | 2026-05-23 | pm-designer (Claude) | 两点收敛：**(a)** §10 给 SQLite 选择补一段独立"选型说明"——单进程访问 / 零运维 / 一个文件易备份 / 单用户 100~10000 个 case 量级远不到 SQLite 上限 / SQLAlchemy + Alembic 抽象 = 未来迁 PG 是 schema 迁移题不是代码题；明确触发迁 PG 的阈值。**(b)** **门类改 DB 驱动可扩展**：新增 §4.5 `case_categories` 元数据表（name / display_name / id_prefix / status_whitelist / default_status / dir_path / display_order / is_active），bug_regression + extension 由 Alembic seed migration 落账；schema 校验、UI tab、skill 对齐题首题、目录扫描**全部从 API 拉**，不在代码里硬编码两个枚举值。§13 加"未来扩门类流程"5 步法。Q26 / Q27 落账。 |
| v0.9 | 2026-05-23 | pm-designer (Claude) | 深读 preflight `suites/functional/plugins/*` 11 例 + `suites/functional/external_systems/*` 18 例 + `runner.py` 解析逻辑后落地。schema 补：**(a)** Step 加 `host:` 字段（cli step 可指定远端主机，渲染 Jinja，host 在 `dut_hosts` 内仍用 `gpadmin`；外部主机用 `root`）；**(b)** `external_deps: [...]` + Jinja 上下文 `external.<svc>.host/port/username/password/extras.*` 加 `coordinator.host` 总是可用；**(c)** Step.timeout_sec 默认 60s → 600s（preflight Run 192 教训）。runner 补：**(d)** Jinja `StrictUndefined`，typo 直接 UndefinedError；**(e)** step exception 全 try/except 转 StepResult，case 标 error 后下一 case 继续（preflight Run 32 教训）；**(f)** 第一个非 pass step 即 break 后续 step，teardown 仍跑且 best-effort；**(g)** `destructive: true` 的 case 在 suite 内排到最后跑（避免污染后续）。skill 补：**(h)** §5.5.5 extension 场景特化追问加 6 条（self-managed preload / external_deps_note banner / 文件追加 vs 覆盖 / profile.d 显式 source / warmup retry / DO $$ 块用于幂等 CREATE FDW）；**(i)** §5.5.6 canonical 顺序补 description/procedure/expected 三段叙事字段（4-tuple 报告需要）；**(j)** §5.5.7 cross-check 加 destructive 一致性 + setup/teardown 幂等守卫 + StrictUndefined typo 检查。§14 R17~R21 新增（preflight 5 个具体踩坑：Run 47 ssh_user 误判 / Run 112 文件覆盖 / Run 97 warmup race / Run 192 timeout / Run 32 一 step 异常拖垮全 suite）。 |
| v1.0 | 2026-05-23 | pm-designer (Claude) | **形成"放后台不用管"开发闭环。**（用户核心诉求）三件事：**(1) §8 重排 agent 表**：`scheduler` → `foreman`（按 preflight foreman.md 范本重写），新增 `reporter` agent（haiku，只读，cron 触发）；**(2) 新增 §15 完整设计自动协作运转模型**：foreman verify loop（10 round / 2h budget，preflight 默认 10 + 用户决策）/ stop conditions（DONE / BLOCKED-ESCALATE / BUDGET-EXHAUSTED）/ "同症状 fail 2 次 立即停 + escalate" 规则 / `docs/status/foreman-state.json` 心跳与状态共享 / GitHub auto-merge 集成（specialist push → `gh pr merge --auto --squash` → CI green 自动合并，配套 §7.1 已有的 Allow auto-merge）/ 12:00 + 00:00 `CronCreate` cron 唤起 reporter → 输出 `docs/status/YYYY-MM-DD-HHMM.md` + 飞书推送（feishu-skills MCP）/ 报告格式 = 上一周期完成 / 进行中 / **needs-human 决策清单** / 阻塞项 / 下周期计划 / "下次报告前不打扰"原则。**(3) §12 Roadmap M0 末加 foreman+reporter+cron 启用步骤**，M1 起就放手让 agent 自跑，人类只在 12:00/24:00 看报告 + 处理 needs-human 项。Q28/Q29/Q30/Q31 落账。 |
| v1.1 | 2026-05-23 | pm-designer (Claude) | **§13.0 新增 M0 启动前自检 5 项**（用户确认全部纳入）：(1) `gh auth status` 确认 PAT 含 `repo + workflow` scope；(2) trivial cron（5 分钟后 echo）验证 `CronCreate` 真能登记本机 cron——这是 §15 整套自动汇报机制的硬前提；(3) `feishu_list_chats` 取私聊 chat_id，写进 `system_settings.feishu_report_chat_id`；(4) `su - gpadmin` 跑 `psql -c "select version()"` + `gp_segment_configuration` + `ssh sdw1 hostname` 三件套验集群可达；(5) 约定 `docs/plans/M<n>.md` 是 foreman 读 sprint 清单的固定位置（与 preflight 同款）。任一不通过 = 不开 M0。 |
| v1.2 | 2026-05-23 | pm-designer (Claude) | **去 reporter 推飞书路径**（用户：飞书 chat 没打通，改人工查目录）。(1) §13.0 自检 5 → 4 项，去掉 C "拿飞书 chat_id"；(2) §15.3 reporter 工作流去掉 "feishu_send_*" step，唯一输出 = `docs/status/<ts>.md`；(3) §15.3.5 "不打扰"原则简化——所有事件都进下次定时报告，**无即时通知通道**；仓库不可访问类"系统级"事件 reporter 检测到时在报告顶部加 `🚨 SYSTEM_ALERT:` 红字行；(4) §15.4 失控防护表去掉飞书 alert 行；(5) §15.5 落地步骤去掉飞书 stub；(6) §8.1 reporter 产出列去 "+ 飞书推送"；(7) §8.4 reporter 工具权限去掉 "调 feishu MCP"；(8) §13.1 step 6 Alembic 0001 seed 去掉 `feishu_report_chat_id` 项；(9) Q29 决议改 "仅本地 docs/status/，人工查目录"，Q31 改 "立即停 + 写 state.json，下次定时报告高亮"，去掉飞书 alert 例外。**注意**：飞书作为**BUG 数据源**仍保留——M4a 接入新 BUG 时 skill 模式 A `<feishu-url>` 仍用 feishu MCP 拉文档原文，这是另一条路径。 |
| v1.3 | 2026-05-23 | pm-designer (Claude) | **A/B/D 自检实测完毕，B 戳破 CronCreate 假设——v1.0~v1.2 错把 Claude Code 内置 `CronCreate` 当作 OS-level cron。实测确认：CronCreate 是 session-only（session 退出即死）+ 必须 REPL idle 才 fire（foreman 持续 mid-query 时永远不 fire）。**改用户决策的 OS crontab 路径：(1) §15.3.1 cron 注册从 `CronCreate` 改 **`crontab -e` 写两条 entry，命令 = `cd <repo> && claude --print "/report-status" >> docs/status/cron.log 2>&1`**——OS 级独立进程，与 foreman session 完全解耦；(2) §13.0 自检 B 改成"`echo hello \| claude --print` 实测能跑 + root crontab 可写"，已通过；(3) §13.1 step 8 改 OS crontab 注册命令；(4) §15.4 失控防护表 cron 那一行同步；(5) §11 加 Q32（CronCreate vs OS crontab 选型）。**自检 A 结果**：PAT 长度 40，`repo` ✅，**缺 `workflow`** ⚠️——用户需要去 GitHub Settings → Developer settings → Personal access tokens 给现有 PAT 加 workflow scope（或重发一张），写进 §13.0 A 项的"修复操作"。**自检 D 结果**（mdw=synxdb-0001，实测）：SynxDB4 4.5.0 build 130 / PostgreSQL 14.4 base / 18 segs / ssh sdw1=synxdb-0003 免密通——填进 §3.1 与 §13.0 D 项实测栏。**v1.3 内追加（不升版号）**：(a) A workflow scope 已补（实测 `x-oauth-scopes: repo, workflow`）；(b) **backend-fixer 从 sonnet 升 opus**（用户决策，backend 是公信力关键路径，opus + reviewer 双层稳健；其他 agent 模型不动）；(c) **M0 step 1 仓库已创建并切 private**——initial commit 29b2507 含 LICENSE / README / .gitignore / design.md 共 2170 行 push 到 main；切 private 后 Wiki 因 GitHub Free 限制自动禁用，§7.1 / §11 Q12 同步修订。(d) **cron 时间从 12:00/00:00 调到 12:00/20:00**（用户决策，2026-05-23 step 7 收尾时）——理由：用户作息下 12:00 + 20:00 比 12:00 + 00:00 更贴用户每日"早扫一眼 / 晚扫一眼"的实际查目录节奏，凌晨 00:00 报告通常要次日上午才被看到，价值低；§15.3 / §13.1 step 8 / §9 文件名示例 / §11 Q28 Q29 / §15.5 / install-cron.sh / `.claude/{agents,skills}/report*` 同步修订；报告时窗调整为：12:00 报告覆盖前一天 20:00→今天 12:00（16h 夜间），20:00 报告覆盖 12:00→20:00（8h 白天）。(e) **M0 step 8 实测把"cron 直调 claude --print"细化为"cron 调 wrapper、wrapper 调 claude"** (2026-05-23): cron 的 minimal env 缺 3 件 claude 必需的东西——HTTP proxy（本机走 10.13.11.1:1080 → 直连 Anthropic 返 403）、`GH_TOKEN`（skill 第 4 步要 gh pr list / gh auth status）、permission-bypass flag（`--print` non-interactive 没法批 tool prompt，但 `--dangerously-skip-permissions` 在 root 下被拒、`acceptEdits` / `dontAsk` 都挡 `gh pr list`，**只有 `--permission-mode auto` 同时放行 Bash 通用 + git + gh + Write to docs/status/**）；新增 `scripts/cron-report-status.sh` 把三件事一并补齐；`scripts/install-cron.sh` 改为 tag-based idempotent（先 grep -Fv 移除旧 CRON_TAG 行再加新行，应对 entry 格式升级）。step 8 实测两轮 smoke 全过（commit `7d97986` / `31f8653`，docs/status/2026-05-23-2211.md / 2217.md）。§15.3.1 / §13.1 step 8 / SKILL.md / reporter.md 同步修订。 |

> 迭代约定：每次重要修订 +0.1，发布前定稿为 v1.0。修订时新增一行，**简述本轮关键决策**（不要只写"修改若干处"）。讨论点在 §11 同步收敛/新增。

---

## 1. 背景与目标

### 1.1 背景
lightning / synxdb 每次升级后，**两类测试都要做一遍**，本项目把它们统一在一个工具下：

**门类 1：BUG 回归（bug_regression）**——一次性回归所有"曾经发生过的 BUG"，确认：
1. 已修复的 BUG 没有回归（regression）。
2. 已知未修复的 BUG 是否仍可复现（用于跟踪修复进度）。
历史 BUG 清单来源：飞书文档「LG 历史 BUG」章节。

**门类 2：周边集成测试（extension）**——验证 lightning 自带 / 常用的 extension 在升级后**仍能装、仍能跑、仍能交付预期**（pgvector / postgis / pgcrypto / pg_hint_plan / fuzzystrmatch / uuid-ossp / pg_search / plgo 等）。研发层面的测试因周边环境不充分（缺数据 fixture、缺真实索引规模、缺与其他 extension 的交互场景）覆盖度不够，必须在交付侧再补一层闸门。

两类测试**共用同一份 runner、同一套 schema、同一个 UI**；通过 schema 顶层 `category` 字段（§4.1）区分，统计 / 看板 / Run 子集筛选都按 category 拆分展示。

### 1.2 目标
- 维护两类**可执行**的测试用例集合（不是文字描述）：
  - `bug_regression`：历史 BUG 的复现 / 修复验证用例。
  - `extension`：周边 extension 的安装 + 基础功能 + 关键边界场景用例。
- 升级后能一键回归全部用例（也可按 category 子集触发），输出 pass/fail/skip 报告。
- 支持后续**持续录入新用例**，包括非工程师通过自然语言描述补录。
- 用例可 review、可版本化、可追溯（who/when/why）。

### 1.3 非目标（明确不做）
- 不做性能压测、不做 chaos / fault injection 平台。
- 不做用例自动发现（不从 GitHub issue / Jira 抓取）。
- 不做调度器（不做 cron 定期跑、不做升级流水线 hook —— 由人手动触发）。
- 首版不做用户系统 / 权限分级（单用户内部工具）。
- 不做 extension 的**性能 benchmark**（pgvector ANN 召回率 / postgis 空间查询耗时基线）——首版只保证"功能正确"。

---

## 2. 范围

| 项 | In scope | Out of scope |
|----|----------|--------------|
| **测试门类（category）**（v0.7） | **`bug_regression`**（历史 BUG 复现）+ **`extension`**（周边 extension 集成测试，pgvector/postgis/pgcrypto/pg_hint_plan/…） | extension benchmark（耗时基线、召回率），AI 训练数据 fixture |
| 用例类型 | SQL、Shell、SQL+Shell 混合 | 多步骤集群编排（failover / 磁盘故障注入） |
| 目标环境 | 本地已部署的 lightning 集群（mdw + std/sdw* 节点，详 §3.1） | 远程 SSH 独立部署、容器化、多集群矩阵 |
| **集群/依赖准备** | **由用户手动保证可用**（含 psql 可连、需要的 DB 已建、必要 GUC 已设、extension 已安装基础包） | **自动 provisioning / 资源池 / golden snapshot** |
| 触发方式 | 前端手动点 "Run All / Run Subset" | CI hook、定时调度 |
| 用例录入 | **两条路径**：(a) 前端 `/cases/new`（自然语言/粘贴 YAML → 编辑器 → Validate → Try → 提 PR）；(b) **Claude Code Skill `add-test-case`**（generator-only，输出 YAML 到 stdout，再 paste 到 (a)）；详 §5.5 | 直接 CLI 落盘 / 直接调 API 写仓库 |
| 报告 | 单次运行 pass/fail/日志，历史可查 | 趋势图、告警、Slack 推送 |

---

## 3. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                       Browser (React+TS)                    │
│   /cases  /runs  /runs/:id  /cases/new                      │
└──────────────────────────┬──────────────────────────────────┘
                           │  HTTP/JSON
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (Python)                 │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────────┐    │
│  │ cases   │ │ runs    │ │ llm     │ │ runner          │    │
│  │ API     │ │ API     │ │ parse   │ │ (sql/shell drv) │    │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────────┬────────┘    │
└───────┼───────────┼───────────┼───────────────┼─────────────┘
        │           │           │               │
        ▼           ▼           ▼               ▼
   cases/*.yaml  SQLite     Claude API     lightning 集群
   (git 仓库)    (run 记录)                (psql + 本地 shell)
```

**几个关键决定：**
- 用例 source of truth = git 仓库下的 YAML 文件，启动时全量加载到内存。
- 运行记录（runs）落 SQLite（单文件、零运维、足够单机用）。
- LLM 解析走 Claude API（`claude-sonnet-4-6` 起步，复杂用例升 `claude-opus-4-7`）。`[讨论]` 是否需要也支持本地 LLM。
- 后端和 lightning 集群在**同一台机器**上跑（你已确认"本地已部署"），psql 走 unix socket / localhost；shell 直接本机执行。
- **测试环境的准备不在本工具职责内**：lightning 集群、需要的 database、外部依赖（如自建 mydb）都由你手动准备并自检可用，本工具只负责"在已就绪的环境上跑 YAML 用例"。集群 down 了 = 用例 fail（正确语义），但**不**触发自动重启或重新 provision——那是另一类项目（参考 preflight 但本项目刻意不做）。

### 3.1 集群访问约定（v0.7 固化；v1.3 补实测）

runner / smoke-runner 实现这些 driver 时**默认**按下面的方式访问集群，不要发明别的连接路径。如果某天集群拓扑变了，**只**改本节，其他代码不动。

**v1.3 自检 D 实测**（2026-05-23 14:33 CST，已 verify）：
- mdw 节点 hostname = `synxdb-0001`，root 身份可登录
- DB 版本 = **SynxDB4 4.5.0 build 130 / PostgreSQL 14.4 / Apache Cloudberry 2.1.0**
- `gp_segment_configuration` 共 **18 行**（1 master + 1 standby + 8 primary + 8 mirror 推测）
- `ssh sdw1` 解析到真实 hostname = `synxdb-0003`，root + gpadmin 均免密通

这意味着：(a) 首批 5 个 case 的 `applies_to.versions` 若需要填，**当前生产版本是 4.5.0**；(b) cluster_topology 表运行时会有 18 行，分 segment / mirror 维度筛选用 `role` + `content` 字段。

| 项 | 约定 |
|----|------|
| **Claude Code / backend 运行节点** | **就是 `mdw`（coordinator / master）**——和 lightning master 同机器。这是 §3 "本地已部署"前提的物理化。 |
| **OS 登录用户 → DB 登录用户** | backend 进程以 `gpadmin` 用户运行（运维脚本里 `sudo systemctl --user`，或手动 `su - gpadmin` 后 `uvicorn …`）。**禁止**以 root / 当前 shell user 跑 backend——psql 不在 PATH / `gp_*` 工具拿不到 GPHOME。 |
| **psql 连接方式** | 走 unix socket / `127.0.0.1`，不指定 host port；连进默认 db 取 GUC，连业务 db 跑 case。无密码（gpadmin 本机 trust）。 |
| **集群拓扑发现** | runner 启动时跑一次 `SELECT * FROM gp_segment_configuration`，把结果缓存为 `cluster_topology`：含每个 segment 的 `dbid / content / role / preferred_role / mode / status / hostname / address / port`。后续 step 想 ssh 去 segment / 看日志，从这里查 host。 |
| **跨节点 shell 执行** | `mdw → std / sdw1 / sdw2 / …` 已 ssh 免密（gpadmin → gpadmin）。shell driver 的远端 step 通过 `ssh <host> '<cmd>'` 一行执行；**禁止**写口令、**禁止**预期 `expect`/`sshpass`。host 名字必须取自 `cluster_topology.hostname`，不要硬编码。 |
| **其他依赖** | 集群以外的依赖（自建 mydb、外部 fixture、kerberos 凭据等）**由你手动准备**——首版 5 例用不到；M4 接入新 BUG 出现需求时你再补充约定到本节。 |
| **失败语义** | psql 连不上 / `gp_segment_configuration` 跑不出来 = backend 启动 fail-fast，不要降级到"什么都跑不了的空壳 UI"。`/admin/healthz` 把这个状态露给前端。 |

**默认日志路径**（log_grep step 的 `log_path` 缺省值）：
- coordinator 日志：`$COORDINATOR_DATA_DIRECTORY/log/`，运维上常见值是 `/data0/synx4data/master/gpseg-1/log/`，**实际路径**通过 `SHOW data_directory` + 拼接 `/log/` 取，不要硬编码。
- segment 日志：通过 `cluster_topology.<hostname>` ssh 过去，按各自 `data_directory + /log/` 抓。

**写到 Tier B 设置**（§4.4）：把 `default_log_path_strategy = "auto-detect via SHOW data_directory"` 这类决议固化为 `system_settings` 的默认值，**不要**散落到代码里。

---

## 4. 数据模型

### 4.1 用例 YAML schema（v0.5 重构，重点 review）

文件路径：`cases/<id>.yaml`（id 用 kebab-case，例如 `lg-bug-0042-vacuum-deadlock.yaml`）。

**v0.5 核心变化**：参考 preflight 的 `Case` schema（`backend/preflight/suites/schema.py:168-216`），把断言下沉到 step 级 `expect:`，取消 top-level `assert: list`（不再用名字反向引用 step）。同时引入 `applies_to` / `preconditions` / `external_deps` / `sessions` 等结构化门控字段。

```yaml
# —— 标识与元信息 ——
id: lg-bug-0001-hashjoin-right-table   # 全局唯一，与文件名一致；英文 kebab-case
                                       # 命名：bug → lg-bug-NNNN-<slug>；extension → lg-ext-<extname>-<slug>
title: hashjoin 右表(小表)的选择正确性   # 自由文本，可中文；面向人读
category: bug_regression               # v0.7 新增。**取值不在 schema 写死**，由 §4.5 `case_categories` 表驱动
                                       # 当前 seed：bug_regression（默认） / extension
                                       # 决定 status 词汇白名单、id 前缀、目录归属、看板分组
status: open                           # 合法值取决于 category（§4.5 status_whitelist 字段）。
                                       # 当前 seed 下：
                                       #   bug_regression: open | fixed | wontfix | stub
                                       #   extension:      stable | experimental | deprecated | stub
                                       # stub 在所有 category 下含义一致：仅录入元信息、缺可执行 steps，run 时 skip
severity: high                         # high | medium | low

source:
  feishu_anchor: "section-9.1"         # bug 用：飞书文档锚点；extension 通常留空
  reported_at: "2025-08-15"
  fixed_version: "lightning 2.3"       # bug + status=fixed 时填；extension 不用
  ext_doc_url: ""                      # extension 用：官方文档 / 仓库 README 链接
issue_url: https://code.hashdata.xyz/field-engineering/dev_collaboration/-/issues/642
tags: [optimizer, hashjoin]            # bug 常见：optimizer/storage/dml/recovery 等
                                       # extension 必带 ext 名：[pgvector, ann] / [postgis, spatial] …

# —— 适用范围（v0.5 新增；不写=适用所有版本） ——
applies_to:
  versions: ">=1.6,<2.0"               # PEP 440 风格 spec
  exclude: ["1.6.3"]                   # 指定版本跳过（已知该版本测试基础设施异常等）

# —— 前置条件（v0.5 新增；不满足 => skip，并在报告里标"前置不满足"） ——
preconditions:
  options.optimizer: [on, off]         # 当前 GUC 值必须在允许集合
  # 还可写 external 维度，例如：
  # external.cluster_count: [">=2"]    # 至少 2 个集群在线

# —— 外部依赖（v0.5 新增；任一不可用 => skip）——
external_deps: []                      # 当前 bug_regression 5 例为空；
                                       # extension 类常用：[hive], [oracle], [kafka], [hive_kerberos, kerberos], ...
                                       # 不在 system_settings.available_services 里 => case skip 而非 fail
                                       # （preflight EXTERNAL_DEPS_SKIP_REASON 同款语义）

# —— v0.9 新增：4-tuple 叙事字段，供报告渲染"目的 / 步骤 / 预期 / 实测"——
description: |                         # 本 case 想验证什么；覆盖了哪个飞书章节 / extension 哪个能力
procedure: |                           # 编号步骤，让 reviewer 不读 SQL 也能懂流程
expected: |                            # 预期结果一句话清单
                                       # 三段都可中文；report 渲染时与 step_records（实测）并排展示。
                                       # 缺省 = ""，报告渲染为 "—"。

# —— 默认连接 ——
defaults:
  database: postgres                   # 默认连接的 db；step / setup 可覆盖

# —— 多会话（v0.5 新增，替代 v0.4 的 background: true）——
sessions: [s1, s2]                     # 命名独立会话；step 用 on: 引用
                                       # 不写则使用单一 "default" 会话
                                       # 取代 background: true，更精确地表达"哪两步并发"

# —— v0.9 新增：destructive 标志 ——
destructive: false                     # true 表示本 case 会改 shared_preload_libraries / gpstop / 删数据目录
                                       # 之类**会污染后续 case** 的操作。runner 在 suite 内把 destructive=true
                                       # 的 case **排到最后**跑（preflight runner.py:263 `sorted by destructive`），
                                       # 避免后续 case 跑在被污染的集群上拿到误判。

# —— 执行 ——
# v0.9：setup / teardown 是 **list[str]**（不是 list of step），每项一条 SQL 或一段 shell。
# runner 按顺序逐条 exec_raw_sql；中间任一条 error => case 标 error，**steps 不会跑**，但 teardown 仍会 best-effort 跑。
# **必须幂等**（DROP IF EXISTS / CREATE IF NOT EXISTS / DO $$ ... END $$ 守卫），因为：
#   (a) Try 闸门可能反复跑；(b) 跨 case 共享 schema 时上一 case 没清干净；(c) 失败重跑友好。
setup:                                 # 可选；前置；list[str]
  - DROP TABLE IF EXISTS tmp_test01
  - DROP TABLE IF EXISTS tmp_test02
  - |
    CREATE TABLE tmp_test01 (i int);
    INSERT INTO tmp_test01 SELECT i FROM generate_series(1, 10000000) i;
    ANALYZE tmp_test01
  - CREATE EXTENSION IF NOT EXISTS pgvector   # 示例：幂等创建 extension

steps:                                 # 必填，按顺序执行；每个 step 一种 driver
  # 推荐惯例（v0.9，借 preflight external_systems 模式）：
  # 第一个 step 通常是 `external_deps_note` 类 banner，
  # echo 出本 case 依赖什么、当前 pool 配的是什么 host/port，
  # 让 skip 时报告里能直接看到原因，不用回去查 yaml。
  - name: external_deps_note
    kind: shell
    cmd: |
      echo "本 case 依赖：external_deps={{ ', '.join(external_deps) if external_deps else '无' }}"
      echo "coordinator: {{ coordinator.host }}"
    expect: { exit_code: 0 }

  - name: "测试1：ORCA off 时 hashjoin 右表应为 tmp_test02"
    kind: sql                          # sql | shell | log_grep | restart_db
                                       # 不写则按字段推断（有 sql=>sql, 有 shell/cmd=>shell）
    on: s1                             # 多会话场景下指定会话；不写=default
    database: postgres                 # 覆盖 defaults.database
    sql: |
      set optimizer to off;
      explain DELETE FROM tmp_test01 f USING tmp_test02 b WHERE f.i = b.i;
    timeout_sec: 600                   # 默认 600s（v0.9 调整，借 preflight Run 192 教训）。
                                       # 60s 是 sync-SSH 时代默认值；现代异步轮询下 600s
                                       # 既宽松又能截断真的卡死。慢操作（dnf install / curl
                                       # 大文件 / gpinitsystem）显式提到更高。
    expect:                            # 本 step 的断言；下列字段任选若干，**全部满足 => 该 step pass**
      # —— 执行层 ——
      exit_code: 0                     # shell 专用；默认 0
      # —— SQL 结果层 ——
      rows_affected: 1                 # 所有 statement 的非负 rowcount 之和
      row_count: 42                    # 最后一个有 description 的 result set 行数
      scalar: kache                    # 单标量；默认 op=eq
      scalar_ge: 1                     # 比较 op：scalar_eq/ne/ge/le/gt/lt（9.4 count>=1）
      # —— 输出层 ——
      stdout_contains: "tmp_test02"    # 子串包含；shell stdout / SQL explain plan
      plan_contains: ["Hash", "tmp_test02"]   # SQL 专用：plan 全部包含
      plan_contains_any: ["Index", "Seq"]     # plan 任一包含（兼容 ORCA / Postgres planner 差异）
      regex: "Hash\\s+\\n.*tmp_test02" # 自由正则；上述都不够用时再用
      not_contains: "ERROR"            # 反向匹配
      # —— 性能层 ——
      duration_lt_ms: 30000            # 步骤耗时上界；默认无限

  - name: "测试2：在 mydb 上跑 upper"
    database: mydb                     # 覆盖默认 db（9.5 LC_CTYPE BUG）
    sql: SELECT upper('AAAAAX/안녕 / XXXXXX')
    expect:
      scalar: "AAAAAX/안녕 / XXXXXX"   # upper 不应丢字符

  - name: 并发 VACUUM
    kind: shell
    on: s2                             # 在 s2 会话异步推进；与 s1 上的 SELECT 同时跑
    cmd: psql -c "VACUUM tmp_test01;"  # v0.9：shell driver 字段名统一为 `cmd`（与 preflight 一致）
    expect:
      exit_code: 0

  # v0.9 新增示例：在外部主机上 seed fixture（典型 extension / external_deps 场景）
  - name: seed_oracle_fixture
    kind: shell
    host: '{{ external.oracle.host }}'  # **可选**：cli / shell step 可指定远端主机；
                                        # 解析规则（§3.1 + §5.3）：
                                        # - host 在 cluster_topology.hostnames 内
                                        #   → ssh 走 gpadmin（沿用 DUT 用户）
                                        # - host 不在 cluster_topology 内（如外部 Oracle / Kafka 主机）
                                        #   → ssh 走 root（外部主机惯例）
                                        # （preflight runner.py `dut_hosts` 策略，Run 47 forensic）
    cmd: |
      [ -f /etc/profile.d/oracle.sh ] && . /etc/profile.d/oracle.sh || true
      # SSH 非交互登录默认不 source profile.d；必须显式带上才能拿到 ORACLE_HOME
      sqlplus -S {{ external.oracle.username }}/{{ external.oracle.password }}@//localhost:{{ external.oracle.port }}/{{ external.oracle.extras.service_name }} <<'SQL'
        DROP TABLE t_demo;
        CREATE TABLE t_demo(id int);
        INSERT INTO t_demo VALUES (1),(2);
        COMMIT;
        EXIT;
      SQL
    expect:
      exit_code: 0

  - name: 服务端日志不能含 recover mode
    kind: log_grep                     # v0.5 新增 step kind；吸收旧 log_pattern 断言
    pattern: "FATAL: the database system is in recover mode"
    log_path: /data0/synx4data/coordinator/gpseg-1/log/   # 可选；不写则从 system_settings 读
    expect:
      matches: 0                       # 期望匹配 0 行；也可写 matches_lt / matches_ge

teardown:                              # 可选；list[str]；即使中间步骤失败也会执行
  - DROP TABLE IF EXISTS tmp_test01
  - DROP TABLE IF EXISTS tmp_test02
  # teardown 失败 = log 但**不**影响 case 最终状态（runner.py:808-813 best-effort）。
  # 设计意图：destructive 类 case 必须给自己留干净的 cleanup，不能因 cleanup 出错把整个 case 标 fail。

# —— 录入审计 ——
created_by: chenqiang
created_at: "2026-05-23"
notes: |                               # 可选；workaround / 上下文 / 已知信息
  workaround：函数加 immutable 修饰可绕过 crash。
```

#### 4.1.1 v0.5 决议要点

**判定语义**（继承 v0.2 + v0.7 扩展到 extension）：
- 两类用例统一以"**正面期望** = 应当 pass"为基础语义。**红色（fail）= 有问题**，不管 BUG 复现还是 extension 退化。
  - `bug_regression`：正面期望 = 已修复后的行为。看板上红色 = 仍有此 BUG。
  - `extension`：正面期望 = extension 装得上、装完能用、关键功能不退化。看板上红色 = extension 集成断了。
- `status` 字段是元信息标注，**不**影响判定逻辑（不会因为 `status: open` 或 `status: experimental` 就把 fail 改成 skip/pass）。
  - 想"暂时不跑"——用 §4.3 `case_skip_list`（带 reason / upstream_issue / until_date 治理）。
  - 想"录入但还没写复现脚本"——用 `status: stub`（runner skip 并标"待补"）。

**Step 级 `expect:` vs v0.4 的 top-level `assert:` list**：

| 维度 | v0.4 | v0.5 |
|------|------|------|
| 断言归属 | top-level `assert: list`，靠 `step: "<name>"` 反向引用 | 直接挂在 step 上，无需引用 |
| step 改名 | 引用名字处全部跟着改 | 无影响 |
| 跨 step 断言 | 通过引用任意 step 实现 | 用 `log_grep` step + step 顺序表达；或写一个最终 SQL 收尾 step |
| 默认成功语义 | `assert: [should_succeed]` | "所有 step 无错且 `expect` 都满足"是隐式默认 |
| 表达力 | 灵活但容易写错（错字、引用孤立 step） | 收敛但强约束 |

**v0.5 验证**：用新 schema 重新表达飞书 §9.1~9.5：

| BUG | 老方案 | 新方案 |
|------|--------|--------|
| 9.1 hashjoin 右表 | `assert: [should_succeed, query_output_matches(step=...)]` | step 上 `expect.plan_contains: ["tmp_test02"]` |
| 9.2 array unnest crash | `assert: [should_succeed, log_pattern(not_contains)]` | 末尾加一个 `kind: log_grep, expect.matches: 0` step |
| 9.3 count 无统计 | `status: stub` | 不变 |
| 9.4 ctas rowcount=0 | `assert: [sql_returns(value=1, op=ge)]` | step 上 `expect.scalar_ge: 1` |
| 9.5 LC_CTYPE upper | step 级 `database: mydb` | 不变 |

**Recover mode 噪声兜底**（v0.3 §4.1 讨论项 2）：仍保留——backend 检测到 `recover mode` 关键字时强制中止后续 step 并标注 "cluster crashed"。这是 runner 行为，不是 schema 字段。

`[讨论]` 剩余细节：
1. `restart_db` step kind 是否在 M1 实现？preflight 单独写了 `restart_step.py`（gpstop+gpstart 带 exit code≤1 重试一次），首版可只 stub 出来。
2. `external_deps` 当前没有触发样本（5 例均空），先入 schema 但不实现 resolver；M4 接入飞书新 BUG 时再补。

### 4.2 运行记录 schema（SQLite）

```sql
CREATE TABLE runs (
  id INTEGER PRIMARY KEY,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  triggered_by TEXT,            -- 用户名/邮箱，UI 输入
  target_version TEXT,          -- 被测的 lightning 版本（运行前手填）
  total INTEGER, passed INTEGER, failed INTEGER, skipped INTEGER,
  status TEXT NOT NULL          -- running | done | aborted
);

-- v0.5 新增：DB 层保证"任意时刻只有一个 active run"（取代应用层互斥锁）
-- 借鉴 preflight：UNIQUE INDEX runs(active) WHERE state='running'
CREATE UNIQUE INDEX uniq_runs_running ON runs(status) WHERE status = 'running';

CREATE TABLE case_results (
  id INTEGER PRIMARY KEY,
  run_id INTEGER REFERENCES runs(id),
  case_id TEXT,                 -- 引用 YAML 的 id
  status TEXT,                  -- pass | fail | skip | error
  skip_reason TEXT,             -- v0.5：skip_list / preconditions_unmet / external_deps_unavailable / stub
  duration_ms INTEGER,
  stdout TEXT, stderr TEXT,
  expect_detail TEXT,           -- 失败时记录哪个 step 的哪个 expect 字段不满足
  artifacts_path TEXT           -- 日志/截图/csv 落盘目录
);
CREATE INDEX idx_case_results_run ON case_results(run_id);
CREATE INDEX idx_case_results_case ON case_results(case_id);
```

### 4.3 用例跳过表 case_skip_list（v0.5 新增，借鉴 preflight alembic 0018）

**问题来源**：preflight 早期用 YAML 里的 `enable_<feature>=true` 之类临时 GUC gate 来标"上游已知 issue，先跳过"。后果：(a) 改 YAML 必走 PR，跳过策略和测试内容耦合；(b) 多个 case 用同一个 gate，删除上游 issue 时漏改；(c) 没有过期时间，过期的跳过策略永远留在仓库。

**v0.5 方案**：把"跳过策略"从 YAML 抽出，放进一张 DB 表，运行时由 runner 在每个 case 开跑前查询。

```sql
CREATE TABLE case_skip_list (
  id INTEGER PRIMARY KEY,
  case_id TEXT NOT NULL,             -- YAML id；可用前缀匹配（例如 'lg-bug-0003'）
  applies_to_version TEXT,           -- NULL = 所有版本；非 NULL 时做 prefix 匹配（'1.6' 匹配 '1.6.3'）
  reason TEXT NOT NULL,              -- 人读说明，至少一句话
  upstream_issue TEXT,               -- GitLab/GitHub issue 链接
  until_date DATE,                   -- NULL = 长期；非 NULL 时该日期之后规则自动失效
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  created_by TEXT                    -- 操作人邮箱
);
CREATE INDEX idx_skip_case ON case_skip_list(case_id);
```

**runner 消费逻辑**（伪码）：
```python
def should_skip(case, target_version, now):
    for rule in load_active_skip_list():  # WHERE until_date IS NULL OR until_date >= now
        if not match_case_id(rule.case_id, case.id):
            continue
        if rule.applies_to_version and not target_version.startswith(rule.applies_to_version):
            continue
        return SkipDecision(reason=f"manual_skip:{rule.id} ({rule.reason})", upstream=rule.upstream_issue)
    return None
```

**Admin UI**：`/admin/skip-list` 提供增删查（无修改——改 = 失效旧的、新增一条），所有变更落 `case_skip_list_history`（审计表，schema 略，v0.5 暂不必须）。

### 4.4 系统设置表 system_settings（v0.5 新增，借鉴 preflight Tier B 配置）

**问题来源**：preflight 早期把可配置项散在 5 个地方（env var / YAML / 前端硬编码 / Python 常量 / docker-compose），导致 pool 121 误分配（vm_cpu 三处不一致）。

**v0.5 方案**：把**运行时可变**的设置统一放到 DB 表，前后端通过 API 读，30s 进程缓存。Admin UI 提供编辑入口。

```sql
CREATE TABLE system_settings (
  key TEXT PRIMARY KEY,              -- 例：default_log_path, claude_api_model, default_db
  value TEXT NOT NULL,               -- 序列化值（字符串、JSON）
  value_type TEXT NOT NULL,          -- string | int | bool | json
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_by TEXT
);
```

**配置分层**（沿用 preflight 三层模型）：

| Tier | 存储位置 | 用途 | 示例 |
|------|----------|------|------|
| **A 引导** | 磁盘文件 `~/.post_upgrade_test/env` (mode 600) | DB 不可达前必须的最小配置 | `DATABASE_URL`, `CLAUDE_API_KEY` |
| **B 运行时** | `system_settings` 表 | 运行后可调；带 Admin UI | `default_log_path`, `default_db`, `claude_api_model`, `default_timeout_sec`, `git_branch_prefix` |
| **C 内容** | git（YAML / Python 常量） | 测试内容、schema、危险模式列表 | `cases/*.yaml`, schema 定义 |

**Tier B 缓存失效**：单用户单进程场景不需要 LISTEN/NOTIFY，简单做 30 秒进程缓存即可；Admin UI 改完弹"30 秒内生效"提示。

### 4.5 测试门类元数据表 case_categories（v0.8 新增，关键扩展点）

**问题来源**：v0.7 把测试门类硬编码为两个枚举值（`bug_regression` / `extension`）。如果未来要加第三类（如 `performance_smoke` / `upgrade_compatibility` / `cluster_recovery`），就要改 schema 校验代码、改前端看板 tab、改 skill 对齐题、改目录扫描——多处遗漏。

**v0.8 方案**：把"门类清单"从代码抽到 DB 表，schema 校验、UI、skill 全部从 API 拉，**新增门类 = 写一条 Alembic seed migration**，不动一行业务代码。

```sql
CREATE TABLE case_categories (
  name TEXT PRIMARY KEY,                 -- 系统识别符，英文 snake_case：bug_regression / extension / ...
  display_name TEXT NOT NULL,            -- 中文显示名，前端看板用："BUG 回归" / "Extension 集成测试"
  description TEXT,                      -- 一句话说明本门类做什么、为什么需要
  id_prefix TEXT NOT NULL UNIQUE,        -- case id 必须以此开头："lg-bug-" / "lg-ext-"
  dir_path TEXT NOT NULL UNIQUE,         -- cases/ 下的子目录名："bug-regression" / "extension"
  status_whitelist TEXT NOT NULL,        -- JSON 数组：["open", "fixed", "wontfix", "stub"]
  default_status TEXT NOT NULL,          -- skill 默认值：bug=open, extension=stable
  display_order INTEGER DEFAULT 100,     -- 看板 tab 排序；小的在前
  is_active BOOLEAN DEFAULT 1,           -- 暂时下线某门类（不删表项）
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  created_by TEXT
);
```

**seed 内容**（Alembic 0001 migration 起点；后续加门类各写一条新 migration）：

```sql
INSERT INTO case_categories (name, display_name, description, id_prefix, dir_path, status_whitelist, default_status, display_order, created_by) VALUES
  ('bug_regression',
   'BUG 回归',
   '历史 BUG 的复现 / 修复验证用例。来源主要是飞书 LG 历史 BUG 文档。',
   'lg-bug-',
   'bug-regression',
   '["open","fixed","wontfix","stub"]',
   'open',
   10,
   'seed:0001'),
  ('extension',
   'Extension 集成测试',
   '周边 extension（pgvector / postgis / pgcrypto / ...）的安装 + 基础功能 + 关键边界验证。',
   'lg-ext-',
   'extension',
   '["stable","experimental","deprecated","stub"]',
   'stable',
   20,
   'seed:0001');
```

**消费点**（所有"知道 category 长什么样"的地方都从这张表读，不写死）：

| 消费方 | 用法 |
|--------|------|
| YAML schema 校验（`yaml_loader.py`） | 启动时把 `case_categories` 全表 load 到内存（轻量，~10 条）；校验 case 时按 `category` 查白名单：(a) `id` 是否以 `id_prefix` 开头；(b) `status` 是否在 `status_whitelist` 内；(c) `cases/<dir_path>/` 是否真的有此文件 |
| 前端看板 `/cases` tab | `GET /admin/categories` → 拿到 `[{name, display_name, display_order, is_active}, ...]`，按 `display_order` 渲染 tab，**前端不写死任何 category 名** |
| skill `add-test-case` 对齐题首题 | grounding 时 `GET /admin/categories` → 把 `name` 列表当作选项；display_name 显示给用户；**skill 也不写死** |
| `add-test-case` skill 模式 D `ext:<extname>` | 模式 D 本质 = "category=extension 快捷方式"，如果未来扩出更多门类，可类比加 `bench:<name>` 等模式（不在 v0.8 范围） |
| 目录扫描器 | 启动时按 `dir_path` 列表扫盘，发现 case 不在已知 dir 下 → 校验失败，提示 admin 加 category 还是改 case |

**新增门类的标准流程**（写在 §13.3）：5 步，全部走 PR。

**不暴露 Admin UI 编辑**：`case_categories` 是**设计层**配置，不是运维层配置。改它意味着新设计动作（决定门类语义、status 词汇、目录归属），必须走 PR + design review，不应该让任何人在浏览器里点几下就改。这点与 §4.4 `system_settings` 走 Admin UI 的可调项形成对比。

---

## 5. 后端设计

### 5.1 目录结构

```
backend/
  app/
    main.py              # FastAPI 入口
    config.py            # 配置（psql conn、log 路径、cases 目录、CLAUDE_API_KEY）
    api/
      cases.py           # GET /cases, GET /cases/{id}
      runs.py            # POST /runs, GET /runs, GET /runs/{id}
      llm.py             # POST /llm/parse-case  (自然语言→YAML 草稿)
      submit.py          # POST /cases/submit   (草稿→提 PR)
    runner/
      orchestrator.py    # 按 steps 顺序/并发驱动
      sql_driver.py      # psycopg + 超时/事务
      shell_driver.py    # asyncio subprocess + 超时/捕获
      assertions.py      # 4 种 assert kind 的判定
    storage/
      yaml_loader.py     # 加载并校验 cases/*.yaml
      sqlite_store.py    # runs / case_results CRUD
    llm/
      parser.py          # 调 Claude API，prompt 工程在这
  tests/                 # 后端自己的单元测试
  cases/                 # 测试用例（也可放仓库根 cases/，下面"项目结构"再决定）
  pyproject.toml
```

### 5.2 关键 API

| 方法 | 路径 | 用途 |
|------|------|------|
| GET  | `/cases` | 列出所有用例（含 status / tags / 最近一次运行结果 / 是否在 skip_list）；支持 `?q=<topic>` 全文搜索，用于 skill **查重 grounding**（v0.6） |
| GET  | `/cases/{id}` | 单个用例详情（含 YAML 原文） |
| POST | `/runs` | body: `{case_ids?: [...], target_version: "..."}`，不传 case_ids = 全跑 |
| GET  | `/runs` | 历史运行列表 |
| GET  | `/runs/{id}` | 单次运行详情 + 每个 case 的结果 |
| GET  | `/runs/{id}/stream` | SSE 实时推送进度（前端显示进度条） |
| POST | `/llm/parse-case` | body: `{description: "用户口述..."}`，返回 YAML 草稿（web 路径） |
| POST | `/cases/validate` | v0.6：body: `{yaml: "..."}`，只做 schema 校验（不试跑），返回 errors/warnings |
| POST | `/cases/try` | v0.6：body: `{yaml: "..."}`，**临时**跑一次（不入库 runs 表、不写 case_results 表），返回逐 step 结果。**提 PR 前的必经闸门**——见 §6.4 R7。 |
| POST | `/cases/submit` | body: `{yaml: "..."}`，写到本地 git work tree，新建分支并提 PR。**强校验**：必须能在 `/cases/try` 上 pass 一次，否则拒绝 |
| GET  | `/admin/step-kinds` | v0.6（**skill grounding**）：当前 runner 支持的 step kind 自描述。返回示例：`[{kind: "sql", fields: ["sql", "on", "database", "timeout_sec", "expect"], example: ...}, {kind: "shell", ...}, ...]` |
| GET  | `/admin/categories` | v0.8（**skill / 前端 grounding**）：列出所有活跃测试门类（从 §4.5 `case_categories` 表读，过滤 `is_active=1`，按 `display_order` 排序）。返回：`[{name, display_name, description, id_prefix, dir_path, status_whitelist, default_status}, ...]`。前端看板 tab、skill 对齐题首题、目录扫描器都消费此端点 |
| GET  | `/admin/skip-list` | v0.5：列出活跃跳过规则（含已过期但保留作审计的项） |
| POST | `/admin/skip-list` | v0.5：新增跳过规则 |
| DELETE | `/admin/skip-list/{id}` | v0.5：失效跳过规则（软删，保留历史） |
| GET  | `/admin/settings` | v0.5：列出所有 Tier B 设置 |
| PUT  | `/admin/settings/{key}` | v0.5：修改单个设置 |
| POST | `/admin/reload` | 触发 `git pull` + 重载 YAML（Q5） |
| GET  | `/admin/healthz` | 健康检查（DB 可达 / git work tree 干净 / Claude API key 已配） |

### 5.3 执行引擎

- **sql_driver**: `psycopg[binary]`，每个 step 独立连接（避免事务粘连），支持 `timeout_sec`。多会话场景下：每个 `session` 名维护一个独立连接，跨 step 复用——这样可以测真正的"两个会话之间的锁/MVCC"行为。
- **shell_driver**: `asyncio.create_subprocess_shell`，捕获 stdout/stderr/exit_code，`timeout_sec`。
- **log_grep_driver**（v0.5 新增）: 读取 `log_path` 下当前 run 期间生成的日志段（按 mtime 过滤），按 `pattern` grep，返回 matches 数。
- **orchestrator**: 顺序跑 steps；不同 `on:` 会话名的 step 在各自连接里推进，主流程并发等待；teardown 始终执行（即使中间步骤失败）。检测到服务端日志的 "recover mode" 关键字 = 强制中止剩余 step 并标 "cluster crashed"。
- **artifacts**: 每个 case 一个目录 `artifacts/<run_id>/<case_id>/`，stdout/stderr/server.log 截取段都落盘。
- **超时默认值**（v0.5；借鉴 preflight `restart_step.py:154-163`：60s 是 sync-SSH 时代默认值，不适配现代异步轮询）：

  | step kind | 默认 timeout | 备注 |
  |-----------|-------------|------|
  | sql | 60s | 一般 OLTP SQL 够用，慢查询请显式提 `timeout_sec` |
  | shell | 60s | psql 一行命令、文件检查 |
  | log_grep | 10s | 纯文件读 |
  | restart_db | 600s | gpstop+gpstart 至少 90~150s，给 4× 余量 |

- **串行保证**（v0.5）：前端发 `POST /runs` 时，backend 用 DB 的 `UNIQUE INDEX runs(status) WHERE status='running'` 写一条 running 记录；冲突 = 已有 active run，返回 409。**不**用应用层互斥锁（Python `asyncio.Lock` 失效面太多，进程崩溃时不能保证释放）。

#### 5.3.1 Jinja 渲染上下文（v0.9 新增）

step 的 `sql` / `cmd` / `host` 三个字段在执行前会过一遍 Jinja 渲染。可用上下文：

| 变量 | 含义 | 来源 |
|------|------|------|
| `coordinator.host` | DUT 集群 coordinator 主机名 | §3.1 cluster_topology 里 role=primary content=-1 的那行 |
| `external.<svc>.host` | 外部依赖 `<svc>` 的主机名 | system_settings 里 `external_services` JSON 字段配置；运行前由 admin UI 维护（§4.4 Tier B） |
| `external.<svc>.port` | 端口 | 同上 |
| `external.<svc>.username` | 登录用户名 | 同上 |
| `external.<svc>.password` | 登录密码（**不写进 YAML 字面值**） | 同上 |
| `external.<svc>.extras.<key>` | 自由扩展键（如 `service_name` / `client_principal` / `keytab_path`） | 同上 |

**渲染策略**：用 Jinja2 `StrictUndefined`——占位符不存在直接抛 `UndefinedError`，runner 把这个异常转 case `error` 状态，error_message 是 jinja 原文报错（preflight runner.py:731-738）。这样一来：

| 写法 | 旧行为（v0.8 无渲染规范） | v0.9 StrictUndefined |
|------|---------------------------|--------------------|
| `{{ external.kafka.host }}` 且配了 kafka | 正常渲染 | 正常渲染 |
| `{{ external.kafka.host }}` 但未配 kafka（typo / 未声明 external_deps） | 渲染成空串，psql `connect to ""` 报错谜语 | 直接 `UndefinedError: 'kafka' is undefined`，error_message 直指原因 |
| `{{ external.kafak.host }}`（typo） | 渲染成空串 | 同上 |

#### 5.3.2 远端 cli/shell step 的 ssh 用户决策（v0.9 新增）

step 上写 `host: '{{ ... }}'` 时，runner 决定 ssh 用哪个用户登录：

1. 渲染 `host` 字段得到具体主机名/IP
2. 如果 host **在** `cluster_topology.hostnames` 集合内（即属于 DUT 集群自己） → 用 `gpadmin`（§3.1 约定）
3. 如果 host **不在** cluster_topology 内（外部服务主机如 Oracle / Hive / Kafka VM） → 用 `root`
4. host 字段缺省（None）= coordinator 自身 = `gpadmin`

**preflight Run 47 forensic**（避免重蹈）：早期版本只判 `host != ssh_host` 就强制 root，结果 `host: '{{ external.standby.host }}'` 解析成自己 standby IP，runner 用 root ssh 上去，standby 的 `authorized_keys` 只允许 gpadmin → 静默失败（`|| true` 掩盖）→ 后续 gpactivatestandby 见到 `/tmp/.s.PGSQL.5432.lock` 拒绝激活，整 case 谜之失败。修法 = 维护 `dut_hosts` 集合显式判定。

#### 5.3.3 step 执行的异常处理与排序（v0.9 新增）

| 行为 | 规则 | 来源 |
|------|------|------|
| step 抛任何异常 | 包 try/except，转 `StepResult(status="error", error="<exc>")`；记入 case 但**不冒泡到 suite 层**，下一个 case 继续 | preflight runner.py:768-787，Run 32 教训：一个 paramiko PipeTimeout 拖垮整个 TEST phase，后面所有 case 没跑 |
| 第一个非 pass step | break 后续 step | preflight runner.py:803-806 |
| teardown 失败 | log + 继续，**不**影响 case 最终状态 | preflight runner.py:808-813 |
| `destructive: true` 的 case | 在 suite 内**排到所有非 destructive case 之后** | preflight runner.py:263 `sorted by destructive` |
| setup 失败 | case 直接标 error；steps 不跑；teardown 仍 best-effort 跑 | preflight runner.py:741-748 |

### 5.4 LLM 解析模块（web 录入路径）

**定位**：服务于前端 `/cases/new` 入口 A（"从描述生成"）。skill 路径不走这个模块——见 §5.5。

输入: 用户在前端填的自然语言描述（"我在 1.6.2 跑 VACUUM 同时另一个会话 ALTER TABLE 会卡死……"）。
输出: 一份合法的 YAML 草稿。

实现:
- 走 Anthropic SDK，模型 `claude-sonnet-4-6`（首选），prompt 里塞 YAML schema + 3~5 个 few-shot 例子。
- **开启 prompt caching**（schema + 例子放到 cached prefix），降低成本。
- 返回前在后端做一次 YAML 合法性 + schema 校验，不合法重试一次（最多 2 次）。
- 前端展示草稿后**必须人工确认**，确认后才进入"Validate → Try → Save → PR"流程，绝不直接落盘。

### 5.5 Claude Code Skill — `add-test-case`（v0.6 新增；借鉴 preflight `add-test-case`；v0.7 支持双 category）

**定位**：第二条录入路径，面向**在终端里用 Claude Code 写录入的开发者**（不开浏览器、不离开命令行）。和 web 路径（§5.4）**并列**，最终都把 YAML paste 到前端编辑器，**汇入同一个 Validate → Try → Save 闸门**。

skill 覆盖**两类 category**——`bug_regression`（默认）和 `extension`——区别在第一题"category"选择后走不同的默认值推导分支与场景关键词集合。

#### 5.5.1 设计原则（铁律）

借鉴 preflight `SKILL.md`，本 skill 严格遵守：

1. **Generator-only，无副作用**：
   - ❌ 不用 Write 工具
   - ❌ 不 `git add` / `git commit` / `git push`
   - ❌ 不调 `POST /cases/submit`
   - ❌ 不跑 case（用户在 UI 上点 Try 跑）
   - ✅ 唯一输出 = stdout 上一段 YAML，用 `─── BEGIN YAML ───` / `─── END YAML ───` 包裹（无围栏、无注释混在内部），方便人复制粘贴。
2. **Live grounding**：生成前必须 fetch 四个 backend 端点（v0.8 加 categories）。失败时显式提示用户，**不**编造字段。
   - `GET /admin/categories` — 当前活跃测试门类清单（**禁止**编造 category 名）。skill 首题选项从这里取，default_status / id_prefix / status_whitelist 也来自这里
   - `GET /cases?q=<topic>&category=<name>` — 按 category 查重（避免做重复 case；已有则建议扩展）
   - `GET /admin/step-kinds` — executor 自描述（**禁止**编造 step kind）
   - `GET /admin/settings` — 当前默认 db / 默认 log path 等 Tier B 值（避免与系统不一致）
3. **House-style 学习**：开工前 Read 2-3 个最相似的已有 case YAML（按 tags / 关键词匹配），匹配字段顺序、注释风格。
4. **不嵌入凭据**：DB 密码走 runner（PGPASSWORD 环境变量或 .pgpass），**不**写进 YAML 字面值。
5. **5 题对齐 + 场景特化追问**：详 §5.5.4 / §5.5.5。
6. **canonical field 顺序**：生成 YAML 必须按 §5.5.6 的字段顺序，与 catalog 一致。

#### 5.5.2 输入模式（四选一，v0.7 新增模式 D）

```
/add-test-case <feishu-url>             模式 A：飞书 LG 历史 BUG 文档锚点（多用于 bug_regression）
/add-test-case <local-sql-file>         模式 B：本地 SQL 复现脚本
/add-test-case ext:<extname> [<doc-url>] 模式 D：v0.7 新增——extension 用例，如 ext:pgvector / ext:postgis
/add-test-case                          模式 C：自然语言（skill 反问要做什么）
```

输入歧义时一问澄清（"这是飞书 URL 还是本地路径？是 BUG 回归还是 extension 集成？"），不要凭猜。

- 模式 A 用 **WebFetch**（如果 MCP 不可达，复用 `project005/feishu-skills/mcp-server/feishu_client.py`，见全局 memory `feishu_client_access.md`）。category 默认 = `bug_regression`。
- 模式 B 用 **Read** 读本地文件。category 让 skill 从脚本内容/路径推断（`cases/extension/` 下 → extension；脚本含 `CREATE EXTENSION` 等关键字 → extension）。
- 模式 C 直接问用户，category 作为对齐题首题。
- 模式 D 直接锁定 category = `extension`，extname 进入 tags 与 id 默认 slug；如附带 `<doc-url>`（GitHub / 官方手册），WebFetch 取首页内容做关键词分析。

#### 5.5.3 工作流（7 步）

| 步骤 | 动作 |
|------|------|
| 1 | Read 2-3 个最相似已有 case YAML（按 tags 匹配；优先看与目标 BUG 同类型的） |
| 2 | Fetch 三个 grounding 端点（§5.5.1 规则 2） |
| 3 | 分析输入，从输入推导 5 个默认值 + 检测场景关键词 |
| 4 | 按 §5.5.4 顺序提 5 题，每题展示默认值；空回车 = 接受默认 |
| 5 | 按 §5.5.5 追问场景特化问题（只问检测到的） |
| 6 | 按 §5.5.6 canonical 顺序起草 YAML；做 5 项 cross-check（§5.5.7） |
| 7 | 打印 `─── BEGIN YAML ───` … `─── END YAML ───` + 3 行 footer |

#### 5.5.4 6 个对齐问题（v0.7：category 加为首题；v0.8：选项从 API 拉）

```
1) category    [bug_regression]:     # 选项从 GET /admin/categories 拉，**skill 不写死**
                                     # 当前 seed 有：bug_regression / extension
2) id          [<auto-slug, 按 category.id_prefix + 推 slug>]:
3) title       [<从飞书锚点/脚本注释/extname 提取>]:
4) applies_to.versions  [全适用]:    # 例：">=1.6,<2.0"，留空=所有版本
5) status      [<category.default_status>]:  # 取自 grounding，不写死
6) severity    [medium]:             # high | medium | low
```

skill 在题 1 拿到答案后，把对应 category 的 `id_prefix` / `default_status` / `status_whitelist` 缓存下来，后续 2~5 题的默认值和校验都用这份数据，**不**在 skill 代码里枚举 `if category == "bug_regression": ...`。

**自动推导规则**：

通用规则（与 category 无关）：
- `id` = `<category.id_prefix>` + 推导 slug。slug 推导：
  - 模式 A → 飞书锚点 slug（如 `9.1` → `9-1-hashjoin`）；
  - 模式 B → 脚本文件名 stem；
  - 模式 D → `<extname>-<场景关键词>`；
  - 模式 C → 让用户填。
  - 如果 category 的 `id_prefix` 含编号位（约定：`lg-bug-` 后跟 4 位数字 `NNNN`），则 fetch `/cases?category=<name>` 取最大编号 + 1；不含编号位的就不编号（`lg-ext-` 用 extname 已经够标识）。
- `title`：模式 A 飞书段落首句；模式 B 脚本顶部注释；模式 D 用 extname + 场景；模式 C 让用户填。
- `applies_to.versions`：输入含具体版本号 → 转 PEP 440 spec；否则留空（适用所有）。
- `status`：默认 = `<category.default_status>`；输入含明确状态关键词（"stub / 仅录入" / "实验中" / "废弃"）→ 按 category 的 `status_whitelist` 匹配最近的一个。
- `severity` 启发式：
  - 含 "crash / panic / FATAL / 集群挂 / 进入 recover" → `high`
  - 含 "返回错值 / 计划错 / 性能退化" → `medium`
  - 含 "风格问题 / experimental / 边缘场景" → `low`
  - 缺省 → `medium`

**关键**：skill 代码里**禁止**出现 `if category == "bug_regression"` 这种条件。所有 category 相关默认值都从 grounding 的 `case_categories` 字典查表，未来加门类时 skill 不需要改一行。

#### 5.5.5 场景特化追问（按需追加；按 category 分两组关键词集合）

按输入关键词检测，每命中一类追加 1 题，**不**命中就跳过。

**通用组**（两种 category 都可能命中）：

| 检测关键词 | 追问 | 影响 |
|-----------|------|------|
| `concurrent` / 并发 / VACUUM 同时 / 两个会话 / two session | "需要多会话吗？默认设 `sessions: [s1, s2]`？[yes]" | 加 `sessions:` 段；后续相关 step 加 `on: s1/s2` |
| `crash` / `panic` / `FATAL` / `recover mode` / 集群挂 | "会让集群进入 recover mode 吗？默认末尾加 `kind: log_grep` step 兜底？[yes]" | 末尾加 log_grep step，`pattern: "FATAL: the database system is in recover mode"`，`expect.matches: 0` |
| `mydb` / `createdb` / 自建库 / `lc_ctype` / `lc_collate` | "本 case 需要在非 postgres db 上跑吗？" | 提示用户填 step 级 `database: <名称>`；setup 加 createdb（idempotent） |
| `set <guc> to` / 优化器 / ORCA / `enable_<feature>` | "本 case 依赖特定 GUC 状态吗？要不要加 `preconditions: {options.<guc>: [<allowed>]}`？[no]" | 加 `preconditions:` 段做运行前 gate |
| `explain` / 计划 / plan / hashjoin / 走索引 | "需要断言执行计划包含某字串吗？" | step 上加 `expect.plan_contains: [<keyword>]`，**不**用 `stdout_contains` |
| 耗时 / 超过 N 秒 / 慢查询 / 退化 | "需要性能断言吗？比如 `duration_lt_ms: <ms>`？" | step 上加 `expect.duration_lt_ms: <ms>` |

**Category-tagged 场景组**（按 category 触发；当前只为 `extension` 配置，未来加门类时在 skill 的"场景注册表"里加新组即可，不动主流程）：

仅当 `category=extension` 时跑这组检测：

| 检测关键词 | 追问 | 影响 |
|-----------|------|------|
| `CREATE EXTENSION` / `extension_url` / shared_preload | "extension 是 `CREATE EXTENSION` 即用，还是要进 `shared_preload_libraries`？[runtime]" | preload 类（pg_search / pgaudit）→ 提示 case 必含 `kind: restart_db` step；runtime 类→ setup 加 `CREATE EXTENSION IF NOT EXISTS` |
| `<extname> 版本` / `version` / `extversion` | "要不要断言 extension 版本？" | 加一 step `SELECT extversion FROM pg_extension WHERE extname='<n>'`，配 `expect.scalar: "<expected>"` 或 `expect.scalar_ge: "<min>"` |
| pgvector 关键词 / `vector(` / `<->` / `<=>` / IVFFlat / HNSW | "做 IVFFlat / HNSW 索引断言吗？" | step 加 `CREATE INDEX ... USING ivfflat / hnsw`，配 `expect.plan_contains: ["IVFFlat" 或 "HNSW Index Scan"]` |
| postgis 关键词 / `ST_*` / `GEOMETRY` / SRID | "需要空间索引 + ST 函数验证吗？" | 加 `CREATE INDEX USING gist`，配 `ST_DWithin` 等查询；setup 注意 `CREATE EXTENSION postgis;`（不带 IF NOT EXISTS 会因 schema 已有报错 → 用 IF NOT EXISTS） |
| pgcrypto 关键词 / `crypt(` / `digest(` / `gen_random_*` | "对 hash 输出做精确断言（确定性算法）还是仅断言无错（随机算法）？" | 确定性（sha256/md5）→ `expect.scalar: "<hex>"`；随机（gen_random_uuid/bcrypt salt）→ 只校验返回非空 |
| `CREATE FOREIGN TABLE` / `IMPORT FOREIGN SCHEMA` / FDW / dblink | "外部数据源是否本机已部署？" | 若否，提示用户补 external_deps（首版不支持自动 provision，让用户在 §3.1 外部依赖准备阶段搞定） |
| `plpython` / `plperl` / `plgo` / `plr` / `plcontainer` / 过程语言 | "过程语言是否安装？需要重启 DB 吗？" | 部分语言（plpython3u）需 `shared_preload_libraries` → 提示加 `kind: restart_db` step |
| **v0.9 加：`shared_preload_libraries` / pgaudit / pg_search / 必须 preload** | "本 extension 需要进 shared_preload_libraries（必须 restart）吗？如是，要自管理还是依赖 deployer 全局加？[self-managed]" | self-managed → 把"加 preload + restart + 业务测试 + 移除 preload + restart"全写进同一 case；标 `destructive: true`（preflight 11_pg_search.yaml 是范本：第 53 步把 pg_search 加进 preload，最后两步移除并再 restart） |
| **v0.9 加：`gphdfs.conf` / `gphive.conf` / `krb5.conf` / 服务端配置文件** | "需要写/改 master 上的配置文件吗？" | 提示用 cli step `cat >> "$DD/<file>" <<'YML' ... YML`（**追加 + grep -q guard**），**不要** `cat > ` 覆盖——preflight Run 112 教训：truncate 把 deployer 写的块清空，后续 case 全 fail |
| **v0.9 加：`kinit` / `keytab` / `principal` / Kerberos** | "kinit 用什么 principal / keytab 路径？" | step 用 `{{ external.<svc>.extras.client_principal }}` + `{{ external.<svc>.extras.client_keytab_local }}` 渲染；**避免** `_HOST` 占位（preflight 13_cdh_kerberos 教训：datalake_fdw 里 _HOST 替换不稳，直接写 FQDN） |
| **v0.9 加：`beeline` / `sqlplus` / `mysql` 等远端 CLI** | "需要 SSH 到外部主机执行吗？" | step 加 `host: '{{ external.<svc>.host }}'`，cmd 开头**显式 source profile.d**：`[ -f /etc/profile.d/<x>.sh ] && . /etc/profile.d/<x>.sh \|\| true`（preflight 12_datalake_fdw_hive 教训：SSH 非交互不 source，beeline 找不到 HIVE_HOME） |
| **v0.9 加：fresh pool / 服务刚起来 / "可能 warmup 中"** | "外部服务可能在测试启动时还没 ready 吗？" | seed step 包 retry 循环（典型 6×10s back-off + `break on success`，preflight 12_datalake_fdw_hive seed_hive_fixture 范本） |

未命中任何关键词 → 跳过本步，进入草拟。

#### 5.5.6 canonical 字段顺序

skill 输出的 YAML **必须**按这个顺序，和 catalog 保持一致，diff 才好读：

```yaml
id: lg-bug-NNNN-<slug>                  # 或 lg-ext-<extname>-<slug>
title: <中文 OK>
category: bug_regression                # 或 extension（v0.7 新增）
status: open                            # bug:open/fixed/wontfix/stub  ext:stable/experimental/deprecated/stub
severity: medium
destructive: false                      # v0.9：true 表示改 shared_preload / gpstop / 删数据目录；suite 内排到最后跑
source:
  feishu_anchor: "section-X.Y"          # bug 模式 A 必填
  reported_at: "YYYY-MM-DD"
  fixed_version: ""                     # bug + status=fixed 时填
  ext_doc_url: ""                       # extension 用：官方文档 / 仓库链接
issue_url: ""
tags: [<推断的语义 tag>]                # extension 必含 extname；bug 含模块名

# v0.9 新增：4-tuple 叙事字段（报告渲染"目的/步骤/预期/实测"用）
description: |                          # 本 case 验证什么；覆盖了哪个飞书章节 / extension 哪个能力
procedure: |                            # 编号步骤，reviewer 不读 SQL 也能懂流程
expected: |                             # 预期一句话清单

applies_to: {}                          # 空 = 适用所有版本
preconditions: {}                       # 命中 GUC 场景时填
external_deps: []                       # 首版常为空

defaults:
  database: postgres

sessions: []                            # 命中并发场景时填 [s1, s2]

setup:
  - sql: |
      <DROP IF EXISTS + CREATE + INSERT + ANALYZE，幂等>

steps:
  - name: <短中文/英文描述>
    kind: <sql|shell|log_grep|restart_db>  # 不写时按字段推断
    on: default
    sql: |
      ...
    timeout_sec: 60
    expect:
      <按 §4.1 expect 字段菜单挑>

teardown:
  - sql: |
      <DROP IF EXISTS 收尾>

created_by: <从 git config user.email 推断>
created_at: "YYYY-MM-DD"
notes: |
  <workaround / 触发条件 / 已知信息>
```

#### 5.5.7 打印前 cross-check（5 项）

skill 在打印 BEGIN/END 之前必须自查：

1. **step kind 在 `/admin/step-kinds` 列表里**——禁止编造 `kind: bash` / `kind: psql`。
2. **`expect.plan_contains` 只用在 `kind: sql` step**；`expect.exit_code` 只用在 shell；`expect.scalar` 只用在返回单行单列的 SQL。
3. **`setup` / `teardown` 幂等**：所有 `DROP` 必带 `IF EXISTS`，所有 `CREATE TABLE` / `CREATE EXTENSION` 必带 `IF NOT EXISTS`（除非测的就是 CREATE 本身的语义）。
4. **不嵌入凭据**：grep YAML 里有没有 `password=` / `PGPASSWORD=` 字面值。
5. **status 与字段一致性**（v0.7：按 category 检查白名单）：
   - `category=bug_regression` → status ∈ {open, fixed, wontfix, stub}；`status=fixed` 时 `source.fixed_version` 必填。
   - `category=extension` → status ∈ {stable, experimental, deprecated, stub}。
   - 两类都满足：`status=stub` 时 `steps:` 必须为空（与 §4.1 stub 语义一致）。
6. **id 前缀与 category 匹配**：`bug_regression` 必须 `lg-bug-*`；`extension` 必须 `lg-ext-*`。前缀错 = skill bug，立即修正。
7. **v0.9：destructive 一致性**：steps 里出现 `gpstop` / `gpstart` / `gpconfig -c shared_preload_libraries` / `restart_db` step / `rm -rf .../data` 任一关键词，则 `destructive` 必须为 `true`。漏标 = case 在 suite 中前置跑，污染后续。
8. **v0.9：setup/teardown 幂等守卫**：grep 每条 SQL，`DROP` 必带 `IF EXISTS`、`CREATE TABLE` / `CREATE EXTENSION` 必带 `IF NOT EXISTS` 或包 `DO $$ BEGIN IF NOT EXISTS ... END $$`；缺一律自动加上。
9. **v0.9：Jinja typo 检查**：所有 `{{ external.<svc>.<field> }}` 的 `<svc>` 必须出现在 case 的 `external_deps` 里；不在则 skill 静默修正（把缺的服务名加进 external_deps）或反问用户"这是 typo 还是新依赖？"。
10. **v0.9：远端 cli step profile.d 显式 source**：所有带 `host: '{{ external.* }}'` 的 cli step，cmd 开头**必须**有 `[ -f /etc/profile.d/<x>.sh ] && . /etc/profile.d/<x>.sh || true` 这种模式；缺则插入（按 svc 名推测 `<x>` 是 hadoop / hive / oracle / mysql / kafka 等）。
11. **v0.9：服务端配置文件用追加 + grep guard**：cli step 里 `cat > $DD/gphdfs.conf` 这种**覆盖写**模式 → 强制改成 `cat >> + grep -q '^<key>:' guard` 模式（preflight Run 112 教训）。

不过 cross-check 任一条 → 修正后重试，不打印 BEGIN/END。

#### 5.5.8 输出格式（footer 不可缺）

```
─── BEGIN YAML ───
id: lg-bug-0006-vacuum-alter-table-deadlock
...
─── END YAML ───

下一步：
1) 打开 http://localhost:8000/cases/new → 选「粘贴 YAML」入口
2) 粘贴上方 YAML 块，点 Validate（schema 校验通过）
3) 点 Try（在你已就绪的集群上试跑一次），全绿后 Save → 自动提 PR
```

#### 5.5.9 不做的事（明示）

借 preflight 同款负面清单：

- ❌ 写 `.yaml` 到磁盘
- ❌ `git add` / `commit` / `push`
- ❌ `POST /cases/submit`
- ❌ 触发集群上的真实运行（那是 `/cases/try` 干的）
- ❌ 修改 skip_list / settings / 任何 admin 资源

skill 是 **YAML 编辑器的打字助手**，不是 deployer，不是 reviewer。前端的 Validate + Try + Save 才是 source of truth。

#### 5.5.10 落地

文件位置：`.claude/skills/add-test-case/SKILL.md`（M3b 阶段落地）。内容包括：

- frontmatter（name / description）
- §5.5.1~5.5.9 全部内容（这一节就是 SKILL.md 的 spec）
- 至少 1 个完整 example transcript（如 9.1 hashjoin BUG 的全程问答）
- "Common mistakes" 反例清单

按 preflight 经验，SKILL.md 控制在 500 行内，example 占一半。

---

## 6. 前端设计

### 6.1 页面 / 路由

| 路径 | 内容 |
|------|------|
| `/` | 看板：最近一次 run 的 pass/fail 概览 + 历史 run 列表 |
| `/cases` | 用例库。**Tab 从 `GET /admin/categories` 动态渲染**（不在前端写死 tab 名）。Tab 内支持搜索/筛选 by tag/status；显示是否在 skip_list |
| `/cases/:id` | 单个用例详情（YAML + 历次运行结果） |
| `/cases/new` | **录入编辑器，双入口**（v0.6）：<br>• 入口 A「从描述生成」— 自然语言描述 → LLM 生成 YAML 草稿（§5.4）<br>• 入口 B「粘贴 YAML」— 直接粘贴 skill 生成的 YAML（§5.5）<br>两入口汇入同一编辑器，统一走 **Validate → Try → Save → PR** 三段闸门 |
| `/runs` | 历史运行列表 |
| `/runs/:id` | 单次运行详情：每个 case 一行，点开看 stdout/stderr/artifacts |
| `/runs/new` | 触发新运行：选 target_version、勾用例（默认全选）、点 Run |
| `/admin/skip-list` | v0.5：跳过规则管理（增/查/失效），含 reason 必填、过期时间 |
| `/admin/settings` | v0.5：Tier B 系统设置编辑 |

### 6.2 关键交互
- `/runs/:id` 跑的过程中通过 SSE 拿实时进度，每个 case 状态从 `pending → running → pass/fail/skip` 滚动更新。
- skip 的 case 在 `/runs/:id` 上**显式**显示 skip_reason（避免"为什么没跑"看不到原因）。
- **`/cases/new` 三段式闸门**（v0.6，借鉴 preflight Validate→Try→Save）：
  1. **Validate**：调 `POST /cases/validate`，只做 schema 校验，秒回。
  2. **Try**：调 `POST /cases/try`，**在用户已就绪的集群上跑一次**，结果**不入库**（不污染 runs / case_results 表）。逐 step 显示 pass/fail。**这一步是提 PR 前的必经门**。
  3. **Save**：调 `POST /cases/submit`，写 git work tree → 新建分支 → 提 PR；返回 PR URL。**强校验**：未通过 Try 的 yaml 拒绝 submit。
- skill 路径（§5.5）在 1 之前——用户复制 skill 输出，paste 到入口 B 编辑器，然后流程相同。

### 6.3 技术选型
- Vite + React 18 + TypeScript + React Router + TanStack Query（数据获取/缓存）。
- UI 库：**Tailwind CSS + shadcn/ui**（v0.2 锁定）。shadcn 组件代码进仓库可改、不锁版本；Tailwind 负责原子样式。

### 6.4 前端强约束（v0.5 新增，吸收 preflight CI Quality Bar）

1. **App-level ErrorBoundary 必须**：根组件包一层 `<ErrorBoundary>` 兜底，任何子树抛错都渲染降级 UI（错误摘要 + "回到首页"）。**blank page 永远不是可接受的失败模式**——preflight 在 2026-05-10 之前因为缺这层 boundary，频繁出现"button 报错→整个页面变白"。
2. **API 类型用 codegen，不手写**：`openapi-typescript` 从 FastAPI 的 `openapi.json` 生成 TS 类型；前端 fetch 走 typed client。任何后端 schema 变化在编译时被 TypeScript 抓住，而不是运行时 404/422。
3. **E2E 用 `data-testid` 选择器**：所有交互元素加 `data-testid` 属性；**禁止**用 `.card + .pool-label` 这种结构选择器或 `.first()`——preflight 在 2026-05-19~5-22 修了好几个"组件加 wrapper 后 E2E 失效"的回归。
4. **表单提交必有 contract test**（关键）：每个提交 API 的表单页要写 Playwright 测试，用 `page.route("**/api/...", route => assert(route.request.postDataJSON() == expected))` 断言**提交体的结构**，而不只是断言 "button 存在 / form 渲染"。preflight 案例：pool 121 表单 `vm_cpu` 硬编码 4，可见性测试通过、但提交时 backend 拿到的是 4 而 YAML 写的是 8——契约测试可以在 CI 抓住。
5. **`/runs/:id` loading state 不能闪烁**：SSE 断流时显示"正在重连…"而非清空进度，避免用户误以为 run 失败。
6. **录入编辑器 Try 闸门强制**（v0.6）：`/cases/new` 的 Save 按钮在 Try 未通过时**置灰**，hover 文案"必须先 Try 一次并通过"。理由：preflight 在引入 Try 前出现过"yaml 没跑过先合并、下次 backend 启动加载时才发现写错语法、整张 catalog 加载失败"的回归。
7. **Try 试跑不入库**：`POST /cases/try` 跑出的结果**不**写 `runs` 和 `case_results` 表，artifacts 也不持久化（只在前端 SSE 显示），避免污染历史统计。
8. **前端不硬编码 category**（v0.8）：所有 category-aware 的展示（看板 tab、筛选下拉、用例详情页的状态徽章着色）必须从 `GET /admin/categories` 拉数据；严禁 `if category === "bug_regression"` 这种代码。codegen 类型也只是约束 `name: string`，**不**做枚举类型——因为枚举值会随 seed migration 增长。

---

## 7. 用例存储与 PR 流程

### 7.1 仓库与协作角色约定（v0.7 明确）

**单账号即够用**：仓库托管在 `github.com/talmacschen-arch/lightning-bug-regression`（v0.2 已定），同一个 GitHub 账号 `talmacschen-arch` 既是 PR author 又是 merger。这不需要任何 workaround——只要不开"必须他人 review 才能合并"的分支保护规则即可。

**仓库初始化时 Settings 一次性配置**：

| 位置 | 设置 | 值 |
|------|------|-----|
| Settings → Branches → Branch protection rules | （不创建） | **不**对 `main` 加保护规则 |
| Settings → Branches → 默认分支 | Default branch | `main` |
| Settings → General → Pull Requests | Allow auto-merge | ✅ 开启（用于 §7.2 "auto-merge on green"） |
| Settings → General → Pull Requests | Automatically delete head branches | ✅ 开启 |
| Settings → Actions → General | Workflow permissions | Read and write（让 CI 能在 PR 上评论 / 自动 merge） |
| Settings → General → Features | Issues / Discussions / Projects | 三项启用（v0.4 Q12，v1.3 修订）。Wiki 在 GitHub Free + private 下被 plan 限制自动禁用，PATCH has_wiki=true 不生效——已弃用 Wiki 用 `docs/` 替代 |

**关键澄清**：agent ≠ GitHub 角色。§8 的 8 个 agent（pm-designer / foreman / backend-fixer / frontend-fixer / doc-writer / reviewer / smoke-runner / reporter）**只**在本机 Claude Code 里跑（reporter 由 OS crontab 起独立进程，仍是本机），**不**对应 GitHub PR 上的 Reviewer / Assignee / Author 字段。`reviewer` agent 跑完输出 "APPROVE / REQUEST_CHANGES" 是给你本人看的决策辅助，**不会也无法**在 GitHub PR 里点 Approve 按钮。所以"单账号 author + merger"不会被 review 流程卡住。

### 7.2 PR 提交流程

1. `cases/*.yaml` 是 source of truth。
2. 前端提交新用例：
   - 后端在本地 git work tree（仓库 clone 在 backend 机器上）创建分支 `case/<id>-<timestamp>`。
   - 写入 `cases/<id>.yaml`，commit（**不**带 Co-Authored-By Claude 行，参考全局规范）。
   - 用 `gh` CLI 或 GitHub API push + 开 PR。
   - 返回 PR URL 给前端。
3. PR 合并后，调用 `POST /admin/reload` 触发 `git pull` + YAML 重载（无 webhook，单用户工具人工触发即可，Q5 v0.1 默认）。

**MR/PR-only 工作流**（v0.5 新增，吸收 preflight `2026-05-18` CI 稳定化教训）：

- **禁止直接 push main**（即便是 doc typo）。所有变更都走 `feat/* | fix/* | docs/* | ci/*` 分支，经 PR + 全绿 CI 后合并。auto-merge on green 把流程成本压到 ~30s/次。
- **CI 是闸门，不是参考**：GitHub Actions 中 `pytest` + `tsc --noEmit` + `ruff` + `eslint` + Playwright 都是必过项，**禁止** `continue-on-error: true`。flake 要么修要么 `@pytest.mark.skip("链接 issue")`，但不准把整个 job 标 allow_failure。
- **Repeated bug = playwright reproduce, no exceptions**：同一 BUG 被报第二次（"我上次说我修了的那个又出现了"），下一步必须是用 Playwright/真集群跑一次复现，**不**能用"看我 commit"来回应。preflight 把这条写进了 CLAUDE.md。
- **LLM Review Board P0 误报转义**：如果 `reviewer` agent 报了 P0，但你判断是误报（比如把 `os.system(SHELL_TOOL_PATH)` 误判为 injection 但路径是服务器侧常量），在 PR body 加：
  ```
  ## LLM_REVIEW_SKIP=1
  Reason: SHELL_TOOL_PATH 是 server 侧常量，不接受用户输入；不构成注入。
  ```
  并打 `llm-review-bypassed` 标签，由人 force-merge。**禁止**静默放弃推送——preflight 2026-05-18 lesson #5 就是 agent 看到 FP 直接放弃 push。

---

## 8. 多 Agent 开发协作流程（项目内部 dev workflow）

这是**开发本项目时**使用的协作模式，不是运行时功能。每个 agent 是 Claude Code 的 subagent 配置。

### 8.1 角色与产出（v1.0 调整）

| Agent | 模型 | Write 权限 | 触发 | 产出 |
|-------|------|-----------|------|------|
| **pm-designer** | opus | ✅ | 人启动 | `design.md`、模块详设、变更设计 |
| **foreman** | opus | ❌ | 人启动一次长 session；内部自循环 | 调度决策、final report；运转规则详 §15.1 |
| **backend-fixer** | **opus**（v1.3 用户决策升级；v1.0~v1.2 是 sonnet） | ✅（worktree） | foreman 派 | backend/ 代码 + 提 PR + `gh pr merge --auto` |
| **frontend-fixer** | sonnet | ✅（worktree） | foreman 派 | frontend/ 代码 + 提 PR + `gh pr merge --auto` |
| **doc-writer** | haiku | ✅ | foreman 派 | README / API 文档 / 用户手册 + 提 PR + `gh pr merge --auto` |
| **reviewer** | sonnet | ❌ | foreman 派（PR 创建后） | review 报告（CI 状态 + 6 域审查）；APPROVE / REQUEST_CHANGES / REJECT |
| **smoke-runner** | haiku | ❌ | foreman 派（merge 后） | E2E 结果 + artifacts。集群由你预先准备并 self-check 可用，agent 不负责起集群 |
| **reporter**（v1.0 新增） | haiku | ✅（仅写 docs/status/） | **OS crontab 12:00 / 20:00 + `claude --print "/report-status"`**（v1.3 改路径），独立 OS 进程 | `docs/status/YYYY-MM-DD-HHMM.md`（v1.2：飞书推送已移除，**人工查目录**）；运转规则详 §15.3 |

**关键变化**（v1.0）：
- `scheduler` 重命名为 **`foreman`**，并按 preflight `.claude/agents/foreman.md` 范本重写为"verify loop"模式（10 round / 2h budget；DONE / BLOCKED-ESCALATE / BUDGET-EXHAUSTED 三种 stop condition；同症状失败 2 次立即停 + escalate）。详 §15.1。
- 新增 **`reporter`** agent，独立 cron session，与 foreman session 解耦；只读 `docs/status/foreman-state.json` + `git log` + `gh pr list` 组合出报告。详 §15.3。
- fixer agent 不只是"改代码 + 提 diff"，而是 **"改代码 → 起分支 → 开 PR → `gh pr merge --auto --squash`"**——开完 PR 后 specialist 直接退出，CI 全绿 GitHub 自动合并，不要让 specialist 等 CI。详 §15.2。
- `reviewer` 在 PR 创建后由 foreman 派；reviewer 通过 PR comment 回 APPROVE / REQUEST_CHANGES（**不**点 GitHub Approve 按钮——§11 Q10），只是本人决策辅助。

**v1.3 模型调整**：
- **`backend-fixer` 从 sonnet 升 opus**（用户决策）。理由：backend 是工具的"公信力关键路径"——runner / Jinja 渲染 / 多 session / 跨节点 ssh / 边界处理一旦出错会让所有 case 误判 pass/fail。preflight 用 sonnet 跑 5 周 backend 没崩，但**单层模型 + 强 reviewer 兜底**与**双层稳健（opus + reviewer）**之间，用户选了后者。代价：foreman loop 每 round +1~3min；M1~M5 估算成本 +$50~100。其他 agent 模型不动。
- 其他 fixer / reviewer 保持 sonnet 不调（frontend 出错影响小、reviewer 是 sonnet 已与 preflight 同款）。

### 8.2 流程（v1.0 改）

参见 §15.1 foreman verify loop。简述：

1. **你**给 foreman 一份 sprint 清单（来自 §12 Roadmap 的当前 milestone 子任务）。
2. **foreman** 进入 loop：选最高优先级未完成项 → dispatch specialist → 收回结果 → 决定下一步。
3. **specialist** 改代码 / 跑测试 / 写文档 → push 分支 → 开 PR → `gh pr merge --auto --squash` → 返回 PR URL。
4. **CI**（GitHub Actions：pytest + tsc + ruff + eslint + Playwright）跑通 → GitHub 自动 merge → main 更新。
5. **foreman** 见到"该 PR merged"事件（轮询 `gh pr view <n> --json state`）→ 标该项完成 → 回 step 2。
6. **stop 条件**：清单空 / blocker 触发 / budget 耗尽 / 同症状 fail 2 次。foreman 写 `docs/status/foreman-state.json` 终态。
7. **reporter** 在 12:00 / 20:00 fire，读 state.json + git log + gh pr list 出报告。

### 8.3 6 域审查清单（reviewer 用）

- **correctness**：逻辑是否正确？边界条件？
- **security**：SQL 注入？shell 命令注入？secrets 泄露？
- **performance**：N+1 查询？阻塞 I/O？大文件加载方式？
- **api**：API 是否向后兼容？schema 一致？
- **readability**：命名、注释、文件长度、复杂度。
- **tests**：测试是否真在测意图（不只是结构通过）。参考全局工作方式总则第 7 条。

### 8.4 落地方式
- 每个 agent 写一个 markdown 文件到 `.claude/agents/<name>.md`，用 frontmatter 声明 model / tools。
- `foreman` 通过 Agent tool 派活，不直接改代码（**Never edit code; Never commit**）。
- `reviewer` 只能调 Bash（跑测试）和 Read，不能 Write。
- `reporter` 只能 Read + Bash（跑 `gh pr list` / `git log`）+ Write（仅 `docs/status/`）；**不能**改代码、不能改其他文档；**不调任何外部消息推送**（v1.2 去掉了飞书 MCP）。

### 8.5 多 agent 并发的 worktree 隔离（v0.5 新增，吸收 preflight 2026-05-18 事故）

**事故复盘**（preflight pipeline 136449）：两个 fixer agent 在同一个 git worktree 上并发执行 → A 写 `test_X.py` 还没提交 → B 跑 lint 顺手把 A 的 WIP 一起 commit → 推上去后 test 引用了不存在的实现 → CI 全红。

**v0.5 规则**：

1. **`foreman` 一次派 ≥ 2 个 agent 时，每个必须带 `isolation: "worktree"`**。Claude Code 会为每个 agent 自动开一个临时 git worktree（独立 branch），互不串数据。
2. 派活前过一遍 lint 脚本 `.claude/scripts/check_agent_dispatch.sh`（v0.5 新增）：从 stdin 读 JSON，检查每个 Agent 调用是否带 isolation 字段；不带就 exit 非 0。
3. `reviewer` 和 `smoke-runner` 不需要 worktree（reviewer 只读、smoke-runner 只跑测试不改代码）。仅写代码的 `backend-fixer / frontend-fixer / doc-writer` 受此约束。

**lint 脚本（`.claude/scripts/check_agent_dispatch.sh`）**：约 20 行 bash，借鉴 preflight 同名脚本；M0 第 3 步落地。

---

## 9. 项目结构（一级目录）

仓库地址：`github.com/talmacschen-arch/lightning-bug-regression`（公开空间，v0.2 确定）。

```
lightning-bug-regression/
  README.md
  design.md                    # 本文档
  .claude/
    agents/                    # v1.0：8 个 agent 定义
      pm-designer.md
      foreman.md               # v1.0：自循环编排（§15.1）
      backend-fixer.md
      frontend-fixer.md
      doc-writer.md
      reviewer.md
      smoke-runner.md
      reporter.md              # v1.0：cron 触发定时汇报（§15.3）
    skills/
      add-test-case/            # v0.6：generator-only YAML 草稿（§5.5），M3b 落地
        SKILL.md
      report-status/            # v1.0：reporter 的工作流入口（§15.3.3）
        SKILL.md
    scripts/
      check_agent_dispatch.sh  # 多 agent 并发 worktree-isolation lint（§8.5）
  cases/                       # 用例 YAML，PR review 入口
    bug-regression/            # v0.7：category=bug_regression 的用例
      lg-bug-0001-hashjoin-right-table.yaml
      lg-bug-0002-array-unnest-crash.yaml
      ...
    extension/                 # v0.7：category=extension 的用例
      lg-ext-pgvector-basic.yaml
      lg-ext-postgis-spatial.yaml
      lg-ext-pgcrypto-hash.yaml
      ...
    SCHEMA.md                  # YAML schema 文档（含 category 取值约定）
  docs/
    status/                    # v1.0：foreman state + 定时报告
      foreman-state.json       # foreman 每 round 写（§15.1.3）
      2026-05-24-1200.md       # reporter cron 12:00 输出（§15.3.4 格式）
      2026-05-24-2000.md       # reporter cron 20:00 输出
      ...
  backend/                     # Python + FastAPI
  frontend/                    # React + TS + Vite
  scripts/
    bootstrap.sh               # 一键起开发环境
    smoke.sh                   # smoke-runner 用的 E2E 入口
  .github/
    workflows/                 # CI: backend pytest + frontend tsc + lint
```

---

## 10. 部署与运维

### 10.1 后台数据库选型：SQLite（v0.8 独立成段）

**结论**：后台数据库用 **SQLite**，文件默认 `./data/runs.db`，可由 Tier A `DATABASE_URL` 覆盖。

**为什么是 SQLite，不是 PostgreSQL / MySQL**：

| 维度 | SQLite 适配 | 选 PG 反而是负担 |
|------|-------------|------------------|
| 访问模式 | **单 backend 进程**串行写（§5.3 DB UNIQUE 约束保证一时只一 active run），写不竞争 | 多连接 / pool 优势在本场景无收益 |
| 数据量 | 单用户一年内 case ~ 10²、runs ~ 10³、case_results ~ 10⁵、artifacts 文本指针 ~ 10⁵——远低于 SQLite 100GB 单文件、~10¹³ 行的现实上限 | 杀鸡焉用 |
| 运维 | **零运维**：装 Python 即有；备份 = 一个 `cp data/runs.db backup/`；迁移 = 拷文件 | 要装 server、配 pg_hba、设角色、留意 vacuum、调内存 |
| 部署 | docker compose 都不用，`uv run uvicorn` 一行起；客户机器条件有限**正是**这里的硬约束 | 多一个 service、多一份内存预算、多一处可坏 |
| 备份恢复 | `tar -czf backup.tgz ./data/ ./cases/` 一行；恢复就反过来 | pg_dump / pg_restore + 角色对齐 |
| Alembic 兼容 | 完全兼容（除少数 ALTER COLUMN 需用 batch_alter_table） | 也兼容 |
| 并发读 | 多前端 tab 并发读没问题（WAL 模式）；只有同时**写**才会阻塞，本场景没有 | 并发写也没需求 |

**SQLite 已知短板和本项目的应对**：

| 短板 | 影响 | 应对 |
|------|------|------|
| 不支持多写并发 | 多人同时点 Run | 单用户工具，本身就规定串行（§5.3 DB 唯一约束） |
| 不支持 LISTEN/NOTIFY | settings 变更不能跨进程广播 | 单进程 backend，30s 进程缓存够用（§4.4） |
| 没有真正的 ALTER COLUMN | Alembic 改类型麻烦 | 用 `batch_alter_table` 即可；本项目大改 schema 频率低 |
| 不能远程访问 | 跨机查 DB 麻烦 | 跨机查 DB 不在 use case 内；要查就 ssh 进 mdw 用 sqlite3 |

**触发迁 PG 的阈值**（任一满足则评估迁移）：

1. 用户从 1 个变成 ≥ 3 个（出现并发写需求）
2. case 数量 > 10⁴ 或 case_results 行 > 10⁷（开始触及性能边界）
3. 引入异步 worker 队列（需要 LISTEN/NOTIFY 或 SKIP LOCKED）
4. 数据需要跨机房 / 跨主机访问

**迁移成本**：用 SQLAlchemy + Alembic 抽象 SQL 层，迁 PG 是一次性 schema 迁移题（参考 preflight HA spec），不是代码重写。约 1~2 天工作量；本项目暂不规划。

### 10.2 部署形态与配置

- 单机部署即可。后端 `uvicorn` 起 8000 端口；前端 build 后由后端 StaticFiles 一起 serve（部署简单），或 nginx 前置。
- 配置分层（v0.5，参考 §4.4）：
  - **Tier A 引导**：`~/.post_upgrade_test/env`（mode 600），含 `DATABASE_URL` / `CLAUDE_API_KEY`，启动时 `dotenv` 加载。
  - **Tier B 运行时**：`system_settings` 表，Admin UI 编辑。
  - **Tier C 内容**：git 仓库下 `cases/*.yaml` + schema 定义代码。
- 数据库 SQLite 文件路径可配置（Tier A），默认 `./data/runs.db`。
- 日志：stdout + 每日切分文件，30 天滚动。
- 备份：单文件 SQLite + 本地 artifacts 目录，`tar -czf backup.tgz ./data/ ./cases/` 即可。schema 走 Alembic，避免"v1 db 文件 v2 跑不起来"。
- **不做 HA**：单用户工具，单点崩溃可接受（且数据可从 git 仓库 + 用户本地备份恢复）。

---

## 11. 开放问题 / 待讨论项（汇总）

> 状态记号: ⏳ 进行中　✅ 已决议（v0.x 落账）　❌ 不做

| # | 状态 | 问题 | 决议 / 现状 |
|---|------|------|-------------|
| Q1 | ✅ v0.3 | 真实 BUG 样本（飞书 9.1~9.5）以验证 schema 覆盖度。 | 已通过 `project005/feishu-skills` MCP 客户端拉取（doc_id `QY4pdciCBoAkbQxpITrcvwTJn9b`）。5 例驱动 v0.3 补出 6 项能力，schema 验证通过。 |
| Q2 | ✅ v0.2 | 测试语义：BUG 复现 = pass 还是 fail？ | **fail**。所有用例正面期望 = 修复后行为；红色 = 仍有 BUG。`should_fail` 已移除。 |
| Q3 | ⏳ | 并发 step 是否要 `wait_for` 同步原语？ | 默认不加；背景 step 在 teardown 前 join。等真实 BUG 样本里有跨 step 强同步需求时再加。 |
| Q4 | ✅ v0.1 默认 | LLM 是否支持本地模型？ | 否，仅 Claude API。 |
| Q5 | ✅ v0.1 默认 | PR 合并后如何刷新？ | `POST /admin/reload` 手动触发 `git pull` + 重载 YAML，不上 webhook。 |
| Q6 | ✅ v0.2 | UI 库 | **Tailwind + shadcn/ui**。 |
| Q7 | ✅ v0.2 | 仓库名 | **`lightning-bug-regression`**，托管 `talmacschen-arch` 公开空间。 |
| Q8 | ✅ v0.1 默认 | 飞书文档锚点 | 仅作人读引用，不程序化访问。 |
| Q9 | ⏳ | 多 agent 协作配置 | §8 v0.1 方案不调整（用户 2026-05-23 确认）。具体 `.claude/agents/*.md` 文件内容待 M0 落地时细化。 |
| Q10 | ✅ v0.4（v0.7 细化） | §8 的 agent 角色（pm-designer / reviewer / smoke-runner 等）是否需要对应到 GitHub 账号？单 GitHub 账号会不会卡 review/merge 流程？ | **不需要**。agent 是 Claude Code 本机 subagent，**与 GitHub PR 上的 Reviewer/Assignee 字段无任何绑定**。reviewer agent 的 "APPROVE/REQUEST_CHANGES" 是给本人看的决策辅助，不需要也无法在 GitHub PR 上点 Approve。单 GitHub 账号（`talmacschen-arch`）既做 PR author 又做 merger 完全可行——**前提是 Settings → Branches 不对 `main` 加 "Require pull request reviews" 保护规则**（详 §7.1 仓库初始化设置表）。GitHub 默认就不设，无需操作。 |
| Q11 | ✅ v0.4 | LICENSE 选型 | **Apache-2.0**（与 cbcopy 等常用项目一致；包含专利授权条款，更适合公开协作）。 |
| Q12 | ✅ v0.4（v1.3 修订） | GitHub 仓库 features 启用范围 | **三项启用**：Issues / Discussions / Projects。v0.4 原决议是全开含 Wiki，但 v1.3 用户切 private 后实测——**Wiki 在 GitHub Free + private 下被 plan 限制自动禁用**（PATCH has_wiki=true 不报错但实际值不变）。**接受现状，不升 plan**——本项目所有 design / 运维 / runbook / 历史报告都走仓库内 `docs/` 目录，比 Wiki 更适合 PR review + version 化追溯。 |
| Q13 | ✅ v0.4 | 首批 5 个用例 `status` 字段约定 | **全部标 `open`**（覆盖 v0.3 §13 的"按飞书有无 fix 版本"方案）。理由：M0 阶段尚未在本机实际验证修复效果，不假设修复版本可信；待手动跑通后再升级为 `fixed`。注意：9.3 仍保留 `status: stub`，因为它根本没有可执行 SQL，与"是否已修复"是正交的两件事。 |
| Q14 | ✅ v0.5 | 断言机制：top-level `assert: list` vs step 级 `expect:` | **step 级 `expect:`**。借鉴 preflight `Step.expect` 设计（`schema.py:117`）。理由：(a) 断言绑定到产生输出的 step，无须反向引用 step 名；(b) step 改名不会破坏断言；(c) 跨 step 的需求用 `kind: log_grep` step 或末尾收尾 SQL step 表达。`log_pattern` 提升为独立 step kind `log_grep`。 |
| Q15 | ✅ v0.5 | 已知上游 issue 的 case 怎么标"跳过" | **新增 `case_skip_list` DB 表 + Admin UI**，不再用 YAML 里的 `status` 或 ad-hoc `enable_X=true` GUC。理由：preflight 早期把 skip 写进 YAML 后非常难治理——多 case 共享一个 gate 时删除上游 issue 容易漏改；表治理带 `upstream_issue` / `until_date`，过期自动失效。 |
| Q16 | ✅ v0.5 | SQLite 还是 PostgreSQL | **SQLite**。单用户本机工具不需要 PG 的 LISTEN/NOTIFY / 多连接 / HA。设计层把 schema 走 Alembic、SQL 层走 SQLAlchemy 抽象，**未来若多用户化可平滑迁 PG**——preflight 的 HA spec 是现成蓝图。 |
| Q17 | ✅ v0.5 | 配置散落问题（preflight pool 121 案例）怎么避免 | **三层配置模型**：Tier A 引导（disk env，DB 不可达前）、Tier B 运行时（`system_settings` 表 + Admin UI）、Tier C 内容（git）。前端 timeout/默认 db/日志路径等可调项必须走 Tier B，**禁止前端硬编码**。 |
| Q18 | ✅ v0.5 | 串行运行保证机制（同时点两次 Run） | **DB 唯一约束**：`UNIQUE INDEX runs(status) WHERE status='running'`，第二次提交直接 INSERT 失败返回 409。不用应用层锁——进程崩了 Python 锁释放不掉，DB 约束随事务回滚自动失效。 |
| Q19 | ✅ v0.5 | 单用户也强制 MR-flow 吗 | **是**。即便单人单仓也走 `feat/* | fix/*` 分支 + PR + green CI auto-merge。理由：(a) 留可审计的 commit 边界；(b) reviewer agent 必须在 PR 上才能干活；(c) auto-merge 把成本压到 30s，没有理由直接 push。 |
| Q20 | ✅ v0.5（v1.0 改名） | 多 agent 并发的隔离 | **强制 `isolation: "worktree"`**，且 `foreman` 在派活前跑 `.claude/scripts/check_agent_dispatch.sh` 校验。理由：preflight 2026-05-18 事故——共享 worktree 下 lint agent 把另一个 agent 的 WIP 一起 commit，CI 全红。（v0.5 原决议写的是 `scheduler`，v1.0 重命名后此项同步） |
| Q21 | ✅ v0.6 | 是否提供命令行录入路径（Claude Code Skill） | **是，新增 `add-test-case` skill（§5.5）**。严格 generator-only：不写盘、不 git、不调保存 API；唯一输出 = stdout 上 `─── BEGIN/END YAML ───` 标记包裹的 YAML 串，由人 paste 到 `/cases/new` 入口 B。理由：v0.5 原方案"CLI / Skill 不做"漏掉了"开发者在终端里就能录"这一刚需场景；preflight 同款 skill 已在生产验证。skill 路径与 web 路径**汇入同一个 Validate→Try→Save 闸门**，质量门统一。 |
| Q22 | ✅ v0.6 | 是否需要"提 PR 前先试跑一次"的强校验 | **是，引入 Try 闸门**（`POST /cases/try`）。Save 按钮在 Try 未通过时置灰。试跑结果**不入库**（不污染 runs/case_results 表）。理由：preflight 在引入 Try 前发生过"yaml 没跑过就合并，下次 backend 启动加载时整张 catalog fail"的回归——单条 case 烂语法连累全局。Try 是 30 秒内的廉价闸门，没有不开的理由。 |
| Q23 | ✅ v0.7 | 是否扩展到 extension 集成测试 | **是**。Schema 顶层新增 `category` 字段，取值 `bug_regression`（默认）和 `extension`。理由：研发侧的 extension 测试因周边环境不充分（数据 fixture / 真实索引规模 / 与其他 extension 交互场景）覆盖度不够，必须在交付侧再补一层闸门。两类用例**共用同一份 runner、schema、UI**，只在统计 / 看板 / Run 子集筛选时按 category 拆分。仓库名仍是 `lightning-bug-regression`（v0.2 已锁定，不动），但范围扩张已在 §1/§2 同步。 |
| Q24 | ✅ v0.7 | 仓库名要不要改成更通用的（如 `lightning-test-regression`） | **不改**。仓库名已在 v0.2 锁定，外部链接 / agent 配置 / 全局 memory 都引用了；改名收益小于成本。"BUG regression" 在中文语境下也常被理解为"回归测试"广义概念。在 README / design.md 里明确范围扩张即可。 |
| Q25 | ✅ v0.7 | `status` 词汇是否要为 extension 单独设计 | **是**。bug_regression 用 `open / fixed / wontfix / stub`（围绕"是否已修"），extension 用 `stable / experimental / deprecated / stub`（围绕"成熟度"）。`stub` 在两类下含义一致（缺可执行 steps，run 时 skip）。schema 层按 `category` 卡白名单，避免误填。 |
| Q26 | ✅ v0.8 | 后台数据库选 SQLite 还是 PG | **SQLite**。已在 v0.5 Q16 决议，v0.8 §10.1 补独立说明：单进程访问 / 零运维 / 一文件备份 / 数据量远不到上限。SQLAlchemy + Alembic 抽象保证未来迁 PG 是 1~2 天 schema 迁移工作，不是代码重写。触发迁移的 4 个阈值见 §10.1。 |
| Q27 | ✅ v0.8 | 未来加测试门类时如何保证不改多处代码 | **门类清单从代码搬到 DB 表**：§4.5 `case_categories` 表存 name / id_prefix / status_whitelist / default_status / dir_path / display_order；前端 tab、skill 对齐题、schema 校验、目录扫描全部从 `GET /admin/categories` 拉。新增门类 = 写一条 Alembic seed migration，**不动业务代码**。Admin UI **不**暴露此表编辑（设计动作走 PR，不走运维界面）。前端 codegen 类型把 `category` 标为 `string` 而非枚举，否则枚举常量会变成新的硬编码点。 |
| Q28 | ✅ v1.0 | 多 agent 协作能不能形成 loop / 不用人盯 | **能**。§15 落地三件套：(a) foreman verify loop（10 round / 2h budget，stop conditions 明确）；(b) GitHub auto-merge（specialist 设 `gh pr merge --auto --squash` 后即退，CI 全绿自动合并）；(c) cron 12:00 / 20:00 定时 reporter 汇报。preflight `.claude/agents/foreman.md` 已生产验证 5 周（2026-04~05）。 |
| Q29 | ✅ v1.0（v1.2 改） | 12:00 / 20:00 报告输出到哪儿 | **仅本地 `docs/status/<YYYY-MM-DD-HHMM>.md`，用户人工到目录下查**（v1.2 用户决策：飞书 chat 未打通）。报告 schema 固定 8 段不变，**§4 needs_human 是唯一允许"挂起"的事项类**。原 v1.0 的飞书推送链路已删除，对应 `feishu_send_*` 代码 / `feishu_report_chat_id` 设置项都不实现。 |
| Q30 | ✅ v1.0 | foreman 一次 session 的预算上限 | **10 round 或 2h，取先到者**（用户决策）。10 round ≈ preflight 默认；2h 壁钟兜底"某个 specialist 跑飞了"的情况。超 budget = 立即写 state.json + handoff doc 后 session 退出，等下次启动。 |
| Q31 | ✅ v1.0（v1.2 改） | 卡住时（同症状 fail 2 次）的处理 | **立即停 + 写 state.json + 等下次定时报告**（用户决策）。foreman 把 `needs_human` 项写进 state.json；reporter 下次 fire 时 §4 高亮上报。**无即时通知通道**（v1.2 去飞书）——所有事件都进下次报告。仓库不可访问 / 强制 push 失败这类系统级事件 reporter 在报告顶部加 `🚨 SYSTEM_ALERT:` 红字行（§15.3.5），让你扫一眼能区分"普通进度"还是"系统挂了"。 |
| Q32 | ✅ v1.3 | 定时 cron 是用 Claude Code `CronCreate` 还是 OS crontab | **OS crontab + `claude --print "/report-status"`**（v1.3 实测发现 `CronCreate` 是 session-only + REPL idle 才 fire，foreman 持续 mid-query 时永远不 fire——根本不适用）。OS crontab 的好处：与 Claude session 完全解耦，独立 OS 进程 fire；session 退出/重启不影响。落地命令在 §15.3.1。残余约束：cron 不读用户 PATH，必须写 `/root/.local/bin/claude` 绝对路径。 |

---

## 12. Roadmap / 里程碑

- **M0 项目骨架**（design.md 定稿 + agent 配置 + skill 占位 + 仓库创建 + CI 框架）
- **M1 后端 MVP**：load YAML / run / sql_driver + shell_driver + log_grep / SQLite + 4 张表（runs / case_results / case_skip_list / system_settings）/ 基本 API
- **M2 前端 MVP**：/cases（按 category 分 tab）、/runs/new、/runs/:id，能完整跑通"看 case → 触发 run → 看结果"
- **M3a Web 录入**：/cases/new 双入口编辑器 + Validate/Try/Save 三段闸门 + LLM 描述路径 + `/cases/submit` PR 流程
- **M3b Skill 录入**：`.claude/skills/add-test-case/SKILL.md` 落地（generator-only，双 category 支持）+ backend grounding 端点（`/admin/step-kinds`、`/cases?q=&category=`）
- **M4a bug_regression 用例填充**：从飞书文档导入历史 BUG 5 例（你提供原文，优先用 skill 路径 dogfood）
- **M4b extension 用例填充**（v0.7 新增）：首批 extension 集成测试 3~5 例（pgvector / postgis / pgcrypto / pg_hint_plan / fuzzystrmatch 中先选 3 个），用 skill 模式 D `ext:<extname>` 路径录入
- **M5 体验打磨**：SSE 进度条、artifacts 下载、tag 筛选、运行历史 diff、Admin UI（skip_list / settings）、看板按 category 分组统计

每个里程碑结束都跑一次 smoke-runner 端到端验收（在你预先准备好的 lightning 集群上跑几个金标用例）。

---

## 13. 下一步行动

v0.8 完成。**等你终审 design.md 后开 M0。**

### 13.0 启动前自检（M0 step 0，**任一不通过则不开 M0**）

下面 4 项（v1.1 是 5 项，v1.2 去掉飞书 chat_id 后变 4 项）是 design.md 假定成立、但需要在动第一个 git commit 之前手动 verify 的"硬前提"。**全部 ✅ 后才进入 §13.1**。

#### A. GitHub PAT scope 够

**v1.3 实测验证方式**（不依赖 `gh auth login`，直接查 token scope）：
```bash
TOKEN=$(sed -n 's|https://[^:]*:\([^@]*\)@github.com.*|\1|p' ~/.git-credentials | head -1)
curl -sI -H "Authorization: token $TOKEN" https://api.github.com/user | grep -i x-oauth-scopes
# 期望返回："x-oauth-scopes: repo, workflow"（至少这两个）
```

**v1.3 实测结果**（两次）：
- 初次（14:33 CST）：`x-oauth-scopes: repo` ——⚠️ 缺 `workflow`
- 用户补完后（14:50 CST）：`x-oauth-scopes: repo, workflow` ——✅ **已补齐**

**当时的修复操作**（已完成，记录留作 reference）：
1. 浏览器打开 https://github.com/settings/tokens
2. 找到 40 字符的 classic PAT
3. Edit → 勾 `workflow` scope → Update token（token 字符串不变）
4. 重跑 curl 验证含 `repo, workflow`

不通过的影响（**v1.3 已规避**）：specialist 提 PR 调 `gh pr merge --auto --squash` 时**普通代码 push 不影响**（只要 `repo`），但**改 `.github/workflows/*.yml` 时 push 会 403**——M0 step 4 接入 CI 那一步会卡。补齐后此风险关闭。

**gh CLI 绑 token**（可选，让 specialist 不用每次带 `GH_TOKEN=$(...) gh ...`）：
```bash
TOKEN=$(sed -n 's|https://[^:]*:\([^@]*\)@github.com.*|\1|p' ~/.git-credentials | head -1)
echo "$TOKEN" | gh auth login --with-token
gh auth status   # 现在应该 OK
```

#### B. 定时汇报路径可行（v1.3 重写）

**v1.0~v1.2 的错误假设**：以为 Claude Code 内置 `CronCreate` 是 OS-level cron。**v1.3 实测打破**：CronCreate 是 **session-only**（session 退出即死）+ **REPL idle 才 fire**（foreman 持续 mid-query 时永远 fire 不了）。改路径。

**v1.3 路径**：OS crontab + `claude --print "/report-status"` 独立进程。

**验证步骤**：
```bash
# 1. claude CLI 支持 non-interactive：
which claude && claude --help | grep -- "--print"
# 2. 跑一次 trivial non-interactive 验证 claude --print 真能跑：
echo "Just say 'pong' and nothing else" | claude --print
# 3. root crontab 当前为空（避免与其他 entry 冲突）：
crontab -l  # 期望 "no crontab for root" 或可控的少量 entry
```

**v1.3 实测结果（已通过）**：
- ✅ `claude --print` 实测能跑（`echo hello | claude --print` 返回正常回答）
- ✅ root crontab 当前空，可安全加 entry
- ✅ `claude` 在 `/root/.local/bin/claude`，crontab entry 里**必须**显式写绝对路径或 `source ~/.bashrc`（cron 不读用户 PATH）

**M0 step 8 真正注册 cron 时**（§13.1 step 8）：
```bash
# 编辑 root crontab：
crontab -e
# 加两行：
0 12 * * * cd /data0/chenqiang/project009/lightning-bug-regression && /root/.local/bin/claude --print "/report-status" >> docs/status/cron.log 2>&1
0 20 * * * cd /data0/chenqiang/project009/lightning-bug-regression && /root/.local/bin/claude --print "/report-status" >> docs/status/cron.log 2>&1
# 验证：
crontab -l   # 看到两行
date         # 等到下个 12:00 / 20:00 后看 docs/status/ 有新 md
```

不通过的影响：v1.3 已实测通过，不再是不确定点。残余风险：cron 跑 `claude` 进程时如果机器重启、claude CLI 更新导致 path 变化、`/root/.local/bin/claude` 不在 cron 的 PATH 内——所以**必须写绝对路径**。

#### ~~C. 飞书私聊 chat_id~~（v1.2 删除）

用户决定不接飞书推送，报告由你**人工到 `docs/status/` 目录下查**。本节及其相关 seed / settings 项已从 design 全部移除。

#### D. lightning 集群三件套自检
```bash
# 在 mdw 节点上跑（即 Claude Code 所在节点）。root 可直接 su 切 gpadmin，无密码。
su - gpadmin -c "psql -c 'SELECT version()'"
su - gpadmin -c "psql -c 'SELECT count(*) FROM gp_segment_configuration'"
ssh -o BatchMode=yes -o ConnectTimeout=5 sdw1 'hostname'   # root 免密
su - gpadmin -c "ssh -o BatchMode=yes -o ConnectTimeout=5 sdw1 'hostname'"  # gpadmin 也免密
```

**v1.3 实测结果**（2026-05-23 14:33 CST）：
- mdw 实际 hostname: `synxdb-0001`（在 §3.1 已固化）
- DB 版本: **SynxDB4 4.5.0 build 130** (PostgreSQL 14.4 / Apache Cloudberry 2.1.0)
- gp_segment_configuration: **18 行**
- ssh sdw1 解析到: `synxdb-0003`，root 和 gpadmin 都通

不通过的影响：M1 第一次跑 runner 时 fail-fast（§3.1 healthz 设计就是为此），M0 阶段先验明能省下排查时间。**v1.3 已 ✅，可放心进 §13.1。**

#### E. `/foreman` 读 sprint 清单的位置约定（**design 补充**）
```
约定：foreman 在 dispatch 第一轮前，按以下顺序找 sprint 清单（停在第一个找到的）：
  1. 用户在 `/foreman <args>` 的 args 里直接贴的 markdown（最高优先级，覆盖一切）
  2. docs/plans/<sprint-label>.md（如 `/foreman M1` → 读 docs/plans/M1.md）
  3. docs/plans/current.md（兜底，让人类能把"当前要干啥"集中在一个文件）
  
清单 markdown 格式（preflight docs/plans/ 同款，**无 frontmatter**）：
  # M1 后端 MVP

  - [ ] M1-1 SQLite Alembic 0001 五张表
  - [ ] M1-2 yaml_loader（含 category 校验、Jinja StrictUndefined）
  - [ ] M1-3 sql_driver + SessionPool（多会话）
  ...

foreman 把每行 `- [ ] <id> <description>` 当一个 sprint item；
完成时改成 `- [x]` 并 commit（**doc-only commit**，无 PR——节流）。
```
不通过的影响：无（这是 design 缺口，本节补完即关）。

#### 自检通过的输出（v1.3 实测填表；2026-05-23）

| # | 项 | 实测结果 | 状态 |
|---|----|----------|------|
| A | PAT scope | `repo, workflow` ✅（14:50 CST 用户补完 workflow scope；初次 14:33 CST 缺 workflow，记录留作 reference）；token 长度 40 | ✅ |
| B | 定时汇报路径 | `claude --print` ✅ 实测能跑（`echo hello \| claude --print` 返回正常），root crontab 空可写。已放弃 v1.0~v1.2 的 CronCreate 路径，改 OS crontab + `claude --print "/report-status"` | ✅ 路径已验，等 M0 step 8 真注册 |
| D | 集群三件套 | mdw=`synxdb-0001`, DB=SynxDB4 4.5.0 build 130 (PG 14.4 / CBDB 2.1.0), gp_segs=18 行, ssh sdw1=`synxdb-0003` 免密通 | ✅ |
| E | 清单位置 | `docs/plans/M<n>.md` 约定已写进 §13.0-E（design 缺口补完） | ✅ |

**4 项整体判定**：**全 ✅，可进 §13.1 step 1 = 在 `talmacschen-arch` 公开空间建仓 `lightning-bug-regression`**。

### 13.1 M0 计划（按顺序）
1. 在 `talmacschen-arch` 公开空间创建仓库 **`lightning-bug-regression`**（LICENSE: Apache-2.0；Issues / Discussions / Wiki / Projects 全开），author email 用 `talmacschen@gmail.com`（按全局环境约定）。
2. 铺目录骨架（§9）+ README + LICENSE 文件 + `.claude/skills/add-test-case/` 占位目录 + `.claude/skills/report-status/` 占位目录（M3b / cron 启用时再填，但目录先建）。
3. **写 8 个 agent 定义**（v1.0 调整）到 `.claude/agents/*.md`（§8.1 表格）+ `.claude/scripts/check_agent_dispatch.sh`（§8.5），统一 model / tools / write 权限。foreman / reporter 严格按 §15.1 / §15.3 写。
4. 接入 CI（GitHub Actions：`pytest` + `tsc --noEmit` + `ruff` + `eslint` + Playwright；**禁止 `continue-on-error`**）。GitHub Settings 按 §7.1 + §15.2.3 一次性配好（Allow auto-merge / squash only / delete head branches / workflow R+W）。
5. 第一批用例落 `cases/bug-regression/`（全部 `category: bug_regression`、`status: open`，9.3 因无可执行 SQL 用 `status: stub`），用 **v0.5 step 级 `expect:` 写法**：
   - `lg-bug-0001-hashjoin-right-table.yaml` (9.1, `status: open`)
   - `lg-bug-0002-array-unnest-crash.yaml` (9.2, `status: open`)
   - `lg-bug-0003-count-no-statistics.yaml` (9.3, `status: stub`)
   - `lg-bug-0004-ctas-rowcount-zero.yaml` (9.4, `status: open`)
   - `lg-bug-0005-lc-ctype-upper.yaml` (9.5, `status: open`)
   - 这 5 个就是 schema 的 dogfooding 验证；待本机实际跑通后再按真实结果把已修复的提到 `fixed`。
   - `cases/extension/` 目录建空，**M4b 才填**首批 extension 用例（不阻塞 M0）。
6. Alembic 0001：建 `runs / case_results / case_skip_list / system_settings / case_categories` 五张表（含 §4.2 唯一约束 + §4.5 seed 两条 category 记录）。
7. **写 `/report-status` skill 骨架**（§15.3.3）：`.claude/skills/report-status/SKILL.md`，跑通"读 git log + gh pr list → 写 docs/status/<ts>.md"即可（v1.2 已去飞书推送，无外部消息通道）。
8. **注册 OS crontab**（M0 收尾的最后一步；v1.3 改路径，step 8 实测细化）：
   ```bash
   sudo ./scripts/install-cron.sh --apply   # idempotent；写 wrapper 路径，不直接 inline claude
   sudo ./scripts/install-cron.sh --check   # 两个 ✓
   ```
   两条 entry 调 wrapper（详 §15.3.1）：
   ```
   0 12 * * * <repo>/scripts/cron-report-status.sh >> <repo>/docs/status/cron.log 2>&1
   0 20 * * * <repo>/scripts/cron-report-status.sh >> <repo>/docs/status/cron.log 2>&1
   ```
   wrapper 承担三件 cron-context-only 事：source `/root/.bashrc` 拉 proxy / inline GH_TOKEN / `claude --print --permission-mode auto`（详 §15.3.1 wrapper 三件事段）。端到端验证已在 step 8 当场实测两轮，分别产出 `docs/status/2026-05-23-2211.md`（commit `7d97986`）与 `docs/status/2026-05-23-2217.md`（commit `31f8653`），8 段 schema 全渲染、§3 PR 数据正确 empty array、push 直达 origin/main。
9. **第一次启动 foreman 做 dry-run**：用户跑 `claude` → `/foreman M0-validate`，给 foreman 一个 trivial 清单（"开一个 docs PR 改 README typo"），观察 foreman→fixer→PR→auto-merge→state.json 全链路；后续 M1 起就真正放手。

### 13.2 待跟进项（不阻塞 M0）
- Q3（并发 step 是否要 `wait_for` 同步原语）：v0.5 引入 `sessions` 后已大幅减少需求，等真实用例出现跨会话强同步时再加 `wait_for: <step name>` 字段。
- Q9（agent 详细配置）：M0 第 3 步落地时细化每个 `.claude/agents/*.md`。
- `restart_db` step kind 实现：M1 之后再做（首批 5 例不需要）。
- `external_deps` resolver：M4 接入飞书新 BUG 时再补。
- `add-test-case` SKILL.md 撰写：M3b 落地（M0 只建空目录）。
- `/cases/try` 实现：M3a 落地（M1 时先实现 runner 内核，M3a 把 "不入库" 选项接出来即可）。
- extension 首批用例选型：M4b 时确认（候选 pgvector / postgis / pgcrypto / pg_hint_plan / fuzzystrmatch）；选哪几个跟当前生产部署最常用的 extension 对齐。

### 13.3 未来新增测试门类的标准流程（v0.8 新增）

当业务出现第三类（甚至第 N 类）测试门类——例如 `performance_smoke`（升级后性能基线快查）、`upgrade_compatibility`（跨版本升级兼容性）、`cluster_recovery`（HA / standby 切换演练）——按以下 **5 步法**执行，**不需要改任何业务代码**：

| 步骤 | 动作 | 产物 |
|------|------|------|
| 1 | 写一份 mini design：本门类的语义、status 词汇语义、典型 case 样例 1~2 个 | PR 描述里写清楚 |
| 2 | 新增一条 Alembic seed migration `INSERT INTO case_categories (name, display_name, id_prefix, dir_path, status_whitelist, default_status, display_order, ...) VALUES (...)` | `backend/alembic/versions/NNNN_add_category_<name>.py` |
| 3 | `mkdir cases/<dir_path>/` 创建对应目录（即便空目录，提一个 `.gitkeep`） | `cases/<dir_path>/.gitkeep` |
| 4 | 如果新门类有**特化场景关键词**（如 performance_smoke 关键词 `tpch / tpcds / clickbench / latency_p99`），在 skill 的"场景注册表"加新组，参照 §5.5.5 现有 extension 组的写法 | `.claude/skills/add-test-case/SKILL.md` 加一节 |
| 5 | 跑一遍 e2e：(a) 启动 backend；(b) 看 `/cases` 看板出现新 tab；(c) skill 跑 `/add-test-case` 看首题选项已含新 category；(d) 用 skill 生成一个新门类的样例 case，走 Validate→Try→Save 走通 | smoke pass 截图附在 PR |

**关键约束**：
- 5 步里**没有一步是改 schema 校验代码、改前端组件、改 skill 主流程**。如果你发现非改不可，说明 §4.5 的元数据字段缺了什么——这种情况要回 design 加字段（而不是绕过元数据写 `if` 分支）。
- 不暴露 `case_categories` 的 admin UI（同 §4.5 末尾的理由），加门类必走 PR。

---

## 14. 风险预警与反模式（v0.5 新增）

本章记录"preflight 趟过的雷"，按风险等级排序。各条都包含**触发场景**、**正确做法**、**preflight 教训来源**。新人/未来的自己读这一章可以省下数周踩坑。

### 14.1 致命级（设计阶段就要规避）

**🔴 R1：配置分多个源头，第一次出 bug 必排查 3 小时**
- 触发：`vm_cpu` 同时存在于 YAML、前端硬编码、env var 三个地方，三者不同步。
- 正确做法：单一来源（Tier B 表）+ 前端通过 API 读 + codegen 类型同步。
- 来源：preflight pool 121 误分配事件（`docs/specs/2026-05-12-config-tiers-redesign.md`）。

**🔴 R2：可见性测试 vs 契约测试**
- 触发：E2E 只断言 "button 渲染 / form 存在"，提交 payload 体结构错了照样通过。
- 正确做法：表单提交必须用 Playwright `page.route()` + `route.request.postDataJSON()` 断言提交体 shape；后端 API 用 Pydantic 强 schema，**禁止** `extra='ignore'`。
- 来源：preflight `docs/specs/2026-05-12-ci-test-pyramid-redesign.md`，2026-05-10 一日 8 个生产 bug 反推。

**🔴 R3：直接 push main 即便是 doc typo**
- 触发：单人项目，"反正没人看，直接 push 快一点"。
- 正确做法：所有变更走 PR + green CI auto-merge。
- 来源：preflight 2026-05-18 CI 稳定化决议。

**🔴 R4：多 agent 并发不加 worktree isolation**
- 触发：foreman 一次派 2 个 fixer，都在主 worktree 上动文件。
- 正确做法：`isolation: "worktree"` + `.claude/scripts/check_agent_dispatch.sh` lint。
- 来源：preflight pipeline 136449 事故（`docs/ops/2026-05-18-daily-status.md` lesson #3）。

**🔴 R4b：把分类/枚举写死在多处代码里（v0.8 新增）**
- 触发：测试门类 `category` 枚举写在 Python schema、TS 类型、前端 tab 列表、skill 对齐题、目录扫描器各一份；加第三个门类时改 5 处漏 2 处。
- 正确做法：把"分类清单"做成 DB 表（§4.5 `case_categories`），所有消费方从 `GET /admin/categories` 拉；新增分类 = 写一条 seed migration，不改业务代码。前端 codegen 类型把 `category` 标为 `string` 而非枚举（枚举字面值本身就是新硬编码点）。
- 来源：preflight 早期 `applies_to.family` 硬编码 lightning / enterprise_4x，加 cloudberry 时改了 7 处（spec `2026-05-12-test-suite-mgmt-redesign.md`）。本项目用 DB 表治理避免重蹈。

### 14.2 严重级（落地阶段反复犯）

**🟠 R5：超时默认 60s 害死一切慢操作**
- 触发：DB 重启、批量导入、远程下载在 60s 内做不完，timeout 后看不出原因。
- 正确做法：分层默认（§5.3 表）；`restart_db` 默认 600s，慢 SQL 显式标 `timeout_sec`。
- 来源：preflight `restart_step.py:154-163` 注释——"60s default was sync-SSH-era".

**🟠 R6：CSS structure selector 用于 E2E**
- 触发：`.card + .pool-id-label` 这种依赖 DOM 结构的选择器，UI 加个 wrapper 就失效。
- 正确做法：所有 E2E 待选元素加 `data-testid` 属性；禁止 `.first()` 依赖渲染顺序。
- 来源：preflight `26958c1 + 67495b8`（2 个 e2e 修复 commit）。

**🟠 R7：前端 ErrorBoundary 缺位 → blank page**
- 触发：组件渲染时抛错，整个 router-view 子树变白。
- 正确做法：根组件强制包 `<ErrorBoundary>`，降级 UI 必显示"返回首页"。
- 来源：preflight 2026-05-10 CI 重设计前的常见故障模式。

**🟠 R8：`test.skip()` 写在测试 body 里**
- 触发：Playwright 已经分配了 browser context 才发现要跳过，超时退出。
- 正确做法：`test.skip("name", fn)` 在 declaration level skip。
- 来源：preflight `853810e | MR!160`。

**🟠 R9：一个 step 抛异常，整个 suite 后续 case 全部不跑（v0.9 新增）**
- 触发：cli step 里 paramiko PipeTimeout / socket.timeout / restart 后 db 连接 drop 等异常，runner 没包 try/except 就让异常冒到 suite 层。
- 正确做法：runner 所有 step 执行包 `try / except BLE001`，转 `StepResult(status="error")`，case 标 error 后**下一个 case 继续**（§5.3.3）。
- 来源：preflight runner.py:768-787，Run 32 forensic：coordinator_failover 一 step 卡住 → mirror_failover / security.tde / pg_search 后续全 case 静默不跑。

**🟠 R10：cli step 用 `cat > file` 覆盖写服务端配置（v0.9 新增）**
- 触发：YAML 用 `cat > $DD/gphdfs.conf <<'YML' ... YML` 写 hdfs 配置，把 deployer 写好的 `hdfs-cluster-1` 块**清空**，后续依赖 hdfs-cluster-1 的 hudi/iceberg case 全 fail "not found in gphdfs.conf"。
- 正确做法：用 `cat >> $DD/file <<'YML' ... YML` + `grep -q '^<key>:' "$DD/file" || cat >>` 守卫追加；skill 在 cross-check 时自动改写（§5.5.7 cross-check 11）。
- 来源：preflight 12_datalake_fdw_hive.yaml 第 60-72 行注释，Run 112 forensic。

**🟠 R11：远端 cli step 不显式 source profile.d（v0.9 新增）**
- 触发：`host: '{{ external.hive.host }}'` 的 cli step 跑 `beeline -u ...`，SSH 非交互登录默认不 source `/etc/profile.d/*`，HADOOP_HOME / HIVE_HOME / JAVA_HOME 缺失，beeline JVM 启动炸。
- 正确做法：远端 cli step `cmd:` 开头**必须**带 `[ -f /etc/profile.d/<x>.sh ] && . /etc/profile.d/<x>.sh || true`；skill 在 cross-check 时自动插入（§5.5.7 cross-check 10）。
- 来源：preflight 12_datalake_fdw_hive.yaml seed_hive_fixture step 第 83-84 行。

**🟠 R12：外部服务 fresh boot warmup 没 retry（v0.9 新增）**
- 触发：fresh pool 第一次跑 case 时 HiveServer2 thrift 端口已 listen 但 transport 没就绪，beeline "Socket is closed by peer" → case 假阳性 fail。
- 正确做法：外部 seed step 包 retry 循环（典型 6×10s back-off + 成功即 break）；skill 在检测到 fresh_pool / warmup 关键词时建议加（§5.5.5）。
- 来源：preflight 12_datalake_fdw_hive.yaml seed_hive_fixture 第 87-93 行，Run 97 forensic。

**🟠 R13：远端 cli step ssh user 误判 standby 是外部主机（v0.9 新增）**
- 触发：`host: '{{ external.standby.host }}'` 解析成 DUT 自己的 standby IP；runner 只判"host != ssh_host"就强制 user=root；standby 的 authorized_keys 只允许 gpadmin → ssh 静默失败，后续 gpactivatestandby 因 stale lock 拒激活。
- 正确做法：runner 维护 `dut_hosts: set[str]`（cluster_topology.hostnames 集合），**host 在 dut_hosts 内 → 用 gpadmin**；不在则用 root（§5.3.2）。
- 来源：preflight runner.py:165-190 注释，Run 47 forensic。

### 14.3 中危级（积累到一定规模会触发）

**🟡 R14：`ON CONFLICT DO NOTHING` 用于两阶段 ingest**
- 触发：discover 插 pending 行 → pull 想 UPDATE 但写成 `DO NOTHING`，pending 永远不变 READY。
- 正确做法：`ON CONFLICT DO UPDATE SET ... WHERE status='pending'`，明确写转换条件。
- 来源：preflight `docs/ops/2026-05-22-media-registry-promote-and-pull-shipped.md §7`。

**🟡 R15：用 `UPDATE` 强制把卡住的 job 拉到 done**
- 触发：job 卡 5 小时，反射写 `UPDATE jobs SET status='failed' WHERE id=X`。
- 正确做法：写 watchdog + 通过应用代码路径（`_fail()`、`reenqueue()`）转移状态，invariant 才能保住。卡住的行先留着做 forensic。
- 来源：preflight `docs/ops/2026-05-18-daily-status.md §4`。

**🟡 R16：LLM Review P0 误报静默放弃**
- 触发：reviewer agent 报 P0，fixer agent 看不懂直接放弃 push。
- 正确做法：分析每个 P0；判定误报后用 `LLM_REVIEW_SKIP=1` 标签转义 + 写明理由（§7）。
- 来源：preflight 2026-05-18 lesson #5。

**🟡 R17：Repeated bug 用 commit hash 回复 = 0 信任**
- 触发：同一 bug 被报第二次，回 "see commit abc123"。
- 正确做法：Playwright 跑一次实际复现，看到是真复现/已修复再回话。
- 来源：preflight CLAUDE.md CI Quality Bar 最后一条。

**🟡 R18：用例命名按章节号**
- 触发：`01_xxx / 02_yyy / 06_row2column` 这种命名，3 个月后没人记得哪个章节对应什么。
- 正确做法：本项目用 `lg-bug-NNNN-<语义描述>` 命名（已采用），避免章节号；目录按语义分类（如 `cases/optimizer/`、`cases/storage/`）。
- 来源：preflight `docs/specs/2026-05-12-test-suite-mgmt-redesign.md`。

### 14.4 轻量级（知道就行）

**🟢 R19：gitleaks 默认扫 git history，force-push 后旧 commit 还会被扫到** → 用 `gitleaks --no-git` 扫 working tree（preflight `28b6a5a`）。

**🟢 R20：xdist 下 worker_id 在 import time 取一定错** → 进 fixture 里取（preflight `docs/ops/2026-05-18-daily-status.md §bugs 4`）。

**🟢 R21：pytest 并行测试用 testcontainers 会 race 出 schema 错误** → 提供 `PYTEST_PARALLEL=""` 关闭并行的逃生口。

### 14.5 不抄的 preflight 设计

不是所有 preflight 决策都适合本项目。明确**不抄**的：

| preflight 做法 | 本项目决议 | 理由 |
|----------------|-----------|------|
| MinIO 对象存储 | 不用，artifacts 落本地 FS | 单用户 / 单机 / 小数据量，PG/SQLite 装不下时再上 |
| Patroni 3-node HA | 不做 | 单用户工具，单点崩溃可接受 |
| RQ/procrastinate 异步队列 | 不做（首版） | UI 触发 + 串行运行，不需要队列 |
| 心跳 / orphan reclaim 工作器机制 | 不做（首版） | 既然不引入异步 long-running job，就没有"卡住的 job"需要 reclaim |
| 双语 EN/ZH 报告 + WeasyPrint PDF | 不做 | 内部使用，UI 中文即可 |
| ZStack VM Pool Manager / golden snapshot | 不做 | **集群与外部依赖由你手动准备**，本项目不管 provisioning |
| Deployer（gpinitsystem / install.sh / Ansible） | 不做 | 同上，部署/拆除集群不在职责内 |
| 资源池健康探测 + 自动重建 | 不做 | 同上 |
| LLM Review Board（独立 CI 阶段） | 简化为本机 `reviewer` agent | 没必要再加云端审查 |
| `applies_to.family`（多产品） | 简化为 `applies_to.versions` | 本项目只测 lightning，无 enterprise/cloudberry 多产品分支 |

---

## 15. 自动协作运转模型（v1.0 新增；核心闭环）

本章解决一个问题：**foreman 一启动，人就不用管了——开发自循环、PR 自动合并、12:00 和 20:00 自动汇报，需要人决策的事情统一在报告里列出。**

借鉴 preflight `.claude/agents/foreman.md`（已生产验证 5 周），本项目落地为 3 个机制：**foreman verify loop** + **GitHub auto-merge 集成** + **cron 定时汇报**。

### 15.1 foreman verify loop（人类启动一次后自循环）

`foreman` 是 opus 模型的本机 subagent，由你在终端 `claude` 会话里一次性启动：

```
$ cd lightning-bug-regression
$ claude
> /foreman M1                # 给 foreman 一个 milestone 标签或自定义清单
```

#### 15.1.1 foreman 的"loop"算法（与 preflight 同款 + 适配本项目）

```
1. 读状态：git log --oneline -10；git status；docs/status/foreman-state.json；gh pr list --json number,state,title。
2. 选目标：从 sprint 清单里挑当前最高优先级未完成项。
   - 优先级：P0 hard invariant > 阻塞下游的项 > 可独立完成的项 > 体验打磨。
3. 派活：用 Agent tool dispatch 一个 specialist（backend-fixer / frontend-fixer / doc-writer / reviewer / smoke-runner）。
   - prompt 模板（来自 preflight foreman.md §"Dispatch prompt template"）：
     Context: <1-2 句背景>
     Task: <精确要做什么>
     Success criteria: <怎么算成功>
     Out of scope: <不要碰什么>
     Report: <返回什么>
   - **必须**带 isolation: "worktree"（§8.5 lint 强制）。
   - 长任务（smoke-runner 跑 e2e）用 run_in_background: true 不阻塞主 loop。
4. 收回结果，evaluate honestly：
   - "backend-fixer 说 pytest 通过" ≠ 证据。reviewer 实跑 pytest = 证据。
   - smoke-runner 给"GO" = 证据；"看起来 OK" ≠ 证据。
   - 任何歧义当未完成。
5. 决定下一步：
   - 通过 → 标该项 done；写 state.json；回 step 1。
   - 失败，且原因明确 → 派**修复**的 specialist（不是再派同一个），具体修法写进 prompt。
   - **同症状连续 fail 2 次** → STOP + escalate（写 needs_human 项进 state.json，下次 reporter 触发时上报）。
   - 失败原因是"集群未就绪 / 凭据缺 / 飞书原文缺" → STOP + escalate（不重试，等你修环境）。
6. Stop 条件：
   - 清单空 → DONE；写 final report；session 退出。
   - 触发 escalate → BLOCKED-ESCALATE；写 state.json + handoff doc；session 退出。
   - budget 用尽（10 round 或壁钟 2h，取先到者） → BUDGET-EXHAUSTED；写 partial progress；session 退出。
7. 任何 stop 都必须写 state.json + handoff doc，然后退出 session。reporter 会从 state.json 拼下次汇报。
```

#### 15.1.2 foreman 硬规则

| # | 规则 | 来源 |
|---|------|------|
| 1 | **Never edit code, never run smoke**——foreman 只 dispatch | preflight foreman.md §"You do not implement, test, or document anything yourself" |
| 2 | **Never claim success without evidence**——必须看到 reviewer / smoke / pytest 实际跑过的输出 | preflight foreman.md §"Hard rules" |
| 3 | **Never commit**——commit 由 specialist 在自己 worktree 里完成 | preflight foreman.md §"Hard rules" |
| 4 | **同症状 fail 2 次立即停**——不要第 3 次（preflight 是 2 次即停，用户决策一致） | preflight foreman.md §"Never run the same failing dispatch twice" |
| 5 | **8+ min 任务用 run_in_background**——不在前台阻塞 | preflight foreman.md §"Time-consuming calls go to background" |
| 6 | **状态每 round 落地**——写 `docs/status/foreman-state.json`，reporter 离线可读 | 本项目新增 |
| 7 | **budget = 10 round 或 2h**——用户 v1.0 决策 | 本项目新增（preflight 是 10 round） |

#### 15.1.3 foreman 状态文件 `docs/status/foreman-state.json`

每 round 结束必写，schema：

```json
{
  "session_id": "uuid-of-this-foreman-session",
  "started_at": "2026-05-23T14:30:00+08:00",
  "last_heartbeat": "2026-05-23T15:42:00+08:00",
  "sprint_label": "M1",
  "round": 6,
  "round_budget": 10,
  "wall_budget_hours": 2,
  "status": "running | done | blocked-escalate | budget-exhausted",
  "items_done": [
    {"name": "M1-3 sql_driver 基础实现", "evidence": "PR #12 merged at 2026-05-23T15:10", "merged_at": "..."},
    ...
  ],
  "item_in_progress": {
    "name": "M1-4 shell_driver",
    "specialist": "backend-fixer",
    "started_at": "...",
    "pr_url": "https://github.com/.../pull/13",
    "pr_state": "open | merged | failed"
  },
  "items_remaining": ["M1-5 log_grep_driver", "M1-6 expect schema 校验", ...],
  "needs_human": [
    {
      "kind": "design_decision | env_setup | credential | external_data",
      "summary": "case 9.5 在 mydb 上跑 upper，需要确认 mydb 的 locale 设置",
      "blocking_item": "M4a-5 lc-ctype-upper case 落地",
      "first_seen_at": "...",
      "attempt_count": 2
    }
  ],
  "last_failures": [
    {"item": "...", "specialist": "...", "symptom_hash": "<sha>", "count": 2}
  ]
}
```

`symptom_hash` = `sha256(specialist + error_pattern)`；连续 2 次相同 hash → escalate。

### 15.2 GitHub auto-merge 集成

#### 15.2.1 specialist 提 PR 的标准动作

每个 fixer / doc-writer agent 完成代码后**必须**做 5 件事，缺一不可：

```bash
# 1. 在 worktree 里 commit（**不**加 Co-Authored-By Claude，参考全局规范）
git add <changed>
git commit -m "<conventional commit message>"

# 2. push 分支（worktree branch = feat/<id>-<slug> 或 fix/<id>-<slug>）
git push -u origin HEAD

# 3. 开 PR
gh pr create --title "..." --body "$(cat <<'EOF'
## Summary
...

## Test plan
- [ ] pytest passed locally
- [ ] tsc --noEmit passed
- [ ] ruff check passed

## Foreman context
sprint=M1, round=6, item=M1-4 shell_driver
EOF
)"

# 4. 给 PR 设 auto-merge（CI 全绿后 GitHub 自动 squash merge）
gh pr merge --auto --squash

# 5. 返回给 foreman 一个 JSON：
#    {"pr_number": 13, "pr_url": "...", "branch": "feat/...", "status": "open-auto-merge-armed"}
```

**关键**：第 4 步设了 auto-merge 后 specialist **立即返回**，不要等 CI。CI 跑 ~5-25 min，等的话拖住 foreman loop。foreman 在下一 round 才轮询 PR 状态。

#### 15.2.2 foreman 轮询 PR 状态

foreman 每 round 结束前跑：

```bash
gh pr list --search "is:open is:pr" --json number,title,statusCheckRollup,mergeable,state
# 找 state == "MERGED" 的，把对应 item 标 done。
# 找 statusCheckRollup 含 "FAILURE" 的 PR，dispatch 修复 specialist。
```

#### 15.2.3 GitHub 仓库一次性配置（§7.1 已经写了，这里强调与 foreman 配套）

```
Settings → General → Pull Requests:
  ✅ Allow auto-merge
  ✅ Allow squash merging（disable merge commit + rebase merge）
  ✅ Automatically delete head branches
Settings → Branches:
  ❌ 不对 main 加任何保护规则（不要求 review / status check 强制等）
Settings → Actions → General:
  ✅ Read and write permissions
  ✅ Allow GitHub Actions to create and approve pull requests
```

**为什么不要求 CI 强制 status check 才合并**：v0.5 §7.2 / v0.5 R3 已说"all test jobs are gates"，CI 红就不会绿，auto-merge 不会触发——逻辑上等价于强制。强制 status check 会让"auto-merge 卡住等某个不存在的 check 名字"，反而成 footgun。

### 15.3 cron 定时汇报（12:00 / 20:00，v1.3 内调整）

#### 15.3.1 cron 注册（M0 末一次性 setup；v1.3 改 OS crontab）

**v1.3 关键改动**：v1.0~v1.2 用 Claude Code 内置 `CronCreate`，实测发现是 session-only + 必须 REPL idle 才 fire——foreman 持续 mid-query 时永远 fire 不了，**不适用**。改用 **OS-level crontab**，与 Claude session 完全解耦。**v1.3 内 step 8 实测又细化一层**（2026-05-23）：cron 的 minimal env 缺 proxy / GH_TOKEN，且 `claude --print` 在 root 下不能用 `--dangerously-skip-permissions`——所以 cron entry 不直接调 claude，而是调 wrapper `scripts/cron-report-status.sh`，由 wrapper 把所有 env 与 permission flag 补齐。

```bash
# root crontab -e（或用 scripts/install-cron.sh --apply 一键写入；idempotent），
# 两条 entry 直接调 wrapper：
0 12 * * * /data0/chenqiang/project009/lightning-bug-regression/scripts/cron-report-status.sh >> /data0/chenqiang/project009/lightning-bug-regression/docs/status/cron.log 2>&1
0 20 * * * /data0/chenqiang/project009/lightning-bug-regression/scripts/cron-report-status.sh >> /data0/chenqiang/project009/lightning-bug-regression/docs/status/cron.log 2>&1

# 验证：
crontab -l                                    # 看到两行
scripts/install-cron.sh --check               # 两个 ✓
# 等到下个 12:00 / 20:00 后查 docs/status/ 有新 md + docs/status/cron.log 有调用日志
```

**`cron-report-status.sh` wrapper 做的三件 cron-context-only 事**：

1. `. /root/.bashrc` 拉 proxy exports（`http_proxy` / `https_proxy` / `NO_PROXY`）。**理由**：本机走公司代理 `http://10.13.11.1:1080`；裸 cron env 不带这些 → Anthropic API 返回 `403 Request not allowed`。`.bashrc` 没 non-interactive 守卫，cron 可直接 source。
2. 从 `~/.git-credentials` inline 提取 `GH_TOKEN` 并 export（per `feedback-gh-token-auto` 记忆）。**理由**：skill 第 4 步要跑 `gh pr list / gh auth status`，cron env 不带 token → `gh auth status` 失败 → 触发 SYSTEM_ALERT #3，`gh pr list` 返空，§3 永远渲不出实数据。
3. 用 `claude --print --permission-mode auto "/report-status"`。**理由**：claude `--print` 是 non-interactive，没人能批 tool prompt；`--dangerously-skip-permissions` 在 root 下被拒（"cannot be used with root/sudo privileges"），`--permission-mode bypassPermissions` 同样被拒，`acceptEdits` 与 `dontAsk` 都挡 `gh pr list`——**只有 `auto` mode 同时放行 Bash 通用 + git ops + gh ops + Write to docs/status/**。

**每次 fire 的执行模型**（OS crontab + wrapper + `claude --print`）：
1. OS cron 在 12:00 / 20:00 启动 `cron-report-status.sh`——独立于任何在跑的 foreman session
2. wrapper source bashrc + export GH_TOKEN → `exec claude --print --permission-mode auto "/report-status"`
3. `claude --print` 走 non-interactive 模式：执行 skill → 输出 stdout
4. stdout 重定向到 `docs/status/cron.log`（保存原始执行记录 + wrapper 的时间戳 banner）
5. reporter agent 内部跑 §15.3.2 工作流，**写**真正的 `docs/status/<ts>.md`（不是 stdout）+ commit + push
6. claude 进程退出，cron 任务结束

**对比 v1.2 假设**（CronCreate）vs v1.3 落地（OS crontab + wrapper）：

| 维度 | v1.2 CronCreate（错） | v1.3 OS crontab + wrapper（对） |
|------|----------------------|--------------------------------|
| 触发是否依赖 foreman session | ❌ 是（同 session + REPL idle） | ✅ 独立 OS 进程 |
| session 退出后是否还能 fire | ❌ 不能（session-only） | ✅ 能 |
| 工具调用 | `CronCreate({...})` | `crontab -e` 或 `install-cron.sh --apply` |
| 实测验证 | session 内 mid-query 永不 fire | wrapper 实测两轮 smoke 通过，commit `7d97986` / `31f8653` |

#### 15.3.2 reporter agent 工作内容（v1.2 简化为 6 步，无推送）

```
1. 读 docs/status/foreman-state.json（如不存在 = "foreman 未启动 / session 已退出"，明确写进报告）
2. 跑 git log --since="<上次报告时间>" --oneline  → 12h 内的 commit
3. 跑 gh pr list --search "merged:>=<上次时间>"   → 12h 内合并的 PR
4. 跑 gh pr list --state open                    → 当前开着的 PR + CI 状态
5. 读 foreman-state.json.needs_human[]            → 待你决策的事项
6. 生成 `docs/status/YYYY-MM-DD-HHMM.md`（格式 §15.3.4），commit + push 到 main（doc-only 提交，无 PR）
7. 退出
```

reporter 不改代码，不调度 specialist，不处理决策，**不发外部消息**——它**只是把状态写进目录**，你 12:00 / 20:00 之后自己来看。

#### 15.3.3 `/report-status` skill

文件：`.claude/skills/report-status/SKILL.md`（M0 末落地，与 cron 同期）。骨架（详细内容 M0 第 3 步细化）：

```yaml
---
name: report-status
description: Generate a 12-hour rollup report from foreman-state.json + git log + gh pr list. Cron-fired; writes docs/status/<date-time>.md. Read-only outside docs/status/.
---

# 工作流（reporter agent 跑）

1. 时间窗口：上次报告时间（找 docs/status/ 最新一份的 frontmatter `to:`）→ 现在。
2. 读 foreman-state.json + 跑 git/gh 命令收集。
3. 按 §15.3.4 格式渲染 markdown。
4. 写 docs/status/<YYYY-MM-DD-HHMM>.md；commit + push（doc-only，无 PR）。
5. 退出（**不调任何外部消息推送**，v1.2）。
```

#### 15.3.4 报告格式（固定 schema，确保你扫一眼就能看完）

```markdown
---
generated_at: 2026-05-24T12:00:00+08:00
from: 2026-05-23T20:00:00+08:00
to: 2026-05-24T12:00:00+08:00
foreman_status: running | done | blocked-escalate | budget-exhausted | not-running
sprint: M1
---

# 进度报告 2026-05-24 12:00

## 1. tl;dr（一句话）
M1 进度 6/12 项；foreman 当前 running（round 6/10）；**1 项需你决策**（见 §4）。

## 2. 本周期完成（12h 内 merged 的 PR）
- ✅ M1-3 sql_driver 基础实现 — PR #12 (merged 03:15)
- ✅ M1-4 shell_driver — PR #13 (merged 08:42)
- ✅ M1-5 log_grep_driver — PR #14 (merged 10:55)

## 3. 进行中（open PR）
- 🔄 M1-6 expect schema 校验 — PR #15 (open, CI 跑了 12 min) — auto-merge armed
- 🔄 M1-7 sessions 多会话 — PR #16 (open, CI failed: pytest backend/tests/runner/test_sessions.py) — foreman 已 dispatch backend-fixer 再修

## 4. **需你决策**（⚠️ 不处理则 foreman 卡住）
- **[design_decision]** 飞书 9.4 ctas_rowcount_zero 的预期断言写 `>=1` 还是 `==1`？
  - 触发 case: M4a-4 ctas-rowcount-zero
  - foreman 已尝试 2 次 → 因不确定语义 escalate
  - **你回复一句话 / 在 GitHub Discussion #xxx 留言即可**

## 5. 阻塞项（agent 自己解不了的）
- 暂无

## 6. foreman session 状态
- session_id: a3b4c5d6
- 启动: 2026-05-24 08:00
- round: 6 / 10
- 壁钟: 4h（已超 budget，session 应该已退出 → 下条警告）
- ⚠️ foreman 报告时还在 running 但已超 2h budget — 检查是否 hang（可能 ScheduleWakeup 死锁）

## 7. 下周期计划（foreman 拟做）
1. 处理 M1-7 失败 → 修 → 重提 PR
2. M1-8 destructive 排序
3. 你回复 §4 决策后继续 M4a-4

## 8. 链接
- foreman state: docs/status/foreman-state.json
- 上一次报告: docs/status/2026-05-24-0000.md
- 本周期 git log: <inline 5 行>
```

#### 15.3.5 "所有事件都进下次报告"原则（v1.2 改）

**无即时推送通道**——飞书 chat 未打通，所有事件统一走"写 `docs/status/<ts>.md`，等你下次主动来查目录"。

| 触发 | 行为 |
|------|------|
| foreman 一切顺利 | 等下次定时报告 |
| foreman BLOCKED-ESCALATE（待你决策） | 写进 state.json；下次定时报告 §4 高亮 |
| foreman BUDGET-EXHAUSTED | 写进 state.json；下次定时报告 §6 写明 |
| reporter 自己跑挂 | cron 会自动捕获失败；你最迟下个 12h 来目录看，会发现"上一次报告时间戳异常 / 缺失" |
| 严重事件：仓库被破坏 / 仓库不可用 | reporter 检测到 `git fetch` fail → 仍生成 `docs/status/<ts>.md`，**报告顶部加 `🚨 SYSTEM_ALERT: <一句话症状>` 红字行**，让你扫一眼能立刻区分"普通进度" vs "系统级故障" |

理由：用户决策回复 12h ≤ 一次大致够；本机工具、单用户开发场景，没必要做即时推送。你养成"早上 / 睡前各扫一眼 `docs/status/` 目录"的习惯即可。

### 15.4 失控防护汇总表

| 失控模式 | 防护机制 | 在哪里 |
|----------|----------|--------|
| foreman 跑飞死循环 | budget = 10 round 或 2h，硬退出 | §15.1.1 step 6 |
| 同症状反复 fail | 2 次相同 symptom_hash 立即停 + escalate | §15.1.1 step 5 |
| specialist 在 PR 等 CI 阻塞 | specialist 设 auto-merge 后立刻退出，foreman 下 round 才轮询 | §15.2.1 + §15.2.2 |
| agent 偷偷改了你不知道的文件 | 所有改动走 PR；reporter 12h 汇报 git log + merged PR | §15.3.4 §2 |
| foreman 不响应 / hang | reporter 检查 `last_heartbeat` 距今 > 30min → 报告里 §6 高亮 | §15.3.4 §6 |
| 多 agent 互踩文件 | `isolation: "worktree"` + `.claude/scripts/check_agent_dispatch.sh` lint | §8.5 |
| 静默放弃 LLM Review P0 | `LLM_REVIEW_SKIP=1` 转义机制 + escalate 到 state.json | §7.2 + §15.1.1 |
| 仓库被破坏 / 推不上 main | reporter `git fetch` fail → `docs/status/<ts>.md` 顶部 `🚨 SYSTEM_ALERT:` 红字行（v1.2 去飞书） | §15.3.5 |
| cron 没注册成功 | M0 step 8 `crontab -l` 验证两条 entry 都在；reporter 第一次跑时检查上一份报告时间间距是否合理 | §15.3.1 |

### 15.5 落地步骤（M0 第 7~8 步新增）

7. **写 8 个 agent 定义**到 `.claude/agents/`：pm-designer / foreman / backend-fixer / frontend-fixer / doc-writer / reviewer / smoke-runner / reporter。各 ~40-80 行 markdown，frontmatter + 工作规则 + dispatch 模板。foreman / reporter 严格按 §15.1 / §15.3 写。
8. **注册 OS crontab**（v1.3 改）：用户在 M0 收尾时 `crontab -e` 加两条 entry（§15.3.1）；`crontab -l` 验证生效；**这是 M0 完成的最后一个动作**。
9. **第一次启动 foreman**：你跑 `/foreman M1`，给 sprint 标签；foreman 接管 M1 全部子任务；12:00 / 20:00 你看报告。

### 15.6 与 §8 流程的关系

§8 是"多 agent 协作的逻辑流程"（谁干啥 / review 怎么做）。§15 是"这套协作如何无人值守地自循环"（运转机制 / 兜底 / 汇报）。**§15 是 §8 的运行时实现**，不是替代关系。

如果 §8 描述了"派活 → 改 → review → smoke"的方向流，§15 就是给这个方向流加了：
- 一个永动机（foreman）
- 一个传送带（GitHub auto-merge）
- 一个仪表盘（reporter + 12:00/20:00 cron）
- 一组保险丝（§15.4 防护表）
