# Review 流水线补齐设计（reviewer 焊进 foreman 流水线 + smoke-runner 落地）

> 状态：**设计稿 v3,待用户最终确认后开工**。确认后由 pm-designer 正式入 design.md §8/§15,再实施。
> 演进：v1(user-driven 手动入口) → v2(foreman 派 + reviewer 两段式调内置) → **v3(避开技术死结,见 §1)**。

---

## 0. 用户最终决策（2026-05-28，三步收敛）

1. reviewer 想用内置 + 保留 §14（v1/v2 方向）
2. reviewer/smoke 改回 foreman 派活，重启 foreman 作为日常开发方式
3. **(最终,推翻 v2 的内置集成)**：
   - **现有自研 reviewer 保留全功能**（§14 联动 + 6 域审查 + verdict），**焊进 foreman 流水线**自动跑
   - **CC 内置 `/review` / `/ultrareview` 由用户手动调用**，不进自动流水线
   - smoke-runner 同样回 foreman 派活

---

## 1. 为什么 v3 推翻 v2（技术死结实测）

v2 想让 reviewer subagent 内部"先 §14 再调内置 /review"(两段式)。**2026-05-28 实测验证发现死结**:

- subagent **能**有 Skill 工具、**能 invoke** 内置 /review(general-purpose subagent 实跑确认,推翻文档说法)。
- **但** 内置 /review、/code-review 自己干活要**派 finder/verifier 子 agent**,而 **subagent 不能再派 subagent**(嵌套禁止,subagents.md L62/L359 + 实跑 caveat 双确认)。
- 结论:reviewer subagent 调内置 review = **能启动,跑不完整**。方案 X 死。fallback Y(Bash 嵌套 claude -p)/Z'(foreman 自己调)都要额外验证 + 加复杂度。

**v3 用户决策直接绕开**:不让任何 subagent 调内置 review。自研 reviewer 做它本来能做的(§14 + 6 域,纯 Read/Bash/Grep,零嵌套);内置 review 用户在顶层交互手动调(顶层 session 无嵌套限制)。**全程不碰死结。**

---

## 2. 两个根因（v3 只需修一处半）

| 根因 | v3 是否要修 |
|------|------------|
| **A：foreman 不启动** | 用户决策重启 foreman 作为日常方式(行为改变,非代码) |
| **B：foreman.md loop 算法缺 wiring** | **要修**:loop 没有"PR 创建后派 reviewer""merge 后派 smoke-runner"步骤,光重启 foreman 这俩 agent 仍不会被派 |

v3 核心代码工作 = **修根因 B(焊 foreman wiring) + 落 smoke.sh**。reviewer.md 几乎不动(保留)。

---

## 3. 目标流水线

```
你 /foreman <sprint>   (经 scripts/dispatch-foreman.sh wrapper,§14 R25)
  └─ foreman verify-loop (§15.1,补 2 个 dispatch 步骤):
       step 3   dispatch specialist (worktree) → 改代码 → 开 PR
       step 3.5 ★新增★ PR 创建后 dispatch reviewer (subagent,只读):
                  reviewer 保留现有全功能 = §14 联动 + 6 域审查 + verdict
                  (纯 Read/Bash/Glob/Grep,不调内置 skill,无嵌套问题)
                  → verdict 回 foreman + gh pr comment
       step 4   foreman 据 reviewer verdict + ci-gate 决定 merge / 派 fix
       step 5   CI-gate poll → merged
       step 6   ★新增★ merge 后 dispatch smoke-runner (run_in_background:true):
                  smoke.sh 全链路跑真集群 → GO/NO-GO 回 foreman

(并行,流水线之外)
  你想深挖某 PR → 手动 /review <PR> 或 /ultrareview <PR>   ← 内置,顶层调,无限制
```

---

## 4. 实施清单

| # | 文件 | 改动 | 估行 |
|---|------|------|------|
| 1 | `.claude/agents/foreman.md` | loop 补 step 3.5(派 reviewer) + step 6(派 smoke-runner) + §15.1.3 state.json schema 加 `reviewer_verdict`/`smoke_verdict` + hard rule(verdict=REQUEST_CHANGES 或 smoke=NO-GO 不算 done) | ~40 |
| 2 | `.claude/agents/reviewer.md` | **基本保留**;仅加一句定位说明"我是 foreman 流水线自动 reviewer,做 §14+6域;内置 /review 是用户手动补充,不归我" | ~5 |
| 3 | `scripts/smoke.sh`(新) | 全链路自包含:自起 backend(8000,复用 README env 注入) → POST /runs 跑 1-2 个 `status:fixed` known-good case(如 lg-bug-0001-hashjoin-right-table) → 轮询 → 验 verdict=PASS → 自停;产物落 docs/status/smoke-<ts>.log;避开 destructive case | ~80-120 |
| 4 | `.claude/agents/smoke-runner.md` | 删 L28 "until then, run a no-op precheck" 占位语,指向真实 smoke.sh | ~5 |
| 5 | 测试 | foreman dispatch lint(check_agent_dispatch.sh)更新 + smoke.sh 自测/dry-run | ~20 |
| 6 | `design.md` §8.1/§8.3/§15.1 + §0 v1.22 | reviewer 行注明"foreman 流水线自动 + 内置手动补充";§15.1 loop 补 dispatch 步骤;记账 | ~30 |

