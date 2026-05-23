"""Case YAML loader + §4.1 schema validator.

Loads a single case YAML file from disk and validates it against the M1
slice of the §4.1 schema (4-tuple narrative fields, step-level expect,
sessions, external_deps, destructive, status).

Caller (orchestrator / API) is responsible for fetching the
`case_categories` whitelist from the DB and passing it in as
``categories_whitelist`` — the loader itself does NOT touch the DB. This
keeps the loader unit-testable and independent of M1-3 (sqlite_store).

All schema violations are raised as :class:`CaseValidationError` with a
``<file_path>:<line_or_key>: <reason>`` message so callers (and the
``POST /cases/validate`` endpoint, M1-10) can surface the exact line /
field to the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml


class _CaseYamlLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2-style bool resolution.

    PyYAML implements YAML 1.1, where bare ``on`` / ``off`` / ``yes`` / ``no`` /
    ``y`` / ``n`` are booleans (the "Norway problem"). §4.1 uses ``on: <session>``
    to route a step at a named session, so we need ``on`` to stay a string.
    YAML 1.2 already restricts bool to ``true`` / ``false`` (case-insensitive),
    matching this loader's behavior.
    """


# Copy resolver map and strip out the default bool resolver, then re-add a
# stricter one. (PyYAML loaders share `yaml_implicit_resolvers` by reference
# through inheritance; we copy to keep the change local to _CaseYamlLoader.)
_CaseYamlLoader.yaml_implicit_resolvers = {
    ch: [(tag, regex) for (tag, regex) in resolvers if tag != "tag:yaml.org,2002:bool"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_CaseYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)

# Category → required id-prefix. If a category is in the whitelist but not
# in this dict, the loader does not enforce a prefix (forward-compat for
# new categories added to `case_categories` before the loader ships).
# Both dash and underscore forms are accepted (DB seeds use underscore;
# legacy YAML files used dash).
_CATEGORY_PREFIX = {
    "bug-regression": "lg-bug-",
    "bug_regression": "lg-bug-",
    "feature-validation": "lg-feat-",
    "feature_validation": "lg-feat-",
    "perf-regression": "lg-perf-",
    "perf_regression": "lg-perf-",
    "ops-runbook": "lg-ops-",
    "ops_runbook": "lg-ops-",
}

# Required top-level keys (sessions is optional — derived when absent).
_REQUIRED_TOP_LEVEL = (
    "id",
    "category",
    "title",
    "description",
    "procedure",
    "expected",
    "steps",
)

_VALID_DRIVERS = frozenset({"sql", "shell", "log_grep"})
_VALID_STATUSES = frozenset({"open", "closed", "stub"})


class CaseValidationError(ValueError):
    """Raised when a case YAML violates §4.1 schema.

    Message format: ``<file_path>:<line_or_key>: <human-readable reason>``.
    """


@dataclass
class ExpectClause:
    """One expect entry inside step.expect or case-level expect.

    Key is the expect field name (e.g. 'exit_code', 'scalar_eq',
    'row_count'); value is whatever the YAML provides (int / str / list /
    dict).
    """

    key: str
    value: Any


@dataclass
class Step:
    id: str
    on: str  # session name (driver-routed)
    driver: Literal["sql", "shell", "log_grep"]
    run: str  # raw template (Jinja rendered later); empty string for log_grep
    timeout_ms: int | None = None
    expect: list[ExpectClause] = field(default_factory=list)
    continue_on_fail: bool = False


@dataclass
class Case:
    id: str  # must match filename stem and start with category prefix
    category: str  # must be in categories_whitelist
    title: str
    description: str  # §4.1 4-tuple: required
    procedure: str  # required
    expected: str  # required
    sessions: dict[str, dict]  # session_name -> {driver: str, ...config}
    steps: list[Step]
    external_deps: list[str] = field(default_factory=list)
    destructive: bool = False
    status: Literal["open", "closed", "stub"] = "open"
    setup: list[str] = field(default_factory=list)
    teardown: list[str] = field(default_factory=list)


def _err(path: Path, where: str, reason: str) -> CaseValidationError:
    """Build a CaseValidationError with the standard message format."""
    return CaseValidationError(f"{path}:{where}: {reason}")


def _parse_setup_teardown(raw: Any) -> list[str]:
    """Convert setup/teardown field to list[str].

    Accepts:
    - list[str] — stored as-is
    - list[dict] — extract the first string value from each dict (forward compat)
    - None / missing — return []
    """
    if not raw:
        return []
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            # Forward compat: pick the first string value found
            for v in item.values():
                if isinstance(v, str):
                    result.append(v)
                    break
    return result


def _parse_expect(raw: Any) -> list[ExpectClause]:
    """Parse expect field into list[ExpectClause].

    Accepts two formats:
    - list of single-key dicts: [{"exit_code": 0}, {"scalar_eq": 5}]  (old schema)
    - plain dict: {"exit_code": 0, "scalar_eq": 5}  (real case format)
    """
    if not raw:
        return []
    if isinstance(raw, dict):
        return [ExpectClause(key=k, value=v) for k, v in raw.items()]
    if isinstance(raw, list):
        clauses: list[ExpectClause] = []
        for entry in raw:
            if not isinstance(entry, dict) or len(entry) != 1:
                # Caller will raise a proper error; return sentinel
                return raw  # type: ignore[return-value]
            ((e_key, e_val),) = entry.items()
            clauses.append(ExpectClause(key=e_key, value=e_val))
        return clauses
    return []


def load_case(path: Path, categories_whitelist: set[str]) -> Case:
    """Load and validate one case YAML.

    Raises :class:`CaseValidationError` with a ``file:key`` location on:

    * YAML syntax error
    * missing required top-level field (``id`` / ``category`` / ``title`` /
      ``description`` / ``procedure`` / ``expected`` / ``steps``)
    * ``category`` not in whitelist
    * ``id`` prefix mismatch for a known category (e.g.
      ``category='bug-regression'`` or ``category='bug_regression'`` requires
      id starting with ``lg-bug-``)
    * ``id`` not equal to ``path.stem``
    * step missing ``id``/``name`` and ``driver``/``kind`` fields
    * ``step.driver`` not in ``{sql, shell, log_grep}``
    * ``step.on`` not in the case's ``sessions`` dict (when sessions is
      explicitly declared)
    * ``step.expect`` entry not a single-key mapping (when list format)
    * ``destructive`` not a bool
    * ``status`` not in ``{open, closed, stub}``
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as e:  # pragma: no cover — fs errors aren't our schema's job
        raise _err(path, "file", f"cannot read file: {e}") from e

    try:
        data = yaml.load(raw_text, Loader=_CaseYamlLoader)
    except yaml.YAMLError as e:
        # yaml.MarkedYAMLError exposes problem_mark.line (0-indexed).
        line: int | str = "yaml"
        mark = getattr(e, "problem_mark", None)
        if mark is not None:
            line = mark.line + 1
        raise _err(path, str(line), f"YAML syntax error: {e}") from e

    if not isinstance(data, dict):
        raise _err(path, "root", "top-level YAML must be a mapping")

    # --- required top-level fields ---
    for key in _REQUIRED_TOP_LEVEL:
        if key not in data:
            raise _err(path, key, f"missing required field '{key}'")

    # --- type checks for scalar fields ---
    for key in ("id", "category", "title", "description", "procedure", "expected"):
        if not isinstance(data[key], str) or not data[key]:
            raise _err(path, key, f"field '{key}' must be a non-empty string")

    case_id: str = data["id"]
    category: str = data["category"]

    # --- category whitelist ---
    if category not in categories_whitelist:
        raise _err(
            path,
            "category",
            f"category '{category}' not in whitelist {sorted(categories_whitelist)}",
        )

    # --- id-prefix enforcement (only for categories with a known prefix) ---
    expected_prefix = _CATEGORY_PREFIX.get(category)
    if expected_prefix is not None and not case_id.startswith(expected_prefix):
        raise _err(
            path,
            "id",
            f"id '{case_id}' must start with expected prefix '{expected_prefix}' "
            f"for category '{category}'",
        )

    # --- id == filename stem ---
    if case_id != path.stem:
        raise _err(
            path,
            "id",
            f"id '{case_id}' must equal filename stem '{path.stem}'",
        )

    # --- sessions: optional dict[str, dict] ---
    # When absent, derive a default session so steps can route to "default".
    sessions_raw = data.get("sessions")
    sessions_derived = False
    if sessions_raw is None:
        sessions = {"default": {"driver": "sql"}}
        sessions_derived = True
    else:
        if not isinstance(sessions_raw, dict) or not sessions_raw:
            raise _err(path, "sessions", "sessions must be a non-empty mapping")
        for s_name, s_cfg in sessions_raw.items():
            if not isinstance(s_name, str) or not s_name:
                raise _err(
                    path, "sessions", f"session name must be a non-empty string (got {s_name!r})"
                )
            if not isinstance(s_cfg, dict):
                raise _err(path, f"sessions.{s_name}", "session config must be a mapping")
        sessions = dict(sessions_raw)

    # --- steps: list[Step] ---
    steps_raw = data["steps"]
    if not isinstance(steps_raw, list) or not steps_raw:
        raise _err(path, "steps", "steps must be a non-empty list")

    steps: list[Step] = []
    for idx, step_raw in enumerate(steps_raw):
        where = f"steps[{idx}]"
        if not isinstance(step_raw, dict):
            raise _err(path, where, "step must be a mapping")

        # --- id: accept "id" or "name" alias; auto-generate if both absent ---
        s_id = step_raw.get("id") or step_raw.get("name") or f"step-{idx}"
        if not isinstance(s_id, str) or not s_id:
            s_id = f"step-{idx}"

        # --- driver: accept "driver" or "kind" alias ---
        s_driver_raw = step_raw.get("driver") or step_raw.get("kind")
        if not s_driver_raw:
            raise _err(path, f"{where}.driver", "step missing required field 'driver' or 'kind'")
        if not isinstance(s_driver_raw, str):
            raise _err(
                path,
                f"{where}.driver",
                "step field 'driver'/'kind' must be a non-empty string",
            )
        s_driver = s_driver_raw

        if s_driver not in _VALID_DRIVERS:
            raise _err(
                path,
                f"{where}.driver",
                f"driver '{s_driver}' must be one of {sorted(_VALID_DRIVERS)}",
            )

        # --- on: default to "default" when absent ---
        s_on = step_raw.get("on", "default")
        if not isinstance(s_on, str) or not s_on:
            s_on = "default"

        # Validate s_on against sessions only when sessions was explicitly
        # declared (not auto-derived). When auto-derived, "default" is always
        # valid and any explicit "on" value is accepted (runner resolves it).
        if not sessions_derived and s_on not in sessions:
            raise _err(
                path,
                f"{where}.on",
                f"on '{s_on}' not declared in case sessions {sorted(sessions)}",
            )

        # --- run: accept "run", "sql", "cmd", or "pattern" aliases ---
        s_run_raw = (
            step_raw.get("run")
            or step_raw.get("sql")
            or step_raw.get("cmd")
            or step_raw.get("pattern")
            or ""
        )
        if not isinstance(s_run_raw, str):
            s_run_raw = str(s_run_raw)
        s_run = s_run_raw

        # For non-log_grep drivers, run must be non-empty
        if s_driver != "log_grep" and not s_run:
            raise _err(
                path,
                f"{where}.run",
                "step missing required field 'run' / 'sql' / 'cmd'",
            )

        timeout_ms = step_raw.get("timeout_ms")
        if timeout_ms is not None and not isinstance(timeout_ms, int):
            raise _err(path, f"{where}.timeout_ms", "timeout_ms must be an int (milliseconds)")

        continue_on_fail = step_raw.get("continue_on_fail", False)
        if not isinstance(continue_on_fail, bool):
            raise _err(path, f"{where}.continue_on_fail", "continue_on_fail must be a bool")

        # expect: list of single-key mappings OR dict -> list[ExpectClause]
        expect_raw = step_raw.get("expect", [])
        if isinstance(expect_raw, dict):
            expect_clauses = [ExpectClause(key=k, value=v) for k, v in expect_raw.items()]
        elif isinstance(expect_raw, list):
            if not isinstance(expect_raw, list):
                raise _err(path, f"{where}.expect", "expect must be a list of single-key mappings")
            expect_clauses: list[ExpectClause] = []
            for e_idx, entry in enumerate(expect_raw):
                if not isinstance(entry, dict) or len(entry) != 1:
                    raise _err(
                        path,
                        f"{where}.expect[{e_idx}]",
                        "expect entry must be a single-key mapping (e.g. '- exit_code: 0')",
                    )
                ((e_key, e_val),) = entry.items()
                expect_clauses.append(ExpectClause(key=e_key, value=e_val))
        else:
            raise _err(path, f"{where}.expect", "expect must be a list or mapping")

        steps.append(
            Step(
                id=s_id,
                on=s_on,
                driver=s_driver,  # type: ignore[arg-type]
                run=s_run,
                timeout_ms=timeout_ms,
                expect=expect_clauses,
                continue_on_fail=continue_on_fail,
            )
        )

    # --- optional top-level fields ---
    external_deps_raw = data.get("external_deps", [])
    if not isinstance(external_deps_raw, list) or not all(
        isinstance(x, str) for x in external_deps_raw
    ):
        raise _err(path, "external_deps", "external_deps must be a list of strings")
    external_deps: list[str] = list(external_deps_raw)

    destructive_raw = data.get("destructive", False)
    if not isinstance(destructive_raw, bool):
        raise _err(path, "destructive", "destructive must be a bool")

    status_raw = data.get("status", "open")
    if status_raw not in _VALID_STATUSES:
        raise _err(
            path,
            "status",
            f"status '{status_raw}' must be one of {sorted(_VALID_STATUSES)}",
        )

    setup = _parse_setup_teardown(data.get("setup"))
    teardown = _parse_setup_teardown(data.get("teardown"))

    return Case(
        id=case_id,
        category=category,
        title=data["title"],
        description=data["description"],
        procedure=data["procedure"],
        expected=data["expected"],
        sessions=sessions,
        steps=steps,
        external_deps=external_deps,
        destructive=destructive_raw,
        status=status_raw,  # type: ignore[arg-type]
        setup=setup,
        teardown=teardown,
    )
