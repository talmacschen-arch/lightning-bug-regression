# external_systems category 设计

## 0. 背景

当前 `case_categories` 有两类（design.md §4.5）：
- **bug_regression** — 历史 BUG 复现 / 修复验证
- **extension** — PG 周边扩展（pgvector / postgis / anon ...）的安装 + 基础功能验证

用户新增需求（2026-05-24）：第三类 **external_systems**，覆盖**依赖外部组件**的集成测试。
具体目标 case：

| 名称 | 类型 | 外部依赖 |
|---|---|---|
| datalake_fdw | PG Foreign Data Wrapper | COS / S3 / OBS / 对象存储 |
| hive_connector | 通过 PXF / datalake_fdw 连 Hive | Hive Metastore + HDFS + 可能 Kerberos |
| PXF | Greenplum Platform Extension Framework | HDFS / Hive / JDBC 等 |
| zombodb | PG ↔ ElasticSearch 集成 | Elasticsearch 集群 |

**与 extension 的根本区别**：
- `extension` 的 case：`CREATE EXTENSION foo` 即用，依赖 PG 二进制里已有 `.so`（部署时已就绪）
- `external_systems` 的 case：**外部服务进程必须运行 + 凭据/网络/profile.d 链路打通**，case 才可跑；若外部服务不可达，case 应判 `awaiting_env`（不是 fail）

---

## 1. 重要发现：plug-and-play 设计**真做到了**

按 design.md §4.5 + §14 R4b "no hardcoded category names"，前 backend probe 显示：

| 文件 | 当前对 category 的依赖 |
|---|---|
| `backend/app/api/admin.py` | `SELECT * FROM case_categories WHERE is_active` → 直接序列化返回，**零 category 字符串硬编码** |
| `backend/app/storage/yaml_loader.py` | 接 `categories: dict[name → CategoryMeta]` 参数；validator 按 dict 查表，**无 if-else** |
| `backend/app/api/cases.py:_iter_case_files` | `for cat in categories: cat_dir = root / cat.dir_path` → **任何新 dir 自动扫描** |
| `frontend/src/routes/CasesPage.tsx` | 按 `GET /admin/categories` 渲染 tab + 按 `status_whitelist.indexOf(...)` 给徽章颜色，**零字符串比较** |

**结论：加 1 个新 category = 1 个 Alembic migration + 1 个目录。不动业务代码、不动前端、不动 type generation。**

唯一 caveat：测试 fixture 可能假设了 2 个 category 数量；probe 显示 `frontend/src/routes/CasesPage.tsx:264` 只查 `categories.length === 0`，**没有写死 "2"**。`grep "categories.length\|len(categories)" backend/tests` 命中 0。

---

## 2. 决策点（需要用户拍板）

### 2.1 directory name

| 选项 | 说明 |
|---|---|
| **A.** `cases/external-systems/` (kebab) | 跟现有 `cases/bug-regression/` + `cases/extension/` 一致 — **推荐** |
| B. `cases/external_systems/` (snake) | 跟 category name `external_systems` 字面一致 |

→ **推荐 A**：现有两个 dir 都是 kebab-case；保持一致避未来 path 写法不统一。category name (DB) 与 dir_path 本就不要求逐字一致（`bug_regression` ↔ `bug-regression` 已经先例）。

### 2.2 id_prefix

YAML 文件名 + case id 都用这个前缀。要求：与 `bug-` / `ext-` 一致风格，3-5 char，**不与现有前缀有歧义**。

| 选项 | 说明 |
|---|---|
| A. `ext-sys-` | 语义清楚但**与 `ext-` 前缀冲突**：现有 `id.startswith("ext-")` 判 extension 的代码会假阳性命中 `ext-sys-xxx`。需要改 prefix 比对逻辑为 `==` 不是 `startswith`，或长前缀优先匹配 — **risk** |
| **B.** `xs-` (xs = external systems) | 4 char，无冲突，唯一 — **推荐** |
| C. `es-` | 同 B，但 ES 容易跟 Elasticsearch 混淆，且与 `ext-sys-` 哪个更直观见仁见智 |
| D. `ext-` 改成 `pgx-`（extension 重命名） | 大动 (15+ files)，**否决** |

→ **推荐 B `xs-`**。语义 `xs = external systems` 缩写。

**验证**：
- 现有 startswith 检查逻辑 grep：
  - `yaml_loader.py` 用 `cat.id_prefix` 查表，不 startswith
  - SKILL.md cross-check #6 写 "`bug_regression` 必须 `bug-*`；`extension` 必须 `ext-*`"——是描述性文字，加 `external_systems` 必须 `xs-*` 即可。

