# post_upgrade_test — 设计文档

> 当前版本: **v1.25**　状态: **M0 ~ M7 全部交付 + post-M6 UX 迭代 wave 1+2 + 简易用户登录模块 (v1.17) + Release 流程 canonical 文档 + bootstrap.sh (v1.18) + target_versions registry (v1.19) + run.errored / error verdict / 进度条 / case 隔离 / 时区 root fix / admin Bearer 迁移 / observability / hadoop_simple external (v1.20) + external_systems status 双轴 (v1.21) + review 流水线补齐并端到端跑通 (v1.22~v1.24) + M7 LLM 草稿生成交付 (v1.25)**（详 §0 历史表 + §13.17）。

---

## 目录

> 读 design 的推荐顺序：先 §0 看本轮关键决策 → 想干啥按下面定位。1800+ 行别从头啃；按章节跳。

| § | 标题 | 一句话 |
|---|------|--------|
| **0** | 版本历史 | v0.1~v1.3 + v1.3 内追加 (a)~(i2)；每行一个关键决策 |
| **1** | 背景与目标 | Lightning 升级回归测试 + 周边 extension 集成测试两类用例 |
| **2** | 范围 | In/Out scope（v0.6 把 Claude Code Skill 移到 In） |
| **3** | 总体架构 | §3.1 集群访问约定（mdw=synxdb-0001 / gpadmin / cluster_topology） |
| **4** | 数据模型 | §4.1 YAML schema · §4.2 runs+case_results · §4.3 case_skip_list · §4.4 system_settings · §4.5 case_categories（v0.8 元数据表） |
| **5** | 后端设计 | §5.1 目录 · §5.2 API 表 · §5.3 runner（sql/shell/log_grep + jinja + ssh user + 异常处理）· §5.4 LLM · §5.5 add-test-case Skill |
| **6** | 前端设计 | /cases 按 category 分 tab · Validate→Try→Save 三段闸门 · §6.4 R7 ErrorBoundary 强制 |
| **7** | 用例存储与 PR 流程 | §7.1 仓库 settings 表（含 v1.3 (h)(i) auto-merge gate）· §7.2 PR 流程 |
| **8** | 多 Agent 协作 | §8.1 8 个 agent 模型表 · §8.3 6 域审查 · §8.5 worktree isolation lint |
| **9** | 项目结构 | 一级目录（backend/ frontend/ cases/ docs/ scripts/ .claude/{agents,skills,scripts}/） |
| **10** | 部署与运维 | §10.1 SQLite 选型 · §10.2 三层配置（Tier A 引导 / B 运行时 / C 内容） |
| **11** | 开放问题 | Q1~Q32（含 Q10 单账号 / Q12 Wiki / Q26 SQLite / Q27 门类扩展 / Q32 cron） |
| **12** | Roadmap | M0 骨架 / M1 后端 MVP / M2 前端 / M3a-b 录入 / M4a-b 用例填充 / M5 打磨 |
| **13** | 下一步行动 | §13.0 启动前自检（4 项 A/B/D/E）· §13.1 M0 计划 9 步 · §13.2 不阻塞项 · §13.3 未来扩门类 5 步法 |
| **14** | 风险预警与反模式 | §14.1 致命 R1~R4b · §14.2 严重 R5~R13/R22/R23 · §14.3 中危 R14~R18 · §14.4 轻量 R19~R21 · §14.5 不抄的 preflight 设计 |
| **15** | 自动协作运转模型 | §15.1 foreman verify loop（10 round/2h budget）· §15.2 GitHub auto-merge（含 §15.2.4 v1.3 gating 修正）· §15.3 cron 12:00/20:00 wrapper · §15.4 失控防护汇总 |

**快速跳转的高频锚**：

- 给 reviewer / 自查代码 → §14（R1~R23 反模式字典）+ §8.3（6 域审查）
- 想加新测试用例 → §4.1（YAML schema）+ §5.5（add-test-case skill 流程）
- foreman / specialist 看怎么干活 → §8.1（agent 表）+ §15.1（foreman loop）+ §15.2（auto-merge 流程）
- 想加新测试门类（如 `performance_smoke`）→ §13.3（5 步法，**不改业务代码**）
- 出问题排查 → §15.4（失控防护汇总）+ §14（R 编号对照）

---

## 0. 版本历史

