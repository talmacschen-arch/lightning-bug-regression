---
name: add-test-case
description: 生成历史 BUG 复现 / extension 集成测试用例 YAML，generator-only（终端入口，对应 M3a /cases/new 入口 B）
model: claude-opus-4-7
---

> **模型规则（2026-05-24 用户决策，永久生效）**：本 skill 文件**必须**钉死
> `model: claude-opus-4-7`。**禁止**临时降级到 `claude-sonnet-4-6` 或其他
> sonnet/haiku 版本——理由：skill 输出需要严谨结构 + canonical 顺序 +
> 多项 cross-check 一次过；sonnet 实战漂移多（M1-followup 暴露过 §14 R4b
> 杜撰 4 个 category），haiku 推理深度不足。任何未来升级（opus-4-8+）
> 必须经用户显式授权，不在 dispatch 时由 agent 自决。
> `.claude/scripts/check_skill_add_test_case.sh` 在 CI 强制此项，绕过
> lint = block PR。

## 设计原则（铁律）

借鉴 preflight `SKILL.md`，本 skill 严格遵守：

1. **Generator-only，无副作用**：
   - ❌ 不用 Write 工具
   - ❌ 不 `git add` / `git commit` / `git push`
   - ❌ 不调 `POST /cases/submit`
   - ❌ 不跑 case（用户在 UI 上点 Try 跑）
   - ✅ 唯一输出 = stdout 上一段 YAML，用 `─── BEGIN YAML ───` / `─── END YAML ───` 包裹（无围栏、无注释混在内部），方便人复制粘贴。
2. **Live grounding**：生成前必须 fetch 三个 backend 端点。失败时显式提示用户，**不**编造字段。
   - `GET /admin/categories` — 当前活跃测试门类清单（**禁止**编造 category 名）。skill 首题选项从这里取，default_status / id_prefix / status_whitelist 也来自这里
   - `GET /cases?q=<topic>&category=<name>` — 按 category 查重（避免做重复 case；已有则建议扩展）
   - `GET /admin/step-kinds` — executor 自描述（**禁止**编造 step kind）
3. **House-style 学习**：开工前 Read 2-3 个最相似的已有 case YAML（按 tags / 关键词匹配），匹配字段顺序、注释风格。
4. **不嵌入凭据**：DB 密码走 runner（PGPASSWORD 环境变量或 .pgpass），**不**写进 YAML 字面值。
5. **6 题对齐 + 场景特化追问**：详 §5.5.4 / §5.5.5。
6. **canonical field 顺序**：生成 YAML 必须按 §5.5.6 的字段顺序，与 catalog 一致。

## 输入模式（四选一）

```
/add-test-case <feishu-url>             模式 A：飞书历史 BUG 文档锚点（多用于 bug_regression）
/add-test-case <local-sql-file>         模式 B：本地 SQL 复现脚本
/add-test-case ext:<extname> [<doc-url>] 模式 D：v0.7 新增——extension 用例，如 ext:pgvector / ext:postgis
/add-test-case                          模式 C：自然语言（skill 反问要做什么）
```

输入歧义时一问澄清（"这是飞书 URL 还是本地路径？是 BUG 回归还是 extension 集成？"），不要凭猜。

- 模式 A 用 **WebFetch**（如果 MCP 不可达，复用 `project005/feishu-skills/mcp-server/feishu_client.py`，见全局 memory `feishu_client_access.md`）。category 默认 = `bug_regression`。
- 模式 B 用 **Read** 读本地文件。category 让 skill 从脚本内容/路径推断（`cases/extension/` 下 → extension；脚本含 `CREATE EXTENSION` 等关键字 → extension）。
- 模式 C 直接问用户，category 作为对齐题首题。
- 模式 D 直接锁定 category = `extension`，extname 进入 tags 与 id 默认 slug；如附带 `<doc-url>`（GitHub / 官方手册），WebFetch 取首页内容做关键词分析。

## 工作流（7 步）