**smoke.sh 前置已确认**(2026-05-28 实测):真集群常驻(mdw=coordinator,8 primary seg);`external/dut.yml` 现成,backend `dsn_builder.dsn_map_from_external_or_env` 已读它,smoke.sh 复用。

---

## 5. 不做的事

- 不做 reviewer 两段式调内置 review(v2 方案,撞嵌套死结)。
- 不做 `scripts/review-pr.sh` 手动入口(v1 方案)。
- 不做 `scripts/check-section-14.sh`(§14 检查保留在自研 reviewer 内部,不外抽脚本)。
- 内置 /review **不进自动流水线**,用户手动调。
- 不让 reviewer 点 GitHub Approve(§11 Q10 不变)。

---

## 5.5 端到端实测结论（2026-05-28，throwaway PR #180 + revert PR #181）

**A/B 流程机制全走通**（非推测，真跑）：
- A：开 PR 不武装 → 即便 CI=SUCCESS 也停 open 不自合（PR #180 实证 `autoMerge=null`+`state=OPEN`）；reviewer APPROVE 后才 `gh pr merge --auto` → 事后武装生效 → 合。
- B：squash commit 单-parent 可 revert；自动开 revert PR → 走 ci-gate → 合（PR #181）；main 探针移除、无关文件保留。

**实测抓到 2 个设计缺陷（猜不出来的，必须落实施）**：

1. **§14 A 类 grep 会假阳性——推翻"零误报"假设**。实测 grep `external_systems` 命中了 cron 报告里一句**文档叙述**，误判成 category 硬编码。根因：grep 不分"代码硬编码"vs"文档/注释提到词"。
   - **修正**：A 类检查器**必须限定只扫代码文件**（`.py/.ts/.tsx/.yaml/.sh`，排除 `docs/**` + `*.md`），且区分代码 vs 注释/字符串；检查器自己要带测试。
   - **D1 结论收紧**：A 类 grep **不能裸进 ci-gate**（会误挡文档 PR）——要么先解决误报（限定范围+测试）再进，要么只作 reviewer 内部参考不进 CI。倾向后者：§14 检查留在 reviewer 内部，不进 ci-gate 强制。

2. **squash commit 自动 revert 会误伤——B 的真实风险**。若 squash commit 混了多个改动（实测探针 PR 混进了 cron status 报告），`git revert <sha>` 全删。
   - **修正**：foreman 自动 revert 前**必须确认 squash commit 只含目标改动**（`git show <sha> --stat` 核对文件清单 = 该 PR 预期范围）；不干净则改精确回退或 escalate。
   - 顺带：cron reporter 有未 push 的本地 commit（git 卫生问题），导致开分支带进无关文件——reporter 落地时要确保 commit 后 push。

## 5.6 真实多 PR sprint 端到端验证（2026-05-28，`m6-run-experience-deepening`）

§5.5 只用 throwaway 单 PR 探针验过机制；本次首次用**真实功能 sprint**（6 item / 6 PR #189~#194）跑完整自动链，证明流水线在连续多 item 下稳定。

- **结果**：6/6 merged，`scripts/dispatch-foreman.sh` 对账 `foreman_exit_code=0` / `foreman_returned_final_json=True` / **`r25_violation=False`** / 6 PR verified-from-gh / 9 of 10 rounds / ~1h49m。每 item 走 specialist un-armed PR → reviewer 前置闸门 → APPROVE 后 foreman 武装 → ci-gate → **前台同步 smoke（同轮消费 GO）** → 下一 item。
- **reviewer 作真闸门**：3 次 REQUEST_CHANGES 各抓真问题（errorCache 双渲染 / 改页面踩坏既有 e2e 契约 testid / §14 R30 stale-branch），非橡皮章。
- **新教训：串行 worktree 不天然免冲突**。foreman 一次派一个、合一个再派，但 specialist 分支若早于上一 PR 合入 main 时切出，仍夹带已合并 commits（#193 backend：`rebase --onto origin/main` 恢复纯净 diff），靠 reviewer R30 兜住。
- **smoke 修法补强**：v1.23 前台同步派发只在单 sprint 验过，本次 6 次连续 GO、零 r25_violation，样本补强。

