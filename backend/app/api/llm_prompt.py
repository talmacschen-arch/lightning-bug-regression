"""LLM prompt builder for ``POST /cases/generate-draft`` (design.md §5.4 / §13.13).

This module is the **single source of truth** for the system prompt the
Anthropic SDK call uses to turn a free-text bug description into a §4.1-shaped
case YAML draft.

Why this lives in its own module:
  * Keeps `cases.py` endpoint code focused on HTTP shape + retry control.
  * Lets the tests assert prompt structure (e.g. "previous validation
    error appears in retry prompt") without parsing endpoint code.
  * §14 R26: schema text + canonical field order + psql-c iron rule
    appear here exactly once; the endpoint pulls them via
    :func:`build_system_blocks`, never re-spelling them inline.

Design choices (§13.13 v1.25 amendment):
  * **Few-shot examples are hardcoded** as 3 verbatim case YAML strings
    (D2). Drift is acceptable — when the seed cases evolve, a follow-up
    PR hand-syncs the strings. Dynamic `/admin/few-shot` was rejected
    as over-abstraction.
  * **Category list is NOT hardcoded** (§14 R4b) — :func:`build_system_blocks`
    takes ``allowed_categories`` and the per-category ``status_whitelist``
    map and injects them at call time, fetched from ``case_categories``.
  * **Prompt caching (G)**: schema + few-shot are placed into a single
    long "shared prefix" block flagged with
    ``cache_control={"type": "ephemeral"}``. The user description varies
    every call and is sent as a separate uncached block.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Static prompt sections (schema simplification + house rules)
# ---------------------------------------------------------------------------

# §4.1 schema 简版 — only the fields the LLM needs to fill. Kept short
# because the full schema includes many optional fields the model can
# learn from few-shot examples without prose.
_SCHEMA_BLOCK = """\
# YAML schema (§4.1 simplified)

Every case MUST be a YAML mapping with these top-level keys:

  id           string, MUST match `<id_prefix><slug>` for chosen category
  title        string (Chinese OK)
  category     one of {{ALLOWED_CATEGORIES}}
  status       one of category's status_whitelist (see per-category list below)
  severity     "high" | "medium" | "low"
  destructive  bool — true iff steps mutate cluster state / restart DB

  description  multi-line string — narrative: WHAT is being verified
  procedure    multi-line string — numbered reproduction steps
  expected     multi-line string — pass criteria

  applies_to       mapping, e.g. {} or {versions: ">=1.6,<2.0"}
  preconditions    mapping — optional, e.g. {options: {orca: ["off"]}}
  external_deps    list — usually [] for bug/extension; external_systems uses it

  defaults     mapping with `database: <db_name>` — see "Defaults" below
  sessions     mapping or omitted — for concurrent / multi-session cases

  setup        list of items — see "setup/teardown items" below
  steps        list of step mappings — see "step mapping" below
  teardown     list — same shape as setup

  source       mapping (feishu_anchor / reported_at / fixed_version / ext_doc_url)
  issue_url    string
  tags         list of strings
  created_by   string
  created_at   "YYYY-MM-DD"
  notes        multi-line string — caveats / known facts
"""


_STEP_BLOCK = """\
# step mapping

Each item under `steps:` is a mapping with:

  name         short Chinese/English description
  kind         one of "sql" | "shell" | "log_grep" | "restart_db"
  on           session name, defaults to "default" if omitted
  timeout_sec  int seconds (typical 30-600)

Per-kind required fields:
  - kind: sql      → `sql: |  <SQL text>`
  - kind: shell    → `cmd: |  <shell command>`
  - kind: log_grep → `pattern: "<regex>"` and optional `expect.matches: <int>`
  - kind: restart_db → no body needed; destructive: true MUST be set on case

