"""Step-kind registry — the single source of truth for legal step kinds.

This module exists so external consumers (the
`.claude/skills/add-test-case` skill in particular, design.md §5.5.7
cross-check) can fetch the canonical list of step kinds + their
required/optional fields via `GET /admin/step-kinds`, instead of
hard-coding their own copy and drifting (§14 R26 dual-code-path).

Required/optional fields below mirror what the drivers + normalizer
actually consume — verified against:
  - `case_normalizer._normalize_one_step`     (sql/cmd/run aliases)
  - `sql_driver.execute_sql_step`             (session/timeout)
  - `shell_driver.execute_shell_step`         (command/timeout)
  - `log_grep_driver.execute_log_grep_step`   (log_path/pattern)
  - `orchestrator._execute_one_step`          (log_path|path alias)

If you add a new kind here you MUST also wire it into the orchestrator
dispatch + add a driver — the registry is the contract, not the impl.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StepKindMeta:
    """Per-kind metadata returned by `/admin/step-kinds`.

    `required_fields` lists the canonical YAML keys a step of this kind
    MUST set. Where the loader/normalizer accepts an alias (e.g. `sql`
    step accepts `run:` in place of `sql:`), the alias appears in
    `optional_fields` with a leading-form comment in the
    step_kinds.py source.
    """

    kind: str
    description: str
    required_fields: list[str]
    optional_fields: list[str] = field(default_factory=list)


# Order here is preserved by `GET /admin/step-kinds` — kept stable so
# the skill's prompt template can reference positional examples.
STEP_KINDS: list[StepKindMeta] = [
    StepKindMeta(
        kind="sql",
        description="对目标数据库执行 SQL，可断言 row_count / scalar / plan_contains 等。",
        required_fields=["sql"],
        # `run` is a loader-accepted alias for `sql` (yaml_loader.py:322).
        # `on` selects a named session; `database` overrides the default DB
        # and is folded into the session key by case_normalizer.
        optional_fields=["run", "on", "database", "timeout_ms", "expect"],
    ),
    StepKindMeta(
        kind="shell",
        description=(
            "在控制节点本地（或通过 ssh 远端）执行 shell 命令，可断言 exit_code / stdout_contains。"
        ),
        required_fields=["cmd"],
        # `run` is a loader-accepted alias for `cmd` (yaml_loader.py:322).
        # `host` is consumed by orchestrator._render_step_fields to choose
        # ssh_user — the YAML author embeds it into the cmd string via
        # `ssh {{ ssh_user }}@{{ host }} '...'`.
        optional_fields=["run", "host", "timeout_ms", "expect"],
    ),
    StepKindMeta(
        kind="log_grep",
        description="在指定目录下按正则扫描 mtime 落在 case 运行窗口内的文件，断言匹配数。",
        required_fields=["pattern", "log_path"],
        # `path` is an orchestrator-accepted alias for `log_path`
        # (orchestrator.py:334). expect.matches / matches_lt / matches_ge
        # live under the generic `expect` mapping.
        optional_fields=["path", "timeout_ms", "expect"],
    ),
]


# Derived set used by case_normalizer + tests. Single source of truth:
# downstream modules import this rather than re-listing `{"sql", ...}`.
VALID_KIND_NAMES: frozenset[str] = frozenset(k.kind for k in STEP_KINDS)


__all__ = ["STEP_KINDS", "StepKindMeta", "VALID_KIND_NAMES"]