### 5.6.1 附带调查：reviewer 本地 e2e + e2e mock 架构（结论：不改 CI）

- reviewer verdict 常报 `Playwright e2e: SKIPPED (libgbm not available on reviewer host)` —— 实测**假阳性**：`/lib64/libgbm.so.1` 在、cached chrome-headless-shell `--dump-dom` 实跑 exit=0。根因 Playwright dep-checker 是 Debian 中心，在 RHEL **el9** 按 `libgbm1` 包名误报 missing。
- 但 **e2e 全 `page.route()` mock 后端**（`frontend/e2e/*.spec.ts` 头明写 "All API calls are intercepted — no real backend needed"，webServer 只起 vite、CI 不起 :8000）→ reviewer 本地跳 e2e **无覆盖损失**；曾以为的"纯后端 PR 漏 e2e 洞"是**误判**（mock 不反映后端契约，后端 PR 跑 e2e 也抓不到）。
- 真实覆盖结构**无真空**：前端行为=e2e(mock) / 后端契约=pytest / 类型契约=`gen:types`+tsc / 真集成=post-merge smoke。**决策：不动 `ci-gate.yml`（方案 A）。**
- **残留隐患（待方案 B，未做）**：**mock 漂移**——e2e fixture 是对后端响应 shape 的硬编码假设，后端真改 shape 后 fixture 失真但 e2e 仍绿。治法 = CI 加一条真集成 e2e（起真 :8000 + 去 mock 跑 1-2 条 happy path）或 CI 检 `gen:types` 后 `git diff` 须为空。属新测试架构活、非改 filter。

## 6. 待确认决策点

**已锁定**:
- ✅ 自研 reviewer 保留全功能 + 焊进 foreman 流水线
- ✅ 内置 /review 用户手动调,不进流水线
- ✅ reviewer/smoke 回 foreman 派,重启 foreman 作为日常方式
- ✅ smoke 全链路 + 跑 fixed case + 自包含自起自停

- ✅ A/B 流程机制端到端实测走通(§5.5)
- ✅ D1 收紧:§14 A 类检查留 reviewer 内部,不裸进 ci-gate(实测会假阳性误挡文档 PR)
- ✅ **真实多 PR sprint 端到端验证(§5.6)**:6 item/6 PR 全自动链 merged,r25_violation=False,reviewer 抓 3 个真问题
- ✅ **e2e 覆盖结构调查(§5.6.1)**:reviewer 本地 e2e 是 el9 假阳性 + e2e 全 mock → 无覆盖真空 → **不改 ci-gate(方案 A)**;残留 mock 漂移待方案 B

**待你拍板**:
- **D5**:smoke.sh 自起自停 backend 确认?(荐 是,自包含)
- **整体**:reviewer + smoke 一起补,还是先 reviewer 后 smoke?(荐 一起,改动已不大)

**实施第一步**:改 foreman.md 补 wiring(根因 B)——这是"焊进流水线"的实质,也是 reviewer/smoke 之前从没被派的真因。

**实施时必须带上 §5.5 两个实测修正**:(1) §14 A 类检查限定只扫代码文件 + 带测试;(2) foreman 自动 revert 前核对 squash commit 文件清单。

---

## 7. reviewer 功能增强 backlog（2026-05-28 入档）

> 范围说明:本节**撇开"reviewer 有没有被调用到"(=§0~§6 的 wiring 问题)**,纯列 reviewer agent **自身能力**还可以加什么新功能。也撇开"接 CC 内置 /review"(已在 §0 决策:内置走用户手动,不进流水线)。这些是**候选增强,非已锁定**,等 §0~§6 wiring 落地、reviewer 真跑起来后再按价值挑做。

**⚠️ 定位边界原则(2026-05-28 评估补充,贯穿所有 E)**:reviewer = merge **前**的**快闸门**(merge 在等它),只放**轻量**检查(grep / dry-run / 格式 / 语义判断,秒级)。**重活(起真集群实跑 case、全量 coverage)归 smoke(merge 后,可慢,background)或 ci-gate,绝不塞 reviewer**——否则前置闸门被拖慢,违背 reviewer 定位。三层分工:reviewer 快闸门(前) / smoke 真集群验收(后) / ci-gate 单元+静态(GitHub runner)。E1/E7 据此归置(见下表)。

按"对本项目(bug-regression harness)的对口度"排序:

### 7.1 项目独有、最高杠杆（CI 和通用 review 都给不了）