expect: mapping. Field menu (pick what's relevant):
  exit_code: 0                   # shell
  not_contains: ["ERROR", "FATAL"]
  contains: ["substring"]
  plan_contains: ["Hash"]        # sql with EXPLAIN — substring on plan text
  scalar_eq: 42                  # sql returning single row/column
  duration_lt_ms: 5000
  matches: 0                     # log_grep — expected number of pattern hits
"""


# (E-1) gpadmin default (2026-05-24 new spec) — must appear EXPLICITLY,
# few-shot example #3 shows it but the model should treat this as a hard
# rule, not an inference target.
_DEFAULTS_BLOCK = """\
# Defaults

When the user description does NOT mention a specific database name, you MUST
fill:
    defaults:
      database: gpadmin

(`gpadmin` is the canonical default since 2026-05-24 — NOT `postgres`. Five
legacy cases on disk still say `postgres`; do not mirror them.)
"""


# (E-2) §4.1.2 psql -c iron rule — must appear EXPLICITLY. The bug this
# guards against (DDL silently rolled back inside a psycopg transaction)
# is invisible from happy-path examples alone, so we tell the model
# in prose.
_PSQL_RULE_BLOCK = """\
# §4.1.2 psql -c iron rule (non-tx-safe DDL)

The following DDL statements CANNOT run inside a psycopg-managed transaction —
PostgreSQL rejects them with "cannot run inside a transaction block" or the
DDL silently has no effect when the connection commits:

  - VACUUM            (any form, including FULL)
  - ANALYZE           (top-level, NOT `ANALYZE` inside SET-then-ANALYZE flow)
  - CREATE DATABASE / DROP DATABASE
  - REINDEX CONCURRENTLY
  - ALTER SYSTEM
  - CLUSTER
  - CREATE EXTENSION / DROP EXTENSION

For these statements you MUST use a `kind: shell` step that wraps the DDL
in `psql -c '<DDL>'`:

  - name: "VACUUM 不应触发 crash"
    kind: shell
    cmd: |
      su - gpadmin -c "psql -d gpadmin -c 'VACUUM FULL toast_bug_array'"
    timeout_sec: 600
    expect:
      exit_code: 0
      not_contains: ["ERROR", "FATAL"]

Do NOT put these statements inside a `kind: sql` step.

Regular tx-safe SQL (CREATE TABLE, INSERT, SELECT, SET, regular CREATE INDEX,
EXPLAIN) goes in `kind: sql` as usual — sql_driver auto-commits at step end
so the data IS visible to a subsequent `psql -c` shell step.
"""


_FIELD_ORDER_BLOCK = """\
# Canonical field order (§17.6)

Emit top-level keys in this exact order (skip the optional ones you don't
need; do NOT reorder):

  id
  title
  category
  status
  severity
  destructive

  source
  issue_url
  tags

  description
  procedure
  expected

  applies_to
  preconditions
  external_deps

  defaults
  sessions

  setup
  steps
  teardown

  created_by
  created_at
  notes
"""


_OUTPUT_BLOCK = """\
# Output format

Reply with **ONLY** the YAML document — no prose, no markdown fences, no
``` code blocks. The first character of your reply MUST be `i` (start of
`id:`) and the last non-whitespace character MUST belong to the YAML.

If you cannot fulfill the request (description too vague, contradictory),
still emit a best-effort YAML draft and put your concerns into `notes:`.
"""


# ---------------------------------------------------------------------------
# Few-shot examples (D2: 3 hardcoded, verbatim from cases/)
# ---------------------------------------------------------------------------
#
# These strings are copy-pasted verbatim from cases/. When the source files
# evolve, hand-sync this module. The 3 examples cover the three main forms:
#
#   1. bug-0001-hashjoin-right-table        — bug_regression, simple SQL
#   2. ext-pgvector-ivfflat-basic           — extension, CREATE EXTENSION
#   3. bug-0008-pax-toast-vacuum-analyze-crash
#                                               — cross-driver §4.1.2
#                                                 (kind: sql + kind: shell
#                                                 psql -c VACUUM/ANALYZE)
#
# Wrapping notes:
#   - `${SCHEMA_BREAK}` deliberately not used; we paste the YAML literally.
#   - Each example is preceded by a one-line "Description that produced this:"
#     so the model can see the description → YAML mapping.

_FEW_SHOT_EXAMPLES = [
    {
        "id": "bug-0001-hashjoin-right-table",
        "trigger_description": (
            "ORCA 关闭、两表 analyze 后，DELETE...USING 的 hashjoin 应当选小表"
            "tmp_test02（1000 行）作为右表（hash build 侧）；若选了大表"
            "tmp_test01（1000 万行）则代价模型有问题。"
        ),
        "yaml": """\
id: bug-0001-hashjoin-right-table
title: ORCA off + analyze 后 hashjoin 右表应选小表 tmp_test02
category: bug_regression
status: fixed
severity: high
destructive: false

source:
  feishu_anchor: "lightning-2.2-2.3-upgrade-regression"
  reported_at: "2025-12-01"
  fixed_version: "SynxDB-4.5.0-build130"
  ext_doc_url: ""
issue_url: ""
tags: [optimizer, hashjoin, planner]

description: |
  ORCA 关闭、两表 analyze 后，DELETE...USING 的 hashjoin 应当选小表
  tmp_test02（1000 行）作为右表（hash build 侧）；若选了大表 tmp_test01
  （1000 万行）则代价模型有问题，会引发严重性能退化。
procedure: |
  1) 关闭 ORCA、建大小两个 temp 表；
  2) 大表 1000 万行、小表 1000 行，两边都 analyze；
  3) explain DELETE FROM 大表 USING 小表 ON eq；
  4) 检查 plan 里 hash build 侧是否是 tmp_test02。
expected: |
  - 步骤 3 的 explain plan 文本里出现 "tmp_test02" 作为 hash build 侧；
  - 不出现以大表 tmp_test01 作为 hash build 侧的形态。

applies_to: {}
preconditions: {}
external_deps: []

defaults:
  database: postgres

setup:
  - DROP TABLE IF EXISTS tmp_test01
  - DROP TABLE IF EXISTS tmp_test02
  - |
    CREATE TEMP TABLE tmp_test01 (i int);
    CREATE INDEX IF NOT EXISTS idx_tmp_test01_i ON tmp_test01 USING btree(i);
    INSERT INTO tmp_test01 SELECT i FROM generate_series(1, 1) i;
    ANALYZE tmp_test01;
    INSERT INTO tmp_test01 SELECT i FROM generate_series(1, 10000000) i
  - |
    CREATE TEMP TABLE tmp_test02 (i int);
    INSERT INTO tmp_test02 SELECT i FROM generate_series(1, 1000) i;
    ANALYZE tmp_test02

steps:
  - name: "ORCA off + analyze 后 explain plan 检查 hash build 侧"
    kind: sql
    sql: |
      SET optimizer TO off;
      ANALYZE tmp_test01;
      EXPLAIN DELETE FROM tmp_test01 f USING tmp_test02 b WHERE f.i = b.i
    expect:
      plan_contains: ["Hash", "tmp_test02"]
      not_contains: "ERROR"

teardown:
  - DROP TABLE IF EXISTS tmp_test01
  - DROP TABLE IF EXISTS tmp_test02

created_by: chenqiang
created_at: "2026-05-23"
notes: |
  ORCA off + analyze 后必须选小表。
""",
    },
    {
        "id": "ext-pgvector-ivfflat-basic",
        "trigger_description": (
            "验证 pgvector extension 基础集成链路：CREATE EXTENSION → vector 类型"
            "→ IVFFlat 索引 → L2 距离查询 → 计划走索引。"
        ),
        "yaml": """\
id: ext-pgvector-ivfflat-basic
title: pgvector IVFFlat 索引基础功能验证
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
tags: [extension, pgvector, vector, ivfflat, similarity_search]

description: |
  验证 pgvector extension 在 lightning 环境下的基础集成链路：
  CREATE EXTENSION → vector 类型 → IVFFlat 索引 → L2 距离查询 → 计划走索引。
procedure: |
  1) CREATE EXTENSION IF NOT EXISTS vector，建 vectors_demo(id int, embedding vector(3));
  2) 插入 10000 条随机三维向量，ANALYZE；
  3) 在 embedding 上创建 IVFFlat 索引（lists=10, vector_l2_ops）；
  4) SET enable_seqscan = off 强制走索引，EXPLAIN ANALYZE 一个 LIMIT 10 的相似度查询；
  5) 断言执行计划包含 "Index Scan using" 且不含 "Seq Scan"。
expected: |
  - CREATE EXTENSION vector 成功；
  - CREATE INDEX ... USING ivfflat 成功且不报错；
  - EXPLAIN 输出含 "Index Scan using idx_vectors_ivfflat"；
  - 不出现 "ERROR" / "FATAL"。

applies_to: {}
preconditions: {}
external_deps: []

defaults:
  database: postgres

sessions: []

setup:
  - DROP TABLE IF EXISTS vectors_demo
  - CREATE EXTENSION IF NOT EXISTS vector
  - |
    CREATE TABLE IF NOT EXISTS vectors_demo (
      id SERIAL PRIMARY KEY,
      embedding vector(3)
    )
  - |
    INSERT INTO vectors_demo (embedding)
    SELECT ARRAY[random(), random(), random()]::vector(3)
    FROM generate_series(1, 10000)
  - ANALYZE vectors_demo

steps:
  - name: "在 embedding 上创建 IVFFlat 索引"
    kind: sql
    sql: |
      CREATE INDEX IF NOT EXISTS idx_vectors_ivfflat
      ON vectors_demo
      USING ivfflat (embedding vector_l2_ops)
      WITH (lists = 10)
    expect:
      not_contains: ["ERROR", "FATAL"]

  - name: "强制走索引并断言 IVFFlat 命中"
    kind: sql
    sql: |
      SET enable_seqscan = off;
      EXPLAIN
      SELECT id, embedding <-> '[0.5,0.5,0.5]'::vector(3) AS dist
      FROM vectors_demo
      ORDER BY embedding <-> '[0.5,0.5,0.5]'::vector(3)
      LIMIT 10
    expect:
      plan_contains: ["Index Scan", "idx_vectors_ivfflat"]
      not_contains: ["ERROR", "Seq Scan on vectors_demo"]

teardown:
  - DROP INDEX IF EXISTS idx_vectors_ivfflat
  - DROP TABLE IF EXISTS vectors_demo

created_by: chenqiang
created_at: "2026-05-24"
notes: |
  pgvector 注册的扩展名是 `vector`，不是 `pgvector`。
""",
    },
    {
        "id": "bug-0008-pax-toast-vacuum-analyze-crash",
        "trigger_description": (
            "PAX + DISTRIBUTED REPLICATED 表里有 1 行 NULL + 1 行需要走 TOAST"
            "的大数组，顺序跑 VACUUM FULL 然后 ANALYZE 会触发集群 crash。"
            "验证 fix 后不再 crash。"
        ),
        "yaml": """\
id: bug-0008-pax-toast-vacuum-analyze-crash
title: PAX 表含 TOAST 大数组与 NULL 行时 VACUUM FULL + ANALYZE 触发数据库 crash
category: bug_regression
status: fixed
severity: high
destructive: false

source:
  feishu_anchor: "section-9.11-pax-toast-vacuum-analyze-crash"
  reported_at: "2026-05-24"
  fixed_version: "SynxDB-4.5.0-build130"
  ext_doc_url: ""
issue_url: https://code.hashdata.xyz/field-engineering/dev_collaboration/-/issues/774
tags: [pax, toast, vacuum, analyze, crash]

description: |
  PAX + DISTRIBUTED REPLICATED 表里有 1 行 NULL + 1 行需要走 TOAST 外部存储的
  大数组（≈10M 元素），顺序跑 VACUUM FULL 然后 ANALYZE 会触发集群 crash。
procedure: |
  1) setup: DROP + CREATE PAX REPLICATED 表
  2) SET pax.enable_toast = on; INSERT 1 NULL 行 + 1 行 10M ARRAY (kind: sql)
  3) psql -c 'VACUUM FULL toast_bug_array' (kind: shell)
  4) psql -c 'ANALYZE toast_bug_array' (kind: shell)
  5) teardown
expected: |
  - INSERT 退出 0、未报错；
  - VACUUM/ANALYZE 退出 0，stderr 不含 ERROR / FATAL / server closed；
  - 集群不 crash。

applies_to: {}
preconditions: {}
external_deps: []

defaults:
  database: gpadmin

setup:
  - DROP TABLE IF EXISTS toast_bug_array
  - |
    CREATE TABLE toast_bug_array (
      id   INT,
      data TEXT[]
    ) USING PAX DISTRIBUTED REPLICATED

steps:
  - name: "SET pax.enable_toast + INSERT 1 NULL + 1 大数组 (10M elements)"
    kind: sql
    sql: |
      SET pax.enable_toast = on;
      INSERT INTO toast_bug_array VALUES
        (1, NULL),
        (2, ARRAY(SELECT 'element_' || generate_series(1, 10000000)));
    timeout_sec: 600
    expect:
      not_contains: ["ERROR", "FATAL", "server closed the connection"]

  - name: "VACUUM FULL 不应触发 crash"
    kind: shell
    cmd: |
      su - gpadmin -c "psql -d gpadmin -c 'VACUUM FULL toast_bug_array'"
    timeout_sec: 600
    expect:
      exit_code: 0
      not_contains: ["ERROR", "FATAL", "server closed the connection"]

  - name: "ANALYZE 不应触发 crash"
    kind: shell
    cmd: |
      su - gpadmin -c "psql -d gpadmin -c 'ANALYZE toast_bug_array'"
    timeout_sec: 600
    expect:
      exit_code: 0
      not_contains: ["ERROR", "FATAL", "server closed the connection"]

teardown:
  - DROP TABLE IF EXISTS toast_bug_array

created_by: chenqiang
created_at: "2026-05-24"
notes: |
  VACUUM/ANALYZE 是 non-tx-safe DDL → 必须 kind: shell + psql -c。
  CREATE TABLE + SET + INSERT 是 tx-safe → kind: sql 走 psycopg。
  sql_driver 每个 sql step 末尾自动 commit，所以 INSERT 对后续 psql -c
  子进程可见。
""",
    },
]


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _format_status_whitelists(status_whitelist_by_category: dict[str, list[str]]) -> str:
    """Render the per-category status_whitelist as a small bullet table.

    The LLM uses this to keep `status:` legal — `closed` / `wip` / `random`
    must NOT appear if the category whitelist doesn't include them, and the
    retry-with-error-injected loop relies on the model knowing which token
    is wrong.
    """
    lines = ["# Per-category status_whitelist (from /admin/categories)"]
    if not status_whitelist_by_category:
        lines.append("(none — backend has no active categories; refuse generation)")
        return "\n".join(lines)
    for cat in sorted(status_whitelist_by_category):
        wl = status_whitelist_by_category[cat]
        lines.append(f"  {cat}: {wl}")
    return "\n".join(lines)


def build_few_shot_block() -> str:
    """Render the 3 hardcoded examples into one string block.

    Exposed (not _underscore'd) so tests can assert e.g. "few-shot block
    contains bug-0008's PAX YAML" without re-spelling the YAML.
    """
    parts: list[str] = ["# Few-shot examples (study these for structure + tone)"]
    for ex in _FEW_SHOT_EXAMPLES:
        parts.append("---")
        parts.append(f"Description that produced this YAML:\n  {ex['trigger_description']}")
        parts.append("YAML:")
        parts.append(ex["yaml"])
    return "\n\n".join(parts)


def build_system_blocks(
    *,
    allowed_categories: list[str],
    status_whitelist_by_category: dict[str, list[str]],
) -> list[dict[str, object]]:
    """Return the system blocks (the **cached** prefix) for `messages.create`.

    Returns a list of one block — the entire prompt prefix (schema +
    examples + house rules) marked with ``cache_control: ephemeral``.
    Anthropic SDK accepts this shape as the ``system=`` parameter.

    The category list is injected at call time per §14 R4b. Allowed
    categories are sorted for prompt-cache stability — feeding the same
    set in a different list order would defeat the cache.

    Returns:
        A list with a single dict::

            [{
                "type": "text",
                "text": "<schema + examples + rules>",
                "cache_control": {"type": "ephemeral"},
            }]

    User-supplied description is **not** part of this prefix — it goes
    into the messages array as a normal (uncached) user turn.
    """
    allowed_list_str = ", ".join(sorted(allowed_categories)) if allowed_categories else "(none)"
    schema = _SCHEMA_BLOCK.replace("{{ALLOWED_CATEGORIES}}", allowed_list_str)
    sw = _format_status_whitelists(status_whitelist_by_category)

    body = "\n\n".join(
        [
            schema,
            sw,
            _STEP_BLOCK,
            _DEFAULTS_BLOCK,
            _PSQL_RULE_BLOCK,
            _FIELD_ORDER_BLOCK,
            build_few_shot_block(),
            _OUTPUT_BLOCK,
        ]
    )
    return [
        {
            "type": "text",
            "text": body,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def build_user_message(
    *,
    description: str,
    category: str | None,
    previous_validation_error: str | None = None,
) -> str:
    """Build the *uncached* user-turn text.

    On retry, ``previous_validation_error`` carries the validator's
    message from the failed attempt — the LLM uses it to correct the
    output. Without this feedback the retry would just be a blind reroll.

    The exact substring of the previous error MUST appear in the returned
    string (test wiring asserts this — §13.13 amendment constraint D).
    """
    parts: list[str] = []
    if previous_validation_error:
        parts.append(
            "## Previous attempt FAILED validation. Fix these errors and try again:\n"
            f"{previous_validation_error}\n"
        )
    parts.append("## Bug / extension description from user:")
    parts.append(description.strip() or "(empty)")
    if category:
        parts.append(f"\n## User-selected category: `{category}`")
        parts.append(
            "Use this category. Choose `id_prefix` and `status` from this category's whitelist."
        )
    else:
        parts.append(
            "\n## Category: user did NOT pre-select; you choose the most appropriate one"
            " from the allowed list above."
        )
    parts.append("\nProduce the YAML draft now. Output ONLY the YAML — no fences, no commentary.")
    return "\n".join(parts)


__all__ = [
    "build_system_blocks",
    "build_user_message",
    "build_few_shot_block",
]