| 步骤 | 动作 |
|------|------|
| 1 | Read 2-3 个最相似已有 case YAML（按 tags 匹配；优先看与目标 BUG 同类型的） |
| 2 | Fetch 三个 grounding 端点（§5.5.1 规则 2） |
| 3 | 分析输入，从输入推导 5 个默认值 + 检测场景关键词 |
| 4 | 按 §5.5.4 顺序提 6 题，每题展示默认值；空回车 = 接受默认 |
| 5 | 按 §5.5.5 追问场景特化问题（只问检测到的） |
| 6 | 按 §5.5.6 canonical 顺序起草 YAML；做 12 项 cross-check（§5.5.7） |
| 7 | 打印 `─── BEGIN YAML ───` … `─── END YAML ───` + 3 行 footer |

**自动推导规则**：

通用规则（与 category 无关）：
- `id` = `<category.id_prefix>` + 推导 slug。slug 推导：
  - 模式 A → 飞书锚点 slug（如 `9.1` → `9-1-hashjoin`）；
  - 模式 B → 脚本文件名 stem；
  - 模式 D → `<extname>-<场景关键词>`；
  - 模式 C → 让用户填。
  - 如果 category 的 `id_prefix` 含编号位（约定：`bug-` 后跟 4 位数字 `NNNN`），则 fetch `/cases?category=<name>` 取最大编号 + 1；不含编号位的就不编号（`ext-` 用 extname 已经够标识）。
- `title`：模式 A 飞书段落首句；模式 B 脚本顶部注释；模式 D 用 extname + 场景；模式 C 让用户填。
- `applies_to.versions`：输入含具体版本号 → 转 PEP 440 spec；否则留空（适用所有）。
- `status`：默认 = `<category.default_status>`；输入含明确状态关键词（"stub / 仅录入" / "实验中" / "废弃"）→ 按 category 的 `status_whitelist` 匹配最近的一个。
- `severity` 启发式：
  - 含 "crash / panic / FATAL / 集群挂 / 进入 recover" → `high`
  - 含 "返回错值 / 计划错 / 性能退化" → `medium`
  - 含 "风格问题 / experimental / 边缘场景" → `low`
  - 缺省 → `medium`

**关键**：skill 代码里**禁止**出现 `if category == "bug_regression"` 这种条件。所有 category 相关默认值都从 grounding 的 `case_categories` 字典查表，未来加门类时 skill 不需要改一行。

## 6 个对齐问题

```
1) category    [bug_regression]:     # 选项从 GET /admin/categories 拉，**skill 不写死**
                                     # 当前 seed 有：bug_regression / extension
2) id          [<auto-slug, 按 category.id_prefix + 推 slug>]:
3) title       [<从飞书锚点/脚本注释/extname 提取>]:
4) applies_to.versions  [全适用]:    # 例：">=1.6,<2.0"，留空=所有版本
5) status      [<category.default_status>]:  # 取自 grounding，不写死
6) severity    [medium]:             # high | medium | low
```

skill 在题 1 拿到答案后，把对应 category 的 `id_prefix` / `default_status` / `status_whitelist` 缓存下来，后续 2~6 题的默认值和校验都用这份数据，**不**在 skill 代码里枚举 `if category == "bug_regression": ...`。

## 场景特化追问

按输入关键词检测，每命中一类追加 1 题，**不**命中就跳过。

**通用组**（两种 category 都可能命中）：