| # | 增强 | 现状缺口 | 做法要点 |
|---|------|----------|----------|
| **E1** | **跑被审的那条 case(按边界原则【拆】)** | reviewer 现在只跑 `pytest/ruff/tsc/playwright`(`reviewer.md:14`),全是通用工程检查;但大量 PR 是 `cases/*.yaml`,真正契约是"buggy build 复现 / fixed build PASS" | **① loader+Jinja render dry-run** (catch §14 R26 normalize 丢字段/模板渲染失败) → **留 reviewer**(纯解析,秒级,符合快闸门)。**② 真集群实触发一次 run 验 verdict → 归 smoke**(merge 后,重活,already smoke 地盘),**不放 reviewer 前置闸门**(会拖慢 merge)。注:smoke 当前是"跑 known-good 试纸验工具链";E1② 是"跑被审的那条 case 验内容"——可作 smoke 的一个扩展模式,但属 merge 后 |
| **E2** | **consumer-impact map(R26 自动化)** | §14 R26 dual-code-path(backend 契约 + N 处 frontend 消费点须 1:1,design.md:2649)反复出现;reviewer 现在只靠 cheatsheet 提醒"记得看 R26",无动作 | api/schema PR 改了 endpoint/TypedDict/storage 字段 → 自动 `grep` 全仓消费站点,列出"被这 N 处消费,逐一核对是否同步改"。确定性活,最易漏 |
| **E3** | **把 §2 claim-vs-fact 产出成"补测试"** | 承接 cbcopy PR #31 教训(CLAUDE.md §2);现在即便发现"claim 覆盖 4 mode、实际 wire 1 mode",也只能写一句话 | reviewer 直接**生成证明 wiring 的测试代码**(pytest 或 case assertion),用 GitHub ` ```suggestion ` 块贴出。从"指出缺测试"升级到"给出缺的测试"。仍只读(评论),不破 hard rule 1 |

### 7.2 通用但高价值（可用性 / 降噪 / 闭环）

| # | 增强 | 现状缺口 | 做法要点 |
|---|------|----------|----------|
| **E4** | **差分再审(differential re-review)** | REQUEST_CHANGES 后 PR 更新,reviewer 会从头重审整个 diff | 记住自己上一条 verdict 评论 → 再审只看新 commit + 逐条核对"上次 findings 改了没"。闭环 + 省 token + 不重复 litigate。verdict 从一次性快照变有状态 |
| **E5** | **每条 finding 带 severity + confidence** | findings 现在平铺 bullet(`reviewer.md:93-97`),只有 §14 R 命中才有红/橙/黄/绿,非 R finding 无权重 | 每条打 `[severity: blocker/major/minor/nit]`×`[confidence: certain/likely/speculative]`。便于 fix specialist triage;把"不确定"显式标出(铁律"不确定就说不确定"),避免噪音淹没真问题 |

### 7.3 锦上添花（各补一个具体盲区）

| # | 增强 | 现状缺口 | 做法要点 |
|---|------|----------|----------|
| **E6** | **harness 专属注入/安全 pass** | 通用 6 域 security 只泛问"SQL/shell injection?"(`reviewer.md:27`);但本 harness 真实攻击面具体:case step 走 `psql -c`/shell(§4.1.2),Jinja context 值拼进 shell/SQL | 针对 case YAML/driver 改动专扫"不可信值是否未转义插进 shell/SQL""external_deps 值是否直达 shell"。比通用问句精准 |
| **E7** | **changed-line coverage delta(按边界原则【归 ci-gate】)** | tests 域判断"测试是否充分"是抽象的 | coverage 是全量测试**重活**,**放 ci-gate**(CI 本就跑 pytest,加 `--cov` + diff 新增行覆盖率报告,如"新函数 X 0% 覆盖"),**不塞 reviewer**(会拖慢前置闸门)。reviewer 可读 CI 产出的 coverage 报告作 tests 域参考,但不自己跑 |
| **E8** | **code↔design.md 漂移检查** | §14 R3 要求行为变更走 PR + design.md 有严格 changelog 纪律;设计稿是真权威 | 行为变更型 PR 若没同时 touch design.md/status 文档 → flag 提醒。防代码漂离设计稿 |

### 优先级建议

- **先做(reviewer 内,轻量)**:E1①(dry-run) / E2(consumer grep) / E5(severity+confidence,最便宜可立刻做) / E3(生成 suggestion,守"建议性"边界)
- **次做(reviewer 内)**:E4(差分再审,注意 subagent 无状态→靠读 PR 历史 comment) / E6(harness 注入扫)
- **归别处(按边界原则,非 reviewer)**:E1②真集群 run → smoke(merge 后) / E7 coverage → ci-gate
- **有余力**:E8(design 漂移,小心误报)

**前置依赖**:全部 backlog 都依赖 §0~§6 的 wiring 先落地(reviewer 真被 foreman 派起来跑),否则是给没人开的车加配置。