### 2.3 status_whitelist + default_status

| Category | status_whitelist | default | 语义 |
|---|---|---|---|
| bug_regression | open / fixed / wontfix / stub | open | BUG 修了没 |
| extension | stable / experimental / deprecated / stub | stable | 扩展功能验证通过没 |
| **external_systems**（拟） | ? | ? | ? |

候选：

| 选项 | status_whitelist | default | 评 |
|---|---|---|---|
| **A.** stable / awaiting_env / deprecated / stub | **awaiting_env** | 新 case 默认 "声明依赖但环境未必就绪"，准备好环境后改 stable — **推荐** |
| B. 同 extension (stable/experimental/deprecated/stub) | stable | 用 `experimental` 表"环境未就绪"；语义稍弱 |
| C. stable / awaiting_env / blocked_external / deprecated / stub | awaiting_env | 加 `blocked_external` 区分"外部服务挂了 → case 暂时跑不了"；**过早抽象** |

→ **推荐 A**。`awaiting_env` 是这类 case 的**特有 lifecycle**：作者把 case 蓝图写好（YAML 完整）+ external_deps 列清，但目标集群未部署该外部服务时，case `status: awaiting_env`；M5 后 runner 真消费 external_deps 后才有可能升 stable。

### 2.4 display_order

```
bug_regression  = 10
extension       = 20
external_systems = 30  ← 拟
```

→ 自然顺位 30；前端 tab 自动按此排。

### 2.5 external_deps 字段是否本 sprint 真消费

**现状**：`Case.external_deps: list[str]`（schema 已有，但 5 BUG + 5 extension 全是 `[]`）；runner 不读 / orchestrator 不读 / API 不读。

**选项**：
- A. 本 sprint **不动**：external_systems case 作者写 `external_deps: [hive, hdfs]`，纯文档性质 / lint 兜底（后续 sprint 加 runtime injection）— **推荐**
- B. 本 sprint 加 `external/<svc>.yml` runtime injection + Jinja `{{ external.<svc>.host }}` 渲染 — **scope creep，否决**

→ **推荐 A**：保持 sprint 紧（只为加 category），M5 或单独 sprint 做 runtime injection。

---

## 3. 实施清单（决策点定后）

| # | 文件 | 改动 | 估行 |
|---|---|---|---|
| 1 | `backend/alembic/versions/0002_seed_external_systems_category.py`（新） | INSERT INTO case_categories（按决策点 2.1-2.4 填值） | ~40 |
| 2 | `cases/external-systems/.gitkeep`（新） | 占位空目录 | 1 |
| 3 | `backend/tests/test_admin_categories.py`（更新） | fixture 期望从 2 行改 3 行（若 fixture 假设 2） | ~5 |
| 4 | `backend/tests/test_yaml_loader.py`（更新） | 同上，CategoryMeta 测试用例补一组 | ~10 |
| 5 | `frontend/src/routes/CasesPage.test.tsx`（更新） | 同上，mock data 加一行 | ~10 |
| 6 | `.claude/skills/add-test-case/SKILL.md` cross-check #6 | 加 "`external_systems` 必须 `xs-*`" 一行 | 1 |

**预计**: ~70 行净增（含 migration + 测试 fixture + 1 行 skill spec 更新）。

**不动**:
- `backend/app/api/{admin,cases}.py` — plug-and-play 数据驱动
- `backend/app/storage/yaml_loader.py` — category meta 是参数
- `frontend/src/routes/CasesPage.tsx` — 完全 data-driven
- `frontend/src/api/types.ts` — codegen 类型 `CategoryOut.name: string` 不是 enum
- runner / orchestrator / SqlSessionPool — external_deps 仍是文档性质

---

## 4. 不在本 sprint 范围（明示）

| 项 | 推迟到 | 理由 |
|---|---|---|
| runner 真消费 `external_deps` + 读 `external/<svc>.yml` | M5 或单独 sprint | scope creep；本 sprint 只为加 category |
| Jinja `{{ external.<svc>.host }}` 渲染支持 | 同上 | 同上 |
| `kind: shell` step 自动 `host: {{ external.* }}` SSH 路由 | 同上 | 同上 |
| 真写 datalake_fdw / hive_connector / PXF / zombodb case YAML | 用户后续 | 用户原话 "case我可以后面再加" |
| SKILL.md "Category-tagged extension 组" 的 6 条 "v0.9 加" 外部组件追问迁到 external_systems 组 | 单独 followup | 不阻塞本 sprint；用户加第一例 external_systems case 时会暴露这个需求再迁 |
| design.md §0 加 v1.11 row + §13.9 实战回顾 | sprint 收尾后 pm-designer | 落地后回顾，不预写 |