| 检测关键词 | 追问 | 影响 |
|-----------|------|------|
| `concurrent` / 并发 / VACUUM 同时 / 两个会话 / two session | "需要多会话吗？默认设 `sessions: {s1: {driver: sql}, s2: {driver: sql}}`？[yes]" | 加 `sessions:` mapping 段（**必须** dict shape；backend `yaml_loader.py` 拒绝 list-of-strings——dogfood 2026-05-24 已踩过 `TypeError: 'in <string>' requires string as left operand, not list`）；后续相关 step 加 `on: s1/s2` |
| `crash` / `panic` / `FATAL` / `recover mode` / 集群挂 | "会让集群进入 recover mode 吗？默认末尾加 `kind: log_grep` step 兜底？[yes]" | 末尾加 log_grep step，`pattern: "FATAL: the database system is in recover mode"`，`expect.matches: 0` |
| `mydb` / `createdb` / 自建库 / `lc_ctype` / `lc_collate` | "本 case 需要在非 postgres db 上跑吗？" | 提示用户填 step 级 `database: <名称>`；setup 加 createdb（idempotent） |
| `set <guc> to` / 优化器 / ORCA / `enable_<feature>` | "本 case 依赖特定 GUC 状态吗？要不要加 `preconditions: {options.<guc>: [<allowed>]}`？[no]" | 加 `preconditions:` 段做运行前 gate |
| `explain` / 计划 / plan / hashjoin / 走索引 | "需要断言执行计划包含某字串吗？" | step 上加 `expect.plan_contains: [<keyword>]`，**不**用 `stdout_contains` |
| 耗时 / 超过 N 秒 / 慢查询 / 退化 | "需要性能断言吗？比如 `duration_lt_ms: <ms>`？" | step 上加 `expect.duration_lt_ms: <ms>` |

**Category-tagged extension 组**（仅当首题答 category=extension 时本组生效；条件由 skill 在运行时按缓存的 category 决定，markdown 不写死）：

| 检测关键词 | 追问 | 影响 |
|-----------|------|------|
| `CREATE EXTENSION` / `extension_url` / shared_preload | "extension 是 `CREATE EXTENSION` 即用，还是要进 `shared_preload_libraries`？[runtime]" | preload 类（pg_search / pgaudit）→ 提示 case 必含 `kind: restart_db` step；runtime 类→ setup 加 `CREATE EXTENSION IF NOT EXISTS` |
| `<extname> 版本` / `version` / `extversion` | "要不要断言 extension 版本？" | 加一 step `SELECT extversion FROM pg_extension WHERE extname='<n>'`，配 `expect.scalar: "<expected>"` 或 `expect.scalar_ge: "<min>"` |
| pgvector 关键词 / `vector(` / `<->` / `<=>` / IVFFlat / HNSW | "做 IVFFlat / HNSW 索引断言吗？" | step 加 `CREATE INDEX ... USING ivfflat / hnsw`，配 `expect.plan_contains: ["IVFFlat" 或 "HNSW Index Scan"]` |
| postgis 关键词 / `ST_*` / `GEOMETRY` / SRID | "需要空间索引 + ST 函数验证吗？" | 加 `CREATE INDEX USING gist`，配 `ST_DWithin` 等查询；setup 注意 `CREATE EXTENSION postgis;`（不带 IF NOT EXISTS 会因 schema 已有报错 → 用 IF NOT EXISTS） |
| pgcrypto 关键词 / `crypt(` / `digest(` / `gen_random_*` | "对 hash 输出做精确断言（确定性算法）还是仅断言无错（随机算法）？" | 确定性（sha256/md5）→ `expect.scalar: "<hex>"`；随机（gen_random_uuid/bcrypt salt）→ 只校验返回非空 |
| `plpython` / `plperl` / `plgo` / `plr` / `plcontainer` / 过程语言 | "过程语言是否安装？需要重启 DB 吗？" | 部分语言（plpython3u）需 `shared_preload_libraries` → 提示加 `kind: restart_db` step |
| **v0.9 加：`shared_preload_libraries` / pgaudit / pg_search / 必须 preload** | "本 extension 需要进 shared_preload_libraries（必须 restart）吗？如是，要自管理还是依赖 deployer 全局加？[self-managed]" | self-managed → 把"加 preload + restart + 业务测试 + 移除 preload + restart"全写进同一 case；标 `destructive: true`（preflight 11_pg_search.yaml 是范本：第 53 步把 pg_search 加进 preload，最后两步移除并再 restart） |

**Category-tagged external_systems 组**（仅当首题答 category=external_systems 时本组生效；2026-05-24 从原 extension 组迁来——FDW + 配置文件 + Kerberos + 远端 CLI + warmup 这 5 类追问本质上是"外部服务可用性"而非"PG 扩展功能"问题）：

