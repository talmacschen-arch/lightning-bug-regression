# M1-followup sprint — 3 fixes from dogfood needs_human

foreman 入口文件（design.md §13.0-E）。M1-11 dogfood 实跑 5 例 case 暴露的 3 个 design_decision 问题，foreman 当时 escalate 为 needs_human 没自动修。本 sprint 把它们清掉。**不阻塞 M2 前端**，但 M2 真用 runner 时会绊到，所以现在修干净。

权威设计：`design.md`
- §4.1（用例 YAML schema — 字段名 + setup/teardown list 形态）
- §5.3 / §5.3.1（sql_driver / Jinja / 异常处理）
- §14 R5（超时分层）/ R9（异常折叠转 StepResult）

## 任务列表

- [x] **F-1 yaml_loader 与 §4.1 对齐**（`backend/app/storage/yaml_loader.py` + tests）— PR #19 (1fa3b07)
  - 问题: 实测 yaml_loader 拒收 5 例 §4.1-shape 真 case（M1-11 用 in-script normalizer 绕过）
  - 根因（按 dogfood 报告）: 字段名 + category-name 形态 + setup/teardown list-of-str shape
  - 修法: 字段名对齐 §4.1（`description/procedure/expected` 4-tuple、`setup: list[str]` 不是 `list[{sql:str}]`、`status` 白名单按 `case_categories` 表拉）；测试增加 5 例 cases/bug-regression/*.yaml 的 round-trip（加载不抛 + 字段都拿到）
  - 验收: `python -m scripts.run_m1_dogfood` 不再走 in-script normalizer——直接 `yaml_loader.load()` 出 Case 对象
  - § 引用: §4.1 + §4.5（case_categories）

- [x] **F-2 sql_driver 把 EXPLAIN 输出 populate 到 StepResult.plan_text**（`backend/app/runner/sql_driver.py` + tests + `assertions.py` 调整）— PR #17 (c5a9d11)
  - 问题: M1-11 dogfood lg-bug-0001 实跑 stdout 含 `Hash` + `tmp_test02`（BUG 已 upstream-fixed），但 `_plan_contains` 拿不到 `plan_text` 返 None 导致 case FAIL（假阳性）
  - 修法: sql_driver 检测 SQL 含 EXPLAIN 时把 result text 落 StepResult.plan_text；assertions._plan_contains 优先看 plan_text，None 时 fallback 看 stdout
  - 验收: lg-bug-0001 重跑 PASS（BUG 已修，runner 正确识别）
  - § 引用: §4.1 (`expect.plan_contains`) + §5.3 sql_driver

- [x] **F-3 sql_driver 处理 non-tx-safe DDL**（`backend/app/runner/sql_driver.py` + tests）— PR #18 (b49b766) + 收尾 commit (psql -c convention 落地，lg-bug-0005 改 `su - gpadmin -c "psql -c ..."` 形式，design.md §4.1 + dogfood normalizer 同步加 `psql ` 子串路由到 shell driver 的约定)。F-3 的 `_NON_TX_DDL_RE` 仍保留作 defense-in-depth（用户漏写 psql 前缀时 sql_driver 兜底自切 autocommit），但**首选写法**是 `su - gpadmin -c "psql -c '<DDL>'"`
  - 问题: M1-11 lg-bug-0005 跑 `DROP DATABASE mydb` 报错 — psycopg 默认 `autocommit=False` 把 DDL 包进 tx，PG 拒绝 tx 里 DROP/CREATE DATABASE
  - 修法: sql_driver 在执行前用正则探测 SQL 是否含 `CREATE DATABASE` / `DROP DATABASE` / `VACUUM` / `REINDEX CONCURRENTLY` 等 non-tx-safe DDL；命中则该 step 临时 `conn.autocommit = True` 跑后改回。**不在 YAML 加新字段**（保持 §4.1 schema 稳定）
  - 验收: lg-bug-0005 重跑 PASS 或 FAIL（取决于实际 BUG 状态），不再 ERROR
  - § 引用: §5.3 sql_driver + §14 R9（异常折叠）

## 完成定义 ✅ done 2026-05-24

- F-1/2/3 全 [x] ✓
- 重跑 dogfood → **5/5 PASS**（`docs/m1-dogfood-2026-05-23-1828.md`）：lg-bug-0001 hashjoin（F-2 plan_text 起效）/ lg-bug-0002 unnest crash / lg-bug-0003 count-no-stats / lg-bug-0004 CTAS rowcount / **lg-bug-0005 LC_CTYPE**（F-3 + psql -c routing + su gpadmin wrap 综合奏效）
- 3 个 needs_human 清掉
- 整 M1 + M1-followup sprint chain 完整闭环

## §14 R 条目预付

- **R9**（异常折叠）: F-2/F-3 改 sql_driver 时新失败模式要继续转 StepResult，不允许冒泡到 suite
- **R5**（超时分层）: F-3 autocommit 切换不影响 `statement_timeout` 路径（per-step 切回后正常）
- **R22**（auto-merge 不等 CI）: 已修；F-1/2/3 PR 走 `--auto --squash` 自动等 ci-gate

## 失控防护

- 同 symptom hash fail 2 次 → escalate
- 10 round / 2h budget
- 阻塞类（集群不可达等）写 needs_human
