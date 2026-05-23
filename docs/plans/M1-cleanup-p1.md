# M1-cleanup-p1 sprint — 4 个 P1 issues from opus review

foreman 入口文件（design.md §13.0-E）。承接 M1-cleanup (P0) 完成，opus review on M1-followup sonnet 代码留的 4 个 P1 issues 在 M2 前清掉。两个独立 PR 可并行 isolation:"worktree" 同时跑。

权威设计：
- §4.1（YAML schema：setup/teardown = list[str]、name/kind canonical 字段）
- §5.3（sql_driver / §14 R5 timeout 分层）
- §14 R5（超时分层）/ R9（异常折叠）/ R24/R25（新硬化的 specialist + foreman 反模式）

reviewer cross-reference §14 R24/R25：specialist 必须跑本地 ci-gate 等价命令 + 7 步连续走完 + 必返 final JSON。

## 任务列表

### P1-yaml — 3 个 yaml_loader.py 修复合 1 PR

**问题**：

1. **R-4 `_parse_expect()` dead code** (`backend/app/storage/yaml_loader.py:161-181`)
   - 函数定义后全文 0 调用；load_case() line 360-377 内联重写了一遍 expect 解析逻辑
   - 维护双份早晚出 bug
2. **R-5 `_parse_setup_teardown` silent-accept list[dict]** (`backend/app/storage/yaml_loader.py:136-158`)
   - `elif isinstance(item, dict): # Forward compat: pick the first string value found` 是反 schema 的 permissive 行为
   - §4.1 明确 setup/teardown = `list[str]`；坏 YAML 不应该静默通过
3. **R-6 字段别名优先级反了** (`yaml_loader.py:293, 298`)
   - `s_id = step_raw.get("id") or step_raw.get("name") or ...` — `name` 是 §4.1 canonical，应首选
   - `s_driver_raw = step_raw.get("driver") or step_raw.get("kind")` — `kind` 是 §4.1 canonical，应首选
   - 5 个真 case 都用 `name:` / `kind:`，但 loader 反过来把 sonnet 喜欢的别名当首选

**修法**：

- [x] **P1-yaml** — PR #24 (85af102) — 删 `_parse_expect` dead code ✓ / `_parse_setup_teardown` 严格 reject list[dict] ✓ / step alias 优先级 swap (name>id, kind>driver) ✓ / +3 测试
  - 删 `_parse_expect()` 函数（line 161-181）；如未来需要复用同款逻辑再抽，**don't** keep dead code
  - `_parse_setup_teardown` 改严格：`elif isinstance(item, dict): raise CaseValidationError(f"setup/teardown entry must be a string per §4.1, got dict: {item!r}")`，把"forward compat"注释整段删
  - `s_id = step_raw.get("name") or step_raw.get("id") or f"step-{idx}"` (swap order)
  - `s_driver_raw = step_raw.get("kind") or step_raw.get("driver")` (swap order)
  - 测试 `test_yaml_loader.py` 加 3 个 case：(a) setup 含 dict 现在报错（之前静默接受）；(b) step 用 `name:` 字段成功解析；(c) step 用 `kind:` 字段成功解析；删任何依赖旧 alias 优先级的现有测试
  - **跑本地 ci-gate 等价命令** (§15.2.1 step 1 / §14 R24)：`backend/.venv/bin/ruff check .` + `ruff format --check .` + `pytest -q` 三个**全绿**才 commit
  - 单 PR；走 ci-gate；reviewer cross-check §14 R24 (本地 ci-gate 已跑) + R4b (没新加硬编码)

### P1-sql — autocommit 分支补 statement_timeout 对称

**问题** (`backend/app/runner/sql_driver.py:134-158`)：

非 autocommit 分支 line 161 `await conn.execute(f"SET statement_timeout = {int(timeout_ms)}")`；autocommit 分支没设。若 `DROP DATABASE` hang 在锁等待，只有外层 `asyncio.wait_for(timeout_ms/1000 + 1.0)` 兜底——比正常 SQL 路径缺一层 PG 级超时。§14 R5"超时分层"原则该对称。

**修法**：

- [x] **P1-sql** — PR #23 (7735132) — autocommit branch 加 SET statement_timeout (在 conn.autocommit=True **之前**，timing 正确) ✓ / +1 测试验证 conn.executed 含 SET 命令 ✓ / §14 R5 超时分层对称恢复
  - autocommit 分支也 `SET statement_timeout = <ms>`；**注意顺序**：`SET` 必须在 `conn.autocommit = True` **之前** 跑（SET 自己得在 tx 里）；建议 pattern：
    ```python
    if needs_ac:
        try:
            await conn.rollback()
        except Exception:
            pass
        if timeout_ms is not None and timeout_ms > 0:
            await conn.execute(f"SET statement_timeout = {int(timeout_ms)}")
        conn.autocommit = True
        async with conn.cursor() as cur:
            ...
    ```
  - 测试 `test_sql_driver.py` 加一条：DDL step + timeout_ms 传入 → conn 收到 `SET statement_timeout` 命令（用现有的 _FakeAsyncConnection.executed list 验证）
  - 跑本地 ci-gate 等价命令全绿才 commit
  - 单 PR；与 P1-yaml 文件不同可并行（isolation:"worktree"）

## 完成定义

- P1-yaml + P1-sql 各一个 PR merged via ci-gate
- 重跑 dogfood `python -m scripts.run_m1_dogfood` → 5/5 PASS 不退（验证两个修复都不破 case 加载 / 不破 DDL 执行）
- 全 backend 单测 + ruff 全过
- M1-cleanup-p1.md 全 [x]，foreman-state.json 终态写好
- foreman **必返 final JSON 到 stdout**（§14 R25 / hard rule 8，前 2 个 session 漏返已记账，本次必须对）

## 失控防护

- 同 symptom hash fail 2 次 → escalate
- 10 round / 2h budget
- specialist 必跑本地 ci-gate 三件套（§14 R24）；ruff format 漏跑直接 reviewer REQUEST_CHANGES