> **注**：表里 `{{ external.<svc>.* }}` Jinja 占位**当前 runner 不解析**（external_deps 字段仍为文档性质，PR #88 范围决策）；case 作者按目标语义写，runtime injection 待 M5 followup。

| 检测关键词 | 追问 | 影响 |
|-----------|------|------|
| `CREATE FOREIGN TABLE` / `IMPORT FOREIGN SCHEMA` / FDW / dblink / datalake_fdw / hive_connector / PXF / zombodb | "外部数据源是否本机已部署？" | 若否，提示用户补 `external_deps: [<svc>]`（首版不支持自动 provision，让用户在 §3.1 外部依赖准备阶段搞定）；status 默认 `open`（v1.21 后 external_systems 主轴为 BUG 修复状态）；若外部服务确实尚未部署可标 `awaiting_env`（与 BUG 状态正交的辅助 lifecycle 值） |
| `gphdfs.conf` / `gphive.conf` / `krb5.conf` / 服务端配置文件 | "需要写/改 master 上的配置文件吗？" | 提示用 cli step `cat >> "$DD/<file>" <<'YML' ... YML`（**追加 + grep -q guard**），**不要** `cat > ` 覆盖——preflight Run 112 教训：truncate 把 deployer 写的块清空，后续 case 全 fail |
| `kinit` / `keytab` / `principal` / Kerberos | "kinit 用什么 principal / keytab 路径？" | step 用 `{{ external.<svc>.extras.client_principal }}` + `{{ external.<svc>.extras.client_keytab_local }}` 渲染；**避免** `_HOST` 占位（preflight 13_cdh_kerberos 教训：datalake_fdw 里 _HOST 替换不稳，直接写 FQDN） |
| `beeline` / `sqlplus` / `mysql` 等远端 CLI | "需要 SSH 到外部主机执行吗？" | step 加 `host: '{{ external.<svc>.host }}'`，cmd 开头**显式 source profile.d**：`[ -f /etc/profile.d/<x>.sh ] && . /etc/profile.d/<x>.sh || true`（preflight 12_datalake_fdw_hive 教训：SSH 非交互不 source，beeline 找不到 HIVE_HOME） |
| fresh pool / 服务刚起来 / "可能 warmup 中" | "外部服务可能在测试启动时还没 ready 吗？" | seed step 包 retry 循环（典型 6×10s back-off + `break on success`，preflight 12_datalake_fdw_hive seed_hive_fixture 范本） |

未命中任何关键词 → 跳过本步，进入草拟。

## Canonical 字段顺序

skill 输出的 YAML **必须**按这个顺序，和 catalog 保持一致，diff 才好读：

