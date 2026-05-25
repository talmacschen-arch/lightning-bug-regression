"""Case YAML normalizer (design.md §4.1 → orchestrator-ready dicts).

Shared between the dogfood CLI (`backend/scripts/run_m1_dogfood.py`) and
the API path (`backend/app/api/runs.py::_load_cases_from_disk`).

**Why this module exists** (M2 dogfood follow-up, 2026-05-24): the M1
dogfood script lived its own normalizer (`backend/scripts/run_m1_dogfood.py`
pre-PR #42) so its on-cluster smoke ran 5/5 PASS. The API path
(`POST /runs` → `_load_cases_from_disk`) read the same YAMLs but did NOT
normalize — it shoved raw `setup: list[str]` dicts at the orchestrator,
which crashed at `_step_id`'s `step.get("id")` because the items were
strings. Dual-code-path divergence (design.md §14 R26 候选). This module
consolidates the normalizer so both paths share one implementation.
"""

from __future__ import annotations

from typing import Any

from app.runner.step_kinds import VALID_KIND_NAMES

# Valid step kinds — re-exported as `VALID_KINDS` for backwards compat.
# The canonical source is `app.runner.step_kinds.STEP_KINDS`; other modules
# (and tests) may still import `VALID_KINDS` from here.
VALID_KINDS = VALID_KIND_NAMES


def normalize_case(raw: dict[str, Any]) -> dict[str, Any]:
    """Turn a raw §4.1-shaped case dict into one the orchestrator can run.

    - setup / teardown of `list[str]` are wrapped into
      `{"kind": "sql", "sql": <str>, "id": "setup-NN"}` dicts (or shell
      `cmd:` for items containing `psql ` — see _normalize_setup_teardown).
    - Each step gets `id`, `kind`, `on` (defaulted) populated.
    - Per-step `database:` override is folded into the `on:` session name
      so the SqlSessionPool maps it to a distinct DSN (`default:<dbname>`).
    """
    defaults = raw.get("defaults") or {}
    default_db = defaults.get("database") or "postgres"

    # external_deps preserved through normalization so M6-5
    # external_deps_loader.collect_external_deps() can read it from the
    # orchestrator-shaped dict.
    external_deps = raw.get("external_deps") or []
    if not isinstance(external_deps, list):
        external_deps = []

    out: dict[str, Any] = {
        "id": raw.get("id"),
        "title": raw.get("title"),
        "category": raw.get("category"),
        "status": raw.get("status"),
        "destructive": bool(raw.get("destructive", False)),
        "external_deps": external_deps,
        "setup": _normalize_setup_teardown(raw.get("setup"), default_db, "setup"),
        "teardown": _normalize_setup_teardown(raw.get("teardown"), default_db, "teardown"),
        "steps": _normalize_steps(raw.get("steps") or [], default_db),
    }
    return out


def _normalize_setup_teardown(
    items: Any,
    default_db: str,
    prefix: str,
) -> list[dict[str, Any]]:
    if not items:
        return []
    out: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if isinstance(item, str):
            stripped = item.lstrip()
            # Convention (design.md §4.1, 2026-05-24 用户决策): setup/teardown 字符串
            # 含 `psql ` 子串时路由到 shell driver 而非 sql_driver。理由 = 像
            # CREATE/DROP DATABASE、CREATE/DROP EXTENSION 这种 non-tx-safe DDL，
            # 让 psql 自己起独立 session 比让 psycopg 试图 autocommit 包它更稳。
            # 用 `in` 不用 `startswith` 是为了支持 `su - gpadmin -c "psql ..."`
            # 这种 wrap 形式（§3.1 集群访问约定）。
            if "psql " in stripped or "psql\t" in stripped:
                out.append(
                    {
                        "id": f"{prefix}-{i:02d}",
                        "kind": "shell",
                        "cmd": item,
                    }
                )
            else:
                out.append(
                    {
                        "id": f"{prefix}-{i:02d}",
                        "kind": "sql",
                        "sql": item,
                        "on": f"default:{default_db}",
                    }
                )
        elif isinstance(item, dict):
            # Already a dict-shaped step — apply same normalization as main steps.
            out.append(_normalize_one_step(item, i, default_db, default_id_prefix=prefix))
        else:
            raise ValueError(
                f"{prefix}[{i}] must be a string or dict, got {type(item).__name__}: {item!r}"
            )
    return out


def _normalize_steps(steps: list[Any], default_db: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"steps[{i}] must be a dict, got {type(step).__name__}: {step!r}")
        out.append(_normalize_one_step(step, i, default_db, default_id_prefix="step"))
    return out


def _normalize_one_step(
    step: dict[str, Any],
    idx: int,
    default_db: str,
    *,
    default_id_prefix: str,
) -> dict[str, Any]:
    """Normalize one step dict.

    - id  ← step.id or step.name or `<prefix>-NN`
    - kind ← step.kind or step.driver, must be in VALID_KINDS
    - on  ← step.on or `default:<default_db>`; per-step `database:` override
            becomes `default:<dbname>` so SqlSessionPool routes to a distinct
            connection.
    - sql / cmd / run / expect / timeout_ms / host / database passthrough.
    """
    out: dict[str, Any] = dict(step)

    # id
    out["id"] = step.get("id") or step.get("name") or f"{default_id_prefix}-{idx:02d}"

    # kind
    kind = step.get("kind") or step.get("driver")
    if not kind:
        raise ValueError(f"step {out['id']!r} missing kind/driver")
    if kind not in VALID_KINDS:
        raise ValueError(
            f"step {out['id']!r} has invalid kind {kind!r}; expected one of {sorted(VALID_KINDS)}"
        )
    out["kind"] = kind

    # on / database
    step_db = step.get("database")
    if step_db:
        out["on"] = f"default:{step_db}"
    else:
        out["on"] = step.get("on") or f"default:{default_db}"

    # YAML-author-friendly alias: timeout_sec → timeout_ms. Orchestrator only
    # reads timeout_ms; without this conversion every author who wrote
    # timeout_sec silently fell back to the 60s default (dogfood 2026-05-25
    # lg-bug-0011 v1: setup INSERT of 98M rows was killed at exactly 60s
    # with asyncio.TimeoutError despite `timeout_sec: 120`). timeout_ms wins
    # on conflict (explicit canonical key).
    if "timeout_sec" in step and "timeout_ms" not in out:
        sec = step["timeout_sec"]
        if sec is not None:
            out["timeout_ms"] = int(sec) * 1000
    out.pop("timeout_sec", None)

    # sql kind needs sql:/run:
    if kind == "sql" and not (step.get("sql") or step.get("run")):
        raise ValueError(f"sql step {out['id']!r} missing sql/run field")
    # shell kind needs cmd:/run:
    if kind == "shell" and not (step.get("cmd") or step.get("run")):
        raise ValueError(f"shell step {out['id']!r} missing cmd/run field")
    # log_grep needs pattern + path/log_path (orchestrator validates).

    return out