| 版本 | 日期 | 作者 | 变更摘要 |
|------|------|------|----------|
| v1.25 | 2026-05-28 | Claude (M7 plan amendment) | **M7 LLM 接入计划开工前最终化** —— §13.13 末尾新增 v1.25 amendment 段，原 2026-05-24 计划保留以见演化。核心决策：**D1=`claude-opus-4-7`**（推翻 §5.4 早期 sonnet 默认，与 skill 路径永久钉 opus 对齐，feedback_model_override_2026-05-24） / D2=hardcode 3 few-shot in `llm_prompt.py` / D3=`ANTHROPIC_API_KEY` env var only / **H=α foreman 串行派发 2 PR（m7-backend → m7-frontend）**（user 决策 2026-05-28：原 β 改 α，目的=补一次自动化流水线真实功能 sprint 端到端验证；接受 R30 风险已在 m6d3t2 #193 验证 reviewer 能兜）。必补项 A-G 全采纳：(A) endpoint 要求 Bearer auth，**不**沿用 `/cases/*` 当前匿名姿态（核实 2026-05-28：那三个 endpoint 当前无 Depends/auth）；(B) `description ≤ 8KB` + `max_tokens=2000`；(C) **retry 语义分两类**——schema-invalid 重试 ≤2 次塞回错误，Anthropic API 错（429/5xx/超时）**不重试**按错误码上抛；(D) M7-4 必 assert 重试时 prompt 真包含上次 validation error 串（CLAUDE.md §2 wiring）；(E) system prompt 显式注入两条 = 默认 `database: gpadmin`（2026-05-24 新规范）+ §4.1.2 psql -c 铁律；(F) 每次调用 `logger.info` 落 `tokens/latency/retry_count`，不持久化；(G) prompt caching = schema+few-shot 共同前缀打 `cache_control:ephemeral`，user description 不缓存，定位"省点是点"非承诺。**错误码细分**：503(key 缺) / 502(Anthropic 5xx) / 429 透传 / 504(超时) / 413(description 超长) / 401(no Bearer)；2 次 schema retry 失败返 200 + body attempts=3。M7-1 隐含一步：`anthropic` 加进 `backend/pyproject.toml`（当前未装）。原"M7 dispatch 提示"段（foreman 派 specialist）**作废**。同步落 `docs/plans/M7.md` 作 user 个人 checklist。**M7 已交付 PR #195（backend `POST /cases/generate-draft`）/ #196（frontend 接线）/ #198（key 缺失禁用）。** |
| v1.24 | 2026-05-28 | Claude (foreman 运维 / 流程验证) | **review-pipeline v3 首次在真实「多 PR 功能 sprint」上端到端跑通**（此前仅 throwaway 单 PR 探针 #180/#181 + 单文档 sprint #183/#185 验过，从未验过连续多 item 自动链）。用 `scripts/dispatch-foreman.sh` 起 foreman 串行跑 `m6-run-experience-deepening`，6 item / 6 PR（#189~#194）全程走自动流水线：specialist 开 un-armed PR → foreman 派 reviewer 作 merge 前置闸门 → APPROVE 后 foreman 武装 auto-merge → ci-gate → **merge 后前台同步派 smoke（v1.23 修法逐 item 实跑生效）→ 同轮消费 GO** → 下一 item。wrapper 对账：`foreman_exit_code=0` / `foreman_returned_final_json=True` / **`r25_violation=False`** / 6 PR 全 verified-from-gh / main `6a47da1`→`19ce4ea` / 9 of 10 rounds / ~1h49m。**验证到的流程性事实**：(1) **reviewer 是真闸门不是橡皮章**——3 次 REQUEST_CHANGES 各抓真问题：errorCache stale-on-retry 双渲染、改页面踩坏既有 e2e 契约 testid（ci-gate e2e 拦下→fix 恢复→转绿才合）、**§14 R30 stale-branch**（backend 分支早于上一 PR 合入时切出、夹带已合并 commits）→ `rebase --onto origin/main` 恢复纯净 diff。(2) **串行 worktree 不天然免冲突**：foreman 一次派一个、合一个再派下一个，但若 specialist 分支创建时间早于上一 PR 合入 main，仍会夹带已合并 commits（#193 实证），靠 reviewer R30 兜住——新教训，记账。(3) **post-merge smoke 逐 item 全 GO**（v1.23 前台同步派发修法在真 foreman 进程里 6 次连续生效，无一 r25_violation，补强 v1.23 仅单 sprint 验过的样本）。**附带调查（结论：不改 CI）**：reviewer verdict 常报 `Playwright e2e: SKIPPED (libgbm not available)`——实测是 **el9 假阳性**（`/lib64/libgbm.so.1` 在、cached chrome-headless-shell 实跑 exit=0），根因 Playwright dep-checker 是 Debian 中心、在 RHEL 系按 `libgbm1` 包名误报；但 **e2e 全 `page.route()` mock 后端**（spec 头明写 "no real backend needed"），故 reviewer 本地跳 e2e 无覆盖损失，"纯后端 PR 漏 e2e"也是误判（mock 不反映后端契约）。真实覆盖结构无真空（前端行为=e2e mock / 后端契约=pytest / 类型契约=gen:types+tsc / 真集成=post-merge smoke）→ **决策不动 `ci-gate.yml`**（残留「mock 漂移」隐患记于 `docs/plans/review-pipeline-completion.md` 待方案 B：真集成 e2e）。 |
| v1.23 | 2026-05-28 | Claude (foreman wiring fix) | **修 v1.22 遗留的 smoke 终态门编排 bug。** 实测 `smoke-pipeline-test` sprint:流水线前半截全走通(doc-writer 开 PR #183 不武装→停 open→reviewer APPROVE→foreman 武装→squash-merge `e41e88a`→CI SUCCESS),但 **step 6.a 派 smoke-runner 用了 `run_in_background: true`,foreman 随即退出(exit 0, 397s),smoke 的 GO/NO-GO 从没回来,final JSON 也丢了(`r25_violation=true`)**。**根因**:foreman 由 `scripts/dispatch-foreman.sh` 以 `claude --print`(一次性非交互)启动——没有 event loop 去 await 后台子 agent;而 smoke 是 foreman 的**终态门**(verdict 必须在同一轮被消费才能 emit final JSON),终态背景化 = orphan 子 agent + 丢 final JSON。**修法(用户决策:前台同步)**:step 6.a 改**前台同步**派 smoke-runner(阻塞等 GO/NO-GO,实测 known-good case <1min,脚本内部 budget ~6min 封顶),`run_in_background` 仅留给"有并行活、之后再回收"的长任务。**改动**:foreman.md hard rule 5 + step 3 + step 6.a 三处 + design.md §8.1/§8.2/§15.1 loop/§15.1 rule-5 表四处。**人工补跑 `scripts/smoke.sh` 对 `e41e88a` 拿基线 = GO**(passed=2 failed=0 errored=0,真集群链路通),证明工具链健康、卡点纯在编排。lint(`check_agent_dispatch.sh`)不涉 background,无矛盾。 |
| v1.22 | 2026-05-28 | pm-designer (Claude) | **review 流水线补齐:reviewer 焊进 foreman 作 merge 前置闸门 + smoke-runner 落地 + 重启 foreman 作日常方式。** 起因:实测发现 reviewer 全仓只跑过 1 次(PR #94)、smoke-runner 从没落地(smoke.sh 不存在)。**两个根因**:(A) foreman 不启动(M5 后转 user-driven);(B) **foreman.md loop 算法本身没有"派 reviewer""派 smoke"步骤**——光重启 foreman 也不会派。**方案(用户三步收敛)**:① reviewer 内部本想"§14 + 内置 /review"两段式,但**实测撞死结**——subagent 能 invoke 内置 /review 但 /review 自身要派 finder 子 agent 而 subagent 不能嵌套派(能启动跑不完);② 故改为:**自研 reviewer 保留全功能(§14+6域)作前置闸门,内置 /review 由用户手动调不进流水线**;③ smoke 回 foreman 派,merge 后跑,**NO-GO 自动开 revert PR**。**改动**:foreman.md loop 补 step 3.5(PR 后派 reviewer,APPROVE 后**foreman**武装 auto-merge)+ step 6.a(merge 后派 smoke,NO-GO→`git show --stat`核对清单后 revert PR)+ state schema(reviewer_verdict/smoke_verdict)+ hard rule 12;**3 个 specialist(backend/frontend/doc-fixer)删自武装步**(改 `open-awaiting-review`,reviewer 当前置闸门的前提——否则 CI 一绿就合 reviewer 来不及);reviewer.md 加流水线定位 + §14 限代码文件;新 `scripts/smoke.sh`(自包含:临时端口+临时 DB 零污染,登录 admin/admin,跑 lg-bug-0001/0002 known-good 试纸验工具链,自起自停)。**throwaway PR #180+#181 端到端实测全走通**(开 PR 不武装→停 open→APPROVE→事后武装→合→smoke NO-GO→revert PR→合)。**实测抓到 3 个"实测>grep"**:§14 A 类 grep 假阳性(限代码文件)/ squash revert 误伤(revert 前核对清单)/ POST /runs 实测 401 要 auth(grep 漏了 CurrentUser 别名)。设计稿 docs/plans/review-pipeline-completion.md(v3 + §5.5 实测 + §7 reviewer 增强 backlog E1-E8 含边界原则:reviewer 快闸门只放轻量,重活归 smoke/ci-gate)。 |
| v1.21 | 2026-05-26 | pm-designer (Claude) | **external_systems status_whitelist 双轴改造**：v1.10 设计时 status_whitelist 只覆盖"环境就绪度" (stable / awaiting_env / deprecated / stub)，与项目主目的"BUG 回归测试"语义不符——external_systems 与 extension 拆分是因依赖外部服务进程，但 case 本质仍是 BUG 复现（PXF / Hive / FDW / zombodb 触发的 PG/Greenplum BUG）。新 status_whitelist `[open, fixed, wontfix, stub, awaiting_env]`，default `open`：主轴 = BUG 修复状态（与 bug_regression 对齐），辅助 awaiting_env 表达外部服务未部署占位。alembic 0006 UPDATE category row + 同 PR 把 3 个旧 case YAML 的 `status: stable` 改为对应的 `fixed` / `open` / `fixed`（loader 严格 not-in-whitelist 检查，PR 必须 atomic squash）。lg-xs-pxf-hdfs-order-by-writable = fixed（BUG 已修），lg-xs-pxf-hive-fdw-encoding-utf8 = open（BUG 未修，用户 dogfood 实测 baseline pass + main fail），lg-xs-zombodb-partition-text-search = fixed。design.md §16.4 表格 + 关键差异 + 新增"status 双轴语义" 段。测试 fixture 改 5 处（backend `test_alembic_upgrade.py` + frontend `DashboardPage.test.tsx` / `FilterBar.test.tsx` / `CaseIdCombobox.test.tsx`），其中 DashboardPage testcase `'uses its OWN whitelist (awaiting_env, not open)'` 反转为 `'shows BOTH BUG-fix axis AND awaiting_env lifecycle value'`，断言 5 行 row testid 全部存在。`statusToBadgeClass()` 零改动——已 cover open/fixed (各落 danger/success)，awaiting_env fall through 落 muted（"环境未部署不评判"）。**用户决策原话**："external-systems 这个分类的 case 依赖外部系统，所以才单独出来的，要跟 bug_regression 一样表示 BUG 修复状态"；当场指出 v1.10 stable 语义错误，要求改造前先设计后实施。 |
| v1.20 | 2026-05-26 | pm-designer (Claude) | **post-v1.19 17 PR 集群修复 + UX 增强（同一天密集迭代）。** 主线 7 类： (a) **run.errored 列 + error verdict + 5-counter 计数器**（#155/#156/#157/#158/#166）— alembic 0005 `runs.errored INT NULL`，case_results 聚合从 case_results.status='error' COUNT 来 + 历史 backfill；run row counters (passed/failed/skipped/errored/total) 在 finish_run 时一次性写，导致 PR #164 进度条 0→100% 一跳现象 → PR #166 改前端 progress bar 从 case_results.length 派生 done + bucket，backend create_run() 加 `total=len(cases)` 启动即写；frontend RunVerdict 加 'error' 单档（与 fail 同红但 label 不同 — diagnostic path 不一样：fail=assertion 不满足，error=驱动崩）。 (b) **case 隔离三连**（#160/#162/#163，dogfood 暴露 zombodb 末位 ERROR）— #160 引入 `SqlSessionPool.discard_all()` 用 DISCARD ALL → run #32 12/17 cases InFailedSqlTransaction（DISCARD ALL 不能 inside tx，psycopg3 autocommit=False 每个 execute() 隐式 BEGIN）→ #162 改 RESET ALL + DEALLOCATE ALL（tx-safe）→ run #33 4 个 _pg3_0 InvalidSqlStatementName（DEALLOCATE 杀 psycopg3 自身 auto-prepare client cache）→ #163 `prepare_threshold=None` 一劳永逸关 auto-prepare。run #34 PASS。 (c) **时区 root fix**（#168/#169/#170）— 用户报"刚跑的 run 显示 8h ago"，UTC+8 时差。#168/#169 前端 formatRelative + ETA 加 tz-less ISO 当 UTC 防御（regex append Z），#170 后端 root fix: `datetime.utcnow()` → `datetime.now(UTC)` × 9 callsites + `backend/app/utils/time.py` 新增 `as_utc()` helper 在所有 API response 边界 attach UTC tzinfo (SQLite SQLAlchemy DateTime 列不保 tz，读回 naive)，9 个新 test + API 契约测 assert `+00:00` 后缀。前端防御 shim 保留作纵深防御。 (d) **进度条** (#164 初版 + #166 live counter fix) — design.md §13.12 line 679 说"前端显示进度条"，M6-1 PR #110 只落 SSE event 没落视觉条，user dogfood "RUNNING live 没看到进度条" → #164 加 `<progress>` + 5-counter + ETA；#166 修 backend 在 create_run 时不写 total / SSE refetch 不更新 run row counter 导致 0→100% 跳。 (e) **observability + auth 迁移** (#150/#161/#167) — #150 readDetail unwrap FastAPI `HTTPException(detail={dict})` 嵌套 → flat 一致；#161 orchestrator artifact 写盘时 sanitize step_id 路径分隔符（zombodb step name 含 "ES /_cluster/health" 导致 artifact dir 嵌套 + step_result.error 落 `.error.txt` artifact 让 sql_driver 异常文本可见；#167 AdminSkipListPage / AdminCasesPage 从 legacy X-Admin-Password (M6-4 PR #115 已删) 迁到 `authHeaders()` Bearer token (v1.17 user-login)。 (f) **path config R27 加固** (#154) — `external_deps_loader._resolve_dir()` 加 `LBR_REPO_ROOT/external` 兜底，uvicorn 从 backend/ cwd 起也能找到 external svc YAML（dogfood 2026-05-26 run #25 zombodb 5ms error 暴露）。 (g) **SSE 修 + 5173 dev 绑真 IP 文档 + hadoop_simple external** — #159 EventSource 用绝对 API_BASE 而非相对路径（vite 不代理 /runs/*）；#165 `external/hadoop_simple.yml` 落库（10.14.3.201 Hadoop 3.1.4 + Hive 3.1.3，root SSH 免密验证、端口实测对齐 Hadoop 3 出厂默认）；外部文档 `lbr-bind-to-real-ip.md` 完善 4 项警示（运行中 run 检查 / alembic head / ARTIFACTS_ROOT 切换 caveat / .env.local build-time 也读）。 |
| v1.19 | 2026-05-26 | pm-designer (Claude) | **target_versions registry 落地 + Trigger New Run 文本框 → 下拉 + Runs 列加 Version 列.** 用户提出需求 "Trigger New Run 时 target_version 是文本框可随意填不严谨，想在 admin 维护清单，NewRun 用下拉，Runs 页搜索 + 历史 run 一列也对齐"。设计 5 决策点用户全选推荐方案 (a) POST /runs 不校验，UI 自约束 → CLI / CI 脚本兼容 (b) 删除被 run 引用的 version 默认拒绝，提示软删；可 ?force=true 硬删 (c) is_default 允许 0 或 1 条不强制 (d) display_order 数字字段手填，不做拖拽 (e) name 不做格式校验。**3 PR 拆分** (PR-A backend / PR-B admin UI / PR-C NewRun+Runs) 并行实施，各自 worktree 不冲突文件 (PR-B 只动 AdminPage.tsx + AdminTargetVersionsPage.tsx + App.tsx route + 本测试；PR-C 只动 RunNewPage.tsx + RunsPage.tsx + 本测试 + grid CSS)。设计详 §13.17。**接管点**：runs.target_version 列保持 `Text \| None` 不变（避免 FK 约束破坏历史数据），新表 target_versions 仅作 catalog 不强制引用；新 alembic 0004 seed `SynxDB-4.5.0-build130` is_default=true；新增 4 endpoint `/admin/target-versions` (GET 公共读 / POST PATCH DELETE 走 get_current_user)。**dogfood follow-up PR #150**：AdminTargetVersionsPage `readDetail` 后修 — FastAPI `HTTPException(detail=<dict>)` 默认嵌套成 `{detail:{detail,run_count}}`，PR #148 frontend 误读 flat shape 导致 "force delete" 二次 confirm 显示 "0 historical runs"；fix 改 readDetail 兼容 nested + flat 双形态，加 1 个 flat-shape 防御测试。 |
| v1.18 | 2026-05-25 | pm-designer (Claude) | **Release 流程 canonical 文档 + README fresh-clone 安装步骤补全 + `scripts/bootstrap.sh` idempotent 脚本.** 用户 v1.17 后追问 "RELEASE 流程，准确的步骤是什么？有没有写进 design.md 和 README.md？现在 README.md 里安装部署步骤，是不是都是错的？" — 审计发现 (a) RELEASE 流程**只在对话里，没写任何 doc**；(b) README "起本机 dev 服务" 只是 daily restart 路径，假定 `.venv/` + `node_modules/` + DB tables 都已就绪，对 fresh clone **是错的**。Fix: (1) **§13.16 Release 流程 canonical 文档** (5 子节)：13.16.1 版本号约定 (v0.x.0 与 design.md 内部版本对齐) / 13.16.2 6 步流程含每步具体命令 + pre-release check 8 项验证表 + RELEASE_NOTES 模板 + tag + gh release / 13.16.3 不做的事 (CHANGELOG.md 独立文件 / auto-release / 跨 minor backport / binary asset / 通知) / 13.16.4 历史版本号 → release tag 映射 / 13.16.5 与 §14 R 对照 (R26 R27); 推荐**首个 release tag = v0.17.0** (跟 design.md v1.17 对齐). (2) **README 重构** "起本机 dev 服务" → 拆 "首次安装" + "日常启动" 两段；"首次安装" 推荐 `bash scripts/bootstrap.sh` 一键，也列手动 4 步 (`python -m venv` + `pip install -e ".[dev]"` + `alembic upgrade head` + `npm ci`)；加 "Release" 段简版 4 步指向 design.md §13.16. (3) **新 `scripts/bootstrap.sh`** ~80 行，idempotent (重跑跳过 .venv / node_modules 已存在)，3 件事: backend venv + pip / alembic upgrade head + seed admin / frontend npm ci；smoke 跑过. **设计原则**: 单人 tool release 是"标记稳定 commit + 留 anchor"不是"发布到 PyPI/npm"；不做 CHANGELOG.md 独立文件 (design.md §0 已是 changelog，独立文件重复维护反而 drift)；不做 auto-release on tag (单人月频，手动 6 步即可); 第一个真 release 标记当前 HEAD = v0.17.0 候选. **数字**: design.md +~150 line (§13.16) / README +~50 line (install 重构 + Release 段) / scripts/bootstrap.sh 新增 ~90 line / 0 业务代码改动. |
| v1.17 | 2026-05-25 | pm-designer (Claude) | **简易用户登录模块交付 (3 PR / 9 文件 / 600+ LOC) — 替换 ADMIN_PASSWORD env 守门。** 开发尾声前最后一个 feature。设计原则: single-user (always admin) + 永久 token (无 expire) + bcrypt 哈希 + sha256-hashed opaque bearer + 多设备 OK + 不主动 invalidate 其他 token (简单)。**3 PR 链**: (a) **#131 backend auth core** — Alembic 0003 加 users + auth_tokens 表 + startup seed admin/admin (password_changed_at=NULL) + 新 endpoints (login / logout / me / change-password) + `Depends(get_current_user)` dependency 替代旧 `require_admin_password` (ADMIN_PASSWORD env + X-Admin-Password header pattern, M6-4 PR #115 落地的) + 新 dep `bcrypt>=4,<6` (passlib 1.7.4 与 bcrypt 5.x 不兼容，直接用 bcrypt 模块) + 20 测试; admin.py 把所有 mutation (skip-list POST/DELETE, delete-case) 改 `Depends(get_current_user)`. (b) **#132 frontend login + guard + Logout** — 新 `routes/LoginPage.tsx` (admin/admin 初始提示 + ?next= 跳转) + `lib/auth.ts` (token 存取 + login/logout/fetchMe helpers) + App.tsx `<RequireAuth>` HOC + Layout sidebar 加 "👤 admin + Logout" + api/client.ts auto-注入 `Authorization: Bearer <token>` + 401 → clearAuthToken + window.location.href '/login'; **CI 撞 1 次 e2e** = 5 个 playwright 测试因没 token 被 RequireAuth Redirect 到 /login 找不到 page-specific selector，fix = `e2e/_helpers.ts` 加 `seedAuth(page)` helper (addInitScript + mock /auth/me) + 3 spec test.beforeEach 调用. (c) **#133 frontend change-password + 红条** — `routes/AdminChangePasswordPage.tsx` (3 字段 + 前端校验 + 成功后 setTimeout 1.5s + reload) + `lib/auth.ts` 加 `changePassword()` helper + Layout 加 `must_change_password` 红条 banner (me.must_change_password=true 才显 + Link to /admin/change-password) + AdminPage 加 Change password 第 4 入口. **Admin 页定型为 4 入口** (v1.17 起): Skip list / External services / Delete case / Change password. **完整 UX 闭环**: /dashboard → RequireAuth gate → /login (admin/admin) → token + 红条提醒 → /admin/change-password → reload → 红条消失. **数字**: backend pytest 396→420 (+24) / frontend vitest 211→244 (+33) / merged PRs 130→133 (+3). **§14 R30 self-check**: 每 PR 1 个 novel mechanism (bcrypt+token / RequireAuth+localStorage / change-password UI+banner). **§14 R26 self-check**: 单 lib/auth.ts 是所有 token 存取 + API 调用 source；admin.py 单 get_current_user dependency 所有 mutation 共用. **忘记密码 fallback** (单人 tool 决策): backend CLI snippet `python -c "..."` reset 密码 — 详 README. |
| v1.16 | 2026-05-25 | pm-designer (Claude) | **M6 post-iter wave 2 (3 PR) + Admin 页面定型 (3 入口) + Dashboard R4b 实战修。** v1.15 落 external/dut.yml 后用户继续 dogfood + 提问：(a) **#125 Admin > External services 浏览页** — 用户："external/<svc>.yml 是 vi 编辑？" → 确认；引入 read-only 浏览页 (扫 EXTERNAL_DEPS_DIR 列 .yml/.yaml + 显完整 YAML 内容 + size + mtime + inline parse_error，**不开 web 编辑入口**遵循 v1.15 #123 "filesystem 是 source of truth" 原则)；顺手修 `external/dut.yml` hosts: `synxdb-0001` → `std` (标准 standby coordinator hostname) + 加 mdw/std/sdw1/sdw2 topology 注释。(b) **#126 Admin > Delete case + 教育性 confirm** — 用户先想要 delete + Runs 页 combobox 保留显示已删 case (历史搜索)，反思后改方案：删除 = forever，combobox 不显已删。`DELETE /admin/cases/{case_id}` 删 YAML 文件，case_results 表保留 (case_id 是 string 无 FK)；confirm dialog 教育文案 = "短期不想跑某 case → 用 Skip List (可加过期日，到期自动恢复)；只有彻底不再保留这个 case 时才走 Delete"；require_admin_password 守门 + path traversal 双重防御 (_iter_case_files + resolve relative_to)；不自动 git commit/push (避 endpoint 持凭据)。CI 撞 1 次 eslint (`_msg: string` 触发 no-unused-vars，项目 config 没 argsIgnorePattern: '^_'；fix = vitest 1.x tuple-arg generic `vi.fn<[string], boolean>`)。(c) **#127 Dashboard row 2 数据驱动 — §14 R4b 实战 N+1 反模式** 用户："为什么外部系统集成测试不在第 2 行？" 根因 = `bugCategory()` / `extensionCategory()` 两个 helper 用 id_prefix 硬找 `lg-bug-`/`lg-ext-`，没找 `lg-xs-`。M5-2 写 row 2 时只考虑 2 个 category；M4c 加 external_systems 后 row 2 缺新 category。Fix = 删两 helper，row 2 改 `data.categories.map(...)` 跟 row 1 同模式；testid 从 `dashboard-kpi-bug-status` / `extension-stability` → `dashboard-kpi-status-<category_name>` 一致命名。**§14 R4b 实战教训**：同一文件 row N 数据驱动 vs row N+1 硬编码是隐性反模式 — visibility gap 拖到第三个 category 加入后才暴露；review 阶段应主动扫"两个看起来一样的 list/row 是否都按数据驱动写"。(d) **Admin 页定型为 3 入口**：Skip list (暂时禁用，可 until_date 自动过期) / External services (read-only YAML 浏览) / Delete case (永久删 + 教育性引导回 Skip List)。**M6 post-iter 累计 PRs**: #119-#127 共 9 个，全 user-driven 手写，0 foreman dispatch；vitest 156→204 / pytest 388→396+ / merged PRs 117→127 (+10)。 |
| v1.15 | 2026-05-25 | pm-designer (Claude) | **M6 sprint 后续 UX 迭代 (5 PR) + DUT 连接统一到 `external/dut.yml`。** 用户 M6 收尾后陆续追问 + UX 优化提议 → 5 个独立小 PR + 1 个 refactor PR + 1 个 EMPTY run DB cleanup，全部 user-driven 手写无 foreman。(a) **#119 Settings allowlist 砍 dev_db_url + cluster_topology** — 2 个 reserved key 没接 consumer，编辑无效。(b) **#120 Skip List case_id 改 shadcn Combobox** — 用户反馈 case_id 长易 typo；引入 cmdk + @radix-ui/react-popover；新 `ui/popover.tsx` + `ui/command.tsx` + 复用业务组件 `CaseIdCombobox.tsx` (fuzzy search id 或 title，rich row = id mono + title + status badge)；vitest.setup.ts 加 ResizeObserver + scrollIntoView polyfill (jsdom 缺)。(c) **#121 RunsPage `?case_id=X` filter + 搜索 scope 收窄** — 用户："搜 ID 意义不大；想搜哪几轮测了某 case"；backend 加 `GET /runs?case_id=X` SQL JOIN case_results；前端 useFilters hook + `case_id` 字段 URL 持久化；FilterBar 下方加 "Includes case:" CaseIdCombobox (PR #120 第 2 处复用); 搜框 hay 从 `id + verdict + version + triggered_by` 收窄到 `version + triggered_by`。(d) **#122 Skip List until_date 加中文 label** — `type="date"` 不渲染 placeholder，原文字看不见；显式 `<label>` 写 "skip 自动过期日 (可选) — 不填 = 永久 skip 直到手动删；填了 = 当天起恢复跑"。(e) **#123 砍 Admin > Settings + DUT 迁到 external/dut.yml** — 用户："Settings 排啥用处？"；翻 15 个 case YAML 后承认 3 个 allowlist key 实际无 consumer (jinja_context 没 case 引用 / dut_hosts 可走 external/ / server_log_path case YAML 自己写); 设计原则：**外部依赖统一 `external/<svc>.yml` 体系，DUT 也是一个外部系统**；新 `external/dut.yml` + `dsn_builder.dsn_map_from_external_or_env` (file > env > default 优先级 per-field) + `_execute_run` 始终包含 dut；删 `/admin/settings` GET/PUT endpoints + AdminSettingsPage frontend + 6 个 settings 测试 + AdminPage Settings 链接 + Layout breadcrumb；real-cluster smoke run #18 lg-bug-0001 PASS 2267ms 验 dut.yml 路径连真集群正确。(f) **DB cleanup**: 删 EMPTY verdict run #18 (M6-6 skip-test 1 case skipped 后 counters 全 0 显 EMPTY)；backup `runs.db.backup-20260525-024905-pre-run18-delete`。**§3.1 集群访问约定**同步加 v1.15 注脚指向 external/dut.yml。**M6 sprint 数字累计**：vitest 195/195 (M6 收尾 187 → +Combobox 9 + RunsPage 4 + AdminPage -5 settings + 净 +8) / pytest 392/392 (388 + dsn_builder 4 + admin -6 settings + runs 替换 -1+1) / merged PRs 117 → ~123。**设计观察**: §14 R26 ("dual-code-path") 新变体 = "spec 层声明的能力 vs runtime 实际接通"——M6-4 PR #115 落 settings endpoint 但 backend `_load_jinja_context_and_dut_hosts` 没 consumer drives the runner，留待 §14 R 候选条 "wiring-gap" 沉淀。 |
| v1.14 | 2026-05-25 | pm-designer (Claude) | **M6 运行体验深化 sprint 完整交付 + M6-4 wiring fix forensic + §13.14 实战回顾入档。** M6 主体（6 子步骤 + 1 dogfood，PR #110/#112/#114/#115/#116/#117 + 报告 `docs/m6-dogfood-2026-05-25-0212.md`）：(a) **M6-1 SSE 进度条** (#110) — `app/runner/event_broker.py` per-run asyncio.Queue broker (publish 非阻塞 best-effort + multi-subscriber + terminal 自关) + `GET /runs/{id}/stream` StreamingResponse (text/event-stream, 含 snapshot 让后到订阅者看 baseline + 20s keepalive comment 防 proxy 关连) + orchestrator `publish_case_done` 每 case 完成 (skip-list 短路也 publish) + `_execute_run` finally `publish_run_done` / `publish_run_aborted` + 前端 RunDetailPage 替换 3s polling 为 EventSource (init GET → SSE event → refetch 模式) + fallback to polling on stream error。**顺修 pre-existing bug**: 旧 `TERMINAL_STATUSES = {'pass','fail','error','completed'}` 用 verdict 比 lifecycle status，polling 永不停止；M6-1 删 stale 常量改判 `{'done','aborted'}`。(b) **M6-2 artifacts download** (#112) — 不需 schema 改（orchestrator 已经写 `<artifacts_root>/<run_id>/<case_id>/step-NN-<step_id>.{stdout,stderr}.txt`）+ `GET /runs/{run_id}/cases/{case_id}/artifacts` 列文件 + `GET .../{filename}` 下载 (FileResponse + `Content-Disposition: attachment` + text/plain charset=utf-8) + 文件名正则解 `step_idx` / `step_id` / `kind`(stdout/stderr/log/other) + path traversal 防护 (拒 `/` `\` `..` + resolve 后 `relative_to(artifacts_dir)` 二次验证防 symlink 跳出) + 前端 RunDetailPage 每 case 行下方 ▸Artifacts 折叠 lazy fetch list/loading/error/empty 4 态 + `<a download>` 直跳后端 endpoint。(c) **M6-3 history diff** (#114) — 纯前端实现无 backend 新 endpoint (两个并行 GET /runs/{id})；`/runs/diff?a=X&b=Y` 新路由 + Layout breadcrumb "Runs / Diff" + RunsDiffPage 客户端 diff 7 类 (pass_to_fail / fail_to_pass / new_case / removed_case / duration_jump(>1.5×) / status_change_other / unchanged) + 排序 regression first → fixed → new → removed → duration_jump → status_change_other → unchanged + unchanged 默认隐藏复选框切换 + Dashboard "Compare last 2 runs →" 链接 (≥2 run 才显)。(d) **M6-4 Admin UI** (#115 + F1 fix in #117) — 新 5 个 endpoint: `GET/POST /admin/skip-list` + `DELETE /admin/skip-list/{id}` + `GET /admin/settings` + `PUT /admin/settings/{key}` + `require_admin_password` 依赖 (env `ADMIN_PASSWORD` 设了就要求 `X-Admin-Password` header；env 没设 → dev mode 不要求；GETs 全开)；存储层加 `add_skip_list_entry` / `delete_skip_list_entry` / `list_settings` 3 个 helper；`ADMIN_EDITABLE_SETTINGS` allowlist 限制可写 key 到 jinja_context/dut_hosts/dev_db_url/cluster_topology/server_log_path 防误改 case_categories；PUT value 必须 JSON 对象 (dict)；前端 `/admin` landing + `/admin/skip-list` (CRUD with confirm() delete) + `/admin/settings` (5 个 textarea JSON 编辑 bad JSON inline error) + Sidebar Admin 从 disabled 改可点 + breadcrumb 3 个新映射 + localStorage.adminPassword 自动注入 header。**F1 wiring fix in #117**: M6-4 PR 落了 CRUD endpoints 但 `_execute_run` **没把 DB 里的 skip_list 传给 `orchestrator.run_suite`**——orchestrator 早就支持 (M2 `_matching_skip_rule`) 但 API 路径从未 wire。Dogfood 暴露 (Run #17 加 skip 仍 PASS) → fix: `_execute_run` 调 run_suite 前 `sqlite_store.get_skip_list(sess)` 转 list[dict] 传 skip_list kwarg + regression test `test_execute_run_passes_skip_list_to_orchestrator`。(e) **M6-5 external_deps runtime injection** (#116) — 新 `app/runner/external_deps_loader.py` (collect_external_deps 跨 case union 去重 + load_external_context 读 `external/<svc>.yml`，默认 `./external/` 可 `EXTERNAL_DEPS_DIR` env 覆盖；missing file / non-dict / invalid YAML → warning + skip 后续 Jinja UndefinedError 给清晰错误) + `_execute_run` 在调 orchestrator 前注入 `jinja_context["external"]`，user-supplied 优先 (本地 override > yaml 默认) + sample `external/elasticsearch.yml` + M4c-1 case `lg-xs-zombodb-partition-text-search` ES URL 2 处 hardcode 改为 `{{ external.elasticsearch.extras.scheme }}://{{ external.elasticsearch.host }}:{{ external.elasticsearch.port }}`。**修 case_normalizer drop external_deps bug** (§14 R26 一例)：之前 normalize_case **drop external_deps 字段**，导致 collect_external_deps 收不到 svc 列表 wiring 静默失败；本 PR 加字段透传 + 3 个新 test。(f) **M6-6 dogfood** (#117) — M4c-1 case 3 轮 real-cluster (synxdb-0001 + ES 192.168.195.203:9200 status=green) verification: Run #15 PASS 1/0/1 (1312ms, SSE 3 events 流式 + M6-5 Jinja 渲染) + Run #16 PASS 1/0/1 (M6-3 diff side B) + Run #18 SKIP 0/0/1 (F1 wiring fix verified)。`docs/m6-dogfood-2026-05-25-0212.md` 完整证据链 + F1 forensic + F2 followup (step 02 missing artifact，shell driver stdout 经 `su` 子 shell 后被吞，low impact 留 backlog)。**§14 R28 满足 (≥3 轮)**。**4 个 parallel UI 小 PR** (与 M6 不冲突，用户授权 parallel)：#111 CasesPage "+ New Case" header CTA + #113 Dashboard quick-actions 去掉重复 "+ New case" + 之前 #107 Dashboard verdict 计数器修 + #109 RunsPage hide no-op category chip。**M6 sprint 总成绩**：~2 小时夜间 push / 6 PR + 1 dogfood / 代码净增 ~2600 行 / vitest 156→187 (+31) / pytest 376→388 (+12) / ci-gate 0 失败 (M5 R24 教训之后 backend-fixer + frontend-fixer hard rule 一致 enforce) / dogfood F1 暴露 1 个 wiring bug + 修 + regression test。**§14 R30 实战**: 每个 M6 子 PR `novel mechanism: 1` self-check 全过 (SSE 端到端 = 1 / artifacts API+UI = 1 / diff classification+UI = 1 / admin CRUD pattern = 1 / external context loading+injection+render = 1)，无 R30 命中。 |
| v1.13 | 2026-05-24 | pm-designer (Claude) | **M7 LLM 接入 sprint plan 入档 (§13.13 + §18.M7)** + §12 Roadmap 加 M7 row + §0.1 Topic Index 加 "Web LLM 接入" row。用户 2026-05-24 PM 问 "/cases/new 从描述生成 现可用么？" → 确认 M3a-5 当时 stub (`handleGenerateStub` 弹 toast) → 用户决策**单列 M7** (option B 独立 milestone，不混入 M6)。**M7 = §5.4 "LLM 解析模块" 真实现**：5 子步骤 (M7-1 backend `POST /cases/generate-draft` 含 Anthropic SDK + retry≤2 / M7-2 prompt 设计 + 3 hardcoded few-shot examples / M7-3 frontend 状态机 + 必须人工确认 gate / M7-4 backend+frontend 单测 / M7-5 user-driven dogfood)。**§14 R 预付** R26/R27/R4b/R6/R24/R29/R30。**待用户决策 3 项**：D1 model (默认 sonnet, §5.4 spec; 备选 opus-4-7 与 skill 一致 / env var) / D2 few-shot 来源 (默认 hardcode 3 例 BUG+ext+跨 driver; 备选 dynamic /admin/few-shot endpoint) / D3 ANTHROPIC_API_KEY 管理 (默认 env var only + README; 拒进 admin UI / system_settings 表)。**M7 不做的事**：streaming response / multi-turn / prompt 版本管理 / 其它 LLM provider / API key 进 UI。M7 完成定义：user 描述真生成一例 + 走通 Validate→Try→Save→PR auto-merge + `docs/m7-dogfood-<ts>.md` 报告。 |
| v1.12 | 2026-05-24 | pm-designer (Claude) | **M5 前端 UX 统一面板 sprint 完整交付 + §14 R29~R32 入档 (foreman → M5-1 PR #94 失败链事后分析)。** M5 主体（5 子步骤 + 1 dogfood，PR #95~#99 + 报告 `8e8746a`）：(a) **M5-1 sidebar layout** (#95, minimal) — 替换 top nav 为 240px sidebar (Dashboard/Cases/Runs/Admin disabled) + breadcrumb + main content；plain CSS 无 Tailwind 响应式 / 无 useEffect mount fetch / 无 shadcn primitive shim；14 vitest 单测，不用 playwright (M5-1 第一次尝试 PR #94 用 full-feature 路径 9/15 e2e fail，**用户决策 close+重写 minimal**——PR #94 → PR #95 走过的弯路成为 R29/R30/R31/R32 的来源)。(b) **M5-2 Dashboard `/`** (#96) — KPI tiles + recent activity + quick actions 一处俯瞰；§14 R4b 实战 ("5-category scenario" 测试 ≠ hardcoded category name)；M5 整套 UX 关键页落地。(c) **M5-3 cross-page link** (#97) — backend 新 endpoint `GET /cases/:id/recent-runs` (`list_recent_runs_for_case` storage 函数 JOIN case_results+runs) + CaseDetailPage Recent runs 区块 + RunDetailPage case_id 加 `<Link to="/cases/:id">`；§14 R26 实战 (storage 模块复用, 禁 inline SQL)。**ci-gate 失败 1 次** = R24 教训实战：本地 `ruff format --check app/` 局部 vs CI `ruff format --check .` 全 repo 含 tests/，新加测试 file 未 format → CI fail → ruff format fixup commit fix。(d) **M5-4 FilterBar + RunsPage** (#98) — useFilters hook (URL `useSearchParams` 持久化 q/category/status/tag/since) + FilterBar 组件 (chips data-driven) + RunsPage 真做出来替换 M2-8 placeholder。(e) **M5-5 RunNewPage preset** (#99) — `?category=X&status=Y` URL 预选匹配 cases + preset banner + Clear 按钮；M5-2 Dashboard Quick Actions 闭环。(f) **M5-6 dogfood** (`docs/m5-dogfood-2026-05-24-2226.md`) — 用户浏览器手验 8 验证点全 PASS，无 spec gap。**§14 R 4 条新入档**（详 §14.2）：**R29 reviewer false-negative**（reviewer 本机 e2e SKIP 仍 APPROVE）、**R30 specialist multi-suspect feature bundling**（PR #94 一次落地 4 个 sus 新 pattern 导致 CI fail 无法 binary search）、**R31 foreman stuck on PR CI failure**（state.json heartbeat 不更新 30+ min，未 escalate）、**R32 CI playwright artifact missing**（无 screenshots/trace 上传，e2e fail log-only 不可诊断）。M5 总成绩：~3 小时 / 5 PR + 1 dogfood / 代码净增 ~3000 行 / vitest 99→127 (+28) / pytest 341→345 (+4) / ci-gate fail 1 次 (R24 教训 fixup)。 |
| v1.11 | 2026-05-24 | pm-designer (Claude) | **design.md 整体重排 3 PR 链 (PR-A1/A2/A3)** + M5 plan docs/plans/M5.md 落地 (retroactively bumped 2026-05-24 PM；用户反馈"关联设计零散翻起来烦")。3 PR 走"新 super-section 加文末 + 旧 §4.5/§5.5/§13.x stub 指向"策略，**零 anchor 破坏** (§0-15 编号 / §14 R1-R28 全不动 / memory / SKILL.md / agent .md / case YAML notes 零更新需求)：(a) **PR-A1 #91** §0.1 Topic Index (跨章节 navigation 入口表) + §16 测试门类 super-section (6 子节：设计原则 / case_categories schema / bug_regression / extension / external_systems / 扩门类 5 步流程) + §4.5/§13.3 stub + 顺手补 §14 missing parent header (pre-existing doc bug)。(b) **PR-A2 #92** §17 add-test-case Skill super-section (10 子节，含 NEW §17.8 模型规则 `claude-opus-4-7` 永久钉 + NEW §17.9 实施回顾 + 双源同步约定 SKILL.md ↔ §17) + §5.5 stub。(c) **PR-A3 #93** §18 Milestones index (按 M 视角导航表，每 M 一段 summary + 关键 PR + 完成定义 + §13.x detail link + §18.x 共通教训对照表)。**docs/plans/M5.md** (commit `634dd94`) sprint entry 文件落地；M5 6 子步骤 + 依赖图 + R 预付清单 + 完成定义。总成绩：3 PR 总 +548 -3 line / design.md 2597 → 3142 line / 4 个新 navigation 入口 (Topic Index + §16 + §17 + §18)。 |
| v0.1–v1.10 | — | — | 历史变更已归档（瘦身，2026-05-28）→ [docs/changelog-archive.md](docs/changelog-archive.md) |

> 迭代约定：每次重要修订 +0.1，发布前定稿为 v1.0。修订时新增一行，**简述本轮关键决策**（不要只写"修改若干处"）。讨论点在 §11 同步收敛/新增。

---

## 0.1 Topic Index（v1.11 新增，跨章节导航）

用户 2026-05-24 反馈："关联的设计零散在各处，翻起来烦"。结构性 refactor 太重，改用 Topic Index + super-section 双策略：

- **canonical 位置**：相关设计集中到末尾 §16~§18 super-sections（PR-A1~A3 分批落地）
- **旧 anchor 保留**：§4.5 / §5.5 / §13.x 加 stub 指向新位置（**保持 §0-15 anchor 不变，memory / SKILL.md 不需要紧急更新**）
- **本表是入口**：任何 topic 看这一节先找到所有相关章节，再决定深读哪个

| Topic | Primary（canonical 最新版） | 历史/相关章节（保留）|
|---|---|---|
| 测试门类 case_categories | **§16**（v1.11 PR-A1） | §4.5（stub→§16.1）/ §13.3（stub→§16.5）|
| bug_regression category | §16.2 | §4.1.1 BUG schema 特化 |
| extension category | §16.3 | §4.1.1 ext schema 特化 |
| external_systems category | §16.4 | §0 v1.10 / §13.10 M4c plan / §14 R4b |
| add-test-case skill 设计 | **§17**（v1.11 PR-A2）| §5.5（stub→§17）/ §13.8 M3b plan / §13.9.4 skill 硬化 |
| skill 模型规则 (opus 4.7) | **§17.8**（v1.11 PR-A2）| SKILL.md model rule block + memory `feedback_model_override_2026-05-24` §B |
| Milestones (M0-M7) 全貌索引 | **§18**（v1.11 PR-A3 起，按 M 视角导航）| §13.x detail (chronological 视角) / §0 changelog rows / §12 Roadmap |
| Web LLM 接入 (M3a 入口 A "从描述生成") | **§13.13 + §18.M7**（v1.13 新增 plan）| §5.4 设计 / `CaseNewPage.tsx` `handleGenerateStub` (M3a-5 stub) |
| 风险预警与反模式 R1-R28 | §14（**不动**，memory 大量引用）| §0 changelog 中 R 入档记录 |
| 多 Agent 协作 (dev workflow) | §8 / §15 | §13.4 M1 retro 中 dispatch 教训 |
| **用户登录模块** (v1.17 新增) | **§13.15** | §0 v1.17 changelog / `app/api/auth.py` / `lib/auth.ts` / Admin 第 4 入口 Change password |
| **Release 流程 + 安装 bootstrap** (v1.18 新增) | **§13.16** | §0 v1.18 changelog / `scripts/bootstrap.sh` / README "首次安装" + "日常启动" + "Release" 3 段 |

**编辑约定**: 想加新 topic 时，先在本表登记 → 决定 canonical 放哪一节 → 再写内容；不要又"东一块西一块"。

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

### 3.1 集群访问约定（v0.7 固化；v1.3 补实测；v1.15 dut.yml 收敛）

runner / smoke-runner 实现这些 driver 时**默认**按下面的方式访问集群，不要发明别的连接路径。如果某天集群拓扑变了，**只**改本节 + `external/dut.yml`，其他代码不动。

**v1.15 (2026-05-25)**: DUT (system under test) 连接信息已收敛到 `external/dut.yml` —— 与 §13.10 / §16 external_systems 体系 (`external/<svc>.yml`) 统一。Backend 读取顺序 (per-field): **`external/dut.yml` > env var (PGHOST/PGPORT/PGUSER/PGDATABASE) > module default**。切集群只需改文件，不需重启或改 env。详 §13.14.8 + `dsn_builder.dsn_map_from_external_or_env`。

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
                                       # 当前活跃 category 清单见 §4.5 seed 表；schema doc 不重复枚举（§14 R4b）
                                       # 决定 status 词汇白名单、id 前缀、目录归属、看板分组
status: open                           # 合法值取决于 category（§4.5 status_whitelist 字段）。
                                       # 具体清单见 §4.5 status_whitelist 字段；schema doc 不重复枚举（§14 R4b）
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
#
# non-tx-safe DDL（CREATE/DROP DATABASE/EXTENSION 等）的写法看 §4.1.2
# ——首选 `psql -c '<DDL>'`，runner normalizer 自动路由到 shell driver。
setup:                                 # 可选；前置；list[str]
  - DROP TABLE IF EXISTS tmp_test01    # 普通 DML/DDL 直接写裸 SQL → sql_driver
  - DROP TABLE IF EXISTS tmp_test02
  - |
    CREATE TABLE tmp_test01 (i int);
    INSERT INTO tmp_test01 SELECT i FROM generate_series(1, 10000000) i;
    ANALYZE tmp_test01
  - psql -c 'create extension if not exists pgvector'   # non-tx-safe DDL 走 psql -c（§4.1.2）

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

#### 4.1.2 non-tx-safe DDL 走 `psql -c`（v1.3 后期约定，2026-05-24 用户决策）

**规则**：YAML 的 `setup` / `steps` / `teardown` 里凡是 **psycopg 没法跑成功**的特殊 DDL——典型包括：

- `CREATE DATABASE` / `DROP DATABASE`
- `CREATE EXTENSION` / `DROP EXTENSION`
- 其他 PG 明确禁止在事务里跑的 DDL（`VACUUM` / `REINDEX CONCURRENTLY` / `ALTER SYSTEM` / `CLUSTER` 等）

**统一写成** `psql -c '<DDL 语句>'` 字符串，**不**直接写裸 SQL。runner 的 normalizer 检测 setup/teardown 字符串里**含 `psql ` 子串**就路由到 `shell_driver`（不进 `sql_driver`），避开 psycopg 默认 `autocommit=False` 把 DDL 包进事务被 PG 拒绝的死路。

**示例**（用户给定的标准形态）：

```yaml
setup:
  - psql -c 'drop database if exists mydb'
  - psql -c 'drop extension if exists pxf'
  - psql -c 'create extension if not exists pxf'

teardown:
  - psql -c 'drop database if exists mydb'
```

**部署侧 caveat**：shell_driver 跑在当前 runner 进程的 OS 用户下（M0 step 1 起本机一直是 root）。root 默认 PATH 没 psql（psql 在 `/usr/local/synxdb4/...` 下，由 `gpadmin` 的 profile 引入）。两种解法：

1. **首选**：YAML 里直接写 `psql -c 'DDL'`，部署侧用 systemd / cron wrapper / Tier A `env` 文件把 psql 路径加进 runner 进程的 PATH（最干净，YAML 短小）。
2. **fallback**：YAML 里包一层 `su - gpadmin -c "psql -c '<DDL>'"`（§3.1 集群访问约定的写法）——临时手工跑 dogfood 时用过；缺点是引号嵌套丑。

normalizer 检测策略用 `"psql " in stripped`（**子串**不是 prefix），两种形态都支持。

**为什么不让 sql_driver 自动 autocommit**：M1-followup F-3 实战引入了一个 regex `_NON_TX_DDL_RE`（位于 `sql_driver.py`）来探测 non-tx-safe DDL 并临时切 `conn.autocommit = True`。该机制**保留作 defense-in-depth**（YAML 漏写 psql 前缀时 sql_driver 兜底），但**不是首选路径**——理由：

- 反向探测靠 regex 维护越多模式越脆弱（漏一个 DDL 关键字就掉沟）
- 切 `autocommit` 影响整个连接状态，需要 finally 复原，复原时机一旦错就污染后续 step
- psql 自己起独立 session 是 PG 工具链的"原生干净"方式，没有 transaction-state 维护成本

**§14 R 编号**：本约定 forensic 来自 PR #18 (commit `b49b766`) + lg-bug-0005 在 dogfood 上的 ERROR 实测；defense-in-depth 的 sql_driver autocommit 实现是 F-3 的副产物。本身是正向 prescription 不是反模式，所以**不**新加 R 条目；reviewer 在 cases YAML 审查时如发现 non-tx-safe DDL 没走 `psql -c` 应直接 REQUEST_CHANGES 引用本节。

**v1.3 (j) 后续硬化**（2026-05-24 M1-followup + M1-cleanup 反复踩同款坑）：(1) backend-fixer / frontend-fixer / doc-writer 的 6-step PR contract 在 `.claude/agents/*.md` 升级为 **7-step**，step 1 显式列出本地 ci-gate 等价命令（backend = ruff check + ruff format --check + pytest；frontend = tsc + lint + vitest + 可选 playwright），commit 前必须**全绿**；新增 hard rule "7 个 step 必须连续走完，commit + push 之后必须 open PR"。(2) foreman.md 加 hard rule 8 "EVERY exit path 必须 print final JSON 到 stdout 作为最后一个动作"——M1-followup + M1-cleanup foreman 各栽一次，连续两次得人手 reality-reconciliation；hard rule 9 "检查 specialist 6-step contract 完整性，commit-but-no-PR 算未完成"。§14 加 R24（specialist commit/push 后不 open PR 或不跑本地 ci-gate 等价命令）+ R25（foreman 不返 final JSON 就 exit）两条反模式。reviewer step 5 cross-check 时凡命中 R24/R25 直接 REQUEST_CHANGES。

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

> **v1.11 (PR-A1 reorg)**：本节内容并入 **§16 测试门类 super-section**（canonical），含完整 3 类 (`bug_regression` / `extension` / `external_systems`) 设计、每类 schema 特化、扩门类标准流程。此处保留作历史 anchor；新编辑请到 §16.1。

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
-- v1.10 (Alembic migration 0002, 2026-05-24): third category for cases
-- depending on external service components (datalake_fdw / hive_connector /
-- PXF / zombodb). Distinct from `extension` which is self-contained
-- CREATE EXTENSION; external_systems needs the external service process
-- + credentials + profile.d wired through before the case is runnable —
-- hence the `awaiting_env` default status.
INSERT INTO case_categories (name, display_name, description, id_prefix, dir_path, status_whitelist, default_status, display_order, created_by) VALUES
  ('external_systems',
   '外部系统集成测试',
   '依赖外部组件（datalake_fdw / hive_connector / PXF / zombodb 等）的集成测试用例。与 extension 不同：外部服务进程必须可达 + 凭据/网络/profile.d 已就绪，case 才能跑；环境未就绪时 status 应为 awaiting_env。',
   'lg-xs-',
   'external-systems',
   '["stable","awaiting_env","deprecated","stub"]',
   'awaiting_env',
   30,
   'seed:0002');
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
- 走 Anthropic SDK，模型 **`claude-opus-4-7`（首选）**——与 skill 路径对齐（feedback_model_override_2026-05-24：skill 永久钉 opus、禁 sonnet）；§13.13 v1.25 amendment 推翻了早期 `claude-sonnet-4-6` 默认。prompt 里塞 YAML schema + 3~5 个 few-shot 例子。
- **开启 prompt caching**（schema + 例子放到 cached prefix），降低成本。
- 返回前在后端做一次 YAML 合法性 + schema 校验，不合法重试一次（最多 2 次）。
- 前端展示草稿后**必须人工确认**，确认后才进入"Validate → Try → Save → PR"流程，绝不直接落盘。

### 5.5 Claude Code Skill — `add-test-case`（v0.6 新增；借鉴 preflight `add-test-case`；v0.7 支持双 category）

> **v1.11 (PR-A2 reorg)**：本节是 v0.6-v0.9 设计快照（保留作历史 anchor）；**canonical = §17**（含双源同步约定 + 当前 6 题对齐 + 12 项 cross-check + 3 场景特化追问组 + 模型规则 + 硬化历程）。新编辑请到 §17。

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

sessions: []                            # 命中并发场景时填 mapping `{s1: {driver: sql}, s2: {driver: sql}}`；空 list / 空 mapping / 省略 = loader 自动 derive default session（M3a-10 dogfood 后兼容）

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
| Settings → General → Visibility | visibility | **public**（v1.3 (i) 改，M1 阶段紧接 ci-gate 架构修复）。M0 step 1 原决策 private 主因"飞书原文外泄"已不成立——cases/*.yaml 早已直接引 issue URL + 触发 SQL；public 解锁 branch protection / rulesets / Wiki，作为 ci-gate gate 的硬前提 |
| Settings → Branches → Branch protection rules (main) | required_status_checks | **`ci-gate / gate`** 单项 required（v1.3 (h) + (i) 落地）；`strict: false` / `enforce_admins: false`（admin bypass for emergency recovery）/ `allow_force_pushes: false` |
| Settings → Branches → 默认分支 | Default branch | `main` |
| Settings → General → Pull Requests | Allow auto-merge | ✅ 开启（用于 §7.2 "auto-merge on green"） |
| Settings → General → Pull Requests | Automatically delete head branches | ✅ 开启 |
| Settings → Actions → General | Workflow permissions | Read and write（让 CI 能在 PR 上评论 / 自动 merge） |
| Settings → General → Features | Issues / Discussions / Projects | 三项启用（v0.4 Q12）。Wiki 在 v1.3 (c) GitHub Free + private 下被 plan 限制自动禁用；v1.3 (i) repo 改 public 后 has_wiki=true 已生效——但项目按 v1.3 决议**仍用 `docs/` 替代不切回 Wiki**（PR review + version 追溯更适合） |

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
- fixer agent **"改代码 → 起分支 → 开 PR → 返回 `open-awaiting-review`"**——开完 PR 后 specialist 直接退出,**但 NOT 自己武装 auto-merge**(review-pipeline v3, 2026-05-28 改)。武装由 foreman 在 reviewer APPROVE 后做(§15.1 step 3.5)。详 §15.2。
- `reviewer` 是 **merge 前置闸门**(review-pipeline v3):PR 创建后由 foreman 派,跑 §14 + 6 域审查;verdict **决定 foreman 武不武装 auto-merge**(APPROVE→武装 / REQUEST_CHANGES→派 fix)。仍走 PR comment 不点 GitHub Approve 按钮(§11 Q10)。CC 内置 `/review` `/ultrareview` 由用户**手动**调,不进流水线(subagent 调内置 review 撞嵌套死结,见 §0 v1.22)。
- `smoke-runner` 在 PR **merge 后**由 foreman 派(**前台同步**,非 background——终态门必须 in-turn 消费 verdict,见 §15.1 hard rule 5);跑 `scripts/smoke.sh` 用 known-good case 验 harness 工具链在真集群健康;NO-GO → foreman 核对清单后开 revert PR(§15.1 step 6.a)。

**v1.3 模型调整**：
- **`backend-fixer` 从 sonnet 升 opus**（用户决策）。理由：backend 是工具的"公信力关键路径"——runner / Jinja 渲染 / 多 session / 跨节点 ssh / 边界处理一旦出错会让所有 case 误判 pass/fail。preflight 用 sonnet 跑 5 周 backend 没崩，但**单层模型 + 强 reviewer 兜底**与**双层稳健（opus + reviewer）**之间，用户选了后者。代价：foreman loop 每 round +1~3min；M1~M5 估算成本 +$50~100。其他 agent 模型不动。
- 其他 fixer / reviewer 保持 sonnet 不调（frontend 出错影响小、reviewer 是 sonnet 已与 preflight 同款）。

### 8.2 流程（v1.0 改）

参见 §15.1 foreman verify loop。简述：

1. **你**给 foreman 一份 sprint 清单（来自 §12 Roadmap 的当前 milestone 子任务）。
2. **foreman** 进入 loop：选最高优先级未完成项 → dispatch specialist → 收回结果 → 决定下一步。
3. **specialist** 改代码 / 跑测试 / 写文档 → push 分支 → 开 PR → 返回 `open-awaiting-review`（**不**自己武装 auto-merge，review-pipeline v3）。
3.5 **foreman 派 reviewer**（merge 前置闸门）→ reviewer 跑 §14 + 6 域 → verdict：REQUEST_CHANGES → 派 fix（回 3.5）；APPROVE → **foreman** `gh pr merge --auto --squash` 武装。
4. **CI**（GitHub Actions：pytest + tsc + ruff + eslint + Playwright）跑通 → GitHub 自动 merge → main 更新。
5. **foreman** 见到"该 PR merged" → **派 smoke-runner**（**前台同步**，merge 后验收）→ GO 标该项完成；NO-GO → 核对 squash 清单后开 revert PR + escalate。回 step 2。
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
| Q12 | ✅ v0.4（v1.3 修订两次） | GitHub 仓库 features 启用范围 | **三项启用**：Issues / Discussions / Projects。v0.4 原决议含 Wiki；v1.3 (c) 切 private 后 Wiki 被 Free plan 自动禁用；v1.3 (i) repo 改 public 后 has_wiki 已可启用——但**仍弃用 Wiki 用 `docs/` 替代**：(a) 所有 design / 运维 / runbook / 历史报告走 `docs/` 更适合 PR review + version 化追溯；(b) Wiki 在 public repo 上有外部可见 + 防滥用顾虑反而比 docs 麻烦。Wiki feature 留 `true` 不主动用。 |
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

> **v1.10 重构 (2026-05-24)**：M4 拆 M4a + M4b + **M4c** (new, external_systems 首批 case)；原 M5 "体验打磨" catch-all 拆 **M5 (前端 UX 统一面板，先做)** + **M6 (运行体验深化)**——理由：用户 2026-05-24 反馈"前端使用不方便、没有统一面板"，UX 痛点优先于 SSE/diff 等锦上添花。

**已完成**：

- **M0 项目骨架** ✅（design.md 定稿 + agent 配置 + skill 占位 + 仓库创建 + CI 框架）—— 完成细节见 §13.1
- **M1 后端 MVP** ✅（load YAML / run / sql_driver + shell_driver + log_grep / SQLite + 5 张表 / 基本 API / 5 例 dogfood 5/5 PASS）—— 完成细节 + 4 sprint chain 实战回顾见 §13.4
- **M2 前端 MVP** ✅（/cases tab / /runs/new / /runs/:id 完整路径 + Playwright E2E）—— 详细 §13.5 plan / §13.6 retro
- **M3a Web 录入** ✅（/cases/new 双入口编辑器 + Validate/Try/Save 三段闸门 + `/cases/submit` PR 流程；LLM 接入仍是 stub）—— §13.7 plan + dogfood 报告 `docs/m3a-dogfood-2026-05-24-1200.md`
- **M3b Skill 录入** ✅（`.claude/skills/add-test-case/SKILL.md` 落地 + 2 grounding 端点 + skill lint CI）—— §13.8 plan + dogfood 报告 `docs/m3b-dogfood-2026-05-24-1340.md`
- **M4a bug_regression 飞书 BUG 补录** ✅（3 新案 §9.7 / §9.11 / §9.12 + sql_driver chain refactor）—— 详 §13.9
- **M4b extension 首批用例** ✅（5 例：pgvector / pg_partman / anon / plpython3u+numpy / postgis；首批 3~5 例上限达成）—— 详 §13.9
- **M4 附加**：external_systems category 落地 (PR #88，§4.5 + §13.10) + skill 硬化 3 PR (#85/#86/#89，详 §13.9.4)

**待做**（按 v1.14 决策排序）：

- **M4c external_systems 首批 case** — 1 例 done (lg-xs-zombodb-partition-text-search, PR #104, status=stable, 9/9 PASS dogfood，M6-5 落地后改 Jinja 渲染)；后续 2 例由用户按环境就绪节奏添加（datalake_fdw / hive_connector / PXF 各候选），蓝图可先写 `status: awaiting_env`；详 §13.10
- **M5 前端 UX 统一面板** ✅ DONE (5 PR + 1 dogfood，v1.12)—— 详 §13.11 / §18.M5
- **M6 运行体验深化** ✅ DONE (6 PR + 4 parallel UI 小 PR + 1 dogfood，v1.14)—— SSE 进度条 / artifacts download / history diff / Admin UI / external_deps runtime injection / dogfood；详 §13.12 plan + §13.14 retro
- **M7 LLM 接入**（v1.13 新增，6 子步骤：backend endpoint + prompt 设计 + frontend wire-up + tests + dogfood）—— 让 `/cases/new` 入口 A "从描述生成" 真 work（M3a-5 当时 stub）。**优先级低，待用户主动开启**。详 §13.13 / §18.M7

**未来 candidate**（不进 milestone）：
- **design.md 整体重排**（v1.10 用户反馈"零散关联翻起来烦"）：把跨章节关联设计 (e.g. external_systems 在 §4.5/§12/§13.10/§14 R4b 都有) 按主题 cluster 重排——大工程（§4-§13 互引 anchor 全要改），调并重设一个 mini-milestone 专门做；本 PR 范围内**不动现有结构**。

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

> **v1.11 (PR-A1 reorg)**：本节并入 **§16.5**（canonical）。external_systems (PR #88) 是这个 5 步法**首次实战验证**——零业务代码改动达成 plug-and-play。此处保留作历史 anchor。

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

### 13.4 M1 实战回顾（v1.3 内追加，2026-05-24 写入）

> 内容已归档（瘦身 design.md，2026-05-28）：完整实战回顾见 [`docs/milestone-retrospectives.md`](docs/milestone-retrospectives.md)。

### 13.5 M2 前端 MVP 计划（按顺序，v1.3 内追加 2026-05-24）

参考 §6（前端设计）+ §6.4（前端强约束 8 条）+ §14 R2/R6/R7/R8/R4b（M3a 前端 R 条目）。M2 目标：把 M1 已就绪的 backend API（§5.2 那张端点表）接出 UI，跑通"看 case → 触发 run → 看结果"端到端体验。

**M2 任务（按依赖图 + 优先级）**：

- **M2-1 frontend 骨架**: `frontend/` 落 `package.json` + `vite.config.ts` + `tsconfig.json` + Vite + React 18 + TS strict + `index.html` + 入口 `src/main.tsx` + 根组件 `src/App.tsx`（仅 hello world 跑通），CI 第一次触发 frontend block（ci-gate path filter `frontend/**`，tsc + eslint + vitest）
- **M2-2 Tailwind + shadcn/ui 接入**: `tailwind.config.ts` + `postcss.config.js` + `src/index.css` + 接入 shadcn CLI + 装基础组件（Button / Card / Tabs / Dialog / Toast / Skeleton）。v0.2 (b) 锁定的选型
- **M2-3 OpenAPI 客户端 codegen**: `openapi-typescript` 从 backend 的 `openapi.json` 自动生成 TS 类型；`src/api/client.ts` 用生成的类型 wrap fetch。**§6.4 R2 强约束**：禁止手写 API 类型（5 倍出错率）
- **M2-4 root layout + ErrorBoundary**: `src/App.tsx` 包一层 `<ErrorBoundary>` 兜底（§6.4 R7 / §14 R7：组件渲染抛错时降级 UI 显"返回首页"，禁止 blank page）；layout 含 header + nav + main area + Toaster
- **M2-5 `/cases` 页面**: 按 category 分 tab（**§14 R4b**：tab 列表从 `GET /admin/categories` 拉，不写死 `["bug_regression", "extension"]`）；每个 tab 列出该 category 下用例（GET /cases?category=X），含 status 徽章、tags、是否在 skip_list、最近一次运行结果
- **M2-6 `/cases/:id` 详情页**: 显示 YAML 原文（语法高亮）+ 4-tuple 叙事字段（description / procedure / expected）解析渲染 + 最近 N 次运行结果列表 + 相关 PR / issue 链接
- **M2-7 `/runs/new` 触发页**: 选 case_ids（多选 + 全选 / category 全选）+ target_version 文本框 → POST /runs；**§6.4 R4 强约束**：表单提交必有 Playwright contract test 断言提交体 shape（不是 button 点击通过）；POST 返 409 时显示"已有 active run"模态
- **M2-8 `/runs` 列表 + `/runs/:id` 详情**: 列出 runs（pagination 简易，按 started_at desc），点入详情显示 per-case results（status / duration_ms / artifacts_path 链接）；SSE `/runs/:id/stream` **推到 M5**（首版用 polling 每 3s 刷一次 GET /runs/:id 替代）
- **M2-9 Playwright E2E suite**: 端到端覆盖 "case 列表 → 触发 run → 看结果" 关键路径；**§6.4 R6 / §14 R6 强约束**：所有交互元素用 `data-testid` 选择器，**禁止** `.card + .pool-label` 结构选择器
- **M2-10 dogfood smoke**: 前后端一起起，跑一遍 M2-1~M2-9 各页面渲染 + 一次完整 run 触发，产 `docs/m2-dogfood-<ts>.md` 报告

**§14 R 预付检查**（写代码时回看）：

- **R2 contract test**: M2-7 表单提交 PR 必有 Playwright `page.route("**/api/runs", ...)` 断言 postDataJSON shape，不是只断 button 渲染
- **R6 data-testid**: M2-9 E2E 全部用 `data-testid="..."` 选择器，每个交互元素都加 testid 属性
- **R7 ErrorBoundary**: M2-4 根组件强制 `<ErrorBoundary>`；任何子树抛错必有降级 UI，禁止白屏
- **R8 test.skip declaration-level**: 任何 Playwright test.skip 写在 declaration（`test.skip("name", fn)`）不是 body
- **R4b category 不硬编码**: M2-5 tab 列表 / 任何 category-aware 渲染 / 用例详情页状态徽章着色 全部从 `GET /admin/categories` 拉，绝禁 `if category === "bug_regression"` 字面比较
- **R24 specialist 跑本地 ci-gate 三件套**: frontend-fixer step 1 必跑 `npx tsc --noEmit && npm run lint && npm test -- --run`（+ playwright if 触及）全绿才 commit
- **R25 foreman wrapper 强制**: dispatch foreman 一律走 `scripts/dispatch-foreman.sh`（详 §14 R25 mitigation）

**M2 sprint dispatch 模式预测**：

参考 M1 实战经验，M2-1（骨架）必须先做（其他都依赖 frontend/package.json 存在 ci-gate frontend block 才触发）。M2-2 ~ M2-4 是横向 infra，可串行做。M2-5 ~ M2-8 是 4 个独立页面，**可并行 4 个 frontend-fixer 各 isolation:"worktree"**（前提 M2-1~M2-4 done）。M2-9 + M2-10 依赖前面全 done。

**预算估算**：10 个 item，参考 M1 单 sprint 6 个 PR (~50 min) 节奏，并行打满 2-3 round 应能吃下 M2-1~M2-8（~30 min）；M2-9 e2e 慢些（~20 min）；M2-10 smoke 真起服务 ~10 min。**单 foreman session 2h budget 应该够**，但留 1 round buffer 给 ci-gate 回归红的可能性。

**完成定义**：
- 全 10 个 item [x] + ci-gate 全绿 + frontend block 真跑过（第一次：M2-1 引入 package.json 触发）
- 端到端 dogfood：你（人）在浏览器打开 `http://localhost:5173/cases` → 看到 5 个 bug-regression case → 点 "新建 run" → 选所有 case → 触发 → 看 run 进度 → 看 5/5 PASS。整流程 ≤ 30s 用户感知延迟（runner 真跑会久，但 UI 不卡）
- reviewer 在每个 PR 上 §14 R 编号 cross-reference（特别 R2/R6/R7/R4b）应当 ≠ REQUEST_CHANGES

**M2 不做的事**（明示）：
- SSE `/runs/:id/stream` 实时推送 — 推到 M5（M2 用 3s polling 占位）
- `/cases/new` 编辑器双入口 + Validate/Try/Save 三段闸门 — M3a 才做
- Admin UI（skip_list / settings） — M3b 后 / M5
- artifacts 下载 / tag 筛选 / 运行历史 diff / 看板分组统计 — M5

### 13.6 M2 实战回顾（v1.5 内追加，2026-05-24 写入）

> 内容已归档（瘦身 design.md，2026-05-28）：完整实战回顾见 [`docs/milestone-retrospectives.md`](docs/milestone-retrospectives.md)。

### 13.7 M3a Web 录入计划（按顺序，v1.5 内追加 2026-05-24）

参考 §6.1（/cases/new 双入口 + Validate/Try/Save 三段闸门）+ §6.2（关键交互）+ §6.4 R1~R7 前端强约束 + §14 R2/R6/R7/R26（M3a 触发：表单 contract test / data-testid / ErrorBoundary 已有 / 编辑器涉及 backend 端点新增 = 注意 dual code path）。

**M3a 任务（按依赖图 + 优先级）**：

- **M3a-1 `POST /cases/validate` endpoint**（backend）：接收 YAML 文本，跑 `yaml_loader.parse + normalize_case` 校验，返回 `{ok: bool, errors: [{path, msg}]}`。秒回（不连 DB / 不跑集群）。复用 §4.1 yaml_loader + §4.1.2 case_normalizer，**禁止重写校验逻辑**（§14 R26）
- **M3a-2 `POST /cases/try` endpoint**（backend）：YAML → normalize_case → 起 SqlSessionPool（同 `/runs` 路径） → 跑一次完整 case（setup + steps + teardown），结果**不入 DB**（不 INSERT runs / case_results，artifacts 临时目录 + 跑完删）。返回 `{step_results: [{step_id, status, duration_ms, stdout, stderr, expect_detail}, ...]}`。**§14 R26 强约束**：与 POST /runs 共享 `_execute_run`-equivalent 但写 in-memory store / no-op sqlite store，**不 fork 第二份 orchestrator 调用代码**
- **M3a-3 `POST /cases/submit` endpoint**（backend）：YAML + meta (case_id, branch_name) → 写文件到 `cases/<category>/<id>.yaml` → `git checkout -b <branch_name>` → `git add cases/<file>` → `git commit -m "cases: add <id>"` → `git push -u origin HEAD` → `gh pr create --title "cases: add <id>" --body <auto-generated>` → `gh pr merge --auto --squash`。返回 `{pr_url, pr_number, branch}`。**409 / 强校验**：Try 未通过的 yaml 拒绝 submit（在 session 内 cache "last try result for this yaml hash"），否则破坏 §6.2 闸门
- **M3a-4 `/cases/new` editor page skeleton**（frontend）：`src/routes/CaseNewPage.tsx`，shadcn Card 包 textarea（先 plain，monaco 推后；YAML 量小够用）+ 三个 button（Validate / Try / Save）+ status panel + step result 区域。`data-testid` 标全（§14 R6）
- **M3a-5 入口 A「从描述生成」**（frontend）：page 顶部 Tab 切换：A=描述生成 / B=粘贴 YAML。A 入口：textarea 用户填自然语言 + button "生成 YAML 草稿" → 调用 LLM API（Claude / OpenAI / 本机 ollama，配置项放 system_settings）→ 把生成的 YAML 自动填到主 editor。**先做 stub**：v1 留按钮但 click 显示 "M3a-5 not yet wired，请用 skill 路径"，避免 M3a 阻塞在 LLM 接入上
- **M3a-6 入口 B「粘贴 YAML」**（frontend）：Tab B 入口直接 textarea，粘 skill 输出（含 `─── BEGIN YAML ───` / `─── END YAML ───` 围栏自动剥离），填到主 editor
- **M3a-7 Validate→Try→Save 三段闸门 UI 状态机**（frontend）：state = `{validate_ok, try_ok, try_step_results}`；Save 按钮在 try_ok=true 之前**置灰** + hover tooltip "必须先 Try 一次并通过"（§6.4 强约束 6）。Validate 失败显示 errors 列表；Try 失败显示 per-step status + stderr 预览前 500 char
- **M3a-8 Playwright contract test for /cases/submit**（frontend e2e）：`e2e/cases-submit-contract.spec.ts` 用 `page.route("**/api/cases/submit", ...)` 拦截 + 断言 body shape `{yaml: str, case_id: str, branch_name: str}`（§6.4 R2 强约束 R2，**M3a 关键 R 条目**）
- **M3a-9 Try mode SSE / polling for live step results**（frontend）：Try 跑的时候 backend SSE `/cases/try/stream/<try_id>` 推每 step 完成事件（或 v1 用 polling /cases/try/status/<try_id> 替代，跟 §13.5 (M2-8) 同款 polling 模式）；UI per-step 显示 pending → running → pass/fail 滚动更新
- **M3a-10 dogfood**: 真起 backend + frontend，**人类用本 skill / 手写一份新 case YAML**（例：`lg-bug-0006-test-m3a-flow` stub），走 Validate → Try → Save 一遍，看 PR 真开出来 + auto-merge fire。产 `docs/m3a-dogfood-<ts>.md` 报告

**§14 R 预付检查**（写代码时回看）：
- **R2 contract test**: M3a-8 必有 Playwright contract test 断言 submit body shape
- **R6 data-testid**: M3a-4 editor / M3a-7 三个 button / Validate / Try / Save 全 data-testid
- **R7 ErrorBoundary**: M2-4 已建，M3a-4 不要破坏 root wrap
- **R26 dual-code-path**: M3a-1 / M3a-2 必须复用 `yaml_loader` / `case_normalizer` / `dsn_builder` 模块，禁止 inline 一份新校验 / normalize 逻辑
- **R27 path config**: M3a-3 `git push` 操作的 cwd 与 `CASES_ROOT` 配置必须显式，不能依赖 uvicorn 启动时偶然 cwd

**关键依赖图**:
```
M3a-1 (validate) ∥ M3a-2 (try) ∥ M3a-3 (submit)   ← 3 backend endpoints 可并行（共享 normalizer/loader）
                ↓
M3a-4 (editor page skeleton)                       ← frontend，依赖 M3a-1/2/3 至少 stub 完成
                ↓
M3a-5 (entry A stub) ∥ M3a-6 (entry B) ∥ M3a-7 (3-gate state machine)   ← 3 路并行
                ↓
M3a-8 (contract test) ∥ M3a-9 (polling Try)        ← 并行
                ↓
M3a-10 (dogfood)
```

**完成定义**:
- M3a-1 ~ M3a-9 全 [x] + ci-gate 全绿（backend + frontend block 都触发）
- M3a-10 dogfood：用户能在浏览器从空白 textarea 起步、走 Validate → Try → Save 把一个新 case 推到 main（PR auto-merge）

**M3a 不做的事**（明示）：
- LLM 真接入（M3a-5 stub 占位）— 推后到 M3a follow-up 或 M5
- monaco 编辑器（plain textarea 够用）— M5
- Validate / Try / Save 三段闸门绕过路径（admin override）— 永不做

### 13.8 M3b Skill 录入计划（按顺序，v1.5 内追加 2026-05-24）

参考 §5.5 完整 skill 设计（10 个子节，2026-05-24 时已规范完成）+ §13.3 未来扩门类 5 步法（skill 场景注册表加 category-tagged 组）。**M3b 几乎是写一份长 markdown 文件 + 配 2 个 backend grounding 端点**，工作量比 M3a 小。

**M3b 任务（按顺序）**：

- **M3b-1 `GET /admin/step-kinds` endpoint**（backend）：返回 `[{kind: "sql", description: "...", required_fields: [...], optional_fields: [...]}, {kind: "shell", ...}, {kind: "log_grep", ...}]`。skill §5.5.7 cross-check 1 项强校验 step kind 是否在此 list（**禁止 skill 编造**）
- **M3b-2 `GET /cases?q=<topic>&category=<name>` 查重增强**（backend）：M1-10 已有 `?category=` 过滤，本步加 `?q=` 全文搜索（filename + title + description 子串包含），返回简表 `[{id, title, status, tags}]`，skill §5.5.3 step 2 fetch 用
- **M3b-3 `.claude/skills/add-test-case/SKILL.md` 骨架 + frontmatter**（skill 文件）：write 该文件，frontmatter `name: add-test-case` / `description: ...` / `model: opus`。骨架按 §5.5.3 7 步工作流 + §5.5.1 设计原则 6 条铁律 + §5.5.2 4 个输入模式分支
- **M3b-4 §5.5.4 6 题对齐 + §5.5.3 自动推导规则**（skill）：把 6 题以 markdown step-by-step 编写；id_prefix / default_status / status_whitelist 全从 `GET /admin/categories` 拉表（**§14 R4b 强约束**：禁止 `if category == "bug_regression"` 字面分支）
- **M3b-5 §5.5.5 通用场景特化追问**（skill）：concurrent / crash / mydb / GUC / plan / 性能 6 类关键词检测，每命中加 1 题；按 design.md 表格内容逐条编入
- **M3b-6 §5.5.5 extension category-tagged 场景追问**（skill）：13 类 extension 关键词（CREATE EXTENSION / pgvector / postgis / pgcrypto / FDW / 过程语言 / shared_preload / 服务端配置 / kinit / 远端 CLI / warmup / 等），仅当 category=extension 才触发
- **M3b-7 §5.5.6 canonical 字段顺序 + §5.5.7 11 项 cross-check**（skill）：写 YAML 时按 canonical 顺序，打印 BEGIN/END 前 self-check 11 条全过
- **M3b-8 §5.5.8 输出格式 + footer**（skill）：`─── BEGIN YAML ───` ... `─── END YAML ───` 围栏 + 3 行 footer 引导用户去 `/cases/new` 入口 B（依赖 M3a 已落地）
- **M3b-9 skill 单测**（backend pytest 模拟 skill 流程 / 或 .claude/scripts 加一段 lint）：脚本 walk skill 的 5.5.4 6 题 → 模拟用户输入 → 检查输出 YAML schema 是否符合 §4.1 / canonical 顺序符合 §5.5.6。**目的**：避免 skill markdown 静悄悄写错没人发现（preflight skill 实战教训）
- **M3b-10 dogfood**: 用户在终端跑 `/add-test-case <feishu-url>` 模式 A 或 `/add-test-case ext:pgvector` 模式 D 一次完整流程，得到 YAML → 复制到 `/cases/new` 入口 B → 走 M3a Validate→Try→Save。产 `docs/m3b-dogfood-<ts>.md` 报告。**M3a 必须先 done**（dogfood 闭环需要 M3a `/cases/new` 入口 B 工作）

**§14 R 预付检查**：
- **R4b 不硬编码 category**: M3b-4 6 题 + M3b-6 extension 组检测**严格按 `case_categories` 表查表**（preflight skill 实战触过 R4b）
- **R26 dual code path**: skill 输出 YAML → M3a `/cases/validate` 校验 → 同一份 yaml_loader。**禁止 skill 自身实现一份校验逻辑**，让前端 Validate 唯一权威
- **§5.5.1 generator-only 铁律**: skill **禁止** `Write` / `git add` / `POST /cases/submit`，所有副作用走 frontend
- 模型选 opus（skill 输出需要严谨结构 + canonical 排序，sonnet 实战漂移多）

**关键依赖图**:
```
M3b-1 (step-kinds endpoint) ∥ M3b-2 (cases query enhance)   ← 2 backend，可并行
                ↓
M3b-3 (SKILL.md skeleton) → M3b-4 (6 题) → M3b-5 (通用追问) → M3b-6 (ext 追问) → M3b-7 (canonical + cross-check) → M3b-8 (输出格式)
                ↓
M3b-9 (skill 单测) → M3b-10 (dogfood, 需 M3a 已 done)
```

**完成定义**:
- M3b-1 ~ M3b-9 全 [x] + ci-gate 全绿
- M3b-10 dogfood：用户跑一次 `/add-test-case ext:pgvector` 拿到合规 YAML，粘到 M3a 入口 B 走通 Validate → Try → Save 三段闸门，PR 真 merge

**M3b 不做的事**（明示）：
- skill 写盘 / git 操作 / 调 submit（§5.5.1 铁律）
- 跑集群（让 user 在 UI 点 Try）
- 模式 A WebFetch 飞书做格式渲染 ≠ 解析飞书 BUG 结构（保留原文，让 LLM/user 推关键字段）

---

### 13.9 M4 实战回顾（v1.10 内追加，2026-05-24 写入）

> 内容已归档（瘦身 design.md，2026-05-28）：完整实战回顾见 [`docs/milestone-retrospectives.md`](docs/milestone-retrospectives.md)。

### 13.10 M4c external_systems 首批 case 计划（v1.10 内追加，2026-05-24）

**前置**：external_systems category 已 landed (PR #88, §4.5 + §13.9.3)，dir `cases/external-systems/` 已存在 (空)；skill external_systems 追问组已 ready (PR #89, §13.9.3)。**真跑 case 需要 M6-5 (external_deps runtime injection) 才完整**——但本 sprint 只要**case 蓝图能 Validate 通过 + status=awaiting_env 占位**即可，不强制 Try 跑通。

**M4c 任务**（按用户节奏，可拖到 M5/M6 期间 parallel；非顺序 milestone）：

- **M4c-1 第一例：datalake_fdw 或 hive_connector 蓝图**（推荐先 datalake_fdw，外部依赖最少）—— skill 模式 D `ext:datalake_fdw` 或模式 C 自然语言；YAML 应含 `external_deps: [hive_metastore, hdfs]` 或类似；setup 写 `CREATE EXTENSION datalake_fdw` + `CREATE SERVER` + `CREATE USER MAPPING`；steps 含 `CREATE FOREIGN TABLE` + `SELECT * FROM ... LIMIT 10`；teardown DROP 全部自建对象 + **不** DROP EXTENSION；status=awaiting_env until M6-5 真跑通
- **M4c-2 第二例：PXF 蓝图** —— PXF 通过 java agent 连 HDFS/Hive/JDBC；case 涉及 `pxf cluster start` + `CREATE SERVER` + `pxf://...` 外表语法
- **M4c-3 第三例：zombodb 蓝图**（ES 集成）—— `CREATE EXTENSION zombodb` + `CREATE INDEX USING zombodb` + `SELECT ... WHERE table ==> '<query>'` 全文搜索
- **M4c-dogfood**：每例至少跑 POST /cases/validate 通过 + /cases?category=external_systems 列出；Try 跑通待 M6-5

**完成定义**：
- 1~3 例 lg-xs-* YAML 落在 `cases/external-systems/`，validate 全 ok
- 前端 `/cases` 在 external_systems tab 列出
- 一定数量 case `status: awaiting_env` 是正常，不视为 fail

**不做的事**：
- 不强制集群部署对应外部服务（数据湖 / Hive / ES）—— 用户自己评估是否值得部署
- 不在本 milestone 加 runtime injection 代码 —— 那是 M6-5
- case 内 `{{ external.<svc>.* }}` Jinja 占位**目前 runner 不渲染**，按未来语义写

---

### 13.11 M5 前端 UX 统一面板计划（v1.10 内追加，2026-05-24）

**问题来源**：用户 2026-05-24 反馈"前端页面使用很不方便、没有统一面板"。现状（M3 之后）：
- `Layout.tsx` 只有 3 个 top nav (Cases / New Case / Runs)，无 sidebar、无 landing、无全局状态条
- `/` 直接 redirect `/cases`，没法俯瞰全局
- 跨页不连贯：case detail 看不到"最近哪些 runs 跑过此 case"；run detail 看不到"case 上次结果"
- 无全局筛选：category tab 只在 /cases；/runs 没法按 category/status/time 筛
- 触发 run 入口单调：`/runs/new` 是 raw 多选 checkbox，缺 preset ("run all bug_regression open" / "run all extension stable")

**M5 设计目标**：把 7 个孤岛页面缝合成"一套有 dashboard / 有 sidebar / 有跨页关联 / 有全局筛选"的 console。

**M5 任务**（按顺序，依赖图见末段）：

- **M5-1 Layout 重构**：top nav (3 链接) → **sidebar + main content area** 两栏布局
  - sidebar 含：Logo / 主导航 (Dashboard / Cases / Runs / Admin) / 当前活跃 run 指示器（红/绿/黄 pip + tooltip "Run #N PASS 4h ago"）
  - main content area: breadcrumb + page content + footer (env / version / 在线状态)
  - 响应式：sidebar < 1024px 自动 collapse；移动端忽略（不是 M5 范围）
  - 实施提示：复用 shadcn/ui 的 `Sidebar` + `Breadcrumb` 组件；React Router nested layout
- **M5-2 Dashboard `/` 页面**（**M5 核心**）：根路径 `/` 不再 redirect `/cases`，新建 `/dashboard` 落地 + `/` redirect 到 `/dashboard`
  - 4 个 KPI Card：Total cases by category (3 类柱图) / Recent runs (最近 7 天 daily count + pass/fail 比例) / BUG status pie (open vs fixed) / Extension stability (stable vs experimental vs awaiting_env)
  - 1 个 "Recent activity" 列：最近 10 个 run，每行 status badge + duration + click 跳详情
  - 1 个 "Quick actions" 横排：Run all bug_regression open / Run all extension stable / View skip_list / New case
  - 数据源：`GET /admin/categories` + `GET /cases` + `GET /runs` (用现有 endpoint，无新 backend 需求；如果聚合慢，M5-2 可加 `GET /admin/stats` 缓存端点，但先走客户端聚合)
- **M5-3 跨页关联**：
  - case detail 加 "Recent runs touching this case" 区块（查 `case_results.case_id = <id>` 最近 N 个）—— 需要新 backend endpoint `GET /cases/:id/recent-runs`
  - run detail 每行 case 加点击 → /cases/:id 跳转（已有 case_id 字段，前端加链接即可）
  - dashboard recent activity 点 run 跳 /runs/:id
- **M5-4 全局筛选 + URL 持久化**：
  - 抽 `FilterBar` 组件（category multi-select / status multi-select / tag autocomplete / time range picker）
  - `/cases` + `/runs` 都用同一份 `FilterBar`
  - 筛选状态 → URL query string (`?category=bug_regression,extension&status=open&since=7d`)，刷新页保留；分享链接他人可见同视图
  - 实施提示：React Router `useSearchParams` + custom hook `useFilters()`
- **M5-5 Quick Actions** (RunNewPage 重做)：
  - `/runs/new` 当前是 "所有 case checkbox + 全选" 太 raw
  - 重做为：上方 **preset 卡片区** (3 个常用：Run all bug_regression open / Run all extension stable / Run all by current filter) + 下方原 case checkbox 区作为 "advanced selection"
  - preset 卡片点击 = 自动填 case 列表 + 跳转 confirm 模态
  - sidebar 上有 "Run by category" 快捷下拉，从任意页面都能触发
- **M5-6 dogfood**：用户浏览器手动验整套新 UX；产物 `docs/m5-dogfood-<ts>.md` 记 6 路径走查 + 截图 + 修补 spec gap

**§14 R 预付检查**：
- **R2** Playwright contract test：新组件 (Sidebar / Dashboard / FilterBar / Preset card) 都加 `page.route()` mock 后端的 contract test
- **R4b 不硬编码 category**：dashboard KPI Card / 全局筛选 dropdown 全 `GET /admin/categories` 拉，**禁止** 写死 `[bug_regression, extension, external_systems]`
- **R26 dual-code-path**：M5-3 `GET /cases/:id/recent-runs` 新 endpoint 复用 `case_results` storage 模块，不再 inline SQL
- **R27 path config**：M5-2 dashboard 数据查询路径走 `client.ts` codegen，不要 inline fetch URL

**关键依赖图**:
```
M5-1 (Layout 重构) ──── 阻塞 ──→ M5-2 (Dashboard) ─── 阻塞 ──→ M5-6 (dogfood)
                                       ↑                            ↑
                                       │                            │
                                  M5-4 (FilterBar) ─────────────────┤
                                       ↑                            │
                                  M5-3 (跨页关联) ───────────────────┤
                                                                    │
                                  M5-5 (Quick Actions) ──────────────┘
```

M5-1 是 hard prerequisite (新 layout 影响所有 page)；M5-2 / M5-3 / M5-4 / M5-5 可 parallel（不同页面 / 不同组件）；M5-6 dogfood 末尾。

**完成定义**：
- M5-1 ~ M5-5 全 [x] + ci-gate 全绿
- M5-6 dogfood：用户浏览器手动验 → dashboard 显得出 / sidebar 工作 / 跨页跳转 OK / 全局筛选 URL 持久化 / preset 触发 run OK；产 `docs/m5-dogfood-<ts>.md`
- 不放过的细节：移动端不支持（明示）；旧 top nav 完全替换（不保留兼容）；CasesPage / RunsPage 必须接 `FilterBar` 替换 inline filter
- §0 changelog 主动 +0.1 (v1.11)

**M5 不做的事**（明示）：
- SSE 进度条（M6-1）
- Run 历史 diff（M6-3）
- Admin UI (skip_list / settings)（M6-4）
- artifacts download（M6-2）
- 移动端响应式
- 自定义 dashboard 布局（用户拖拽）—— 过度抽象，先固定 layout 跑一段

---

### 13.12 M6 运行体验深化计划（v1.10 内追加，2026-05-24）

**问题来源**：M5 解决前端"看"的体验，M6 解决"跑"和"管理"的体验。当前 `/runs/:id` 是 3s polling、`stdout/stderr` 没法下载、Admin 资源只能 SQL 直改、external_deps 字段写了 runner 不读。

**M6 任务**（按顺序，依赖图见末段）：

- **M6-1 SSE 进度条**：POST /runs 触发后，新 endpoint `GET /runs/:id/stream` (text/event-stream)，每个 step 完成立刻推 SSE event；前端 RunDetailPage 替换 3s polling 为 EventSource；终端事件 (run done / aborted) 关流
  - 实施提示：FastAPI 用 `StreamingResponse` + asyncio queue；前端 `EventSource` 原生 API；fallback 到 polling 如果 SSE fail
  - 注意：sql_pool 长连不能阻塞 SSE 写；orchestrator step 完成立刻 publish 事件到 in-memory broker
- **M6-2 artifacts download**：case_results 表加 `stdout_path` / `stderr_path` / `log_grep_path` 字段；runner 把每 step output 写到 `runs/<run_id>/<case_id>/<step_idx>/{stdout,stderr,log}.txt`；前端 RunDetailPage 每 step 行加 "Download" 按钮；新 endpoint `GET /runs/:run_id/cases/:case_id/steps/:idx/{stdout|stderr|log}` 返文件
- **M6-3 history diff**：新页面 `/runs/diff?a=<run_id>&b=<run_id>`，并排显示两次 run 的 case 状态变化（pass→fail / fail→pass / new case / removed case / duration diff > X%）；Dashboard 加 "Compare with previous run" 快捷链接
- **M6-4 Admin UI**：新页面 `/admin/skip-list` + `/admin/settings`
  - skip_list 在线 CRUD（add/remove case_id with reason）；后端 endpoint 已有 (M2+ work 占位)，本步真实现
  - settings：dev_db_url / cluster_topology 等运行时可调项；**不** 暴露 case_categories（设计层走 PR）
  - 加 `ADMIN_PASSWORD` 或 basic auth 防误改（不写 full auth，M6 只防 accident，user 是单人）
- **M6-5 external_deps runtime injection**（M4c 真跑通的前提）：
  - `external/<svc>.yml` 文件存储外部服务配置（host / port / credentials / extras）
  - case_normalizer 加 Jinja 渲染：`{{ external.hive.host }}` → 替换；`{{ external.hive.extras.principal }}` → 替换
  - orchestrator 调度时把 `external_deps` 列表里的 svc 配置加载注入 Jinja context
  - shell step `host: '{{ external.<svc>.host }}'` 真按渲染后 host SSH 路由（已用 jinja_render 的 decide_ssh_user）
  - 增强 case_normalizer 测试 + 加 1 个 e2e fixture
  - **§14 R26 dual-code-path 风险**：case_normalizer 与 jinja_render 必须共享 external context 加载逻辑
- **M6-6 dogfood**：用户实跑一例 external_systems case（M4c 第一例 + M6-5 渲染）；产 `docs/m6-dogfood-<ts>.md`；先决条件：集群上至少一个外部服务 (datalake / Hive / ES) 可达

**§14 R 预付检查**：
- **R26 dual-code-path** (M6-5)：external context 加载 / Jinja 渲染必须模块化共享，不要 inline 两份
- **R27 path config**：external/<svc>.yml 默认路径用绝对路径 or env var，不要相对路径地雷
- **R8 declaration-level skip** (M6-2)：artifacts download 测试如果 fixture 文件不存在，必须 `pytest.skip` 在 declaration 层级，不能 inline `if`
- **R28 intermittent sampling** (M6-6)：dogfood 跑 external_systems case 至少 3 次确认稳定

**关键依赖图**:
```
M6-1 (SSE) ────────────────────── 独立 ─────┐
M6-2 (artifacts) ─── 阻塞 ─→ M6-3 (history diff) ──┤
M6-4 (Admin UI) ─── 独立 ───────────────────┤
M6-5 (external_deps runtime) ─── 阻塞 ─→ M6-6 (dogfood) （需 M4c 已 done）
```

M6-1 / M6-2 / M6-4 / M6-5 可并行；M6-3 依赖 M6-2（diff 用 artifacts）；M6-6 末尾。

**完成定义**：
- M6-1 ~ M6-5 全 [x] + ci-gate 全绿
- M6-6 dogfood：至少 1 例 external_systems case (M4c-1) Try 跑通真集群 + SSE 进度条工作 + artifacts 下载可用 + Admin UI skip_list 改动持久；产 `docs/m6-dogfood-<ts>.md`
- §0 changelog 主动 +0.1 (v1.12)

**M6 不做的事**（明示）：
- M5 已交付的前端 UX（M6 不重做 sidebar / dashboard）
- 任何 case category 新增 / case YAML schema 改（§4.1 / §4.5 冻结）
- 完整身份认证（M6-4 只防 accident，user 单人模式）
- 大型 dashboard 自定义（M6-3 只做固定 diff 视图）

---

### 13.13 M7 LLM 接入计划（v1.13 内追加，2026-05-24）

**问题来源**: M3a-5 当时（2026-05-24 M3a sprint）决策 "LLM 接入复杂度阻塞主流程；M5 或单独 followup 再做真 LLM"——`/cases/new` 入口 A "从描述生成" 按钮目前是 stub，click 弹 toast `M3a-5 not yet wired — 请用 skill 路径（/add-test-case）或 Tab B 粘贴` (`CaseNewPage.tsx:140` `handleGenerateStub`)。skill 路径已 work（M3b done），但 web LLM 路径作为 §5.4 "LLM 解析模块" 设计层 spec 已写，未实现。本 sprint 真实现 §5.4，让不开 Claude Code 的用户也能用 web 完整流程。

**触发**: 用户 2026-05-24 PM 问 "/cases/new 从描述生成 现在可用么？" → 现状 stub 确认 → 用户决策**单列 M7**（option B）独立 milestone，不混入 M6。

**M7 任务（按顺序，依赖图见末段）**:

- **M7-1 backend endpoint `POST /cases/generate-draft`**（核心，§5.4 实现）
  - `backend/app/api/cases.py` 加新 endpoint
  - request: `{description: str, category?: str | None}`（category 可选，用户已选则 LLM 用对应 status_whitelist + id_prefix）
  - response: `{yaml_draft: str, attempts: int, validation_errors_during_retry: list[str]}`
  - 实现细节:
    - Anthropic SDK 调用 (`pip install anthropic`)
    - 模型: **claude-sonnet-4-6 (§5.4 spec 默认)** — sonnet 对 schema-bounded 输出已足够；opus-4-7 是 skill 路径（generator-only canonical 顺序更严）必需，web LLM 路径成本/性能 trade-off 选 sonnet。**待用户决策 D1 (见末尾)**
    - Prompt caching enable（schema + few-shot examples 放 cached prefix；§5.4 spec）
    - System prompt 含: §4.1 YAML schema 简版 + canonical 字段顺序 (§17.6) + status_whitelist (依据 category)
    - User prompt: 描述文本 + "请生成符合上述 schema 的 YAML"
    - 后端再做一次 yaml_loader.parse + case_normalizer.normalize_case 校验（**§14 R26**: 必须复用模块，不 inline 校验）；不通过则把错误塞回 prompt 重试 ≤2 次
    - 全部 attempt 失败 → return `{yaml_draft: "", attempts: 3, validation_errors_during_retry: [...]}` + HTTP 200（错误状态在 body，不 raise）
  - **§14 R 预付**: R26 复用 yaml_loader / case_normalizer / R27 ANTHROPIC_API_KEY env var documented in README / R29 reviewer 必须 disclose 是否真调过 Anthropic SDK (本机可能无 API key)

- **M7-2 prompt 设计 + few-shot examples**
  - 抽 3 个 representative cases 作 few-shot（hardcode 在 prompt module，**不**做 dynamic /admin/few-shot endpoint——过度抽象）:
    1. `lg-bug-0001-hashjoin-right-table` (BUG, 简单 GUC + SELECT 验证)
    2. `lg-ext-pgvector-ivfflat-basic` (extension, CREATE EXTENSION + INDEX + plan_contains)
    3. `lg-bug-0008-pax-toast-vacuum-analyze-crash` (跨 driver kind: sql + kind: shell psql -c，§4.1.2 实战)
  - 文件位置: `backend/app/api/llm_prompt.py` 或类似 module，便于后续维护
  - Examples drift management: hardcode；若 case 变 → followup PR 手动同步（drift 概率低，case 是 source of truth）
  - **§14 R 预付**: R4b prompt 不写死 category names 列表 (用 {{ALLOWED_CATEGORIES}} placeholder fill from /admin/categories at request time)

- **M7-3 frontend wire-up**
  - `CaseNewPage.tsx` `handleGenerateStub` 改成真 fetch
  - 状态机: idle → calling LLM (loading spinner) → loaded (draft 填到 main textarea + 用户必须勾 "确认草稿，进入 Validate" checkbox 才解锁 Validate 按钮) → error (panel 显示 retry attempts + validation errors)
  - **必须人工确认 gate** (§5.4 spec)：draft 显示后**不**自动 trigger Validate；用户勾确认 checkbox 才能继续 Validate → Try → Save 流程
  - data-testid: `btn-generate-real` / `confirm-draft-checkbox` / `llm-status-idle` / `llm-status-loading` / `llm-status-loaded` / `llm-status-error`
  - **§14 R 预付**: R6 data-testid 全 / R7 ErrorBoundary 不破坏 / R27 apiFetch 走 client.ts codegen

- **M7-4 tests**（与 M7-1/M7-2/M7-3 同 PR）
  - backend pytest:
    - mock `anthropic.Anthropic.messages.create` 验 happy path
    - 验 retry-on-invalid-YAML 链路（第 1 次返恶意 YAML / 第 2 次返合法）
    - 验 ≤2 次失败后 attempts=3 + validation_errors 列出
    - 验 ANTHROPIC_API_KEY 缺时 endpoint 返 503 + 明示
  - frontend vitest:
    - mock `apiFetch('/cases/generate-draft')` 各状态
    - 验状态机 4 阶段渲染 + 确认 checkbox gate

- **M7-5 dogfood**: 用户浏览器手验
  - 1 个真生成: 描述 "VACUUM 同时另一个会话 ALTER TABLE，集群卡死" → click "从描述生成" → 看 LLM 返 YAML draft → 勾确认 → Validate → Try → Save → PR auto-merge
  - 1 个 retry path: 描述故意让 LLM 编错 (e.g. "用 status: closed 这个状态") → 看 retry attempt + 最终通过 (LLM 改写) 或失败 (清晰错误信息)
  - 产 `docs/m7-dogfood-<ts>.md` 报告

**§14 R 预付清单**:
- **R26** dual-code-path: backend endpoint 复用 yaml_loader + case_normalizer；prompt validation 不 inline
- **R27** path config: ANTHROPIC_API_KEY env var + `README.md` "起本机 dev 服务" 章节加进必需 env 表
- **R4b** prompt 不硬编码 category：fetch /admin/categories at request time inject prompt
- **R6** data-testid 全 (6+ 新 testid)
- **R24** specialist 本地 ci-gate triplet
- **R29** reviewer 必须 disclose 本机是否真调 Anthropic SDK (依赖 API key)；若 SKIP → TENTATIVE_APPROVE (§14 R29 实战)
- **R30** 本 sprint 多个子步骤 (M7-1 backend / M7-3 frontend / M7-2 prompt) — 拆 PR or 同 PR？同 PR 因为 endpoint + prompt + frontend 是 contract-coupled，且每个组件 ≤1 novel mechanism (Anthropic SDK 是唯一 novel)；prompt module 不算 novel mechanism 是配置。R30 check 通过 = ≤1 novel = 同 PR OK

**依赖图**:
```
M7-1 (backend endpoint)  ∥  M7-2 (prompt + few-shot)
       ↓
M7-3 (frontend wire-up; 依赖 M7-1 contract finalize)
       ↓
M7-4 (tests; backend + frontend 同 PR inline)
       ↓
M7-5 (dogfood; user-driven 末尾)
```

M7-1 + M7-2 可 parallel（不同文件）；M7-3 依赖 M7-1 endpoint shape 定下；M7-4 与 M7-1/M7-2/M7-3 同 PR；M7-5 末尾 user。

**完成定义**:
- M7-1 ~ M7-4 全 [x] + ci-gate 全绿
- M7-5 dogfood: user 描述真生成 + retry path 验证 + 产 `docs/m7-dogfood-<ts>.md`
- §0 changelog 主动 +0.1 (v1.14) commemorate M7 done
- `CaseNewPage.tsx` `handleGenerateStub` rename to `handleGenerate` + 灰色 "V1 STUB" 提示去掉

**M7 不做的事**（明示）:
- streaming response (SSE 是 M6-1，不在本 sprint)
- multi-turn 对话（一次描述 → 一次 YAML draft；不做 iterative refine）
- prompt 版本管理 / A/B 测试（prompt 是 source code, 走 git 历史）
- 其它 LLM provider (OpenAI / DeepSeek)：仅 Anthropic
- ANTHROPIC_API_KEY 进 admin UI 或 system_settings 表（secrets 永远只走 env var；admin UI 一律不暴露）
- 5+ few-shot examples（3 个够覆盖 BUG / extension / cross-driver 3 类形态）

**待用户决策**（在 implementation PR 开之前需拍板）:
- **D1 model 选**: 默认推荐 **claude-sonnet-4-6** (§5.4 spec) — 便宜 + prompt caching 效果好；备选 claude-opus-4-7 (与 skill 路径一致，cost ~5x sonnet)；备选 env var `ANTHROPIC_MODEL` 配置化
- **D2 few-shot 来源**: 默认推荐 **hardcode 3 个 representative cases in `llm_prompt.py`**；备选 dynamic /admin/few-shot endpoint (M7 内 +1 endpoint，过度抽象)
- **D3 ANTHROPIC_API_KEY 管理**: 默认推荐 **env var only** + README 写；不接 admin UI / system_settings 表（secrets 永远 env var）

**M7 dispatch 提示**:
- 走 `scripts/dispatch-foreman.sh M7` (§14 R25, §14 R31 hardened)
- foreman 模型 opus；specialist M7-1 用 backend-fixer (opus per §8.1)；M7-2 prompt 写法可能反复调，先 backend-fixer 写初版；M7-3 frontend-fixer (sonnet)；M7-5 user-driven
- §14 R29-R32 4-gate 防御已 spec 化 (PR #101/#102)，foreman + reviewer + specialist 三方守门会拦下次 M5-1-like 失败链

---

#### 13.13.v1.25 amendment（2026-05-28，开工前最终化）

> 经 m6 sprint 真实多 PR 流水线验证 + 几条新规范沉淀后，对 2026-05-24 原计划补/改如下。**落地以本段为准**；原文保留以见演化。amendment 由 4 天后 (2026-05-28) 人/Claude 二次审产生。

**核心决策落定（D1 / D2 / D3 / H）**:
- **D1 = `claude-opus-4-7`**（**推翻 §5.4 早期默认 `claude-sonnet-4-6`**）—— 与 skill 路径已永久钉 opus 4.7 对齐（feedback_model_override_2026-05-24：skill 文件永久钉 `claude-opus-4-7`、禁 sonnet、CI lint 拦）。理由：web LLM 与 skill 干**同一件事**（描述 → schema-bounded YAML），项目已对该任务类别表态"质量 > 成本"；5x 价差在低频 dev tool 上月成本差 ~$15-30；opus 首次成功率更高 → retry 概率低 → 等效 token 成本接近。**§5.4 spec 同步刷新默认值**。不引入 `ANTHROPIC_MODEL` env 配置化（YAGNI）。
- **D2 = hardcode 3 例 in `backend/app/api/llm_prompt.py`**（plan 默认）；不做 dynamic `/admin/few-shot` endpoint。
- **D3 = `ANTHROPIC_API_KEY` env var only**；不进 admin UI / `system_settings` 表（secrets 永远 env var）；缺时 endpoint 返 503。
- **H = α foreman 串行派发 2 PR**（**user 决策 2026-05-28 修正：原 β 改 α**）：m7-backend → m7-frontend 两条 PR，foreman 串行派 specialist（不 `run_in_background`，"不飞起"）。**目的=补一次自动化流水线真实功能 sprint 端到端验证**（m6 是 6 PR 大样本、M7 是 2 PR 小样本，规模不同但都是真功能 sprint；β user-driven 跳过了 reviewer/foreman 派工链，验证密度不够）。**R30 stale-branch 风险**（specialist 分支早于上一 PR 合入时切出 → 夹带已合并 commits）**已在 m6d3t2 #193 实证 reviewer 能兜**（rebase --onto origin/main）；接受这一风险作为流水线压测的一部分。原文 1893-1896 "M7 dispatch 提示" 段（foreman 派 specialist）**保留并增强**——细节见下方"PR 走法（α foreman 串行）"段。

**必补项 A-G（全部纳入实施）**:

- **A. endpoint auth**：`POST /cases/generate-draft` **要求 Bearer auth**（v1.17+），**不**沿用 `/cases/{validate,try,submit}` 当前的开放姿态（核实 2026-05-28：那三个 endpoint 当前 routes 无 `Depends`、tests 不带 Bearer，即匿名可调）。理由：每次调用真实烧 Anthropic 配额，匿名 = 任意人能耗光配额。`/cases/{validate,try,submit}` 是否补 auth 是独立议题，**不**在本 sprint 范围。
- **B. size cap**：`description` 长度 **≤ 8 KB**（超出返 **413** + 明示）；Anthropic 调用 `max_tokens=2000`（防 LLM 失控吐 100K tokens）。
- **C. retry 语义分两类**：原 plan 只说"≤2 次重试"混了两种错。明确分开：
  - **(C-1) schema-invalid（attempt 输出过不了 yaml_loader + normalize）→ retry ≤2 次**，把上次的 validation error 串塞回下次 prompt（这是 plan 原意）。
  - **(C-2) Anthropic API 错（429 / 5xx / 网络 / 超时）→ 不重试、不进 retry quota**，立即失败按错误码上抛（见下"错误码细分"）。重试只会更烧配额。
- **D. retry feedback 必须 assert wiring**（覆盖 CLAUDE.md §2 "covers X 必须 assert"）：M7-4 backend pytest **必须**有一条 = mock 第 1 次返恶意 YAML、第 2 次返合法；**断言第 2 次的 `messages.create` 调用的 prompt body 里真包含上次的 validation error 串**（而非只测"retry 发生了"）。否则 LLM 重试拿不到信号 = 盲重试。
- **E. 注入两条近期规范到 system prompt**（在 §5.4 schema 简版之外**显式声明**，不能只靠 few-shot #3 例子推断）：
  - **(E-1)** 默认 `database: gpadmin` —— 2026-05-24 新规范：case YAML 未显式 database 时默认填 `gpadmin`（不是 `postgres`）。
  - **(E-2)** §4.1.2 psql -c 铁律 —— non-tx-safe DDL（`VACUUM` / `ANALYZE` 顶层 / `CREATE DATABASE` / `REINDEX CONCURRENTLY` 等）**绝禁** `kind: sql` 走 psycopg，**必须** `kind: shell + cmd: psql -c '<DDL>'`。
- **F. 可观测性 / 成本日志**：每次成功/失败调用 `logger.info` 落 `prompt_tokens / completion_tokens / latency_ms / retry_count / validation_errors_count / model`。**不**做持久化（KISS，需要审计时再说）。
- **G. Prompt caching 实现细节**：原 plan "enable" 没说怎么 enable。明确：**schema + few-shot 共同前缀**打 `cache_control: {"type": "ephemeral"}` marker；user `description` **不**缓存。注意 cache TTL 默认 **5 min**，dev tool 低流量场景命中率有限——定位为"省点是点"优化，不是承诺。

**错误码细分（与 C 配套，前端 error panel 据此分流文案）**:
| 情形 | HTTP 码 |
|---|---|
| `ANTHROPIC_API_KEY` 缺 | **503** |
| Anthropic 5xx | **502** |
| Anthropic 429（限流） | **429** 透传 |
| 网络 / 请求超时 | **504** |
| `description > 8 KB` | **413** |
| Bearer auth 缺 | **401** |
| 2 次 schema retry 均失败 | **200** + body `{yaml_draft:"", attempts:3, validation_errors_during_retry:[...]}`（plan 原设计保留——这是业务态，不是错） |

**M7-1 隐含一步（plan 漏写）**: 把 `anthropic` 加进 `backend/pyproject.toml` deps（当前未装，已核实 2026-05-28）。M7-prep 单列。

**M7-4 tests 追加项**（除原 plan 列表外）:
- backend pytest：**Bearer auth 缺时返 401** 的契约测；上面 C-1/C-2 各错误码的覆盖测；**D 的 retry-feedback-contains-error 必 assert**。
- frontend vitest：确认 checkbox 关时 Validate **真不可点**（不是仅视觉灰，要 assert click handler 不触发或按钮 `disabled` 属性）。

**M7 不做的事 追加**（除原 plan 已列）:
- "Regenerate（同描述）" 按钮（审 9. 🟢 I）—— 本期不做，需要时单独 PR。
- 错误文案精细化（区分"请稍后重试" vs "API key 未配"等）—— 错误码细分已就位，前端文案先落到最简：`generate 失败：HTTP <code> · <body.detail>`；UI 文案优化留后续。
- `/cases/{validate,try,submit}` 补 auth（与 A 关联但范围更大，独立议题）。

**PR 走法（α foreman 串行 2 PR，replace 原 1893-1896 段）**:
- **Sprint label** = `M7`，dispatch 入口 `scripts/dispatch-foreman.sh M7`（§14 R25 wrapper / R31 heartbeat 都已 hardened）。
- foreman 模型 **opus**；**串行派 2 个 specialist**（"不飞起"——禁 `run_in_background: true`，每个 item 全链 merged + smoke GO 后才派下一个）：

  | item | specialist | scope |
  |---|---|---|
  | **m7-backend** | backend-fixer (opus per §8.1) | M7-prep（`anthropic` → `pyproject.toml` + README env）+ M7-1（endpoint）+ M7-2（`llm_prompt.py`）+ backend pytest |
  | **m7-frontend** | frontend-fixer (sonnet per §8.1) | **依赖 m7-backend merge 后 `npm run gen:types`**；M7-3（CaseNewPage wire-up）+ frontend vitest |

- 每 item 走 review-pipeline v3 完整链（与 m6 sprint 同款，v1.24 验证过）：specialist 开 un-armed PR → reviewer 前置闸门（§14 R29 可声明 ANTHROPIC SDK SKIP 给 TENTATIVE_APPROVE，本机无 ANTHROPIC_API_KEY）→ foreman 武装 `gh pr merge --auto --squash` → CI gate → merge → **foreman 前台同步派 smoke**（v1.23 修法）→ 消费 GO → 下一 item。
- **R30 预案**：m7-frontend 分支极可能在 m7-backend 合入时刻之后才被切出，但 specialist 仍可能从陈旧 main 切（m6d3t2 实证）→ reviewer §14 R30 check 抓到 → fix specialist `rebase --onto origin/main` 恢复纯净 diff → 差分复审 APPROVE。**这一循环已知会发生且被验证修复**，不作 escalate。
- **M7-5 dogfood**：两个 PR 全合入 + smoke GO 后，user 浏览器手验（本机配 `ANTHROPIC_API_KEY` 真调 Anthropic），产 `docs/m7-dogfood-<ts>.md`。
- `docs/plans/M7.md` 作 **foreman 消费的 sprint plan**（`- [ ]` 清单 + specialist 角色注明 + 跨项硬约束 gen:types），不再是 user 个人 checklist。

---

### 13.14 M6 实战回顾（v1.14 内追加，2026-05-25 写入）

> 内容已归档（瘦身 design.md，2026-05-28）：完整实战回顾见 [`docs/milestone-retrospectives.md`](docs/milestone-retrospectives.md)。

### 13.15 简易用户登录模块（v1.17 内追加，2026-05-25 写入）

**触发**: 开发尾声前用户提："请帮设计一个简易的用户登录模块：(1) 初始账号 admin/admin；(2) 支持登录后修改密码"。M6-4 PR #115 的 `ADMIN_PASSWORD` env + `X-Admin-Password` header 模式被认作 placeholder，本 sprint 真做 single-user login。

**核心决策（设计前 user 拍板）**:

| 项 | 选择 | 理由 |
|---|---|---|
| 用户数 | 单 user (admin) | 单人项目，不做 multi-user / 角色 |
| 用户名 | 始终 admin | 不允许改用户名（简化）|
| 初始密码 | admin | UX 提示登录后第一时间改 |
| Token 类型 | 不透明 random 32-byte (sha256 存) | 单人 tool 不值得引 JWT；DB 泄漏不可立即 replay |
| Token 过期 | 永不过期，logout 才失效 | 多设备 OK；用户嫌严格可手动 logout |
| 改密码后旧 token | 不主动 invalidate | 简化；user 想严格则手动 logout 多设备 |
| 首次登录强制改密码 | 红条提醒，可忽略 | 不强制，但视觉提醒 |
| 忘记密码 | backend CLI snippet reset | 单人 tool，邮件重置过度设计 |
| 密码哈希 | bcrypt | 工业标准；passlib 弃用直接用 `bcrypt` 模块 |
| 替换 ADMIN_PASSWORD env | 删 | 旧机制 vestigial，新 auth 取代 |

**3 PR 链**:

| PR | 范围 | 文件数 |
|---|---|---|
| **#131 backend** | Alembic 0003 + users/auth_tokens model + auth.py endpoints + get_current_user dep + 替换 require_admin_password + 20 测试 | 9 |
| **#132 frontend login + guard** | LoginPage / lib/auth.ts / App.tsx RequireAuth / api/client.ts auto-Bearer + 401 redirect / Layout sidebar Logout + Logout 测试 + e2e seedAuth helper | 8 |
| **#133 change-password + 红条** | AdminChangePasswordPage / lib/auth.ts changePassword helper / Layout must_change_password banner / AdminPage 第 4 入口 | 8 |

**实战教训**:

(a) **passlib 1.7.4 vs bcrypt 5.x 不兼容** (PR #131 实战)：`passlib` 读 `bcrypt.__about__.__version__` 但 bcrypt 5.x 删了；fix = 直接用 `bcrypt` 模块（更简单，少一层）。**未来加 argon2 等算法时再考虑 wrapper**。

(b) **B008 noqa 反模式** (PR #131)：ruff `B008` 把 FastAPI 推荐的 `Depends(...)` 默认参数标 false positive；fix = 用 `typing.Annotated` 把 dependency type 化 (`CurrentUser = Annotated[User, Depends(get_current_user)]`)，参数变 type-only 没默认值，绕过 lint。**FastAPI 现代推荐做法**。

(c) **CI playwright e2e 找不到 selector** (PR #132)：新加 `<RequireAuth>` HOC 没 token 就 redirect /login → 5 个 e2e 测试访问 protected route 全失败。fix = `e2e/_helpers.ts` 新 `seedAuth(page)` helper (`page.addInitScript(localStorage.setItem)` + mock `/auth/me`)，3 spec 加 `test.beforeEach`. **教训**：加 frontend guard 时必须同步检查 e2e 是否依赖 protected route。

(d) **token 存 sha256 而非原文**：DB dump 不能即时 replay session。开发尾声单人项目本不严格需要，但成本几乎为 0（一行 `hashlib.sha256`），习惯比较好.

**完整 UX 闭环**:
```
1. 浏览器 → /dashboard → RequireAuth (no token) → Navigate /login?next=/dashboard
2. /login admin/admin → POST /auth/login → token 存 localStorage → Navigate /dashboard
3. Layout fetchMe (useEffect) → me.must_change_password=true → 顶部红条 "请改密码"
4. 点红条 / Admin → Change password → /admin/change-password → form 提交 →
   POST /auth/change-password → 1.5s setTimeout → window.location.reload
5. reload 后 Layout fetchMe → me.must_change_password=false → 红条消失 ✓
6. Logout → POST /auth/logout + clearAuthToken → Navigate /login
```

**Admin 页 4 入口** (v1.17 起定型):

| 入口 | 功能 |
|---|---|
| Skip list | 暂时禁用 case (可 until_date 自动过期) |
| External services | 浏览 `external/<svc>.yml` (read-only) |
| Delete case | 永久删 YAML (历史保留) |
| Change password | 修改当前用户密码 |

**忘记密码 CLI fallback**:

```bash
backend/.venv/bin/python -c "
from app.api.auth import hash_password
from app.storage import sqlite_store
from app.storage.models import User
from sqlalchemy import select
with sqlite_store.get_session() as sess:
    user = sess.scalar(select(User).where(User.username == 'admin'))
    user.password_hash = hash_password('admin')
    user.password_changed_at = None
    sess.commit()
print('reset to admin/admin')
"
```

**数字最终**：backend pytest 396→420 (+24) / frontend vitest 211→244 (+33) / merged PRs 130→133 (+3) / 600+ LOC.

**§14 R26 self-check (dual-code-path)**:
- `lib/auth.ts` 是 frontend 唯一 token 存取 source — apiFetch + Layout fetchMe + change-password 全走它
- `app/api/auth.py::get_current_user` 是 backend 唯一 auth dependency — admin.py 所有 mutation 共用
- 删除 ADMIN_PASSWORD env 后**不存在 dual auth path**（之前 `require_admin_password` 同时支持 env + header 两种，现在收敛到一种）

**§14 R30 self-check (≤1 novel mechanism per PR)**:
- PR #131: 1 mechanism = bcrypt password + opaque-token session (coherent backend unit)
- PR #132: 1 mechanism = RequireAuth + localStorage token + apiFetch auto-Bearer + 401 redirect (一个 frontend auth UX flow)
- PR #133: 1 mechanism = change-password UI + 红条 + 成功 reload (一个 password-mutation flow)

**未来 expansion path** (留 backlog，**不在本 sprint scope**):
- 多用户 + 角色 (需要重做 schema + dependency)
- OAuth / SSO (集成 GitHub / OIDC)
- Token expiry + refresh
- Rate limit on login endpoint (单人 tool 暂不需要)
- Password complexity policy (单人 tool 用户自管)

---

### 13.16 Release 流程（v1.18 内追加，2026-05-25 写入）

**问题**: v1.17 用户登录模块交付后 user 问 "RELEASE 流程？" — 发现仓库里只有 design.md §0 内部版本号 (v0.1 ~ v1.17，文档号)，从来没打过 git tag / GitHub release。开发尾声需要标记一个稳定版本作为回滚 anchor + 给将来"自从 v0.x 起这个 BUG 是不是引入的"提供基线。

**Release 性质** (单人项目实事求是):
- 不是发布到 PyPI / npm / Docker Hub
- 不是给外部用户分发 binary
- 是 **标记一个稳定 commit + 留可比较的 anchor** (`git tag` + GitHub Release page)

#### 13.16.1 版本号约定

| 阶段 | 版本 | 含义 |
|---|---|---|
| v0.x.0 (Pre-1.0) | 与 design.md 内部版本对齐 (e.g. design.md v1.17 → tag v0.17.0) | 单人 tool 还有迭代空间；不承诺 backward compat |
| v0.x.y (patch) | 同 minor + 小 bugfix | 跨 minor 不 maintain 旧 v0.x branch (单人项目不值得) |
| 未来 v1.0.0 | "公开 user 多人使用 + API 承诺稳定" 才升 | 暂不计划 |

**当前推荐**: `v0.17.0` (跟 design.md v1.17 对齐)。

#### 13.16.2 6 步 release 流程

```
[1] pre-release check
    ↓
[2] 决定版本号
    ↓
[3] 生成 RELEASE_NOTES_v<X>.md
    ↓
[4] git tag + push
    ↓
[5] gh release create
    ↓
[6] post-release sync (design.md / README 加 "v0.x.0 released")
```

##### Step 1 — Pre-release check

| 项 | 命令 | 期望 |
|---|---|---|
| working tree clean | `git status` | nothing to commit |
| main 同步远端 | `git pull origin main` | Already up to date |
| backend 全绿 | `cd backend && .venv/bin/python -m pytest -q` | 420+ passed |
| backend lint | `.venv/bin/ruff format --check . && .venv/bin/ruff check .` | clean |
| frontend tsc | `cd frontend && npx tsc --noEmit` | (no output) |
| frontend lint | `npm run lint` | clean |
| frontend vitest | `npx vitest run` | 244+ passed |
| design.md / README 最新 | 看 §0 顶部 / README 顶部 status 写的版本号是否就是要 release 的 | match |

任何一项不过 → 不打 tag (修完再来)。

##### Step 2 — 决定版本号

跟 design.md 内部版本对齐，例如内部 v1.17 → tag `v0.17.0`。除非本次 release 跨多个 minor (e.g. 攒了 v1.15 + v1.16 + v1.17 一起 release)，取最高的那个数字。

##### Step 3 — 生成 RELEASE_NOTES_v\<X\>.md

模板（写到 `/tmp/RELEASE_NOTES_v0.17.0.md` 或 `docs/release-notes/v0.17.0.md`）:

```markdown
## v0.17.0 — <一句话主题>

发布日期: YYYY-MM-DD

### 主要变化
- <从 design.md §0 changelog 抽 3-5 条 highest impact 的变化>

### 完整 milestone 状态
| Milestone | 状态 | §详情 |
|---|---|---|
| M0 项目骨架 | ✅ done | §18.M0 |
| M1 后端 MVP | ✅ done | §18.M1 |
| ... | | |

### Breaking changes / Migration notes
<列出与上次 release 比 break 的 API / config / behavior。第一次 release 写 "First release" 即可>

### 已知限制
- <e.g. M7 LLM 接入 stub，未真接入>
- <e.g. single-user 设计，多用户需 schema 重做>

### 完整变更
详 design.md §0 changelog (v0.1 ~ v1.17) + §18 milestones index。
```

**抽 highlights 原则**:
- 从 design.md §0 changelog 拉最近 5 个版本号摘要拼起来
- 重点 surface user-facing 变化 (新 UI / 新 endpoint / API break)
- 内部 refactor (e.g. "passlib → bcrypt") 放 changelog 不放 release highlights

##### Step 4 — git tag + push

```bash
git tag -a v0.17.0 -m "v0.17.0 — <主题> — design.md v1.17"
git push origin v0.17.0
```

**annotated tag** (`-a`) 不是 lightweight tag — 携带 message + author + date，可以 `git show v0.17.0` 看；GitHub release UI 依赖 annotated tag。

##### Step 5 — gh release create

```bash
GH_TOKEN=$(sed -n 's|https://[^:]*:\([^@]*\)@github.com.*|\1|p' ~/.git-credentials | head -1)
GH_TOKEN=$GH_TOKEN gh release create v0.17.0 \
  --title "v0.17.0 — <主题>" \
  --notes-file /tmp/RELEASE_NOTES_v0.17.0.md \
  --target main
```

- `--target main` 显式锁 main (默认推断，显式更稳)
- 不附 binary (源代码 release，GitHub 自动生成 tar.gz/zip)
- 不勾 prerelease (单人 tool 不需要 RC 流程)

##### Step 6 — Post-release sync

- design.md §0 顶部加一条注释 "Released as v0.17.0 (2026-05-25)" (或在 changelog row 末尾加)
- README 顶部 status 加 "Released as [v0.17.0](https://github.com/.../releases/tag/v0.17.0)"
- 用一个小 PR 提，命名 `docs: post-release v0.17.0 sync`

#### 13.16.3 不做的事 (明示)

| 不做 | 理由 |
|---|---|
| CHANGELOG.md 独立文件 | design.md §0 已经是 changelog，独立文件重复维护反而 drift |
| Auto-release on tag (GitHub Action) | 单人 tool 频率低 (~每月 1 次)，手动跑 6 步即可，自动化收益<维护成本 |
| 跨 minor backport (e.g. v0.16.1) | 单人 tool 永远只 maintain HEAD，前 minor 不修 |
| Binary asset (deb / rpm / docker) | 源码 release 足够，使用者本机 `python -m venv` + `npm install` |
| 公告通知 (邮件 / Slack / 飞书) | 单人项目不需要 |

#### 13.16.4 版本号回顾（开发完成时点的快照）

| design.md 内部版本 | 主题 | 对应 release tag (建议) |
|---|---|---|
| v0.1 ~ v0.9 | 设计文档迭代 | 无 release (pre-M0) |
| v1.0 ~ v1.3 | M0 starts → ci-gate 架构 | 无 release (in-flight) |
| v1.4 | M1 后端 MVP done | 无 release (continuous) |
| v1.5 ~ v1.6 | M2 前端 MVP + M3a/b plan | 无 release (continuous) |
| v1.7 ~ v1.9 | M3a/b done + M4a/b 5 BUG + 5 extension | 无 release (continuous) |
| v1.10 ~ v1.13 | external_systems + Roadmap 重构 + M5/M6/M7 plan | 无 release (continuous) |
| v1.14 | M6 sprint done | 无 release |
| v1.15 ~ v1.16 | post-M6 UX iteration wave 1+2 (DUT external_dut.yml / Admin 页 3→4 入口) | 无 release |
| **v1.17** | **简易用户登录模块 (auth sprint done)** | **首个 release: v0.17.0** ← 当前打 tag 点 |

→ **当前 main HEAD = v0.17.0 release 候选** (假设 design.md / README / 测试全过 step 1 pre-check)。

#### 13.16.5 与 §14 R 对照

- **R27** path config (env var defaults vs absolute paths): release notes 应该提醒用户从 fresh clone 跑 `bootstrap.sh` 而不是猜 cwd
- **R26** dual-code-path: release notes "Breaking changes" 段尤其要注意，例如 v1.17 删 ADMIN_PASSWORD env 是个潜在 breaking change，必须明示

### 13.17 target_versions registry（v1.19 内追加，2026-05-26 写入）

**问题**: `Trigger New Run → Target version` 是自由文本输入，用户可随意填（typo / 大小写不规范 / 历史遗忘的格式）。需要 admin 维护一个 catalog，让 NewRun 用下拉，Runs 列显示 + 搜索对齐到 catalog 里的 canonical 字符串。

#### 13.17.1 5 个决策（用户 2026-05-26 拍板）

| # | 决策 | 选 | 理由 |
|---|------|----|------|
| 1 | POST /runs 是否拒绝 catalog 外的字符串 | **不校验** | CLI / CI 脚本继续工作；UI 自约束足够 |
| 2 | 删除被历史 run 引用的 version 行为 | **默认拒绝（409 + run_count），可 ?force=true 硬删** | 历史 run.target_version 是 Text 非 FK，硬删后 stale 字符串不掉链子；但默认提示软删（is_active=false）保留 catalog 行 |
| 3 | `is_default` 数量约束 | **0 或 1（at-most-one，不强制）** | 首次安装可零；设第二行为 default 时 server 同 tx 清其他行 |
| 4 | display_order 维护方式 | **数字字段 admin 手填** | MVP；不做拖拽避免复杂度 |
| 5 | name 格式校验 | **无正则** | 未来可能有 hashdata-xx / cbdb-xx 等，硬正则会拦坑 |

#### 13.17.2 数据模型

新表 `target_versions`（alembic 0004，独立于 §4.x 现有表）：

```sql
CREATE TABLE target_versions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT    NOT NULL UNIQUE,
  display_order INTEGER NOT NULL DEFAULT 100,
  is_active     INTEGER NOT NULL DEFAULT 1,
  is_default    INTEGER NOT NULL DEFAULT 0,
  notes         TEXT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**同 migration 内 seed**：
```sql
INSERT INTO target_versions (name, display_order, is_active, is_default)
VALUES ('SynxDB-4.5.0-build130', 100, 1, 1);
```

`runs.target_version` 列**不动**（仍是 `Text | None`、无 FK 约束）—— 历史数据保留，新数据继续允许任意字符串（决策 #1）。

#### 13.17.3 API 契约

4 个 endpoint，`/admin/target-versions` 前缀：

| 方法 | 路径 | 权限 | 行为 |
|------|------|------|------|
| GET | `/admin/target-versions[?active=true]` | 公共读（与 /admin/categories 一致） | active=true 仅返 is_active 行；默认全返；排序 `display_order ASC, name ASC` |
| POST | `/admin/target-versions` | `Depends(get_current_user)` | body `{name, display_order?=100, is_active?=true, is_default?=false, notes?=null}` → 201；400 空 name；409 重名 |
| PATCH | `/admin/target-versions/{id}` | `Depends(get_current_user)` | body 任一字段子集 → 200；404；409 重名 |
| DELETE | `/admin/target-versions/{id}[?force=true]` | `Depends(get_current_user)` | 默认查 `SELECT COUNT(*) FROM runs WHERE target_version = name`，>0 且无 force → 409 含 `run_count`；204 成功 |

**`is_default` 互斥执行**: POST/PATCH 若设新行 `is_default=true`，service 层同 tx 跑 `UPDATE target_versions SET is_default = 0 WHERE id != <new>`。不靠 DB CHECK 约束。

`TargetVersionOut` 响应：`{id, name, display_order, is_active, is_default, notes, created_at}`。

#### 13.17.4 前端落地

| 文件 | 改动 |
|------|------|
| `frontend/src/routes/AdminTargetVersionsPage.tsx` | 新增 CRUD 表（add form + 行内 inline edit + active 复选 + default 单选 + 删除二次确认） |
| `frontend/src/routes/AdminPage.tsx` | 加第 5 个 link `/admin/target-versions` |
| `frontend/src/App.tsx` | 新 Route `/admin/target-versions` |
| `frontend/src/routes/RunNewPage.tsx` | `<input type="text">` → `<select>`；mount 时 GET `?active=true`；预选 `is_default=true` 行；保留 `— None —` 选项 → 仍允许提交 null |
| `frontend/src/routes/RunsPage.tsx` | 表行从 5 列 → 6 列加 Version 列；CSS grid-template-columns 同步 |
| `frontend/src/routes/RunsPage.test.tsx` | 加 Version 列断言；保留 search 含 version substring 的 regression 测试 |
| `frontend/src/api/types.ts` | **不手编**（OpenAPI 自动生成）；类型 inline 在消费 component |

**搜索 alignment**：RunsPage `target_version` 已纳入搜索 hay (RunsPage.tsx:89)；catalog 化后用户输入与下拉值对齐，substring 命中率提升。不需要改搜索逻辑。

#### 13.17.5 PR 拆分

| PR | 范围 | 文件 |
|----|------|------|
| PR-A `feat/target-versions-registry` | alembic 0004 + model + sqlite_store helpers + 4 endpoint + 后端测试 | `backend/alembic/versions/0004_target_versions.py` + `backend/app/storage/models.py` + `backend/app/storage/sqlite_store.py` + `backend/app/api/admin.py` + `backend/tests/test_admin_target_versions.py` |
| PR-B `feat/admin-target-versions-page` | admin CRUD UI | `frontend/src/routes/AdminTargetVersionsPage.tsx` + 本测试 + `AdminPage.tsx` + `App.tsx` |
| PR-C `feat/run-new-target-version-select` | NewRun 下拉 + Runs 列 + grid CSS | `frontend/src/routes/RunNewPage.tsx` + `RunsPage.tsx` + 本测试 + runs-page CSS |

3 PR 文件级零冲突，并行可 merge。frontend tests mock API，不依赖 PR-A 先 merge。

#### 13.17.6 与 §14 R 对照

- **R26** dual-code-path: API 契约 (TargetVersionOut shape) backend + 3 处 frontend 消费点必须形 1:1；TypeScript 仅在消费 component inline 局部类型（types.ts 自动生成不手编）
- **R27** path config: alembic 0004 落入 versions/ 目录与 0003 共用 `down_revision` 链；fresh clone 跑 `bootstrap.sh` 后自动包含 seed 行

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

**🟠 R22：`gh pr merge --auto` 在没 required status check 时不等 CI（v1.3 新增，M1 实战暴露）**
- 触发：本项目早期设计（§7.1 / §15.2.3 v1.3 前）刻意**不**对 main 加任何 branch protection；以为 "CI 红就不会绿，auto-merge 不会触发——逻辑上等价于强制"。实际 `gh pr merge --auto` 的 *"necessary requirements"* 来自 branch protection rules，**不是**来自"workflow 跑出 success"——没设 required check = 无 requirement = `--auto` 立即合，CI 是 post-merge advisory。
- 后果（M1 实战）：9 个 PR (#2~#10) 全部走"先 merge 后跑 CI"，PR #8 (M1-6 shell_driver) 同分钟被 created + merged，CI 在 3 秒后才首次跑出 failure；origin/main HEAD CI 红了 6 次但 PR 仍正常 squash-merge。
- 正确做法：main branch protection 加 **required status check = `ci-gate / gate`**（聚合 workflow，无 path filter，PR 必跑，详 §15.2.4）；不要走"多个 path-filtered workflow + 各自的 check 名"路线（GitHub 会卡在"等不存在的 check name" footgun，§15.2.3 v1.3 前担心的也是这个）。
- 来源：本项目 M1 forensic（commits 879e89f / d3f8821 / 3726b82 一系列 CI 红但已合并的 squash-merge）；GitHub `gh pr merge --auto` 文档隐含的 "necessary requirements" 语义。

**🟠 R23：GitHub branch-protection 的 required_status_checks `contexts` 用 check 的 `name` 不是 `workflow_name / job_name`（v1.3 新增，PR #11 实战暴露）**
- 触发：以为 GitHub Actions 跑出来的 check name 是 `<workflowName> / <jobName>`（看 PR UI 上确实显示成这样），把 branch-protection required check contexts 设成 `"ci-gate / gate"`。实际 GitHub Actions check_runs API 报告的 `name` 字段是**job 的 `name` 字段直出**（这里 = `gate`），所以 required check 永远不会被认为 satisfied，PR 永远 mergeStateStatus=BLOCKED 即便所有 check 都绿。
- 后果（PR #11 实战）：ci-gate 全绿 + PR mergeable=MERGEABLE + auto-merge armed，但 PR 8 分钟没 auto-merge。`gh pr view --json statusCheckRollup` 显示 check `name="gate"`，`gh api .../branches/main/protection/required_status_checks` 显示 contexts=["ci-gate / gate"] — 名字不匹配。改成 `["gate"]` 后 GitHub 立即重评估 + auto-merge 触发 squash-merge。
- 正确做法：required_status_checks contexts 用 **job 的 `name` 字段值**（如果 job 有 `name:` 字段；否则用 job id）。验证方法：跑一次 workflow，然后 `gh api repos/.../commits/<sha>/check-runs --jq '.check_runs[].name'` 取实际报告的 name 字符串去匹配。如果多 workflow 各自有同名 job，得用 `app_id` 字段消歧或更严格的 job 命名规范。
- 来源：本项目 2026-05-23 PR #11 实战 (commit 81e46ec)。PR UI 显示的 "ci-gate / gate" 是为了人类阅读拼出来的展示形式，**不是** API 里的 check name 实际值，是 footgun。

**🟠 R24：specialist agent commit + push 后不 open PR / 不跑本地 ci-gate 等价命令（v1.3 新增，M1 / M1-followup / M1-cleanup 反复踩坑）**
- 触发场景一：backend-fixer 改完代码 commit + push 分支但**不开 PR**，foreman 等着永远来不到的 merge 事件。M1-cleanup PR #22 真踩了——backend-fixer 推 `2d95576` 到 `refactor/yaml-loader-category-meta` 分支后 session 结束（理由不明），foreman 输出 "Continuing to wait on backend-fixer." 没收到 PR 就退；人手 `gh pr create` 才补上。
- 触发场景二：backend-fixer / frontend-fixer 改完代码 commit + push **不跑本地 ruff format / tsc / eslint**，依赖 ci-gate 远程发现——ci-gate 红 → foreman 多消耗一 round dispatch 修复 specialist → 修复 specialist 也犯同款错 → 同症状 fail 2 次 escalate。M1-followup F-3 PR #18 + M1-cleanup P0-A PR #22 **连续两次**栽在 `ruff format --check` 上，都靠人手补一个 trivial format commit 收尾。
- 正确做法：6-step PR contract 在 `.claude/agents/{backend-fixer,frontend-fixer,doc-writer}.md` 同步硬化两条：
  1. step 1 显式列出**本地 ci-gate 等价命令**（backend: `ruff check` + `ruff format --check` + `pytest -q`；frontend: `tsc --noEmit` + `npm run lint` + `npm test -- --run` + 可能的 playwright），**三者绿了才能 git commit**
  2. hard rule 加一条「**7 个 step 必须连续走完，commit+push 之后必须 open PR**，不要在 commit 之后假死或等下游事件——open PR 是 specialist 责任不是 foreman 责任」
- 来源：本项目 2026-05-23 ~ 2026-05-24 实测，M1-followup PR #18（commit `73acb0f`，ruff format 漏）+ M1-cleanup PR #22（commit `7ceda51`，ruff format 漏 + 无 PR 开两份病灶）。

**🟠 R25：foreman session 不返 final JSON 就 exit（v1.3 新增，M1-followup / M1-cleanup / M1-cleanup-p1 连续 3 次踩坑——spec 硬化未起效）**
- 触发：foreman dispatch specialist 后等响应，但因为 round budget tight / specialist 半路死 / 自己 idle 太久某种内部超时，**session 退出但没 print final JSON 到 stdout**。output 末尾留下一句中间态消息（如 "Continuing to wait on backend-fixer." 或 "PR #21 confirmed merged (gate=SUCCESS). Continuing to wait."）——非 JSON、非 final。
- 后果：下游（cron-fired reporter / 人手 reconciliation）必须 grep PR 列表 + git log + worktree 状态把 session 实际做了什么逆向重建，每次浪费 5-10 min 人工。
- spec 硬化无效（重要）：commit `126bba3` 给 `.claude/agents/foreman.md` 加 hard rule 8 + Loop step 8「EVERY exit path 必须 print final JSON to stdout」**5 分钟后** M1-cleanup-p1 session 启动，**仍然犯**——模型对自己 system prompt 里的新加规则不可靠遵守。这是 R25 之前以为是 spec 漏洞，**v1.3 后期承认是模型行为问题**。
- **mitigation（v1.3 内补，commit `<本节 commit>`，用户决策"option A 包装层"）**：新增 `scripts/dispatch-foreman.sh` wrapper：
  - 调度前 snapshot `origin/main` SHA + ISO ts
  - 跑 `claude --print --agent foreman ...` 捕获 stdout 到 `docs/foreman-runs/<sprint>-<ts>.log`
  - 调度后再 fetch + 跑 `gh pr list --state merged --search "merged:>=<start_ts>"` 列窗口内实际 merged PR + `git log <start_sha>..<end_sha>` 列窗口内 new commit
  - 尝试 best-effort 从 stdout 提 foreman 的 JSON（fenced ```json 块优先，balanced-brace 兜底）
  - 写 reconciled JSON 到 `docs/foreman-runs/<sprint>-<ts>.json` 含 `r25_violation: bool` + `verified_merged_prs_in_window` + `new_commits_on_main_in_window` + `foreman_self_report` (extracted JSON or null)
  - **caller parse 这份 wrapper JSON**，foreman 自己返不返 stdout JSON 不影响——R25 实际影响降到 0
- 正确使用：所有 foreman dispatch **都通过 wrapper**：`echo "<prompt>" | scripts/dispatch-foreman.sh <sprint-label> [--model opus|sonnet]`。foreman.md hard rule 8 / Loop step 8 保留作 model best-effort 指引，但不再依赖。
- 来源：本项目 2026-05-23 ~ 2026-05-24 实测，state.json 里 `last_failures.symptom_hash = "foreman:no-final-json-on-exit"` 各记一次（共 3 次）；wrapper option A 由用户 2026-05-24 决策选 A 后落地。

**🟠 R26：同一份输入存在两条代码路径，其中一条没测（v1.3 新增，M2 dogfood 连续暴露 2 次）**
- 触发：同样数据（YAML case）走 API 路径 vs CLI dogfood 脚本路径产生不同结果——一条路径有 `normalize_case` / `build_dsn_map` 等预处理，另一条没有。CLI 路径有 test_dogfood_script.py 覆盖 + 集群 smoke 验过 5/5 PASS，所以"功能没问题"成立；API 路径单测过 happy path 但**没拿同一份真实 YAML 走完一遍**，缺的预处理在 API 上变 silent error。
- 后果（M2 dogfood 实战 2026-05-24 真实代价）：
  - **第一次**: `_load_cases_from_disk` 漏 `normalize_case` → orchestrator `_step_id` 拿到 str instance 抛 `AttributeError: 'str' object has no attribute 'get'`，所有 case `status=error, duration_ms=0`。修：PR #42 抽 `case_normalizer.py` 共享模块两路都引用。
  - **第二次（同 sprint 内）**: API path `_execute_run` 调 `run_suite()` 漏 `sql_pool=` 参数 → orchestrator 显式吐 "sql step requires sql_pool to be configured"，所有 SQL step 1ms 假性 error，artifacts dir 创建了但空。修：PR #43 抽 `dsn_builder.py` + API 加 `SqlSessionPool(dsn_map_from_env(cases))` + `close_all()` finally 兜底。
- 正确做法：
  1. **共享 prep 模块**：normalize / DSN map / artifacts 路径解析等 "把 raw 数据转成 runner-ready 形态" 的步骤抽独立模块，**两条路径强制 import 同一份**，禁止 inline 复制。
  2. **integration test 覆盖 wiring**：API 路径必须有一份 test，喂一份 **真实 YAML**（不是 fixture mini-shape），断言 `_execute_run` 调 `run_suite` 时各参数 shape 正确（normalize 已跑过 / sql_pool 非 None）。`pytest -k api` 必须验 wiring，不是只验 happy path 响应码。
  3. **dogfood smoke 走两条路径**：M1 dogfood 5/5 PASS 走 CLI；下一次类似 milestone 收尾要**显式走 API + 浏览器一遍**。本项目 §13.5 (M2-10) 已加 "人类浏览器手动验" 一步，但 M1 时只跑 CLI——补 M1-followup 也跑一次 API smoke 会早 1 周抓到 #42/#43 bug。
- 来源：preflight 早期亦有类似（runner direct-exec 路径 vs scheduler dispatch 路径有功能漂移，scheduler 路径漏 step normalize），未细记；本项目 2026-05-24 M2-10 dogfood (`docs/m2-dogfood-2026-05-24-0535.md`) + 后续两 PR (#42 / #43) 实战。
- **R26 轻量变体（v1.7 新增，M3a-10 dogfood 暴露）**：frontend regex / 校验逻辑 vs backend parser 容忍度不一致也算同类——前端 `extractCaseId` `^id:` 严格 vs backend `yaml_loader.parse` 容忍 leading whitespace + BOM。**症状**：用户粘带 leading 2-space indent 的 YAML，validate + try 都过（backend parser 容忍），但 Save 在前端 regex 失败"missing id: field"——闸门顺序错位（应该 Validate 时挡，结果 Save 时挡）。**修法 1**（被采用，PR #57）：前端 regex 改成 `^[\s﻿]*id:` 与 backend parser 容忍度一致；**修法 2**（建议但未做）：抽一份 "input weirdness fixture"（leading whitespace / BOM / trailing newline / tab indent / 混合 indent）放共享 fixture，前后端各跑一份 reference test，verdict 不一致就 CI fail。**模式**：闸门顺序（input 经过 N 个校验层）必须**前层比后层更严**，否则用户感受混乱（早过晚挡）。R26 的核心是"复用 prep 模块"，这里复用的是"输入 normalization 语义"。来源：M3a-10 dogfood (`docs/m3a-dogfood-2026-05-24-1200.md` 暴露 spec gap 2)。

**🟠 R27：默认配置用相对路径，只在某 cwd 才工作（v1.3 新增，M2 dogfood debug 30 min 暴露）**
- 触发：`DEFAULT_CASES_ROOT = Path("cases")` / `DEFAULT_DATABASE_URL = "sqlite:///./data/runs.db"` 这类**相对路径默认值**——从 repo root 起 uvicorn 时 cases/ 跑不到 backend/data/ 又找不到；从 backend/ 起 cases/ 跑不到 backend/cases/（不存在）。两个相对路径互斥的 cwd 要求 = **没有一个 cwd 让两个 default 都工作**。
- 后果（M2 dogfood 实战 2026-05-24）：作者 dogfood 起 uvicorn 时第一次 cwd=backend → `/cases` API 返空（cases 找不到）；改 cwd=repo root → DB 报 `unable to open database file`（data/ 不存在）；最终只能 explicit override `CASES_ROOT=$repo/cases` + `DATABASE_URL=sqlite:///$repo/backend/data/runs.db` 才工作。**约 30 min 来回试错**才搞清楚冲突点。文档 / README 都没说必须这两个 env。
- 正确做法：
  1. **相对路径默认值用 `__file__` 锚到模块自身位置**（绝对路径）。例如 `DEFAULT_CASES_ROOT = (Path(__file__).resolve().parent.parent.parent / "cases")`（runner module → backend/ → repo root → cases/）。这样无论 cwd 在哪都解析到同一处。
  2. 或者**默认值用 user-config dir / XDG_DATA_HOME**（如 `~/.local/share/lightning-bug-regression/data/runs.db`），与项目源码解耦，开发 / 部署都一致。
  3. 若坚持相对路径（"开发期方便"），**README 显式列必须的 cwd + 必须的 env**，且 `app.main` 启动期 fail fast 验证 path resolve 到的目录存在（`if not _cases_root().is_dir(): logger.error("CASES_ROOT %s not found ...", _cases_root()); sys.exit(2)`），不要让 API 返空数据装作正常。
  4. 即便用 (3) 留相对路径作 fast-path，**生产部署 systemd unit / dockerfile 必须 explicit set 两个 env**，不要继承 cwd 偶然性。
- 来源：本项目 2026-05-24 dogfood 实测（`docs/m2-dogfood-2026-05-24-0535.md` 末尾 "踩到的两个 spec gap" 第 2 项原始记录）。

**🟠 R28：intermittent BUG 采样不足导致假阴性（v1.10 新增，M4a lg-bug-0009 反转 fixed→open 实战）**
- 触发：BUG 是 random / non-deterministic 触发（每次 ~30% 概率 fail），case 复现脚本里只跑 N 次（N 太小，如 3）。statistically 看不到 fail：N=3 + 命中率 30% → 全 PASS 概率 (0.7)³ ≈ 34%，假阳性 PASS 概率三分之一。CI / dogfood / reviewer 都看 "全绿" 写 `status: fixed`，bug 落 main 后 user 一跑就喊回。
- 后果（lg-bug-0009 §9.12 UNION ALL 行序错误，2026-05-24 实战）：V1 PR 用 3 rounds repetition 跑 → 本地 + dogfood + CI 全 PASS → 落 main + `status: fixed`。用户 review 立刻喊 "3 次会误判，改成 10 次"。改 10 rounds → round 1 立刻 fail → 反转 `status: open` + `fixed_version: ""` + notes 加 "Status reverted" 段落。第一例 user catch 比 reviewer / CI / dogfood 都早的案例。
- 正确做法：
  1. **默认 ≥10 rounds** 跑随机性触发的复现脚本（VALUES/UNION ALL 顺序 / hashjoin 选错 / lock contention / planner choice 等多解 BUG 类型）。
  2. **binary search 最低 N**：从 10 起，如果一直 fail 可降到 5/3/1（说明 100% 触发）；如果 10 rounds PASS 再加到 30/50 确认稳定（说明 <10% 触发，case 不够 sharp 需要 sharper trigger）。
  3. **在 case notes 写明**："intermittent 触发；N rounds 反映 X% 命中率" + "fix 前 reliably reproduce 在 ≥M rounds"，提供 reviewer 决策依据。
  4. **PR review checklist 加一项**："这是 intermittent 触发吗？rounds 是不是 ≥10？" reviewer 命中 BUG 修复类 PR 时主动问。
  5. **铁律 1 实战**：低重复跑 PASS 不能写 `status: fixed`——必须先证 fail 可复现，再证 fix 后不可复现。否则就是 "没验证就说完成"。
  6. **不要默认 N=1**：单次跑 BUG 复现脚本对 deterministic BUG 够用（hashjoin / unnest / planner 100% 触发），但对 random BUG 等于自欺欺人。case 作者要标 BUG 类型决定 N。
- 来源：lg-bug-0009 §9.12 V1 PR + V2 user-driven fix（PR #79 commit chain），user 主动 catch 比所有自动化都早；§13.9.5 详细分析。

**🟠 R29：reviewer agent 在本机测试 SKIP 时仍给 APPROVE（v1.12 新增，M5-1 PR #94 失败链实战）**
- 触发：reviewer agent 6-step protocol 跑 `npx tsc + npm run lint + npx vitest + npx playwright test` 本机；某些测试（典型：playwright e2e on libgbm-missing host）SKIP 而非 PASS；reviewer 报告把 SKIP 当 "不阻塞"（"R8 declaration-level skip 正确范式 → APPROVE"），但实际 reviewer 没真验证 e2e 行为。同时 ci-gate 还 IN_PROGRESS——reviewer 写了 "CI gate still IN_PROGRESS at verdict time. Foreman must confirm green before letting auto-merge proceed" 作为附注，但 verdict 仍是 APPROVE → foreman 看到 APPROVE 就放行 → CI 之后 fail。
- 后果（M5-1 PR #94 实战 2026-05-24 PM）：foreman dispatch frontend-fixer 写 sidebar Layout 含 useEffect + apiFetch + Tailwind 响应式 + shadcn shim 等多个 sus 新 pattern；reviewer 本机 vitest 92/92 PASS + playwright SKIP → APPROVE；CI 实跑 playwright 9/15 FAIL "element not found"；auto-merge 仍 BLOCK（mergeStateStatus BLOCKED 因 ci-gate FAIL）但 foreman state.json 不更新（详 R31），整 sprint 卡住 30+ min 直到 user 手动 kill+close PR+重写 minimal PR #95。
- 正确做法：
  1. **reviewer verdict 显式 disclose 哪些测试本机 SKIP 而非 PASS**——"playwright e2e SKIPPED here (libgbm missing); rely on ci-gate for browser-rendering verification"
  2. **如果任何测试 SKIP**，verdict **不能 APPROVE 当 ci-gate 还 IN_PROGRESS**——必须 REQUEST_CHANGES + comment "waiting for ci-gate playwright real run before APPROVE"，或显式标 verdict 为 "TENTATIVE_APPROVE (ci-gate pending)" 让 foreman 不放行
  3. **reviewer 6-step protocol 加 step 7 "ci-gate readiness check"**：若 ci-gate 状态 IN_PROGRESS 或 FAILURE，verdict 自动 downgrade
  4. 设计层：`.claude/agents/reviewer.md` 加规则 "**任何**关键测试 SKIP 时禁止 APPROVE while CI is IN_PROGRESS"（关键测试 = playwright e2e / 后端 pytest 主路径）；只允许 declaration-level SKIP **且**已被同等 ci-gate 真跑覆盖时才放行
- 来源：M5-1 PR #94 实战 2026-05-24 PM（commit `a230fb4`，9 playwright e2e fail）；user 决策 kill foreman + close PR + 重写 minimal PR #95 直接绿。reviewer 的 APPROVE 是 false-negative 的主因之一。

**🟠 R30：specialist 一次提交多个 sus 新 pattern 导致 CI 失败无法 binary search（v1.12 新增，M5-1 PR #94 实战）**
- 触发：specialist 写新组件时把"看起来有用"的多个 novel pattern 一次性塞进 PR：响应式 Tailwind 类（`lg:inline hidden` / `w-14 lg:w-60`） + useEffect 内 apiFetch (mount fetch race) + 引用未安装的 shadcn primitive 用 Tailwind 拼凑 + `import.meta.env.VITE_APP_VERSION` 访问 + 复杂 NavItem disabled 状态机——任何一个出问题，CI fail 但日志不指明 root cause（"element not found" only），specialist / reviewer / 你都难以从 log 定位是 N 个 sus 之中哪几个。
- 后果（M5-1 PR #94 实战）：9 playwright e2e 都 `getByTestId(...).toBeVisible()` fail。可疑变量至少 4 个：Tailwind 响应式 generation / Vite dev server 路由 / apiFetch mount race / shadcn 缺失 shim。本地 vitest 92/92 PASS（jsdom 不 layout），无法复现。CI artifact 不上传（详 R32），无 screenshot 可看。**结果**：debug-from-log 无解 → user 决策 close PR + 重写 **minimal**（Layout.tsx 删 useEffect / 删响应式 / 删 shadcn shim / 删 import.meta.env / 用 plain CSS） → PR #95 第一次 ci-gate 绿。**Pattern**: minimal-first 把变量降到 1 个 → 后续 PR 增量加 feature 每个 PR ≤1 个 sus。
- 正确做法：
  1. **新组件 PR 走 minimal-first**：核心 contract（data-testid / 主结构）一次实现，**禁止**同时引入 N>1 个 novel pattern；feature 加在后续 PR 每 PR ≤1 个 sus
  2. **响应式 / mount fetch / 新依赖 / env 访问 等都算 sus pattern**——单独 PR 加每一个，前后测试 baseline 易对账
  3. **specialist 自查清单**："这个 PR 我引入了几个新机制？" >1 → 拆 PR
  4. **reviewer 也要查这条**：cross-check PR diff，>1 个新 mechanism 标 R30 violation + REQUEST_CHANGES 让 specialist 拆
- 来源：M5-1 PR #94 → PR #95 重写对比；PR #95 minimal sidebar (Layout.tsx 1 个 sus = "用 plain CSS 替换 Tailwind 响应式") 直接绿。

**🟠 R31：foreman 在 PR ci-gate 失败时不更新 state.json，未 escalate（v1.12 新增，M5-1 PR #94 实战）**
- 触发：foreman dispatch specialist → specialist 开 PR → PR 触发 ci-gate → ci-gate FAIL → foreman state.json `last_heartbeat` 不更新，`item_in_progress.pr_state` 一直 "dispatching"，`last_failures` 空，`needs_human` 空。foreman 进程仍 alive (`ps` 显示 idle in `ep_pol`)，但没 react ci-gate FAIL。结果：user 通过 /loop 检查 30+ min 后才发现 foreman 没动作。
- 后果（M5-1 PR #94 实战）：foreman 跑 ~37 min（被 user SIGTERM 时 elapsed_seconds=2247），全程没 react PR #94 CI fail 状态；最终 wrapper 写 `r25_violation: true / foreman_returned_final_json: false`，foreman 完全 silent fail。user 损失：~30 min wait + lost confidence in autonomous mode。
- 正确做法：
  1. **foreman.md hard rule 11**：verify_loop 每 round（≤5 min 间隔）必须 `gh pr view <pr> --json statusCheckRollup` 检查 ci-gate；若 FAILURE 持续 >2 round 且未触发 fixer dispatch → 写 needs_human entry + 立即停（同 R25 R-similar）
  2. **state.json `last_heartbeat` 强制每 round update**——即便 "no action needed"，时间戳必须前进，否则 wrapper 把 foreman 判 stuck
  3. **wrapper option B**：检测 foreman state.json 30 min 不更新 → 自动 SIGTERM foreman + 触发 needs_human 报告（当前 wrapper 仅 R25 post-hoc reconciliation，不主动 SIGTERM）
  4. **interim**: user-facing/loop wakeup prompt 加一项 "if state.json last_heartbeat > 10 min stale → escalate to user"（已 informal 实践，正式入档）
- 来源：M5-1 PR #94 失败链 2026-05-24 PM；foreman PID 607552 跑 29 min 后 state.json 还是 start time；user 通过 /loop wakeup 检查发现，决策 kill。

**🟠 R32：CI playwright 测试失败无 artifact 上传 → 失败诊断从 log 不可能（v1.12 新增，M5-1 PR #94 实战；中级）**
- 触发：ci-gate.yml 跑 `npx playwright test` 在 chromium；e2e fail；failure mode "element not found" only 在 log 里，**没有** screenshot / DOM snapshot / playwright trace 上传为 GitHub Actions artifact；ci-gate.yml 没 `actions/upload-artifact@v4` step。
- 后果（M5-1 PR #94 实战）：reviewer 本机 SKIP playwright（详 R29），无法本地复现；user 想看 CI 实际 DOM → `gh run download` returns "no valid artifacts found to download"。debug 完全靠读 log 行号 + 反推 React 渲染——但 jsdom 单测 PASS, chromium fail，本质是布局 / 响应式 / 时序问题，log 完全看不出。
- 正确做法：
  1. **ci-gate.yml playwright e2e step 后加 `actions/upload-artifact@v4 if: failure()` 上传 `frontend/test-results/`** —— playwright 失败默认生成 screenshot + trace.zip；7-day retention
  2. **playwright.config.ts 加 `use.trace: 'retain-on-failure'`** + `use.screenshot: 'only-on-failure'` 默认开启
  3. 现成 fix 量极小（~10 line YAML + 2 line config），但失败时价值巨大——M5-1 PR #94 失败链 30+ min 诊断如果有 screenshot 5 min 内能定位
  4. 优先级：next playwright-touching PR 顺手加；如不顺手，单 doc PR 加
- 来源：M5-1 PR #94 失败诊断 2026-05-24 PM；`gh run download 26361285322` 返 "no valid artifacts found"。

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
   - 长任务用 run_in_background: true 不阻塞主 loop——**仅当还有并行活、之后再回收**。**smoke-runner 是终态门，例外：前台同步派**（hard rule 5 / step 6.a：`--print` 模式下后台终态门会 orphan 子 agent + 丢 final JSON）。
   - **specialist 开 PR 后返回 `open-awaiting-review`，NOT 自己武装 auto-merge**（review-pipeline v3）。
3.5 **派 reviewer（merge 前置闸门，review-pipeline v3）**：specialist 开 PR 后 dispatch reviewer（只读，无 worktree）跑 §14 + 6 域。verdict：REQUEST_CHANGES/REJECT → 不武装，派 fix（回 3.5）；APPROVE/TENTATIVE_APPROVE → **foreman** `gh pr merge <pr> --auto --squash` 武装。写 state.json `reviewer_verdict`。（CC 内置 /review 用户手动调，不在此环——subagent 调内置 review 撞嵌套死结，§0 v1.22。）
4. 收回结果，evaluate honestly：
   - "backend-fixer 说 pytest 通过" ≠ 证据。reviewer 实跑 pytest = 证据。
   - smoke-runner 给"GO" = 证据；"看起来 OK" ≠ 证据。
   - 任何歧义当未完成。
5. 决定下一步：
   - 通过（reviewer APPROVE + CI SUCCESS + merged）→ **派 smoke-runner（前台同步，merge 后验收，review-pipeline v3）** → **GO** 才标该项 done；**NO-GO** → `git show <squash-sha> --stat` 核对文件清单 == 该 PR 预期范围（§5.5 实测约束：squash 混了无关文件会被全删）→ 干净则 `git revert` 开 revert PR，不干净则 escalate。写 state.json `smoke_verdict`；回 step 1。
   - 失败，且原因明确 → 派**修复**的 specialist（不是再派同一个），具体修法写进 prompt。
   - **同症状连续 fail 2 次** → STOP + escalate（写 needs_human 项进 state.json，下次 reporter 触发时上报）。
   - 失败原因是"集群未就绪 / 凭据缺 / 飞书原文缺" → STOP + escalate（不重试，等你修环境）。
6. Stop 条件：
   - 清单空 → DONE；写 final report；session 退出。
   - 触发 escalate → BLOCKED-ESCALATE；写 state.json + handoff doc；session 退出。
   - budget 用尽（10 round 或壁钟 2h，取先到者） → BUDGET-EXHAUSTED；写 partial progress；session 退出。
7. 任何 stop 都必须写 state.json + handoff doc，然后退出 session。reporter 会从 state.json 拼下次汇报。
8. **ALWAYS print 最终 JSON 到 stdout 作为最后一个动作**，不论 stop 条件是哪种——见 hard rule 8 + §14 R25。即使是 mid-flight 假死（"在等 specialist 但 specialist 没回来"），也要 print 带 `status="blocked-escalate"` + `last_failures` 解释的 partial-progress JSON。
```

#### 15.1.2 foreman 硬规则

| # | 规则 | 来源 |
|---|------|------|
| 1 | **Never edit code, never run smoke**——foreman 只 dispatch | preflight foreman.md §"You do not implement, test, or document anything yourself" |
| 2 | **Never claim success without evidence**——必须看到 reviewer / smoke / pytest 实际跑过的输出 | preflight foreman.md §"Hard rules" |
| 3 | **Never commit**——commit 由 specialist 在自己 worktree 里完成 | preflight foreman.md §"Hard rules" |
| 4 | **同症状 fail 2 次立即停**——不要第 3 次（preflight 是 2 次即停，用户决策一致） | preflight foreman.md §"Never run the same failing dispatch twice" |
| 5 | **长任务用 run_in_background 不在前台阻塞——仅当有并行活、之后再回收**。**终态门（merge 后 smoke）例外:前台同步派**(`--print` 一次性进程没 event loop await 后台子 agent,终态背景化 = orphan 子 agent + 丢 final JSON;smoke-pipeline-test 2026-05-28 实测 r25_violation) | preflight foreman.md §"Time-consuming calls go to background" + 2026-05-28 修正 |
| 6 | **状态每 round 落地**——写 `docs/status/foreman-state.json`，reporter 离线可读 | 本项目新增 |
| 7 | **budget = 10 round 或 2h**——用户 v1.0 决策 | 本项目新增（preflight 是 10 round） |
| 8 | **EVERY exit path 必须 print final JSON 到 stdout 作为最后一个动作**——DONE / BLOCKED-ESCALATE / BUDGET-EXHAUSTED / mid-flight bail 都不例外。state.json 写盘**不算替代**：caller (cron / 人手 / 上层 foreman) parse 的是 stdout JSON。本项目新增 §14 R25，M1-followup + M1-cleanup 2 次踩坑 |
| 9 | **检查 specialist 6-step contract 完整性**——commit + push 但没 `gh pr create` 的 specialist 算未完成，需要 foreman 补救（开 PR 是允许的 recovery action，与 hard rule 3 "Never commit" 不冲突——后者管 code commit）。本项目新增 §14 R24 |

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

每个 fixer / doc-writer agent 完成代码后**必须**做 6 件事，缺一不可（**v1.3 内补 step 0**——2026-05-23 M0 step 9 dry-run 实测发现 doc-writer 直接 `git push -u origin HEAD` 在 main 上跑就是直推 main，绕过 PR 闸门；root cause = worktree 创建时 HEAD 是 main，agent 必须显式 checkout 分支）：

```bash
# 0. 起分支（worktree HEAD 默认是 main，必须先切到 feature branch；
#    否则后面 push -u origin HEAD 等于直推 main，PR + auto-merge 全绕过）
git checkout -b <feat|fix|docs>/<id>-<slug>   # 例：fix/m1-4-shell-driver-timeout

# 1. 写代码 + 测试 + 跑本地 ci-gate 等价命令（**v1.3 后期硬化**——见 §14 R24）：
#       backend:  ruff check . && ruff format --check . && pytest -q
#       frontend: tsc --noEmit && npm run lint && npm test -- --run
#    三者绿了才能进 step 2。pushing red 让 ci-gate 远程发现 → foreman 多消耗
#    一 round dispatch 修复——M1-followup PR #18 + M1-cleanup PR #22 连续两次
#    都栽在 `ruff format --check`，都靠人手补 trivial format commit 收尾。

# 2. 在 worktree 里 commit（**不**加 Co-Authored-By Claude，参考全局规范）
git add <changed>
git commit -m "<conventional commit message>"

# 3. push 分支
git push -u origin HEAD

# 4. 开 PR
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

# 5. 给 PR 设 auto-merge（CI 全绿后 GitHub 自动 squash merge）
gh pr merge --auto --squash

# 6. 返回给 foreman 一个 JSON：
#    {"pr_number": 13, "pr_url": "...", "branch": "feat/...", "status": "open-auto-merge-armed"}
```

**关键**：第 5 步设了 auto-merge 后 specialist **立即返回**，不要等 CI。CI 跑 ~5-25 min，等的话拖住 foreman loop。foreman 在下一 round 才轮询 PR 状态。

**v1.3 step 0 教训**（2026-05-23 M0-validate dry-run）：doc-writer round 1 跳过 step 0，直推 main 为 commit `4db14d7`。foreman 自动 recover：lease-protected force-push 撤回 main → 重 dispatch doc-writer + 显式步骤 → PR #1 走完 squash auto-merge（`14136da`）。`last_failures[]` 记一条 `doc-writer:direct-push-to-main-no-pr` symptom；spec gap 已修（`.claude/agents/{backend-fixer,frontend-fixer,doc-writer}.md` 全部补 step 0）。

**v1.3 后期 step 1 + 全 7 步连续硬化教训**（2026-05-23 ~ 2026-05-24 M1-followup + M1-cleanup）：(1) backend-fixer 在 PR #18 (F-3) + PR #22 (P0-A) **两次**栽在 `ruff format --check`——commit 前没跑本地 format check；(2) PR #22 backend-fixer 推 `2d95576` 后 session 结束没开 PR，foreman 等 PR 没等到自己也退出。fix：step 1 显式列**本地 ci-gate 等价命令**列表（backend = ruff×2 + pytest，frontend = tsc + lint + vitest），三者绿了才能进 step 2；agent.md hard rule 加"7 个 step 必须连续走完，commit + push 之后必须 open PR，不要 commit 完假死"。详 §14 R24。

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
Settings → Branches → Branch protection rules (main):
  ✅ Require status checks to pass before merging
     Required check = "ci-gate / gate"（聚合 workflow，详 §15.2.4 v1.3 修订）
Settings → Actions → General:
  ✅ Read and write permissions
  ✅ Allow GitHub Actions to create and approve pull requests
```

#### 15.2.4 auto-merge 真正的 gating 模型（v1.3 修订，M1 实战暴露）

**v0.5~v1.3 早期错误假设**：v0.5 §7.2 / R3 写"all test jobs are gates，CI 红就不会绿，auto-merge 不会触发——逻辑上等价于强制"，因此 §7.1 + §15.2.3 早期版本明确写**不**对 main 加任何保护规则。

**M1 实战打脸（2026-05-23 step 8 后）**：`gh pr merge --auto --squash` 的实际行为是 *"merge after **necessary requirements** are met"*——这里 *necessary requirements* 来自 branch protection rules，**不是**来自"workflow 跑出 success"。没设 required status check = 无 requirement = `--auto` 立即合（实测 PR #8 M1-6 shell_driver 在 15:29:18 同分钟被 created 与 merged，CI 在 15:29:21 才首次报告 failure；M1 共 9 个 PR 全部走的是这条"先合后跑 CI"路径）。

**v1.3 修订路径**（commit XXX，待 phase-1 push 后回填）：

1. 新增 `.github/workflows/ci-gate.yml` 聚合 workflow——单 job `gate`，**不带 workflow 级 path filter**（每个 PR 都会跑），内部用 `dorny/paths-filter@v3` 按 backend / frontend / agents 各自的 path 条件跑对应的 check step；docs-only PR 走到 final `gate ok` step 直接 pass。
2. 删 `.github/workflows/{backend,frontend,agents-lint}.yml` 三个旧 workflow——功能全被 ci-gate.yml 吸收（init-guard pattern 保留，搬到 ci-gate.yml 的 step 内）。
3. main branch protection 加 required check = **`ci-gate / gate`** 一项（单 check，单 workflow，无 "等不存在的 check name" footgun）。
4. 工作流：specialist 设 `gh pr merge --auto --squash` → ci-gate 在 PR head 跑 → 通过则 GitHub 触发 squash-merge → 没通过则 PR 卡 open / foreman 下 round 看到 statusCheckRollup=FAILURE 并 dispatch fix specialist（§15.2.2 流程不变）。

**对 §14 的影响**：R22 新增「auto-merge 在没有 required status check 时不等 CI」（v1.3，M1 实战 forensic）。**对 reviewer 的影响**：reviewer.md 不变——本地实跑 + 6 域 / §14 cross-reference 仍是 second line of defense；ci-gate 是 GitHub-side gate，reviewer 是 logic-side gate，二者互补不替代。

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

---

## 16. 测试门类 case_categories（v1.11 PR-A1，canonical）

> **本章是 case_categories 设计的 canonical reference**——汇总原 §4.5 (元数据表)、§13.3 (扩门类标准流程)、各 category schema 特化、external_systems M4c plan 引用 等所有 case-category 相关设计。原 §4.5 / §13.3 stub 指向这里。

### 16.0 设计原则（§14 R4b "category 不写死多处"的实现）

`case_categories` 是 v0.8 引入的关键扩展点。**核心约束**：业务代码（schema 校验 / 前端 tab / skill 对齐题 / 目录扫描）**不许写死 category 名称**——全部从 DB 表读，加新门类 = 1 个 Alembic seed migration + 1 个空目录，**零业务代码改动**（§14 R4b 反模式从设计层杜绝）。

**v1.10 实战印证**（M4 sprint）：external_systems 落地 PR #88 实测——backend cases.py 用 `for cat in categories: cat_dir = root / cat.dir_path` 自动扫；CasesPage.tsx 用 `status_whitelist.indexOf(status)` 自动给徽章配色；CategoryOut.name 是 `string` 不是 enum，前端 codegen 无需 regenerate。整 PR ~75 行（迁移 + 空 dir + 1 行 skill prefix + fixture 数字 2→3），**业务代码零行改动**。

### 16.1 case_categories 元数据表 schema

```sql
CREATE TABLE case_categories (
  name TEXT PRIMARY KEY,                 -- 系统识别符 (snake_case)：bug_regression / extension / external_systems
  display_name TEXT NOT NULL,            -- 中文显示名（前端看板用）
  description TEXT,                      -- 一句话说明本门类做什么
  id_prefix TEXT NOT NULL UNIQUE,        -- case id 必须以此开头：lg-bug- / lg-ext- / lg-xs-
  dir_path TEXT NOT NULL UNIQUE,         -- cases/ 下子目录：bug-regression / extension / external-systems
  status_whitelist TEXT NOT NULL,        -- JSON 数组，按 category 不同
  default_status TEXT NOT NULL,          -- skill 默认值
  display_order INTEGER DEFAULT 100,     -- 看板 tab 排序
  is_active BOOLEAN DEFAULT 1,           -- 暂时下线某门类（不删表项）
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  created_by TEXT
);
```

**seed (Alembic 0001 + 0002)**：3 行（bug_regression / extension / external_systems），详见 §16.2-16.4 每类的字段值。

**消费点**：

| 消费方 | 用法 |
|---|---|
| YAML schema 校验 (`yaml_loader.py`) | 启动时把 `case_categories` 全表 load；校验 case 按 category 查白名单 (id_prefix / status_whitelist / dir_path) |
| 前端看板 `/cases` tab | `GET /admin/categories` → 按 `display_order` 渲染 tab，**不写死任何 category 名** |
| skill `add-test-case` 对齐题首题 | grounding 时拉 `GET /admin/categories`，`name` 列表当选项，`display_name` 给用户看 |
| 目录扫描器 | 启动按 `dir_path` 列表扫盘，发现 case 不在已知 dir 下 → 校验失败 |

**不暴露 Admin UI 编辑**：`case_categories` 是**设计层**配置，改它意味着新设计动作（决定门类语义、status 词汇、目录归属），**必须走 PR + design review**。与 §4.4 `system_settings`（运维层、Admin UI 可改）形成对比。

### 16.2 bug_regression — 历史 BUG 复现 / 修复验证

| 字段 | 值 |
|---|---|
| name | `bug_regression` |
| display_name | BUG 回归 |
| id_prefix | `lg-bug-` |
| dir_path | `bug-regression` |
| status_whitelist | `[open, fixed, wontfix, stub]` |
| default_status | `open` |
| display_order | 10 |

**status 语义**：
- `open` — BUG 复现仍 fail，未修复
- `fixed` — 当前 build 已不复现（`source.fixed_version` 必填）
- `wontfix` — 设计决策不修
- `stub` — 占位（`steps:` 必为空）

**已有 cases 概览**（截至 v1.11）：
- 原 5 例 (PR #47 status 改 fixed)：lg-bug-0001 hashjoin / 0002 unnest / 0003 ANALYZE / 0004 CTAS / 0005 LC_CTYPE upper
- M4a 飞书 3 例：lg-bug-0007 §9.7 orca-sort (#70 fixed) + lg-bug-0008 §9.11 pax-toast (#74/#80 fixed) + lg-bug-0009 §9.12 union-all (#79 **open**，§14 R28 intermittent 实战)
- M3a dogfood 副产 1 例：lg-bug-0006-m3a-dogfood-smoke

**case 作者约定**（M4a 实战确立）:
- 来源飞书 BUG → `source.feishu_anchor` 填章节号 (`"section-9.7-..."`)
- `source.reported_at` / `fixed_version` 必填（status=fixed 时）
- `notes` 段记 "Verified upstream-fixed on SynxDB-X.Y.Z" 作客观证据
- **intermittent BUG（§14 R28）**：在 case `notes` 写 "N rounds 反映 X% 命中率" 给 reviewer 决策依据；默认 ≥10 rounds

### 16.3 extension — PG 周边扩展集成测试

| 字段 | 值 |
|---|---|
| name | `extension` |
| display_name | Extension 集成测试 |
| id_prefix | `lg-ext-` |
| dir_path | `extension` |
| status_whitelist | `[stable, experimental, deprecated, stub]` |
| default_status | `stable` |
| display_order | 20 |

**status 语义**：
- `stable` — 当前 build 完整链路 PASS
- `experimental` — 边缘 case / 部分功能未稳定
- `deprecated` — 业务已不依赖（保留观察）
- `stub` — 占位

**已有 cases 概览**（M4b 首批 5 例，3~5 例上限达成）：
- pgvector IVFFlat 基础（#68）
- pg_partman RANGE 分区 + retention（#82）
- anon 动态脱敏 (跨 db case，#83)
- plpython3u + numpy 1.25.2（#84）
- postgis 2.5.4 ST_DWithin + GIST（#87）

**case 作者约定**（M4b 5 例确立的 best practices）:
- 浮点断言：`abs(actual - expected) < 1e-9` 单 bool（避 IEEE 754 末位 jitter）
- 每 step `expect.not_contains: ["ERROR", "FATAL"]` 兜底（半透明失败防御）
- teardown **不 DROP EXTENSION**（共享资源；DROP CASCADE 会牵连其他业务）
- 跨 db case：`pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='...' AND pid != pg_backend_pid()` 强解 SqlSessionPool 长连后再 DROP DATABASE
- `source.feishu_anchor` 留空（extension 不来源于飞书 BUG 文档）；`source.ext_doc_url` 填官方文档链接

### 16.4 external_systems — 依赖外部服务组件的集成测试（v1.10 新增，v1.21 status 语义补强）

| 字段 | 值 |
|---|---|
| name | `external_systems` |
| display_name | 外部系统集成测试 |
| id_prefix | `lg-xs-` |
| dir_path | `external-systems` |
| status_whitelist | `[open, fixed, wontfix, stub, awaiting_env]` |
| default_status | `open` |
| display_order | 30 |

**关键差异 (vs extension)**：
- `extension` 假设 `CREATE EXTENSION foo` 即用，依赖 PG 二进制里已有 `.so`（部署时就绪），`status` 表达扩展功能稳定性 (stable / experimental / deprecated / stub)
- `external_systems` 需要**外部服务进程 + 凭据 + 网络 + profile.d**全部就绪——`datalake_fdw` / `hive_connector` / `PXF` / `zombodb` 这类典型；但 case 本质仍是 BUG 复现（外部组件触发的 PG/Greenplum BUG），`status` 主维度与 `bug_regression` 对齐用 open / fixed / wontfix / stub，附加 `awaiting_env` 表达外部服务未部署占位

**id_prefix `lg-xs-` 决策**（PR #88，user-approved 2026-05-24）：
- `lg-ext-sys-` 与 `lg-ext-` startswith 冲突（虽然 backend 用 cat.id_prefix 查表不用 startswith，但语义上有歧义）→ 否决
- `lg-es-` 与 Elasticsearch 缩写冲突 → 否决
- **选 `lg-xs-`**：4 char，xs = external systems 缩写，无任何冲突

**status 双轴语义**（v1.21 修订）：
- **主轴 = BUG 修复状态**（与 `bug_regression` 共享语义）
  - `open` — BUG 未修复 (default，新 case 进库时的初始状态)
  - `fixed` — BUG 已在某版本修复（详情可在 `source.fixed_version` / `notes` 里写）
  - `wontfix` — 设计上不修复
  - `stub` — case 蓝图占位，缺执行步骤
- **辅助轴 = 环境 lifecycle**：
  - `awaiting_env` — 外部服务尚未部署，case 暂时无法跑（与 BUG 修复状态正交，不应与 `open` 混淆）

**v1.21 反转原因**（2026-05-26）：v1.10 设计时 status_whitelist 只覆盖环境就绪度 (stable / awaiting_env)，与项目主目的"BUG 回归测试"语义不符——external_systems 与 extension 拆分的真实理由是依赖外部进程，不是 case 性质不同。3 个已落库 case (`lg-xs-pxf-hdfs-order-by-writable` / `lg-xs-pxf-hive-fdw-encoding-utf8` / `lg-xs-zombodb-partition-text-search`) 都是 BUG 复现性质，用 `stable` 无法区分"BUG 已修复 vs BUG 未修复但环境跑得起来"。

alembic migration `0006_external_systems_status_realign.py` 上线时 UPDATE category row + 同步把 3 个旧 case YAML 的 `status: stable` 改为对应的 `fixed` / `open` / `fixed`，atomic squash 进 main。

**candidate cases (M4c plan，§13.10 详细)**：1~3 例蓝图，user 按外部服务部署节奏添加
- datalake_fdw（外部依赖最少，推荐首例）
- hive_connector（PXF 或 datalake_fdw + Hive Metastore + HDFS）
- PXF（HDFS / Hive / JDBC via java agent）
- zombodb（PG ↔ Elasticsearch 全文搜索）

**`external_deps` 字段当前状态**（v1.11）：仅文档性质，runner **不读** / **不渲染** Jinja `{{ external.<svc>.* }}`。Runtime injection 推 M6-5（§13.12）。case 作者按未来语义写。

**SKILL.md "Category-tagged external_systems 组" 追问**（PR #89，5 行从 extension 组迁出）：
- FDW / dblink / datalake_fdw / hive_connector / PXF / zombodb 关键词检测
- gphdfs.conf / gphive.conf / krb5.conf 配置文件写法（追加 + grep guard，**不**覆盖）
- kinit / keytab / principal Kerberos（`{{ external.<svc>.extras.client_principal }}` Jinja 占位）
- beeline / sqlplus / mysql 远端 CLI（host: '{{ external.<svc>.host }}' SSH 路由 + profile.d 显式 source）
- fresh pool / warmup / 服务刚起来（seed step 包 retry 循环）

### 16.5 未来新增门类的标准流程（v0.8 流程；v1.10 实战首次验证）

**5 步法**（external_systems PR #88 是首次实战，0 业务代码改动达成）：

| 步骤 | 动作 | 产物 |
|---|---|---|
| 1 | 写 mini design：本门类语义 / status 词汇语义 / 典型 case 1~2 样例；user-facing 决策点（dir_path / id_prefix / status_whitelist / default_status / display_order）显式列清 + 走 AskUserQuestion 拍板 | `docs/plans/<category>-category.md`（external_systems 范本：`docs/plans/external-systems-category.md`） |
| 2 | 新增 Alembic seed migration `INSERT INTO case_categories (...)` | `backend/alembic/versions/NNNN_seed_<category>_category.py` |
| 3 | `mkdir cases/<dir_path>/ && touch cases/<dir_path>/.gitkeep` 创建对应目录 | `cases/<dir_path>/.gitkeep` |
| 4 | 如有特化场景关键词，在 SKILL.md 加 `**Category-tagged <name> 组**` 表 + lint script 加 banned pattern `if category == '<name>'` | `.claude/skills/add-test-case/SKILL.md` + `.claude/scripts/check_skill_add_test_case.sh` |
| 5 | smoke e2e：(a) `alembic upgrade head` 跑通；(b) `GET /admin/categories` 返新数；(c) `GET /cases?category=<name>` 返 `[]`；(d) skill grounding 拉到新 category；(e) 一次 POST /cases/validate 用 stub case 验 id_prefix + status_whitelist；(f) 跑 backend pytest（fixture 数字 N→N+1）+ frontend vitest（无破）+ skill lint | smoke 验证表 + 测试 fixture 更新 PR |

**关键约束**：
- 5 步里**没有一步是改 schema 校验代码、改前端组件、改 skill 主流程**。如果你发现非改不可，说明 §16.1 元数据字段缺了什么——回 design 加字段，**不要**绕过元数据写 `if` 分支（§14 R4b 反模式）
- 不暴露 `case_categories` 的 admin UI（同 §16.1 末尾）
- mini design 必走 AskUserQuestion 拍板 5 决策点，不要 agent 自决

**实战 cycle time**（external_systems PR #88，参考）：
- 设计文档（含 5 决策点 + plug-and-play 现状探明 + 不在范围明示）：~30 min
- AskUserQuestion 4 决策点拍板：~5 min
- 实施（migration + dir + skill prefix + fixture + ci-gate run）：~30 min
- PR review + merge：~5 min
- 合计 ~70 min（user-on-loop 全程响应）。比"改业务代码"省至少 10x

---

## 17. add-test-case Skill（v1.11 PR-A2，canonical）

> **本章是 skill 设计的 canonical reference**——汇总原 §5.5 (v0.6-v0.9 设计快照)、§13.8 (M3b plan)、§13.9.4 (硬化 PR 链)、SKILL.md 模型规则块。原 §5.5 stub 指向这里。

### 17.0 概述 + design vs runtime 双源同步

**两个文件，不同角色**：
- **`.claude/skills/add-test-case/SKILL.md`**（runtime markdown）：用户 `claude --print --agent /add-test-case ...` 时实际加载执行的脚本；含 example transcripts / Common mistakes 反例清单等运行时材料
- **本章 §17**（design canonical）：设计意图 + 不变量 + 演化历史 + 跨章节关联

**双源同步约定**（v1.11 起）：
- SKILL.md 改 → §17 必须同步更新（同 PR 内）
- §17 改 → 同步 SKILL.md
- `.claude/scripts/check_skill_add_test_case.sh` CI lint 守 SKILL.md 关键字段（model / sections / banned patterns）
- 若两者出现 drift，**SKILL.md 为准**（runtime 真消费的版本），§17 跟改

### 17.1 设计原则（6 条铁律）

借鉴 preflight `SKILL.md`，本 skill 严格遵守：

1. **Generator-only，无副作用**：
   - ❌ 不用 Write 工具
   - ❌ 不 `git add` / `git commit` / `git push`
   - ❌ 不调 `POST /cases/submit`
   - ❌ 不跑 case（用户在 UI 上点 Try 跑）
   - ✅ 唯一输出 = stdout 上一段 YAML，用 `─── BEGIN YAML ───` / `─── END YAML ───` 包裹（无围栏、无注释混在内部），方便人复制粘贴
2. **Live grounding**：生成前必须 fetch **三个** backend 端点（PR #86 起从 4 个削减——`/admin/settings` 不存在故剔除）。失败时显式提示用户，**不**编造字段。
   - `GET /admin/categories` — 当前活跃测试门类清单（**禁止**编造 category 名）
   - `GET /cases?q=<topic>&category=<name>` — 按 category 查重
   - `GET /admin/step-kinds` — executor 自描述（**禁止**编造 step kind）
3. **House-style 学习**：开工前 Read 2-3 个最相似的已有 case YAML（按 tags / 关键词匹配），匹配字段顺序、注释风格
4. **不嵌入凭据**：DB 密码走 runner（PGPASSWORD 环境变量或 .pgpass），**不**写进 YAML 字面值
5. **6 题对齐 + 场景特化追问**（PR #86 起从"5 题"升级到"6 题"，category 题为首；详 §17.4 / §17.5）
6. **canonical field 顺序**：生成 YAML 必须按 §17.6 的字段顺序，与 catalog 一致

### 17.2 输入模式（四选一）

```
/add-test-case <feishu-url>             模式 A：飞书 LG 历史 BUG 文档锚点（多用于 bug_regression）
/add-test-case <local-sql-file>         模式 B：本地 SQL 复现脚本
/add-test-case ext:<extname> [<doc-url>] 模式 D：v0.7 新增——extension 用例（如 ext:pgvector）
/add-test-case                          模式 C：自然语言（skill 反问要做什么）
```

输入歧义时一问澄清（"这是飞书 URL 还是本地路径？是 BUG 回归还是 extension 集成？"），不要凭猜。

- 模式 A 用 **WebFetch**（MCP 不可达时复用 `feishu_client.py`，详 memory `feishu_client_access.md`）；category 默认 = `bug_regression`
- 模式 B 用 **Read** 读本地文件；category 从脚本内容/路径推断
- 模式 C 直接问用户，category 作为首题
- 模式 D 锁定 category = `extension`，extname 进入 tags 与 id slug

### 17.3 工作流（7 步）

| 步骤 | 动作 |
|------|------|
| 1 | Read 2-3 个最相似已有 case YAML（从 `cases/<dir_path>/` 下，按 tags 匹配）|
| 2 | Fetch **三个** grounding 端点（§17.1 规则 2）|
| 3 | 分析输入，从输入推导默认值 + 检测场景关键词 |
| 4 | 按 §17.4 顺序提 **6 题**，每题展示默认值；空回车 = 接受默认 |
| 5 | 按 §17.5 追问场景特化问题（只问检测到的；按 category 选组） |
| 6 | 按 §17.6 canonical 顺序起草 YAML；做 **12 项** cross-check（§17.7）|
| 7 | 打印 `─── BEGIN YAML ───` … `─── END YAML ───` + 3 行 footer |

### 17.4 6 个对齐问题（v0.7：category 加为首题；v0.8：选项从 API 拉）

```
1) category    [<auto-推断, default by 模式>]:  # 选项从 GET /admin/categories 拉
                                                # 模式 D 直接锁 extension，仍展示题让用户确认
2) id          [<auto-slug, 按 category.id_prefix + 推 slug>]:
3) title       [<从飞书锚点/脚本注释/extname 提取>]:
4) applies_to.versions  [全适用]:               # 例：">=1.6,<2.0"
5) status      [<category.default_status>]:    # bug=open, ext=stable, external_systems=awaiting_env
6) severity    [medium]:                       # high | medium | low
```

skill 题 1 拿到答案后，把对应 category 的 `id_prefix` / `default_status` / `status_whitelist` 缓存下来，后续 2~6 题都用这份数据。**禁止** skill 代码里出现 `if category == "bug_regression"` 字面分支（§14 R4b 反模式，lint 强校）。

### 17.5 场景特化追问

按输入关键词检测，每命中一类追加 1 题，不命中跳过。**3 组**：

**通用组**（任何 category 都可能命中）：
- 多会话 / VACUUM 同时 / two session → `sessions:` mapping
- crash / FATAL / recover mode → 加 `kind: log_grep` step
- 自建 db / lc_ctype → step 级 `database:` override + setup createdb
- GUC / ORCA / enable_X → `preconditions:` 段
- explain / hashjoin → `expect.plan_contains`
- 性能 / 慢查询 → `expect.duration_lt_ms`

**Category-tagged extension 组**（仅 category=extension 时生效）：
- CREATE EXTENSION / shared_preload (pg_search / pgaudit) → `kind: restart_db` step；标 `destructive: true`
- pgvector vector/IVFFlat/HNSW → `expect.plan_contains: ["IVFFlat" ...]`
- postgis ST_*/GEOMETRY/SRID → GIST 索引 + ST_DWithin 等
- pgcrypto crypt/digest/gen_random_* → 确定性算法 → `expect.scalar`；随机 → 仅校非空
- plpython/plperl 过程语言 → 部分需 `shared_preload_libraries` + `kind: restart_db`
- 版本断言 → 一 step `SELECT extversion FROM pg_extension WHERE extname=...`

**Category-tagged external_systems 组**（仅 category=external_systems 时生效；PR #89 从原 extension 组迁出）：
- CREATE FOREIGN TABLE / FDW / dblink / datalake_fdw / hive_connector / PXF / zombodb → 补 `external_deps: [<svc>]`；status 默认 `awaiting_env` 直到环境就绪
- gphdfs.conf / krb5.conf 服务端配置文件 → cli step `cat >> ... grep -q guard`（**不**覆盖）
- kinit / keytab / principal Kerberos → `{{ external.<svc>.extras.client_principal }}` Jinja
- beeline / sqlplus / mysql 远端 CLI → `host: '{{ external.<svc>.host }}'` + cmd 开头 `source profile.d`
- fresh pool / 服务刚起来 warmup → seed step 包 retry 循环

> **注**：表里 `{{ external.<svc>.* }}` Jinja 占位**当前 runner 不解析**（external_deps 字段是文档性质，runtime injection 待 M6-5）；case 作者按目标语义写。

未命中任何关键词 → 跳过本步，进入草拟。

### 17.6 canonical 字段顺序（v1.8 起 `defaults.database: gpadmin`）

skill 输出的 YAML **必须**按这个顺序：

```yaml
id: lg-bug-NNNN-<slug>                  # 或 lg-ext-<extname>-<slug> 或 lg-xs-<svc>-<slug>
title: <中文 OK>
category: bug_regression                # / extension / external_systems
status: open                            # 按 category whitelist
severity: medium
destructive: false

source:
  feishu_anchor: "section-X.Y"          # bug 模式 A 必填
  reported_at: "YYYY-MM-DD"
  fixed_version: ""                     # bug + status=fixed 时填
  ext_doc_url: ""                       # ext / external_systems 用
issue_url: ""
tags: [<语义 tag>]

description: |                          # 4-tuple 叙事：本 case 验证什么
procedure: |                            # 4-tuple 叙事：编号步骤
expected: |                             # 4-tuple 叙事：预期一句话清单

applies_to: {}
preconditions: {}
external_deps: []                       # external_systems 必填；bug/ext 通常 []

defaults:
  database: gpadmin                     # v1.8 起默认 gpadmin（旧 5 例显式写 postgres 不受影响）

sessions: {}                            # 命中并发场景填 mapping {s1: {driver: sql}, ...}；空/省略 = loader 自动 derive default

setup:
  - sql: |
      <DROP IF EXISTS + CREATE + INSERT, 幂等>

steps:
  - name: <短描述>
    kind: <sql|shell|log_grep|restart_db>
    on: default
    sql: |
      ...
    timeout_sec: 60
    expect:
      <按 §4.1 expect 字段菜单挑>

teardown:
  - sql: |
      <DROP IF EXISTS 收尾；不 DROP EXTENSION>

created_by: chenqiang                   # 从 git config user.email 推断
created_at: "YYYY-MM-DD"
notes: |
  <workaround / 触发条件 / 已知信息>
```

### 17.7 打印前 cross-check（12 项；PR #86 起从 13 项合并）

1. **step kind 在 `/admin/step-kinds` 列表里** — 禁止 `kind: bash` / `kind: psql`
2. **expect 字段与 step kind 匹配** — `plan_contains` 只 sql / `exit_code` 只 shell / `scalar` 只单行单列 SQL
3. **setup/teardown 幂等守卫** — DROP 必带 IF EXISTS / CREATE 必带 IF NOT EXISTS（除非测 CREATE 本身）
4. **不嵌入凭据** — grep YAML 无 `password=` / `PGPASSWORD=` 字面值
5. **status × category 一致性** — bug/ext/external_systems 各自 whitelist；status=stub 时 steps 必为空
6. **id 前缀 × category 一致性** — bug→`lg-bug-*`、ext→`lg-ext-*`、external_systems→`lg-xs-*`
7. **destructive 一致性** — steps 含 gpstop/gpstart/gpconfig -c shared_preload/restart_db/rm -rf data → 必 destructive=true
8. **Jinja typo 检查** — `{{ external.<svc>.* }}` 的 `<svc>` 必须出现在 external_deps
9. **远端 cli step profile.d source** — 带 `host: '{{ external.* }}'` 的 cli step cmd 开头必须 `source /etc/profile.d/<x>.sh`
10. **服务端配置文件用追加 + grep guard** — `cat > $DD/...conf` 覆盖写式 → 改 `cat >> + grep -q '^<key>:' guard`
11. **non-tx-safe DDL 必须走 psql -c** — VACUUM / 顶层 ANALYZE / CREATE DATABASE / REINDEX CONCURRENTLY / ALTER SYSTEM / CLUSTER 等关键词出现 → 绝禁 `kind: sql`，必 `kind: shell + cmd: psql -c '...'`（§4.1.2 约定）
12. **跨 driver 数据可见性** — kind: sql + kind: shell 混搭时：sql_driver 自动 commit-after-step（PR #80 起）所以前序 sql 的 CREATE/INSERT 对后续 psql -c 子进程自动可见；保守仍可全 psql -c

**任一项未过 → 修正后重试，不打印 BEGIN/END。**

### 17.8 模型规则（v1.11 新增，PR #85 落地，**永久生效**）

**规则**：`.claude/skills/*/SKILL.md` 文件**必须**钉 `model: claude-opus-4-7`（exact 字符串，不写 generic `opus`）。

**Why**：
- skill 输出需要严谨结构 + canonical 顺序 + 多项 cross-check 一次过
- sonnet 实战漂移多（M1-followup yaml_loader 杜撰 4 个 category 是 §14 R4b 真实震慑案例）
- haiku 推理深度不足

**CI 守门**：`.claude/scripts/check_skill_add_test_case.sh` line ~61 收紧到精确匹配 `^model:[[:space:]]*claude-opus-4-7[[:space:]]*$`。绕过 lint 修 sonnet/haiku/generic-opus 都会被 PR 卡住。Reverse-test 验过：注入 `model: opus` / `model: sonnet` 都 exit 1。

**与 §A agent override 互不冲突**：memory `feedback_model_override_2026-05-24` 拆 §A (agent 一次性 override 仅 2026-05-24 那次例外) + §B (skill 文件永久钉 opus 4.7)。**agent quota fallback 不适用于 skill 文件**（静态文档，无 fallback 概念）。

**例外**：`.claude/skills/report-status/SKILL.md` 无 `model:` frontmatter——reporter agent 设计就是 haiku（§8.1），新规则不强制 report-status 改 opus；只限制"如果 skill 写 model:，必须是 claude-opus-4-7"。

**升级路径**：未来 opus 4.8+ 上线，仍需用户**显式**授权才能升版本；agent 自决禁止。

### 17.9 实施回顾（M3b sprint + 硬化 3 PR 链）

**M3b sprint**（详 §13.8 plan，已 done）：10 子步骤完成 + 1 bug 修补（assertions list-form fix, PR #67 dogfood 暴露）+ M3b-10 web flow dogfood 闭环（PR #68 lg-ext-pgvector via skill 路径真 merge 进 main）。SKILL.md 588 行 bundle 在 PR #65 内交付。

**skill 硬化 3 PR 链**（v1.10/v1.11，2026-05-24 PM）：

| PR | 改动 | 触发 |
|---|---|---|
| **#85** | frontmatter `model: opus` (generic) → `model: claude-opus-4-7` (exact)；lint 收紧 | user "skill 坚持改用 opus 4.7，不再使用 sonnet" |
| **#86** | opus self-review 7 spec fixes：/admin/settings 404 删 grounding / sessions list→mapping (backend 真接受 shape) / 5题→6题三处统一 / cross-check #3+#8 合并 (13→12) / DROP EXTENSION 反例 + 通用规则 / created_by example 修对 / Fetch 端点数同步 | user "用 opus review skill 及周边" |
| **#89** | SKILL.md 5 行外部服务追问 extension 组 → external_systems 组；lint 加 external_systems banned pattern | user "迁追问到 external_systems 组" |

**M3b 与 skill 硬化的关系**：M3b 把 skill 从 design 概念落到可运行的 markdown；硬化 3 PR 把 dogfood 暴露的 spec gap 闭合 + 引入永久模型规则。这是 "spec → 落地 → dogfood → 硬化" 完整循环的典型范例。

### 17.10 输出格式 + 不做的事

**输出格式**（footer 不可缺）：

```
─── BEGIN YAML ───
id: lg-bug-NNNN-<slug>
...
─── END YAML ───

下一步：
1) 打开 http://localhost:5173/cases/new → 选「粘贴 YAML」入口
2) 粘贴上方 YAML 块，点 Validate（schema 校验通过）
3) 点 Try（在你已就绪的集群上试跑一次），全绿后 Save → 自动提 PR
```

**不做的事**（明示）：
- ❌ 写 `.yaml` 到磁盘
- ❌ `git add` / `commit` / `push`
- ❌ `POST /cases/submit`
- ❌ 触发集群上的真实运行（那是 `/cases/try` 干的）
- ❌ 修改 skip_list / settings / 任何 admin 资源

skill 是 **YAML 编辑器的打字助手**，不是 deployer，不是 reviewer。前端的 Validate + Try + Save 才是 source of truth。

---

## 18. Milestones index（v1.11 PR-A3，按 M 视角导航）

> **本章是 milestone-视角的索引**——按 M0 / M1 / M2 / M3a / M3b / M4 / M4c / M5 / M6 顺序，每个 M 给一段 summary + plan / retro / 关键 PR / 完成定义的 §13.x 链接。**§13 仍是 detail 主体**（chronological 视角，sprint 真实顺序）；本章给你"想看某个 M 全貌"时的入口。
>
> 原 §13.0-§13.12 不动，仅头部不加 stub（§13 这个章节本来就是 canonical detail；本章只是导航，不是 canonical）。

### 18.0 概述

design.md §13 当前 13 个子节按时间线展开：plan 写在 sprint 启动时（§13.5 M2 plan / §13.7 M3a plan 等），retro 写在 sprint 收尾时（§13.4 M1 retro / §13.6 M2 retro 等），混在一起。用户从 milestone 视角查"M2 是怎么搞的"得跳 §13.5 + §13.6 两节；找 "M4 整体回顾"得看 §13.9 + cross-ref 飞回 §0 changelog v1.10 行。本章按 M 顺序集中每个 milestone 的索引。

### 18.M0 项目骨架（done）

- **状态**：✅ done（design.md 定稿 + 8 agent 配置 + skill 占位 + 仓库创建 + CI 框架）
- **关键 §**：§13.0 启动前自检 / §13.1 M0 计划 / §13.2 待跟进项 / §0 changelog v1.0-v1.3
- **关键 PR**：#1 initial commit (29b2507) + foreman dry-run smoke (commit `7d97986` / `31f8653`)
- **核心收尾**：M0 step 9 dry-run 发现 doc-writer 漏 `git checkout -b` 直推 main → 6-step → **7-step PR contract** 硬化（§14 R24 入档）

### 18.M1 后端 MVP（done）

- **状态**：✅ done — 4 sprint chain (M1 main + followup + cleanup P0/P1/P2)，25 PR + 3 direct commit
- **关键 §**：§13.4 M1 实战回顾（含 sprint 时间线 + 文件 deliverable map + opus review 10 finding P0/P1/P2 三级 fix 对照）
- **关键 PR**：#2~#10 + #12~#25
- **核心交付**：load YAML / run / sql_driver + shell_driver + log_grep / SQLite 5 表 / 基本 API / 5 例 dogfood 5/5 PASS / **§14 R22/R23/R24/R25 入档**
- **完成定义**：API path 跑 5/5 PASS（M2 dogfood 才挖出 dual-code-path 残余，§13.6）

### 18.M2 前端 MVP（done）

- **状态**：✅ done — 5 sprint round + 2 followup hotfix + 2 docs PR，20 PR 横跨 #26~#45
- **关键 §**：§13.5 M2 计划 + §13.6 M2 实战回顾（plan + retro 已相邻）
- **关键 PR**：#28~#41（10 个 M2-* item）+ #42（case_normalizer hotfix）+ #43（dsn_builder hotfix）+ #44（§14 R26/R27 入档）+ #45（§0 v1.4+v1.5 retroactive bump）
- **核心交付**：Vite + React + TS strict / Tailwind + shadcn/ui / 4 个页面 / Playwright E2E / **dual-code-path 暴露 + §14 R26 / R27 入档**
- **完成定义**：UI 6 路径走查全 PASS（`docs/m2-dogfood-2026-05-24-0535.md`）

### 18.M3a Web 录入（done）

- **状态**：✅ done — 10/10 子步骤 + 4 spec gap follow-up
- **关键 §**：§13.7 M3a Web 录入计划
- **关键 PR**：#49~#55 + #56/#57 hotfix + #58/#59 浏览器 dogfood + #60 报告 + #61 spec gap
- **核心交付**：`/cases/new` 双入口编辑器 + Validate→Try→Save 三段闸门 + `POST /cases/submit` 真 git push + gh pr create + auto-merge
- **完成定义**：浏览器用户视角真 web flow 通 PR #58/#59 merge 进 main

### 18.M3b Skill 录入（done）

- **状态**：✅ done — 10/10 子步骤 + 1 bug 修补 + skill 硬化 3 PR (#85/#86/#89)
- **关键 §**：§13.8 M3b Skill 录入计划 / §17 add-test-case Skill canonical（v1.11 PR-A2）
- **关键 PR**：#63（cases?q=）+ #64（/admin/step-kinds）+ #65（SKILL.md 588 行 bundle）+ #66（lint）+ #67（assertions list-form fix）+ #68（首例 lg-ext-pgvector via skill 路径）+ #69 dogfood 报告 / 硬化：#85 model pin + #86 7 spec fixes + #89 追问迁 external_systems
- **核心交付**：`.claude/skills/add-test-case/SKILL.md` runtime + grounding 端点 + CI lint 守 + **claude-opus-4-7 永久钉**（§17.8）
- **完成定义**：programmatic skill 路径走通三段闸门 + dogfood `docs/m3b-dogfood-2026-05-24-1340.md`

### 18.M4 用例填充（done）

**M4 是 3 子轨道 parallel**（不是单一 sprint）：M4a + M4b + 附加 external_systems landing + skill 硬化。

- **状态**：✅ done — 17 PR 横跨 #68~#89
- **关键 §**：§13.9 M4 实战回顾（6 子节：M4a + M4b + external_systems landed + skill hardening + R28 候选 + §0 gap defense）
- **M4a 飞书 BUG 补录**：3 例新 case (`lg-bug-0007` §9.7 / `0008` §9.11 V1+V2 / `0009` §9.12 intermittent) + sql_driver chain refactor（PR #73→#75→#80 autocommit→commit-after-step）
- **M4b extension 首批 5 例**：pgvector #68 / pg_partman #82 / anon #83 / plpython3u+numpy #84 / postgis #87 — **§12 首批 3~5 例上限达成**
- **核心副产**：§14 R28 入档（intermittent BUG sampling ≥10 rounds，`lg-bug-0009` 反转 fixed→open 实战）；§16 测试门类 super-section（PR-A1，本 reorg 链 §16）；§17 skill super-section（PR-A2，本 reorg 链 §17）
- **完成定义**：3 类 case YAML 共 14 例 stable / 5 旧 BUG `fixed` 维持 / `lg-bug-0009` `open`（铁律 1 实战）

### 18.M4c external_systems 首批 case（plan，待 user 添加）

- **状态**：📋 plan only — case 蓝图可写 `status: awaiting_env` 占位；真跑 Try 阻塞 M6-5 runtime injection
- **关键 §**：§13.10 M4c plan / §16.4 external_systems schema 特化
- **候选 cases**：datalake_fdw（外部依赖最少，推荐首例）/ hive_connector / PXF / zombodb
- **完成定义**：1~3 例 `lg-xs-*` YAML 落 `cases/external-systems/`，validate ok；前端 tab 列出
- **不做的事**：不强制集群部署对应外部服务；不在本 milestone 加 runtime injection（M6-5 才做）

### 18.M5 前端 UX 统一面板（plan，**用户优先级 #1**）

- **状态**：📋 plan only — 6 子步骤
- **关键 §**：§13.11 M5 plan
- **触发**：用户 2026-05-24 反馈"前端使用不方便、没有统一面板"——M5 原 catch-all (SSE/Admin UI/diff/etc) 拆出"前端 UX"单列 milestone，**先做**
- **子步骤**：M5-1 Layout sidebar / M5-2 Dashboard `/` (KPI + recent activity + quick actions) / M5-3 跨页关联 / M5-4 全局筛选 + URL 持久化 / M5-5 Quick Actions（preset 卡片） / M5-6 dogfood
- **完成定义**：Dashboard `/` 显得出 + sidebar 工作 + 跨页跳转 + 全局筛选 URL 持久化 + preset 触发 run；产 `docs/m5-dogfood-<ts>.md`
- **§14 R 预付**：R2 (Playwright contract) / R4b (不写死 category) / R26 / R27

### 18.M6 运行体验深化（done, v1.14 + post-M6 iter v1.15 + wave 2 v1.16）

- **状态**：✅ DONE — 6 子步骤 + 1 dogfood + 4 parallel UI 小 PR + 9 PR post-sprint UX iteration (两 wave)
- **关键 §**：§13.12 M6 plan / §13.14 M6 retro (含 §13.14.8 post-M6 wave 1 + §13.14.9 wave 2)
- **关键 PR (sprint main)**：#110 SSE / #112 artifacts / #114 history diff / #115 Admin UI / #116 external_deps / #117 dogfood + F1 wiring fix；parallel UI: #107 / #109 / #111 / #113
- **关键 PR (post-M6 wave 1, v1.15)**：#119 Settings allowlist 砍 2 / #120 Skip List combobox / #121 RunsPage `?case_id=X` filter / #122 until_date label / #123 砍 Settings + 加 external/dut.yml (设计层重大决策)
- **关键 PR (post-M6 wave 2, v1.16)**：#125 Admin > External services 浏览页 + dut.yml topology 修 / #126 Admin > Delete case + 教育性 confirm / #127 Dashboard row 2 R4b 数据驱动修
- **Admin 页定型为 3 入口** (v1.16 起)：Skip list / External services / Delete case
- **dogfood 报告**：`docs/m6-dogfood-2026-05-25-0212.md` — M4c-1 case 3 轮 real-cluster verification (PASS / PASS / SKIP-as-expected) + F1 wiring fix forensic + F2 step-02 artifact missing 留 backlog
- **关键学到**：(1) **R30 "≤1 novel mechanism per PR" sprint-wide 0 命中** — vertical-slice (e.g. SSE 端到端 = 1 broker + 1 endpoint + 1 client) 比 horizontal-slice 更易 review；(2) **F1 = §14 R26 一种隐性变体**——"endpoint 落地 + 单测验 persistence 但 runtime 路径未接通"，添 regression test `test_execute_run_passes_skip_list_to_orchestrator` 防退；(3) **user-driven 路径在 R-stabilized codebase 上显著比 foreman 路径快**（M6 2h vs M5-1 foreman ~6h）
- **数字**：vitest 127→187 (+60) / pytest 345→388 (+43) / merged PRs +18

### 18.Auth 简易用户登录模块（done, v1.17）

- **状态**：✅ DONE — 3 PR / 9 文件 / 600+ LOC / 全 user-driven 手写
- **关键 §**：§13.15 (sprint retro) / §0 v1.17 changelog
- **关键 PR**：#131 backend (users/auth_tokens + /auth/* + bcrypt + Bearer + 替代 ADMIN_PASSWORD) / #132 frontend login + guard + Logout (含 e2e seedAuth helper 修 playwright) / #133 change-password + 红条提醒
- **核心决策**: 单用户 admin / 永不过期 token / sha256 存 hash / 不主动 invalidate 多设备 / 红条提醒可忽略
- **Admin 页定型 4 入口** (v1.17 起): Skip list / External services / Delete case / Change password
- **数字**: backend pytest 396→420 (+24) / frontend vitest 211→244 (+33) / merged PRs 130→133 (+3)
- **关键学到**: passlib 1.7.4 与 bcrypt 5.x 不兼容 (直接用 bcrypt 模块) / FastAPI `Depends` 默认参数 ruff B008 用 `Annotated` 绕过 / 新加 frontend guard 时必须同步检查 playwright e2e 是否依赖 protected route (PR #132 e2e fix)

### 18.M7 LLM 接入（plan, v1.13 新增）

- **状态**: 📋 plan only — 4 子步骤 + dogfood (M7-1 backend / M7-2 prompt / M7-3 frontend / M7-4 tests / M7-5 dogfood)
- **关键 §**: §13.13 M7 plan / §5.4 LLM 解析模块设计
- **触发**: M3a-5 当时 stub (`CaseNewPage.tsx:140 handleGenerateStub` 只弹 toast)；user 2026-05-24 PM 问"现可用么？" → 决策单列 M7 (option B 独立 milestone)
- **核心交付**: backend `POST /cases/generate-draft` + Anthropic SDK + 3 few-shot examples + frontend 状态机 + 必须人工确认 gate (§5.4 spec)
- **待用户决策**: D1 model (sonnet/opus/env) / D2 few-shot 来源 (hardcode/dynamic) / D3 API key 管理 (env var/admin UI) — 详 §13.13
- **完成定义**: user 描述真生成一例 + 走通 Validate→Try→Save→PR auto-merge

### 18.x 共通教训对照（cross-milestone）

| Milestone | 触发的关键 §14 R 入档 | 触发的关键设计转向 |
|---|---|---|
| M0 | R24 (specialist 漏 step 0) | foreman.md / fixer.md 6→7 step PR contract |
| M1 | R22 (--auto 不等 CI), R23 (required check name), R25 (foreman no final JSON), R24 (本地 ci-gate triplet) | ci-gate.yml 聚合 + branch protection + dispatch-foreman.sh wrapper |
| M2 | R26 (dual-code-path), R27 (relative-path env defaults) | case_normalizer.py + dsn_builder.py 抽共享 prep 模块 |
| M3a | R26 轻量变体 (frontend regex vs backend parser 容忍度) | extractCaseId regex 与 backend 同步；M3a-10 dogfood 暴露 |
| M3b | — | SKILL.md 硬化 + lint CI 守 (PR #85/#86/#89) |
| M4 | R28 (intermittent BUG sampling ≥10 rounds) | sql_driver chain refactor + lg-bug-0009 反转 fixed→open 铁律 1 实战；§4.1.2 psql -c 约定硬化 |
| M5 ✅ done | R29~R32 (M5-1 PR #94 失败链事后) | sidebar + dashboard 统一面板；moving away from flat top nav |
| M6 ✅ done (v1.14) | R26 隐性变体 (F1 wiring-gap: endpoint 落地 + 单测过 + runtime 不读) / R30 sprint-wide 0 命中 (vertical-slice 模式实战印证) | SSE event broker + artifacts API + admin CRUD pattern + external_deps Jinja injection; user-driven 路径 2h 闭环 vs foreman 路径 ~6h |
| **Auth ✅ done (v1.17)** | passlib/bcrypt 5.x 兼容 / FastAPI B008+`Annotated` / **新 frontend guard 必须同步修 e2e** (PR #132 5 个 playwright 失败) | bcrypt + opaque token + Bearer + RequireAuth HOC + must_change_password 红条 + Admin 第 4 入口 |
| M7 (待, v1.13) | — | Anthropic SDK 接入 / `/cases/new` 入口 A 真 work / 必须人工确认 gate |

**模式**：每个 milestone 至少触发 1 个新 §14 R 入档 / 1 个核心设计转向。"sprint = 学习一轮 = 沉淀一条反模式"——§14 是 milestone 的副产物，不是孤立的章节。

---