```yaml
id: bug-NNNN-<slug>                  # 或 ext-<extname>-<slug>
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
  database: gpadmin                     # v1.8 起默认 gpadmin（Synxdb owner-home db；非 postgres）；如需别的库显式覆盖

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

## 打印前 cross-check（12 项）

skill 在打印 BEGIN/END 之前必须自查：

1. **step kind 在 `/admin/step-kinds` 列表里**——禁止编造 `kind: bash` / `kind: psql`。
2. **`expect.plan_contains` 只用在 `kind: sql` step**；`expect.exit_code` 只用在 shell；`expect.scalar` 只用在返回单行单列的 SQL。
3. **`setup` / `teardown` 幂等守卫**：grep 每条 SQL — 所有 `DROP` 必带 `IF EXISTS`、所有 `CREATE TABLE` / `CREATE EXTENSION` 必带 `IF NOT EXISTS`（除非测的就是 CREATE 本身的语义），或包 `DO $$ BEGIN IF NOT EXISTS ... END $$`；缺一律自动加上。
4. **不嵌入凭据**：grep YAML 里有没有 `password=` / `PGPASSWORD=` 字面值。
5. **status 与字段一致性**（按 category 检查白名单）：
   - `category=bug_regression` → status ∈ {open, fixed, wontfix, stub}；`status=fixed` 时 `source.fixed_version` 必填。
   - `category=extension` → status ∈ {stable, experimental, deprecated, stub}。
   - 两类都满足：`status=stub` 时 `steps:` 必须为空（与 §4.1 stub 语义一致）。
6. **id 前缀与 category 匹配**：`bug_regression` 必须 `bug-*`；`extension` 必须 `ext-*`；`external_systems` 必须 `xs-*`。前缀错 = skill bug，立即修正。
7. **destructive 一致性**：steps 里出现 `gpstop` / `gpstart` / `gpconfig -c shared_preload_libraries` / `restart_db` step / `rm -rf .../data` 任一关键词，则 `destructive` 必须为 `true`。漏标 = case 在 suite 中前置跑，污染后续。
8. **Jinja typo 检查**：所有 `{{ external.<svc>.<field> }}` 的 `<svc>` 必须出现在 case 的 `external_deps` 里；不在则 skill 静默修正（把缺的服务名加进 external_deps）或反问用户"这是 typo 还是新依赖？"。
9. **远端 cli step profile.d 显式 source**：所有带 `host: '{{ external.* }}'` 的 cli step，cmd 开头**必须**有 `[ -f /etc/profile.d/<x>.sh ] && . /etc/profile.d/<x>.sh || true` 这种模式；缺则插入（按 svc 名推测 `<x>` 是 hadoop / hive / oracle / mysql / kafka 等）。
10. **服务端配置文件用追加 + grep guard**：cli step 里 `cat > $DD/gphdfs.conf` 这种**覆盖写**模式 → 强制改成 `cat >> + grep -q '^<key>:' guard` 模式（preflight Run 112 教训）。
11. **non-tx-safe DDL 必须走 psql -c**（design.md §4.1.2，M4a-2 BUG 9.11 实战暴露）：steps / setup / teardown 里出现 `VACUUM` / `VACUUM FULL` / 顶层裸跑的 `ANALYZE` / `CREATE DATABASE` / `DROP DATABASE` / `REINDEX CONCURRENTLY` / `CREATE INDEX CONCURRENTLY` / `DROP INDEX CONCURRENTLY` / `CREATE TABLESPACE` / `DROP TABLESPACE` / `ALTER SYSTEM` / `CLUSTER` 任一关键词时，**绝禁** `kind: sql` 走 psycopg，**必须**改写为 `kind: shell` + `cmd: su - gpadmin -c "psql -c '<DDL>'"`（如果 setup 是 list[str] 字符串，写成 `su - gpadmin -c "psql -c '<DDL>'"` 字符串项，case_normalizer 自动识别 `psql ` 前缀转 shell driver）。理由：sql_driver 已移除 autocommit 分支；non-tx-safe DDL 走 psycopg 必报 PG 错或撞 AsyncConnection autocommit 状态机怪圈。
12. **跨 driver 数据可见性**：当主 `steps:` 含 `kind: shell` step（特别 `psql -c` 形式），且某前序 `kind: sql` step（或 setup）创建了持久化 schema（CREATE TABLE / INSERT 等需被后续 shell step 看见的数据）时——
    - **当前实现**：sql_driver 在每个 `kind: sql` step 末尾自动 `await conn.commit()`，所以前序 `kind: sql` 的 CREATE TABLE / INSERT 对后续独立 psql -c 子进程**自动可见**。不强制改 setup 为 psql -c。
    - **保守可选**：若不确定 sql_driver commit 语义（或 case 跑在老版本 sql_driver 上），把 setup 改成 `kind: shell + cmd: su - gpadmin -c "psql -c '...'"` 仍是安全选择（每次独立连接 + 隐式 commit；与 sql 长连接 commit 等效）。bug-0008 用 kind: sql + 依赖 sql_driver commit 通 Try gate。
    - **何时仍必须 psql -c**：cross-driver 情况下，**non-tx-safe DDL**（#11 列的关键词集合）依然必须 psql -c（这是 #11 的硬约束，与 #12 无关）；仅 tx-safe schema 操作可以 kind: sql。

**任一项未过 → 修正后重试，不打印 BEGIN/END。**

## 输出格式

```
─── BEGIN YAML ───
id: bug-0006-vacuum-alter-table-deadlock
...
─── END YAML ───