---

## 5. 验证 plan

**migration 阶段**：
- [ ] `alembic upgrade head` 跑通；`case_categories` 多一行 `external_systems`
- [ ] `alembic downgrade -1` 回滚干净（注意：现 `0001_initial_schema` 是 baseline，新 migration `0002` downgrade 应 DELETE 那行而不是 DROP table）

**功能验证**：
- [ ] `curl /admin/categories` 返 3 项，按 display_order 排
- [ ] `curl /cases?category=external_systems` 返 `[]`（目录空）
- [ ] 前端 `/cases` 自动多一个 tab，点开显示 empty state（用现有 i18n `cases-empty-<category.name>` 测试 hook）

**skill 兼容**：
- [ ] `claude --print --agent "/add-test-case ext:datalake_fdw"` 或类似的 external_systems-prompted 输入：grounding 拉到 3 个 category，首题选项含 `external_systems`
- [ ] cross-check #6 加 prefix 后，lint 仍 PASS（skill SKILL.md 改 1 行）

**runtime 验证**（手工，sprint 内不强制）：
- [ ] 假写一个 `cases/external-systems/xs-zombodb-stub.yaml` 占位（`status: awaiting_env` + `steps: []`），看 `GET /cases` 列得出 + 前端 tab 显得出 + Validate 不报错。

---

## 6. 风险点 / 待澄清

1. **id_prefix `xs-` 与 `ext-` 兼容性**：本设计已确认 backend 用 `cat.id_prefix` 查表（不是 startswith），但**前端**或 **skill** 是否有硬编码 startswith 检查？
   - SKILL.md cross-check #6 是描述性文字 → 加一行即可
   - 前端 grep `ext\|bug` 命中 0
   - **结论**: 无 startswith 风险

2. **alembic migration 命名**：`0001_initial_schema.py` 是 baseline。新 migration 用 `0002_seed_external_systems_category.py` 还是 `0002_<sprint>_external_systems.py` 风格？
   - `0001` 之后没有 `0002`，本 sprint 是 first follow-on
   - 推荐 `0002_seed_external_systems_category.py`，与 `0001_initial_schema.py` 同 voice（描述性）

3. **`awaiting_env` 是否需要 frontend 徽章色映射？**
   - CasesPage.tsx 用 `status_whitelist.indexOf(status)` 取 palette index：`stable`(0=default) / `awaiting_env`(1=secondary) / `deprecated`(2=destructive) / `stub`(3=outline)
   - 跟现有 extension 的 `stable`(0) / `experimental`(1) 配色不冲突；前端不动
   - **结论**: 无前端改动需求

4. **测试 fixture 数 2→3 影响范围**：
   - `frontend/src/routes/CasesPage.test.tsx` mock data 写死 2 个 category 吗？需 grep 确认
   - `backend/tests/test_admin_categories.py`（若存在）同问
   - 实施时先 `grep -rn "bug_regression.*extension\|2 categories" backend/tests/ frontend/src/`，命中数 0 = 最佳，命中数 > 0 = 加测试更新（实施清单 #3/#4/#5）

---

## 7. 实施顺序提议

落地按 5 步走（合并在 1 个 PR 或拆 2 个，由实施时判断）：

1. **migration** `0002_seed_external_systems_category.py` + 跑 `alembic upgrade head`
2. **目录** `cases/external-systems/.gitkeep`
3. **测试 fixture 更新**（probe 实际有几处 + 改）
4. **SKILL.md cross-check #6** 加 `xs-*` 一行
5. **本地 verification**：`curl /admin/categories` + `curl /cases?category=external_systems` + 前端浏览器看 tab + skill grounding 拉 3 项

---

## 8. 等用户拍板的决策（请回答）

A. directory name → `cases/external-systems/`（推荐 kebab）OK 吗？
B. id_prefix → `xs-` OK 吗？还是用 `ext-sys-`（要冒 startswith 风险）？
C. status_whitelist → `stable / awaiting_env / deprecated / stub` + default `awaiting_env` OK 吗？
D. display_order = 30 OK 吗？
E. external_deps 字段本 sprint **不**真消费（保持文档性质）OK 吗？

5 项决策定后立即开 PR；预计 < 100 行净增。

