# 里程碑实战回顾（archived from design.md §13）

> 从 `design.md` §13.4 / §13.6 / §13.9 / §13.14 抽出（2026-05-28 瘦身）。
> 已完成里程碑的事后实战记录（append-only 历史）；design.md 留指针桩。

---

## 13.4 M1 实战回顾（v1.3 内追加，2026-05-24 写入）

M1 实际跑了 **4 个 sprint + 1 cycle spec 硬化**，共 25 PR + 3 direct-to-main commits。最初 plan 11 个 item，实际 backend-fixer 自加 1 个 prep + opus review 后挖出 10 个 cleanup item + 2 条 spec 反模式（R24/R25）+ 1 个 wrapper（option A R25 mitigation）。

#### 13.4.1 sprint 时间线

| sprint | item 数 | PR | session 备注 |
|---|---|---|---|
| **M1 main** | 11 + 1 prep | PR #2~#10 (9 PR; M1-1~M1-8 + foreman 自加的 M1-prep-runner-types) + #12 (M1-9) + #13 (M1-10) + #14/#15/#16 (M1-11 chain) | foreman opus，1 session 干完，returned final JSON ✓ |
| **M1-followup** | 3 (F-1 / F-2 / F-3) | PR #17 / #18 / #19 | M1-11 dogfood 暴露 3 个 design_decision needs_human；foreman **sonnet 一次例外**（用户 2026-05-24 授权，[[feedback-model-override-2026-05-24]]）；R25 第 1 次违反 |
| **opus review** | 10 findings | — | opus 模型手工 review sonnet 写的代码，分 P0/P1/P2 三级；详 §13.4.3 |
| **M1-cleanup (P0)** | 3 (R-1 / R-2 / R-3) | PR #20 / #21 / #22 | yaml_loader §4.5 align + §14 R4b 反模式消除；R25 第 2 次违反 |
| **M1-cleanup-p1 (P1)** | 4 (R-4/R-5/R-6/R-7) | PR #23 / #24 | yaml_loader 严格化 + sql_driver autocommit timeout 对称；R25 第 3 次违反 |
| **spec 硬化** | 0 (spec only) | direct commit `126bba3` | foreman.md hard rule 8/9 + 6→7 step PR contract + §14 R24/R25 加 |
| **wrapper (option A)** | 0 (infra) | direct commit `d07e8c0` | `scripts/dispatch-foreman.sh` R25 mitigation 实装 |
| **M1-P2 cleanup** | 3 (R-8/R-9/R-10) | PR #25 | 风格 / 文档 / 守卫；首次完美走通 7-step contract（local ci-gate triplet 全绿才 commit） |
| **dogfood smoke** | 4 次 rerun | docs/m1-dogfood-* | 每次 sprint 后跑 5/5 PASS 验证 refactor 不退化 |

#### 13.4.2 文件级 deliverable map

```
backend/
  pyproject.toml                                          # M1-1
  alembic/versions/0001_initial_schema.py                 # M0 step 6 (5 tables)
  app/
    config.py                                             # M0 step 6
    runner/
      types.py                                            # M1-prep (StepResult/StepStatus/StepError 共享)
      assertions.py                                       # M1-4 (19 evaluators + dispatcher)
      sql_driver.py                                       # M1-5 + F-2 plan_text + F-3 autocommit + P1-sql + P2-R8/R10
      shell_driver.py                                     # M1-6 + Phase 2 fix (PR #11) kill+wait
      log_grep_driver.py                                  # M1-7
      jinja_render.py                                     # M1-8 (StrictUndefined + ssh_user decision)
      orchestrator.py                                     # M1-9 (groups + R9 + stdout fallback for plan_contains F-2)
    storage/
      yaml_loader.py                                      # M1-2 + F-1 §4.1 align + P0-A CategoryMeta + P1-yaml + P2-R9
      sqlite_store.py                                     # M1-3 (CRUD + ActiveRunExists / 409)
      models.py                                           # (CategoryMeta projection added in P0-A)
    api/
      main.py + cases.py + runs.py                        # M1-10 (POST /runs / GET /runs / GET /cases / GET /admin/categories)
  scripts/
    run_m1_dogfood.py                                     # M1-11 (PR #14)
  tests/
    test_alembic_upgrade.py                               # M0 step 6 (8 assertions)
    test_types / test_assertions / test_sql_driver / 
    test_shell_driver / test_log_grep_driver / 
    test_jinja_render / test_orchestrator /
    test_yaml_loader / test_sqlite_store / test_api       # M1-* 各对应单测，最终 269+ passed

scripts/
  dispatch-foreman.sh                                     # R25 wrapper (d07e8c0)
  cron-report-status.sh                                   # M0 step 7
  install-cron.sh                                         # M0 step 8

docs/
  m1-dogfood-2026-05-23-172355.md                         # 第 1 次 dogfood (3 pass / 1 fail / 1 error)
  m1-dogfood-2026-05-23-1828.md                           # M1-followup 后 dogfood (5/5 PASS)
  m1-cleanup-dogfood-2026-05-23-1908.md                   # M1-cleanup 后 (5/5 PASS)
  m1-cleanup-p1-dogfood-2026-05-23-1927.md                # M1-cleanup-p1 后 (5/5 PASS)
  foreman-runs/                                           # wrapper 产出目录 (M2 起开始有内容)
```

#### 13.4.3 opus review 10 findings 分级 + 解决映射