下一步：
1) 打开 http://localhost:5173/cases/new → 选「粘贴 YAML」入口（frontend dev server；见 README 起本机 dev 服务 章节）
2) 粘贴上方 YAML 块，点 Validate（schema 校验通过）
3) 点 Try（在你已就绪的集群上试跑一次），全绿后 Save → 自动提 PR
```

## 不做的事（明示）

借 preflight 同款负面清单：

- ❌ 写 `.yaml` 到磁盘
- ❌ `git add` / `commit` / `push`
- ❌ `POST /cases/submit`
- ❌ 触发集群上的真实运行（那是 `/cases/try` 干的）
- ❌ 修改 skip_list / settings / 任何 admin 资源

skill 是 **YAML 编辑器的打字助手**，不是 deployer，不是 reviewer。前端的 Validate + Try + Save 才是 source of truth。

## Example: ext:pgvector 完整问答

本例演示一个 extension 集成测试用例的完整创建过程，从用户输入到最终 YAML 输出。

### 用户输入
```
/add-test-case ext:pgvector
```

### Skill 问答流程

**问题 1：category**
```
请选择测试门类 [bug_regression]:
当前有：bug_regression, extension
> extension
✓ 选定：extension
```

**问题 2：id**
```
测试用例 ID [ext-pgvector-<auto>]:
（根据下面的 title 推导；或自己填）
> 
✓ 用默认值 ext-pgvector-ivfflat-basic
```

**问题 3：title**
```
测试用例标题 [pgvector IVFFlat 索引基础功能]:
> pgvector IVFFlat 索引基础功能测试
✓ 用户输入
```

**问题 4：applies_to.versions**
```
版本约束 [留空=所有版本]:
例如 ">=1.6,<2.0" 或留空
> 
✓ 所有版本适用
```

**问题 5：status**
```
测试状态 [stable]:
可选：stable, experimental, deprecated, stub
> stable
✓ stable
```

**问题 6：severity**
```
严重等级 [medium]:
high | medium | low
> medium
✓ medium
```

### 场景特化追问

**命中关键词**：`vector(` / `ivfflat`

**追问**：
```
需要做 IVFFlat 索引性能/执行计划断言吗？[yes]
> yes
✓ 将在 step 中加 CREATE INDEX ... USING ivfflat + expect.plan_contains 检查
```

### 生成的 YAML

```
─── BEGIN YAML ───
id: ext-pgvector-ivfflat-basic
title: pgvector IVFFlat 索引基础功能测试
category: extension
status: stable
severity: medium
destructive: false

source:
  feishu_anchor: ""
  reported_at: "2026-05-24"
  fixed_version: ""
  ext_doc_url: "https://github.com/pgvector/pgvector"
issue_url: ""
tags: [pgvector, vector, ivfflat, similarity_search]

description: |
  验证 pgvector extension 的 IVFFlat 索引在 lightning 环境下的创建、写入和查询性能。
  涵盖向量数据类型、L2 距离操作、IVFFlat 索引创建和基础查询。
procedure: |
  1) 建表 vectors_demo，列为 id / embedding（vector(3) 类型）
  2) 插入 1000 条随机向量
  3) 在 embedding 上创建 IVFFlat 索引（lists=10, probes=10）
  4) 执行相似度查询 (SELECT ... ORDER BY embedding <-> ...)
  5) 验证执行计划包含 IVFFlat Index Scan
expected: |
  - CREATE EXTENSION IF NOT EXISTS pgvector 成功
  - CREATE INDEX ... USING ivfflat 成功
  - 查询执行计划显示 IVFFlat Index Scan
  - 查询返回正确数量的结果（10 条最近邻）

applies_to: {}
preconditions: {}
external_deps: []