---

## 9. 2026-05-26 status 语义补强（v1.21 修订）

**触发**：用户在 xs-pxf-hive-fdw-encoding-utf8 case 落库后指出 v1.10 设计的 `status: stable` 与项目主目的（BUG 回归测试）不符——external_systems 与 extension 拆分是因为**依赖外部服务进程**，但 case 本质仍是 BUG 复现（PXF / Hive / FDW / Zombodb 触发的 PG/Greenplum BUG），不是"扩展功能稳定性验证"。用户原话："external-systems 这个分类的 case 依赖外部系统，所以才单独出来的，要跟 bug_regression 一样表示 BUG 修复状态"。

**问题根源**：v1.10 §2.3 决策点把 status_whitelist 锁定在"环境就绪度"单一维度 (`stable` / `awaiting_env` / `deprecated` / `stub`)——这与 `extension` 类别的语义同源（都是"功能稳定性"），但没考虑 external_systems case 实际承载的 BUG 复现意图。3 个已落库 case 都用 `stable`，但有的 BUG 已修复有的未修复，`stable` 无法区分。

**v1.21 反转**：

| 维度 | v1.10 设计 | v1.21 修订 |
|---|---|---|
| status_whitelist | `[stable, awaiting_env, deprecated, stub]` | `[open, fixed, wontfix, stub, awaiting_env]` |
| default_status | `awaiting_env` | `open` |
| 主轴语义 | 环境就绪度 | **BUG 修复状态**（与 bug_regression 对齐） |
| 辅助语义 | — | `awaiting_env`（外部服务未部署占位，与 BUG 状态正交） |

**3 个已落库 case 同步迁移**（在同一 atomic PR 内执行，避免 loader strict `not in whitelist` 检查破坏）：

| Case | v1.10 status | v1.21 status | 真实 BUG 状态 |
|---|---|---|---|
| `xs-pxf-hdfs-order-by-writable` | stable | **fixed** | BUG 已修复 |
| `xs-pxf-hive-fdw-encoding-utf8` | stable | **open** | BUG 未修复（dogfood 实测 baseline pass + main fail） |
| `xs-zombodb-partition-text-search` | stable | **fixed** | BUG 已修复（SynxDB-4.5.0-build130 + zombodb 3000.1.8 + ES 7.10.2 验证） |

**实施清单**（1 个 atomic PR，~110 行净改动）：

1. `backend/alembic/versions/0006_external_systems_status_realign.py` — UPDATE case_categories row（status_whitelist + default_status + description）
2. 3 个 case YAML status 改
3. `backend/tests/test_alembic_upgrade.py` — fixture 2 处改
4. `frontend/src/routes/DashboardPage.test.tsx` — mock + 1 测试 invariant 反转 + quick action testid
5. `frontend/src/components/FilterBar.test.tsx` + `CaseIdCombobox.test.tsx` — mock 改
6. `frontend/src/routes/DashboardPage.tsx` — 1 行 quick-action 注释
7. `design.md` §16.4 表格 + 关键差异 + 新增 "status 双轴语义" 段 + §0 v1.21 row
8. 本 doc §9 追加

**保留 awaiting_env 的理由**：用户选 D1.B 方案（兼顾两套语义），不选 D1.A "完全对齐 bug_regression 丢掉 awaiting_env"。awaiting_env 作为环境维度独立值仍有价值——未来某个 external_systems case 蓝图写好但 ES / Hive 集群尚未部署时，可标 awaiting_env 而不用 `open`（避免与 BUG 未修复混淆）。当前 3 个 case 没有 awaiting_env 实例，仅为未来预留。

**v1.10 plug-and-play 决策保留**：本次改造仍是**纯数据层 + 测试 fixture 改动**，无业务代码改动；frontend Dashboard KPI tile / FilterBar / CaseIdCombobox 全部 data-driven，新白名单 5 个值自动渲染 5 行 status tile，无需 UI 逻辑改动。这印证 v1.10 §1 "plug-and-play 设计真做到了" 的论断在二次反转时仍成立。

**经验教训**：v1.10 §2.3 status_whitelist 决策时 candidates A/B/C 都围绕"环境就绪度"维度，没把 bug_regression 当作可对齐参考——本质上把"依赖外部组件"和"BUG 复现"两个正交属性混在一个轴上。下次新增 category 时，决策点 status_whitelist 应明确：**这个 category 的 case 是 BUG 复现还是功能验证？** 前者对齐 bug_regression，后者对齐 extension。