| Tier | R# | Issue | Fix PR / commit | 来源 |
|---|---|---|---|---|
| 🔴 P0 | R-1 | `_VALID_STATUSES = {open, closed, stub}` 与 §4.5 矛盾 ("closed" 杜撰) | PR #22 (CategoryMeta) | yaml_loader.py |
| 🔴 P0 | R-2 | `_CATEGORY_PREFIX` 杜撰 4 个 category + 漏 `extension` | PR #22 | yaml_loader.py |
| 🔴 P0 | R-3 | `_VALID_DRIVERS` 漏 `restart_db` | PR #20 | yaml_loader.py |
| 🟠 P1 | R-4 | `_parse_expect()` dead code | PR #24 | yaml_loader.py |
| 🟠 P1 | R-5 | `_parse_setup_teardown` silent-accept list[dict] | PR #24 | yaml_loader.py |
| 🟠 P1 | R-6 | step alias 优先级反了 (id>name, driver>kind) | PR #24 | yaml_loader.py |
| 🟠 P1 | R-7 | sql_driver autocommit 分支无 statement_timeout (§14 R5 不对称) | PR #23 | sql_driver.py |
| 🟡 P2 | R-8 | `_NON_TX_DDL_RE` 不完整 (CONCURRENTLY 索引/TABLESPACE 漏) | PR #25 (docstring 标已知漏覆盖 + 指向 §4.1.2) | sql_driver.py |
| 🟡 P2 | R-9 | YAML bool tag 字面值出现两次 | PR #25 (抽 `_YAML_BOOL_TAG` 常量) | yaml_loader.py |
| 🟡 P2 | R-10 | autocommit 路径 rollback 是 no-op | PR #25 (加 `if not conn.autocommit` 守卫) | sql_driver.py |

#### 13.4.4 M1 暴露并固化的 spec / 工程教训

1. **§14 R22 `gh pr merge --auto` 不等 CI**（M1 主 sprint 9 个 PR 全部"先合后跑"暴露）→ Phase 1/2/3 架构修：ci-gate.yml 聚合 workflow + repo 改 public + branch protection 加 `gate` 必过 check（commit `5ac2823` / `c7a68e6`）
2. **§14 R23 branch-protection `contexts` 字符串格式 footgun**（"ci-gate / gate" vs `gate`）→ PR #11 实战修
3. **§4.1.2 non-tx-safe DDL convention**（`psql -c '<DDL>'` 走 shell driver，§4.1.2 落地，commit `aa48a18` + `3013ad2`）
4. **§14 R24 specialist 不跑本地 ci-gate**（PR #18 / PR #22 两次栽在 `ruff format --check`）→ §15.2.1 6→7 step + step 1 显式列本地 ci-gate triplet（commit `126bba3`）
5. **§14 R25 foreman 不返 final JSON**（3 次连续违反 + spec 硬化 5 min 内仍犯）→ option A: `scripts/dispatch-foreman.sh` wrapper post-hoc reconstruction（commit `d07e8c0`，foreman 不返 JSON 也有 reconciled JSON 落盘）
6. **§14 R4b 真实震慑案例**: M1-followup sonnet 在 yaml_loader 杜撰 4 个未来 category + 漏 `extension` + 杜撰 status `closed`，opus review P0 抓到。后续 reviewer 在 §14 cross-reference 时凡命中 R4b 直接 REQUEST_CHANGES

#### 13.4.5 5 例 bug-regression 实际 BUG 状态（M1-followup-p1 后 dogfood 终态）

dogfood 5/5 PASS 不等于"5 个 BUG 都修了"——runner 跑过 ≠ BUG 复现失败：

| Case | YAML status | Runner verdict | 推断 BUG 实际状态 |
|---|---|---|---|
| bug-0001 hashjoin 右表 | open | PASS | upstream-fixed（候选改 status: fixed；EXPLAIN plan 含 tmp_test02 = 优化器选对小表） |
| bug-0002 unnest crash | open | PASS | upstream-fixed（temp table 路径未触发 recover mode + log_grep matches=0） |
| bug-0003 count-no-statistics | open | PASS | upstream-fixed（ANALYZE 后 NOTICE 流不含 "do not have statistics"） |
| bug-0004 CTAS rowcount=0 | open | PASS | upstream-fixed（ORCA off + clock_timestamp + REPLICATED 不再 0 行） |
| bug-0005 LC_CTYPE upper | open | PASS | upstream-fixed（LC_CTYPE='C' 数据库里 upper(multibyte) 不报错） |

**M2 开张前不批量改 status: fixed**——5 例都是"工具说 PASS"作证据，但工具自身刚 dogfood 通过，证据链置信度不到"我亲手过一遍每个 step 验证过"那级。等 M5 体验打磨阶段 + 人工对照飞书原文修复版本号再统一提状态。

---

## 13.6 M2 实战回顾（v1.5 内追加，2026-05-24 写入）

M2 实际跑了 **5 个 sprint round + 2 个 followup hotfix + 2 个 docs PR**。最初 plan 10 个 item，实际 PR 编号横跨 #26 ~ #45（20 个 PR），其中 14 个是 M2-* item 直接交付，3 个是 plan 维护（PR #27 创 plan / #30 #38 #40 标 [x] 推进），1 个是 dogfood 报告（#41），2 个 backend hotfix（#42 / #43），2 个 spec sync（#44 R26/R27 / #45 §0 版本号 retro bump）。

#### 13.6.1 sprint 时间线