defaults:
  database: gpadmin

sessions: []

setup:
  - sql: |
      DROP TABLE IF EXISTS vectors_demo;
      CREATE EXTENSION IF NOT EXISTS pgvector;
      CREATE TABLE vectors_demo (
        id SERIAL PRIMARY KEY,
        embedding vector(3)
      );
      INSERT INTO vectors_demo (embedding)
      SELECT ARRAY[random(), random(), random()]::vector(3)
      FROM generate_series(1, 1000);
      ANALYZE vectors_demo;

steps:
  - name: "创建 IVFFlat 索引"
    kind: sql
    on: default
    sql: |
      CREATE INDEX idx_vectors_ivfflat ON vectors_demo
      USING ivfflat (embedding vector_l2_ops)
      WITH (lists = 10)
    expect:
      not_contains: ["ERROR", "FATAL"]
      
  - name: "执行向量相似度查询并检查执行计划"
    kind: sql
    on: default
    sql: |
      EXPLAIN (ANALYZE, BUFFERS)
      SELECT id, embedding <-> '[0.5, 0.5, 0.5]'::vector(3) AS distance
      FROM vectors_demo
      ORDER BY embedding <-> '[0.5, 0.5, 0.5]'::vector(3)
      LIMIT 10
    timeout_sec: 60
    expect:
      plan_contains: ["IVFFlat", "Index Scan"]

teardown:
  - sql: |
      DROP TABLE IF EXISTS vectors_demo;

created_by: chenqiang
created_at: "2026-05-24"
notes: |
  pgvector 的 IVFFlat 索引是最常见的近似相似度搜索实现。本 case 验证 lightning 环境下
  从扩展安装、向量数据类型、索引创建到查询执行的完整流程。

  关键点：
  - IVFFlat 是 nearest neighbor search 的快速索引（HNSW 是另一类）
  - lists 参数影响精度 vs 性能权衡；通常 lists = sqrt(rows/probes)
  - 必须指定 operator class (vector_l2_ops / vector_ip_ops / vector_cosine_ops)
  - EXPLAIN ANALYZE 确认使用了索引，否则可能走全表扫描

  **teardown 不 DROP EXTENSION pgvector**：extension 是**共享资源**，case 跑完不应
  卸载——其他 case / 业务可能依赖；`DROP EXTENSION ... CASCADE` 还会牵连 schema
  中其他用了 `vector` 列的表。通用规则：**case teardown 只清自己 setup 时建的
  TABLE / SCHEMA / FUNCTION**，**不**碰 EXTENSION（pgvector / pg_partman /
  plpython3u / anon / postgis 等同理）。例外：destructive=true 的 case 显式测试
  "加载 + 卸载"全周期时才 DROP EXTENSION。
─── END YAML ───

下一步：
1) 打开 http://localhost:5173/cases/new → 选「粘贴 YAML」入口（frontend dev server；见 README 起本机 dev 服务 章节）
2) 粘贴上方 YAML 块，点 Validate（schema 校验通过）
3) 点 Try（在你已就绪的集群上试跑一次），全绿后 Save → 自动提 PR
```

## Common mistakes（反例清单）

### 1. ❌ 硬编码 category 名字进 markdown 条件分支（违反 §14 R4b）

**反例**：
```python
if category == "bug_regression":
    id_prefix = "bug-"
    status_options = ["open", "fixed", "wontfix", "stub"]
elif category == "extension":
    id_prefix = "ext-"
    status_options = ["stable", "experimental", "deprecated", "stub"]
```

**正例**：
```python
# 从 grounding 缓存的 case_categories 字典查表
id_prefix = category_config[category]["id_prefix"]
status_options = category_config[category]["status_whitelist"]
```

**原因**：未来加新 category（如 `integration`）时，代码不需要修改，只需后端 API 返回新的分类配置。

---

### 2. ❌ 用 Write 工具落盘 YAML（违反 §5.5.1 铁律 1）

**反例**：
```
Write tool: 
  file_path: /tmp/case.yaml
  content: id: bug-0006...
