# M1-cleanup sprint — yaml_loader §4.5 alignment + restart_db whitelisting

foreman 入口文件（design.md §13.0-E）。M1-followup PR #17/#18/#19 落地后 opus review 发现 yaml_loader.py 里 3 个 P0 问题——都是与 design.md schema 直接矛盾的"功能现在跑通但加新 case / 加新 category 时必爆"。本 sprint 修这 3 项。

权威设计：
- §4.1（YAML schema：name/kind canonical 字段、status_whitelist、id_prefix）
- §4.5（case_categories 元数据表，**source of truth**，§14 R4b 必读）
- §14 R4b（分类/枚举不写死多处）

reviewer cross-reference §14 R4b：本 sprint 任何 PR 命中 R4b 反模式即 REQUEST_CHANGES。

## 任务列表

### 任务 P0-A — yaml_loader 从 categories_whitelist 拉 status + id_prefix

**问题**（R-1 + R-2 合并修）：

1. `backend/app/storage/yaml_loader.py:80` 的 `_VALID_STATUSES = frozenset({"open", "closed", "stub"})` 与 §4.5 直接矛盾：
   - `bug_regression` 真正 whitelist = `{open, fixed, wontfix, stub}`（"closed" 是 sonnet 杜撰）
   - `extension` whitelist = `{stable, experimental, deprecated, stub}`
   - 当前 5 个真 case 全 `status: open` 过校验是偶然，加 `fixed`/`wontfix` 直接被拒
2. `backend/app/storage/yaml_loader.py:57-66` 的 `_CATEGORY_PREFIX` dict：
   - 杜撰 `feature_validation / perf_regression / ops_runbook` 等 §4.5 不存在的 category
   - **完全缺 `extension`**——`ext-*.yaml` case 走到 line 246 `expected_prefix = None` → 静默 skip id 前缀检查，失去安全网
3. **§14 R4b 双层违反**：分类硬编码到 loader + 杜撰未来 category

**修法**：

- [x] **P0-A 修 yaml_loader 接收 §4.5 case_categories 元数据** — PR #22 (f2b664b refactor) + PR #21 (815473c design.md §4.1 pointer) 两步组合；`_VALID_STATUSES` 与 `_CATEGORY_PREFIX` 已删；新 `CategoryMeta` dataclass + `cases.py` API caller 同步改 + 5 个新测试（status=fixed 接受 / status=stable 接受 / status=closed 拒 / ext- prefix enforced / prefix data-driven）；§14 R4b 反模式已修
  - 新增 `CategoryMeta` dataclass（或 TypedDict）含 `name / id_prefix / status_whitelist: set[str]`
  - `load_case()` 签名改为 `categories: Mapping[str, CategoryMeta]`（替换 `categories_whitelist: set[str]`）
  - 删 `_VALID_STATUSES` 模块常量、删 `_CATEGORY_PREFIX` 字典——这两份 source-of-truth 同时存在就是 R4b 反模式
  - status 校验改为 `if status_raw not in categories[category].status_whitelist:`
  - id-prefix 校验改为 `if not case_id.startswith(categories[category].id_prefix):`
  - 测试 `test_yaml_loader.py` 更新 fixture：构造 CategoryMeta 字典传入；新增测试覆盖：(a) status=fixed 在 bug_regression 下接受 / (b) status=stable 在 extension 下接受 / (c) status=closed 任何 category 都拒（验证 sonnet 杜撰值已清掉）/ (d) ext-* id 在 category=extension 下 prefix-enforced
  - 更新 `backend/scripts/run_m1_dogfood.py` 调 yaml_loader 时构造的 CategoryMeta（暂硬编码，待 M2 接 DB 时换掉）
  - design.md §4.5 不动（已是 source of truth），design.md §4.1 加一句指向 §4.5 说明 "**status 与 id_prefix 由 §4.5 表驱动，schema doc 不再列枚举值**"
  - 单 PR；走 ci-gate 必须绿；reviewer cross-check §14 R4b 已修

### 任务 P0-B — `_VALID_DRIVERS` 加 restart_db 名字

**问题**（R-3）：

`backend/app/storage/yaml_loader.py:79` 的 `_VALID_DRIVERS = frozenset({"sql", "shell", "log_grep"})` 漏 `restart_db`。§4.1 schema 注释明写 4 个 step kind 都接受，§13.2 也讲"restart_db M1 之后实现但 schema 先入"。当前是把"驱动还没实现"误等于"schema 不接受 kind 名字"，未来 M3a 录入器写 restart_db case 落库时被 loader 拒。

**修法**：

- [x] **P0-B `_VALID_DRIVERS` 加 restart_db** — PR #20 (557ad3a) — `_VALID_DRIVERS` = frozenset({"sql", "shell", "log_grep", "restart_db"})；Step.driver Literal type 同步扩；1 个新测试覆盖 schema-level 接受
  - 改 `_VALID_DRIVERS = frozenset({"sql", "shell", "log_grep", "restart_db"})`
  - Step.driver Literal 类型加 "restart_db"
  - 加一个测试：`load_case` 在 step kind=restart_db 时**接受**且 driver=restart_db 落对（不实现真驱动，只 schema-level 接受）
  - orchestrator 仍不知道怎么真跑 restart_db step——遇到时按已有的 unknown-driver 报错路径走（应该有；如无，本 task 不补，加 needs_human 留给 M2）
  - 单 PR；与 P0-A 同一文件 yaml_loader.py，foreman 应**顺序 dispatch** 不并发（merge 冲突）；P0-B 简单先做

## 完成定义 ✅ done 2026-05-24

- P0-A + P0-B 都 merged via ci-gate；外加 P0-A 的 design.md 部分独立 PR #21
- 重跑 dogfood `docs/m1-cleanup-dogfood-2026-05-23-1908.md` → **5/5 PASS** 不退 ✓
- 全 backend 单测 264 passed + 1 skipped + ruff 全过 ✓
- §14 R4b 反模式已删除（grep 全 backend 看不到硬编码 category 字典 / status enum）
- foreman 在 PR #22 ci-gate 红时退出未返 final JSON；ruff format fix 由人手补 commit `7ceda51` (P0-A follow-up)

## 失控防护

- 同症状 fail 2 次 → escalate needs_human
- 10 round / 2h budget
- P0-A 是较大 refactor（接口变 + 多 caller 改）；P0-B 是 1 行 + 1 测；不应触发任何 R 条目