| sprint | item | PR | session 备注 |
|---|---|---|---|
| **M2 plan 创建** | docs/plans/M2.md | #27 | foreman 入口文件落地，markdown todo 列表 |
| **M2 round 1**（M2-1）| frontend skeleton | PR #28 + #29（duplicate recovery）| foreman bg-mode specialist 实际跑完了但 wrapper 提前退；我捡 dangling branch 又开了 #29，两 PR 内容 = 同一 commit `d21cb49` 的 squash |
| **M2 round 2**（M2-2/M2-3/M2-4 parallel）| Tailwind+shadcn / openapi codegen / ErrorBoundary+router | #33 / #32 / #31 | foreman 派 3 worktree fixer 并行；M2-3 因 ci-gate trigger race 被卡，force-push empty rebase 唤醒 CI |
| **M2 round 3**（M2-5~M2-8 parallel）| 4 个 page 实现 | #37 / #34 / #35 (bundle M2-8 RunsPage) / #36 (closed) | 同期并行又触 3 个 sibling-file conflict（package.json / App.tsx / M2.md / client.ts）；M2-8 standalone PR #36 close 原因 = m2-7 specialist scope creep 顺手把 RunsPage 做了，m2-8 specialist 后开的 PR 包含错误的 sibling 文件删除 |
| **M2 round 4**（M2-9）| Playwright E2E + ci-gate playwright step | #39 | specialist 顺手把 m2-7 留下的 1-line placeholder RunDetailPage 重写为 minimal real 实现 |
| **M2-10 dogfood** | human 浏览器手动验 | #41（报告） | UI 6 路径全 PASS（详 `docs/m2-dogfood-2026-05-24-0535.md`） |
| **M2 hotfix #1** | case_normalizer 共享 | #42 | M2-10 提交真 run 时所有 case `'str' object has no attribute 'get'`，挖出 API 路径绕过 normalizer |
| **M2 hotfix #2** | dsn_builder + SqlSessionPool wired | #43 | 修完 hotfix #1 又发现 API 路径还漏 sql_pool=；真集群 5/5 PASS 在此 PR 之后实现 |
| **§14 R26/R27 入档** | dual-code-path + relative-path env defaults | #44 | 两条 hotfix 抽象为反模式 |
| **§0 retroactive v1.4+v1.5 bump** | design.md 版本号 | #45 | 用户提示发现 v1.3 行已变 catch-all，拆出 v1.4 (M1) + v1.5 (M2) |

#### 13.6.2 文件级 deliverable map

```
frontend/                                              # 全新建
  package.json + package-lock.json                     # M2-1 / M2-2 (Tailwind+shadcn deps) / M2-3 (openapi-typescript) / M2-4 (react-router)
  vite.config.ts + tsconfig.json + .eslintrc.cjs       # M2-1
  tailwind.config.ts + postcss.config.js               # M2-2
  index.html + src/main.tsx + src/App.tsx              # M2-1 (skeleton) → M2-4 (ErrorBoundary + Routes) → M2-5/6/7/8 (route components 挂入)
  src/index.css                                        # M2-2 (Tailwind directives)
  src/components/
    ErrorBoundary.tsx                                  # M2-4 (class component, componentDidCatch, 降级 UI 含 "返回首页" Link)
    ui/                                                # M2-2 shadcn 装的 Button/Card/Tabs/Dialog/Toast/Skeleton + M2-5 加 Badge
  src/api/
    types.ts                                           # M2-3 codegen 输出（544 行 TS types）
    client.ts                                          # M2-3 + M2-7 加 ApiFetchInit.allowedStatuses
    openapi.json                                       # M2-3 committed snapshot
  src/routes/
    CasesPage.tsx + .test.tsx                          # M2-5 (PR #37)
    CaseDetailPage.tsx + .test.tsx                     # M2-6 (PR #34)
    RunNewPage.tsx + .test.tsx                         # M2-7 (PR #35)
    RunsPage.tsx + .test.tsx                           # M2-7 bundled (PR #35) — full polling load-more impl
    RunDetailPage.tsx + .test.tsx                      # M2-7 (1-line stub) → M2-9 (PR #39, full impl with 3s polling)
  e2e/
    smoke.spec.ts                                      # M2-1 placeholder
    run-new-contract.spec.ts                           # M2-7 (§6.4 R2 contract test, page.route + postDataJSON)
    case-to-run-flow.spec.ts                           # M2-9 完整 happy path
    _helpers.ts                                        # M2-9 抽 chromiumCanLaunch + SKIP_REASON（§14 R8 declaration-level skip 正确范式）
  playwright.config.ts + vitest.setup.ts               # M2-1 + M2-7 + M2-9 

scripts/gen-api-types.sh                               # M2-3 codegen pipeline 脚本

.github/workflows/ci-gate.yml                          # M2-1 frontend init + M2-9 加 playwright install + run step

backend/                                               # M2 followup hotfix
  app/runner/case_normalizer.py                        # M2 hotfix #1 (PR #42) — 抽 normalize_case 共享，scripts/run_m1_dogfood.py 旧 inline 删除转引用
  app/runner/dsn_builder.py                            # M2 hotfix #2 (PR #43) — 抽 build_dsn_map + dsn_map_from_env，scripts/run_m1_dogfood.py 同样转引用
  app/api/runs.py                                      # M2 hotfix #1 (加 normalize_case 调用) + #2 (SqlSessionPool 接入)
  tests/test_case_normalizer.py + test_dsn_builder.py  # M2 hotfix 配套 17 + 8 tests

docs/plans/M2.md                                       # PR #27 创 / #30 #38 #40 推进 [x] 标记
docs/m2-dogfood-2026-05-24-0535.md                     # PR #41 (M2-10 human dogfood 报告)

design.md
  §13.4 + §13.5                                        # PR #26 (M1 实战回顾 + M2 计划补完)
  §14 R26 + R27                                        # PR #44 (dual-code-path + relative-path env defaults)
  §0 v1.4 + v1.5 rows                                  # PR #45 (retroactive bump, 拆 v1.3 catch-all)
  §13.6 + §13.7 + §13.8                                # 本 commit (M2 retro + M3a 计划 + M3b 计划)
```

#### 13.6.3 M2 暴露并固化的 spec / 工程教训

参考 §14 R 编号已入档的两条 + M2 dispatch 实战观察到的 4 条非 R 级模式（暂未升 R，但 dispatch prompt 须显式带）：