```

**正例**：
```
唯一输出方式：
─── BEGIN YAML ───
id: bug-0006-...
...
─── END YAML ───
```

**原因**：generator-only 原则，skill 的唯一职责是生成文本，不能有落盘副作用。用户需手动复制粘贴到 Web UI 的 Tab B。

---

### 3. ❌ 调 POST /cases/submit（违反 §5.5.1 铁律 1）

**反例**：
```
Bash tool:
  command: curl -X POST http://localhost:8000/cases/submit \
    -H "Content-Type: application/json" \
    -d '{"yaml": "id: bug-..."}'
```

**正例**：
```
footer 提示用户：
1) 打开 http://localhost:5173/cases/new
2) 粘贴 YAML → Validate
3) Try → Save（自动提 PR）
```

**原因**：Save 才是唯一的"提交"入口，它同时做 schema 校验、跑 Try、开 PR。直接调 POST 绕过 Validate + Try 双保险。

---

### 4. ❌ DROP TABLE 不带 IF EXISTS（违反 §5.5.7 cross-check 8）

**反例**：
```yaml
setup:
  - sql: DROP TABLE test_table
  
teardown:
  - sql: DROP TABLE test_table
```

**问题**：如果 case 跑了两遍（如 Re-run 按钮），第二遍 teardown 的 DROP 会失败（表已删），导致整个 case 失败。

**正例**：
```yaml
setup:
  - sql: DROP TABLE IF EXISTS test_table
  
teardown:
  - sql: DROP TABLE IF EXISTS test_table
```

**为什么幂等性重要**：
- CI 可能重试 case
- 用户在 Try 和 Save 之间会运行多次
- 并发 suite 执行时，setup/teardown 顺序不保证

---

### 5. ❌ step kind 用 `bash` 而非 `shell`（违反 §5.5.7 cross-check 1）

**反例**：
```yaml
steps:
  - name: 检查 gpadmin 权限
    kind: bash
    sql: whoami
```

**问题**：`bash` 不在 `/admin/step-kinds` 列表里，executor 不认识，case 报错。

**正例**：
```yaml
steps:
  - name: 检查 gpadmin 权限
    kind: shell
    cmd: whoami
```

**发现方式**：
```bash
curl http://localhost:8000/admin/step-kinds
# 返回列表：[sql, shell, log_grep, restart_db]
```

---

### 6. ❌ destructive: false 但 case 含 gpstop（违反 §5.5.7 cross-check 7）

**反例**：
```yaml
destructive: false

steps:
  - name: "重启集群"
    kind: shell
    cmd: gpstop -a
  - name: "启动集群"
    kind: shell
    cmd: gpstart -a
```

**问题**：
- destructive: false 意味着 case 是"只读"，不会改变集群状态
- 实际上含 gpstop/gpstart，会打断后续其他 case 的运行
- suite 调度器依赖 destructive 标志，把破坏性 case 排到最后

**正例**：
```yaml
destructive: true

steps:
  - name: "重启集群"
    kind: shell
    cmd: gpstop -a
  - name: "启动集群"
    kind: shell
    cmd: gpstart -a
```

---

### 7. ❌ CREATE EXTENSION 不带 IF NOT EXISTS（违反 §5.5.7 cross-check 8）

**反例**：
```yaml
setup:
  - sql: CREATE EXTENSION pgvector
```

**问题**：
- 如果 case try-run 了一次，CREATE EXTENSION 失败（已存在）
- 再 try-run 一次，setup 就失败
- 用户看到"try 失败，我没法 save"

**正例**：
```yaml
setup:
  - sql: CREATE EXTENSION IF NOT EXISTS pgvector
```

**检查工具**：
```bash
grep -E 'CREATE (TABLE|EXTENSION|DATABASE|SCHEMA|INDEX)' case.yaml | grep -v 'IF NOT EXISTS'
```

---

结论：幂等性（setup/teardown 可重复跑）是 case YAML 最重要的性质，cross-check 的一半是为了保证这一点。