1. **§14 R26（已入档，PR #44）** dual code path 分叉：M1 dogfood 5/5 PASS 走 CLI 路径有 inline normalizer；API 路径绕过 normalizer + SqlSessionPool wiring 双双漏掉 → M2-10 dogfood 实测全 case ERROR。修：抽 `case_normalizer.py` + `dsn_builder.py` 共享模块，两条路径强制 import 同一份。
2. **§14 R27（已入档，PR #44）** relative-path env defaults：`DEFAULT_CASES_ROOT = Path("cases")` + `DEFAULT_DATABASE_URL = "sqlite:///./data/runs.db"` 两个相对默认值的 cwd 要求互斥，dogfood 30 min trial-and-error。修：anchor 到 `__file__` 或 README 明列必需 env，启动期 fail-fast 验路径。
3. **同期 parallel PR 改同一份文件**（非 R 级）：M2 round 2 (3 路) + round 3 (4 路) 反复触发 package.json / App.tsx / M2.md / client.ts 冲突。**dispatch prompt 应预提**："如多 PR 同期改这些文件，每 PR 都预留 rebase loop"。
4. **specialist scope creep**（非 R 级）：M2-7 specialist 顺手把 M2-8 RunsPage 整个写完导致 PR #36 (m2-8 standalone) 必须 close。**好事**（实际工作完成）但破坏"1 PR 1 item"clean history 规约。reviewer 在 cross-check 时识别 + plan markdown 写明 "bundled into PR #N"。
5. **specialist deletion blindness**（非 R 级）：m2-8 branch 从 stale base 起，把同期 sibling 文件当 "main 上不存在" 删，rebase 会一并删 sibling 工作。**fix 时先 inspect** `git diff main..branch --name-status`，大量 D 不能盲 rebase。
6. **ci-gate trigger race**（非 R 级）：M2-3 / M2-7 / M2-8 出现"branch 在 origin 上有但 ci-gate 没跑"（GitHub 未收 push webhook 事件），fix = force-push empty rebase 触发 CI 重跑。

#### 13.6.4 5 例 BUG 状态变更证据（M2 dogfood 完成后）

| Case | YAML status (M2 前) | M1 CLI dogfood 证据 | **M2 API dogfood 证据**（新增）| 推断 BUG 实际状态 |
|---|---|---|---|---|
| bug-0001 hashjoin 右表 | open | CLI PASS | **API PASS 2204ms**（真 EXPLAIN，含小表 tmp_test02 选对）| upstream-fixed |
| bug-0002 unnest crash | open | CLI PASS | **API PASS 104ms**（unnest 不 crash + recover mode log 0 matches）| upstream-fixed |
| bug-0003 count-no-statistics | open | CLI PASS | **API PASS 60ms**（ANALYZE 后 NOTICE 流不含 "do not have statistics"）| upstream-fixed |
| bug-0004 CTAS rowcount=0 | open | CLI PASS | **API PASS 44ms**（CTAS rowcount > 0）| upstream-fixed |
| bug-0005 LC_CTYPE upper | open | CLI PASS | **API PASS 5467ms**（LC_CTYPE='C' DB 里 upper(multibyte) 不报错）| upstream-fixed |

**M5 review 阶段统改 `status: open → fixed`**：现在有 CLI + API 两条独立证据链，比 M1 后 §13.4.5 "工具说 PASS = 弱证据" 置信度高一档。但保守做法仍是 M5 时人工对照飞书原文修复 commit / 版本号再统改，**不**因 M2 dogfood 通过就冲动改 status。

---

## 13.9 M4 实战回顾（v1.10 内追加，2026-05-24 写入）

M4 实际跑了 **3 个子轨道并行**（不是顺序 sprint）：M4a 飞书 BUG 补录 / M4b extension 首批 / 附加 skill 硬化 + external_systems category 落地。共 17 PR (#68/#70/#73/#74/#75/#79/#80/#81/#82/#83/#84/#85/#86/#87/#88/#89) + 1 docs PR (本 v1.10)，跨 2 天 (2026-05-23~05-24)。

#### 13.9.1 M4a 飞书 BUG 补录（3 例新 case + sql_driver chain refactor）

| case | PR | 飞书 § | status |
|---|---|---|---|
| **bug-0007-orca-sort-pathkey** | #70 | §9.7 | fixed（SynxDB-4.5.0-build130 验不复现）|
| **bug-0008-pax-toast-vacuum-analyze-crash** | #74 (V1) + #80 (V2 重构) | §9.11 | fixed |
| **bug-0009-union-all-const-distributed-row-order** | #79 | §9.12 | **open**（10 轮 intermittent fail，反转 fixed→open，铁律 1 实战）|

**sql_driver chain refactor**（M4a-2 bug-0008 真集群 dogfood 暴露驱动）：

```
PR #73 (修法 1)   conn.autocommit = True → await conn.set_autocommit(True)
                  ↓ AsyncConnection autocommit 是 read-only property，赋值 = AttributeError
PR #75 (修法 2)   整支 autocommit 分支删除 → 强制 YAML 作者按 §4.1.2 走 psql -c
                  ↓ 后果：bug-0008 setup 用 kind: sql CREATE TABLE 后，
                          step 用 kind: shell + psql -c VACUUM 看不到 table（visibility gap）
PR #80 (修法 3)   sql_driver 每个 kind: sql step 末尾自动 await conn.commit()
                  ↓ 跨 driver visibility 自动恢复：前序 kind: sql CREATE TABLE 对
                    后续独立 psql -c 子进程自动可见
```

附加：bug-0008 user 决策 V1→V2 重构（"step 2 别用 psql -c"）= setup 改 sql + commit-after-step；删除 bug-0006-m3a-dogfood-smoke2 (PR #81，与 smoke.yaml 重复)；SKILL.md cross-check #13 软化承认两种写法都通 Try gate。

#### 13.9.2 M4b extension 首批 5 例（首批 3~5 例上限达成）

| # | case | PR | 核心算子覆盖 |
|---|---|---|---|
| 1 | **ext-pgvector-ivfflat-basic** | #68 | M3b dogfood 副产 / IVFFlat 索引 + L2 距离 + EXPLAIN Index Scan |
| 2 | **ext-pg-partman-range-month-retention** | #82 | RANGE 分区 (1 month) + retention='2 months' + run_maintenance |
| 3 | **ext-anon-dynamic-masking-role-based** | #83 | TDM GUC + SECURITY LABEL + SET ROLE 动态脱敏 / **跨 db** (defaults.database=gpadmin, main step database=testdb) |
| 4 | **ext-plpython3u-numpy-array-distance-matmul** | #84 | PL/Python3u + numpy 1.25.2 三典型 (np.sum / np.linalg.norm / np.matmul) |
| 5 | **ext-postgis-st-dwithin-gist-index** | #87 | PostGIS 2.5.4 USE_GEOS+USE_PROJ+USE_STATS 全栈 + ST_DWithin (geography 球面/geometry 平面) + GIST 索引 + EXPLAIN Index Scan |

**共通约定**（M4b 5 例确立的 case 作者 best practices）：
- 浮点断言用 `abs(actual - expected) < 1e-9` 单 bool（避 IEEE 754 末位 jitter 误判）
- 每 step `expect.not_contains: ["ERROR", "FATAL"]` 兜底（半透明失败防御）
- teardown **不 DROP EXTENSION**（共享资源；DROP CASCADE 牵连其他业务）—— 已写入 SKILL.md cross-check #7 example + notes
- 跨 db case `pg_terminate_backend(...)` 强解 SqlSessionPool 长连后再 DROP DATABASE

#### 13.9.3 external_systems category 落地（PR #88，§4.5 + §13.10）

第三 case 门类 `external_systems`，覆盖外部组件依赖测试（datalake_fdw / hive_connector / PXF / zombodb）。**§4.5 plug-and-play 设计实战印证**：业务代码**零行改动**（cases.py `for cat in categories: cat_dir = root / cat.dir_path` 自动扫；CasesPage.tsx 数据驱动；CategoryOut.name=string 不是 enum，前端 codegen 无需 regenerate）；整条改动 = Alembic seed migration (0002) + 空目录 (`cases/external-systems/.gitkeep`) + 1 行 skill prefix + fixture 数字 2→3 = 75 行净增。

5 项设计决策（PR #88 设计文档 `docs/plans/external-systems-category.md`，用户 2026-05-24 拍板）：
- `dir_path = external-systems`（kebab，与 bug-regression 一致）
- `id_prefix = xs-`（4 char 无 startswith 冲突；`ext-sys-` 与 `ext-` startswith 重叠故否决）
- `status_whitelist = [stable, awaiting_env, deprecated, stub]`，`default = awaiting_env`（外部环境未必就绪的 lifecycle）
- `display_order = 30`
- `external_deps` 字段**本 sprint 仅文档性质**，runtime injection (Jinja `{{ external.<svc>.host }}` 渲染 + `external/<svc>.yml` 读取 + host SSH 路由) 推 M6-5

PR #89 followup：SKILL.md 5 行外部服务追问从 "Category-tagged extension 组" 迁出到新 "Category-tagged external_systems 组"（FDW / 配置文件 / Kerberos / 远端 CLI / warmup 是外部服务可用性问题，不是 PG 扩展功能问题）；lint 加 `if category == 'external_systems'` banned pattern。

#### 13.9.4 skill 硬化 3 PR 链

| PR | 改动 | 触发 |
|---|---|---|
| **#85** | SKILL.md frontmatter `model: opus` (generic) → `model: claude-opus-4-7` (精确版本) + lint 收紧到 exact-match | 用户 2026-05-24 "skill 相关坚持改用 opus 4.7，不再使用 sonnet" |
| **#86** | opus self-review 7 spec fixes：/admin/settings 404 删 grounding / sessions list→mapping (backend 真接受的 shape) / 5题→6题三处统一 / cross-check #3+#8 合并 (13→12) / DROP EXTENSION 反例 + 通用规则 / created_by example 修对 / Fetch "三个 vs 四个"端点数同步 | 用户 "请用 opus 模型 review skill 及周边" |
| **#89** | SKILL.md 5 行外部服务追问 extension 组 → external_systems 组 + lint 加 external_systems banned pattern | 用户 "迁 6 条追问"（实际 5 条；shared_preload_libraries 留 extension 组）|

memory `feedback_model_override_2026-05-24.md` 拆 §A (agent 一次性 override) + §B (skill 永久钉 opus 4.7)。

#### 13.9.5 §14 R28 候选 → 入档

**R28 intermittent BUG 采样不足导致假阴性**：低重复次数 (≤3 rounds) 跑随机性 BUG 复现脚本 statistically 看不到 fail。

**触发场景**：bug-0009 §9.12 UNION ALL 行序错误是 intermittent 触发——首版 3 rounds repetition，本地 + dogfood + CI 全 PASS → status: fixed。用户 review 提"3 次会误判"，改 10 rounds → round 1 立刻 fail → 反转 status: open。3 rounds 看不到 = false negative。

**正确做法**：
- 默认 **≥10 rounds** 跑随机性触发的复现脚本
- 必要时 **binary search 最低 N**：从 10 起，若一直 fail 可降到 5/3/1；从 10 起若 PASS 再加到 30/50 确认稳定
- 在 case `notes:` 写明"intermittent 触发；N rounds 反映 X% 命中率"，提供 reviewer 决策依据
- ⚠️ **铁律 1 实战**：低重复跑 PASS 不能写 `status: fixed`——必须先证 fail 可复现，再证 fix 后不可复现

**preflight 教训来源**：bug-0009 V1 PR 落 main 后 user 立刻喊回，反转 status；用户 catch 比 reviewer / CI / dogfood 都早。新加：M4a 类 PR review 时显式问"这是 intermittent 触发吗？rounds 是不是 ≥10？"

#### 13.9.6 §0 changelog gap 教训

v1.7 → v1.10 之间 spec 真改了 ~15 处（§4.1.2 / default DB gpadmin / sql_driver chain / SKILL.md 多次硬化），但 §0 changelog **没有 retroactive bump**——v1.5 上次主动拆 catch-all 的教训没传承。本 v1.10 一次性补 v1.8 / v1.9 / v1.10 三 row，向前对账（PR #45 之后第二次 retroactive bump）。

**未来防御**：M5 / M6 计划完成定义里加一句"§0 changelog 当 sprint 收尾时主动 +0.1"，避免下次又攒成 catch-all。

---

---

## 13.14 M6 实战回顾（v1.14 内追加，2026-05-25 写入）

**M6 sprint 主线** = 完成 §13.12 计划的 6 个子步骤 + 真集群 dogfood：M6-1 SSE 进度条 / M6-2 artifacts download / M6-3 history diff / M6-4 Admin UI (skip-list + settings) / M6-5 external_deps runtime injection / M6-6 dogfood (M4c-1 + M6-1~5)。**全部 dispatch 走 user-driven 手写**（非 foreman），节奏 6 PR + 4 parallel 小 PR ≈ 2 小时夜间 push。

#### 13.14.1 6 子步骤交付时间线

| 子步骤 | PR | 文件级 deliverable | novel mechanism (§14 R30 self-check) |
|---|---|---|---|
| M6-1 SSE | #110 | `app/runner/event_broker.py` (NEW) / `app/runner/orchestrator.py` (publish hooks) / `app/api/runs.py` (`GET /runs/{id}/stream` + `_execute_run` publish terminal) / `frontend/src/routes/RunDetailPage.tsx` (EventSource client + polling fallback) | SSE/event-broker 端到端 = 1 |
| M6-2 artifacts | #112 | `app/api/runs.py` (ArtifactInfo + list + download endpoints + path traversal 防护) / `frontend/src/routes/RunDetailPage.tsx` (CaseArtifacts disclosure component) | artifacts API + UI disclosure = 1 |
| M6-3 history diff | #114 | `frontend/src/routes/RunsDiffPage.tsx` (NEW) / `frontend/src/App.tsx` route / `frontend/src/components/Layout.tsx` breadcrumb / `frontend/src/routes/DashboardPage.tsx` "Compare last 2 runs" link | diff classification + sorting + UI = 1 |
| M6-4 Admin UI | #115 + #117 | `app/api/admin.py` (skip-list CRUD + settings PUT/GET + `require_admin_password` 守门) / `app/storage/sqlite_store.py` (`add_skip_list_entry` / `delete_skip_list_entry` / `list_settings` 3 个 helper) / `frontend/src/routes/AdminPage.tsx` / `AdminSkipListPage.tsx` / `AdminSettingsPage.tsx` (NEW) / Sidebar Admin 改可点 + Layout breadcrumb 3 个新映射 | admin CRUD 模式 (auth-gated mutation + UI) = 1；F1 wiring fix (`_execute_run` 接 skip_list) = followup in #117 |
| M6-5 external_deps | #116 | `app/runner/external_deps_loader.py` (NEW, collect + load_context + 4 失败模式 warn-skip 不 raise) / `app/api/runs.py` (`_execute_run` 注入 `jinja_context["external"]`) / `app/runner/case_normalizer.py` (修 drop external_deps bug) / `external/elasticsearch.yml` (sample) / M4c-1 case ES URL 2 处 Jinja 化 | external context loading + injection + render 链路 = 1 |
| M6-6 dogfood | #117 | `app/api/runs.py` (F1 wiring fix: load skip_list from DB and pass to orchestrator) / `backend/tests/test_api_runs.py` (regression test) / `docs/m6-dogfood-2026-05-25-0212.md` (报告) | F1 wiring fix (无新机制，单点 plumbing) |

#### 13.14.2 Parallel UI 小 PR（与 M6 不冲突）

| PR | 内容 | 触发 |
|---|---|---|
| #107 | Dashboard RecentRunsTile counters 全 0 修 (verdict 派生 vs lifecycle status) | 用户截图反馈 |
| #109 | RunsPage 隐藏 no-op category chip | 用户反馈 chip 点了没用 |
| #111 | CasesPage header "+ New Case" CTA | 用户反馈 New Case 入口不显眼 |
| #113 | Dashboard quick-actions 去掉重复 "+ New case"（PR #111 后冗余） | 用户主动要求清理 |

**parallel 授权来源**：用户 M6 sprint kick-off 时说"M6 不要并行，但 UI 小 PR 若不冲突可与 M6 parallel"——这些 PR 与 M6 子步骤完全不同文件，符合授权。

#### 13.14.3 实战暴露的 2 个 bug

**F1 — M6-4 skip-list wiring missing**（dogfood Run #17 暴露 → fix in PR #117）
- 现象：M6-4 PR #115 落了 `/admin/skip-list` CRUD endpoints + frontend UI，单测全过；但 dogfood 加 skip 条目后 case 仍 PASS（不 skip）
- 根因：`backend/app/api/runs.py::_execute_run` 调 `orchestrator.run_suite(...)` 时**没传 skip_list kwarg**。orchestrator 自 M2 就支持 `skip_list` 参数（`_matching_skip_rule`），API 路径从未 wire。这是 pre-M6-4 就存在的 dual-path divergence——后端有能力但前端入口不通。
- Fix：`_execute_run` 在调 `run_suite` 前 `sqlite_store.get_skip_list(sess)` 转 `list[dict]` 传 `skip_list` kwarg；失败 fall back 空 list + log warning (R9)
- 教训：**M6-4 backend 单测 `test_create_skip_list_entry_round_trip` 只测了 row persists，没测"添加条目后真跑 run 验证 case 被 skip"——单测自调 endpoint 绕过 wiring，§14 R26 dual-code-path 一个不那么明显的变体（路径分叉不是"两份代码"而是"endpoint 落地但 runtime 不读"）**。新加 regression test `test_execute_run_passes_skip_list_to_orchestrator` seed 条目 + 调 `_execute_run` 断言 captured["skip_list"] 含该条目，防退回。
- 类比：cbcopy PR #31 DDL filter "covers 4 modes" 实际只调 1 mode 的故事重演（用户铁律 2 "Covers X / Y / Z 是 claim 不是 fact"）

**F2 — Step 02 (precondition) artifact missing from list**（低影响 followup）
- 现象：run #15 的 artifacts 列表中 step_idx 0/1 (setup) + 3/4/5+ (ZQL queries) 全有，但**缺 step_idx 2** (precondition ES health check)
- 假设：step 2 是 `kind: shell + su - gpadmin -c 'curl ...'`，`su` 子 shell 把 stdout 路径切换可能让 `execute_shell_step` 拿到空 stdout → `_write_artifact` 对空内容返 None 不落盘
- 影响：低——case PASS 证明 `stdout_contains: '"status" : "green"'` 评估对了某个非空值；只是没有用户可下载的 artifact
- 决策：留 backlog 不在 M6-6 scope 内。下次触 shell_driver 或 M7+ 时一并查

#### 13.14.4 §14 R 实战教训

**R28 (intermittent sampling) 满足**：M4c-1 case 3 轮 real-cluster verification（Run #15 PASS / #16 PASS / #18 SKIP-as-expected），全部一致。external_systems case 依赖外部 ES 服务，不存在 bug-0009 那种"3 rounds 假阳性"风险。R28 ≥3 rounds 底线已踩到。

**R30 (specialist multi-suspect feature bundling) 全 sprint 0 命中**：每个子 PR 严格 ≤1 novel mechanism。最复杂的 M6-1 SSE 涉及 4 个模块（broker / orchestrator / endpoint / EventSource client）但**单一新模式 = "SSE/event broker 端到端"，4 个模块是同一 coherent unit**。reviewer 视角看这种 vertical-slice PR 比 "horizontal-slice 一次落 4 类模块" 更容易接受——前者是单一 mental model，后者要拼接 4 个独立 mental model。

**R26 (dual-code-path) 实战 1 例修复 + 1 例预警**：
- 修复：`case_normalizer.normalize_case` drop `external_deps` 字段（yaml_loader 校验保留 + normalize drop = 一种 dual-path divergence，下游 `collect_external_deps` 收到空），本 sprint M6-5 PR #116 加字段透传 + 3 个新 test 防退
- 预警：F1 wiring fix 是 **第二种** R26 变体——"endpoint 落地但 runtime 不读"。本来不算典型 dual-code-path 但本质是同一类问题：**spec 层声明的能力 vs 运行时实际接通的能力**之间的 gap。新增加 §14 R 候选条 "wiring-gap" 留待 v1.x 沉淀

**R29 (reviewer false-negative) 0 命中**：本 sprint 全 user-driven 手写无 reviewer agent 介入；规则未被实战检验

**R31 (foreman stuck on PR CI fail) / R32 (CI artifact missing) 0 命中**：同上，全 user-driven 路径

#### 13.14.5 §13.12 完成定义对照

- [x] M6-1 ~ M6-5 全 [x] + ci-gate 全绿
- [x] M6-6 dogfood: ≥1 external_systems case (M4c-1) Try 跑通真集群 ✓ (Run #15 PASS)
- [x] SSE 进度条工作 ✓ (3 events captured)
- [x] artifacts download 可用 ✓ (9 files / 2885B verified)
- [x] Admin UI skip_list 改动持久 ✓ (after F1 wiring fix, Run #18 SKIP w/ persisted reason)
- [x] `docs/m6-dogfood-<ts>.md` 报告 ✓
- [x] §0 changelog 主动 +0.1 (v1.14) ✓ (本行)

M6 sprint **完成定义 7/7 全勾**，sprint 收尾。

#### 13.14.6 数字对照（before / after M6）

| 维度 | M5 收尾 (v1.12) | M6 收尾 (v1.14) | Δ |
|---|---|---|---|
| frontend vitest | 127 | 187 | +60 |
| backend pytest | 345 | 388 | +43 |
| design.md line count | ~3142 | ~3220 (含本节) | +78 |
| §14 R 数量 | R1-R32 | R1-R32 (未新增，候选 "wiring-gap" 留 v1.x) | 0 |
| merged PRs (cumulative) | ~99 | ~117 (+11 M6 + 4 parallel + ~3 cherry) | +~18 |

#### 13.14.7 sprint 总结一句话

**M6 是 v1.x 系列第一个 user-driven 全手写的复杂 sprint**（M0-M3 用 foreman + specialist；M4 部分手写；M5 失败链后 user 决定 M6 全手写）；6/6 子步骤 + 4 parallel UI 小 PR + 1 dogfood + 1 wiring bug 暴露并修复，总 ~2 小时夜间 push 闭环。证明 user-driven 路径在已 R-stabilized 的代码库上**显著比 foreman 路径快**（M5-1 foreman 路径 PR #94 + 重写 PR #95 共耗 ~6 小时）。下个 sprint （M7 LLM 接入）若 dispatch foreman，R29-R32 hard-gate 已就位，应能避免 M5-1 重演。

#### 13.14.9 M6 收尾后 UX 迭代 Wave 2（v1.16 内追加，2026-05-25 写入）

v1.15 #123 砍 Settings 后用户继续 dogfood，连续提 3 轮观察 → 3 PR：

| PR | 触发 | 改动 |
|---|---|---|
| **#125** | "external/<svc>.yml 是 vi 编辑？" | 加 `/admin/external-services` read-only 浏览页 + 顶部 hint banner（编辑方式 = `vi + git commit`）+ inline parse_error；顺手修 `external/dut.yml` hosts (`synxdb-0001` → `std`) + 加 mdw/std/sdw1/sdw2 topology 注释 |
| **#126** | "加删除 case 功能 (历史保留)" | 先想要 combobox 保留显示已删 case（历史搜索），用户反思后简化：删除 = forever，combobox 不显已删。`DELETE /admin/cases/{case_id}` 删 YAML + 教育性 confirm dialog 引导回 Skip List；require_admin_password 守门 + path traversal 双重防御；不自动 git commit/push |
| **#127** | "为什么外部系统集成测试不在 Dashboard 第 2 行？" | §14 R4b 实战修：删 `bugCategory()` / `extensionCategory()` 两个硬找 helper，row 2 改 `data.categories.map(...)` 跟 row 1 同模式 |

**Admin 页定型为 3 入口**（v1.16 起稳定）：

| 入口 | 用途 | 可逆性 |
|---|---|---|
| Skip list | 暂时禁用某 case（支持 until_date 自动过期）| 删条目即恢复 |
| External services | 浏览 `external/<svc>.yml` 配置（read-only）| N/A — 仅查看 |
| Delete case | 永久删 YAML 文件，历史 run 保留 | 需要 git restore 回滚 |

**§14 R4b 实战 N+1 反模式**（候选入 §14.x）：

同一文件里 row N 数据驱动 vs row N+1 硬编码是**隐性 R4b 违反**。M5-2 DashboardPage row 1 数据驱动从一开始就对；row 2 落地时只考虑当时 2 个 category 偷懒硬找两个 helper，给 M4c 加 external_systems 后留 visibility gap（从 v1.10 落 external_systems → v1.16 才被用户注意，间隔约 1.5 个月）。

**反模式特征**:
- 同一组件 / 同一 page 内多个 list/grid，**N 个数据驱动，N+1 硬编码**
- 静默 — 现有 2 个硬编码值都"看上去正常"，缺的第 3 个用户不知道该有
- 永远要等"加新元素时才暴露"

**Review 阶段防御**:
- 看到 `*.map(category => ...)` 或类似数据驱动 pattern 时，**主动扫同文件**有没有"看上去一样但写死 2 个具名变量"的对应 list
- 把"row 1 数据驱动 + row 2 数据驱动"当 R4b 实战 baseline，row 2 写死 = 主动 flag

**§14 R 候选条 "R4b-secondary-row-hardcoded"** 留 v1.17+ 沉淀（pattern 至少需要再撞 1 次才确认是 sprint-wide 反模式）。

**M6 post-iter 累计**（wave 1 + wave 2 = 9 PR，2026-05-24 至 25 连续 2 晚）:
- vitest 156 → 204 (+48)
- pytest 388 → 396+ (+8)
- merged PRs 117 → 127 (+10)
- 全部 user-driven 手写，0 foreman dispatch
- 平均每 PR ≤30 min（review 阶段已 R-stabilized，没有 R29-R32 类失败链）

#### 13.14.8 M6 收尾后的 UX 迭代（v1.15 内追加，2026-05-25 写入）

M6 sprint 主交付后用户陆续 dogfood，提出 5 轮 UX 优化 → 5 个独立小 PR + 1 个 refactor PR：

| PR | 触发 | 改动 |
|---|---|---|
| **#119** | 用户："Setting 里 dev_db_url / cluster_topology 拍啥用处？" | 砍 2 个无 consumer 的 allowlist key (M6-4 §13.12 plan 占位但 backend 没接通)；剩 3 个真用的 (jinja_context / dut_hosts / server_log_path) |
| **#120** | 用户："case_id 容易写错，能否下拉？" | shadcn Combobox + cmdk (新 `ui/popover.tsx` + `ui/command.tsx`) + 复用业务组件 `CaseIdCombobox.tsx`：fuzzy 搜 id 或 title，rich row = id mono + title 截断 + status badge；polyfill jsdom 缺的 ResizeObserver + scrollIntoView |
| **#121** | 用户："Runs 搜 ID 意义不大，想搜哪几轮含某 case" | backend `GET /runs?case_id=X` SQL JOIN case_results；前端 `useFilters` hook + `case_id` 字段 URL 持久化；RunsPage FilterBar 下方加 "Includes case:" + CaseIdCombobox (PR #120 第 2 处复用)；搜框 hay 从 4 字段收窄到 2 (`version + triggered_by`)，删除冗余 id+verdict 搜索（chip 更精准） |
| **#122** | 用户："Skip List 日期框只显示'年/月/日'，做什么用？" | `type="date"` 不渲染 placeholder 属性 (HTML spec)；改显式 `<label>` "skip 自动过期日 (可选) — 不填 = 永久 skip 直到手动删；填了 = 当天起恢复跑" |
| **#123** | 用户："Settings 排啥用处？这个设计主要考虑什么场景？" | **设计层重大决策**：承认 Settings 是过度设计；外部依赖统一 `external/<svc>.yml` 体系 (M6-5 落地)，**DUT 也是一个外部系统**；新 `external/dut.yml` + `dsn_map_from_external_or_env` (file > env > default per-field)；`_execute_run` 始终包含 dut；删 `/admin/settings` GET+PUT endpoints + AdminSettingsPage frontend + 6 个 settings 测试；保留 storage helpers + SystemSetting model 作 dead code (DB 字节几乎不计，未来需要再加回不用 Alembic migration) |

**设计层的核心收获 (#123)**：原 M6-4 设计假设"GUI 编 JSON > 编辑 yaml 文件"，dogfood 证伪 — 用户更愿意编 git 跟踪的 `external/*.yml` 文件（diff 可视，change history 自然走 PR）。"Admin GUI" 在单人项目里其实是反模式：单一 source of truth + git 工作流足够。

**M6-6 F1 wiring bug forensic 的延伸**：F1 ("M6-4 endpoint 落了但 _execute_run 没读 skip_list") 后再看 #123 的 Settings — 同样是 "spec 层声明能力 vs runtime 实际接通"的 gap，但比 F1 更深：F1 是 wiring 缺失，**Settings 是整套 GUI 假设都不成立**。两个案例联合 → §14 R 候选条 **"wiring-gap" / "vestigial-feature"**，留待下次 sprint 末沉淀。

**DB cleanup 副产**：删 EMPTY verdict run #18 (M6-6 skip-test 跑出来的，1 case skipped → counters 全 0 → runVerdict 派生 'empty')。runVerdict 的'empty' 状态对 fully-skipped 跑显得歧义，未来若多见再修 runVerdict (低优 backlog)。

**数字最终累计 (M6 + post-M6 iter)**：vitest 127 → 195 (+68) / pytest 345 → 392 (+47) / merged PRs ~99 → ~123 (+24) / design.md +220 line (v1.14 + v1.15 changelog + §13.14 7 子节 + §13.14.8)。

**节奏观察**：M6 主 sprint 2h；post-M6 iter 5 PR + 1 refactor 在同一晚连续 push，每个 PR ≤30 min。user-driven + R-stabilized + 良好 testid 习惯让小迭代 cost 接近"评估一下要不要做"的成本。

---

---

