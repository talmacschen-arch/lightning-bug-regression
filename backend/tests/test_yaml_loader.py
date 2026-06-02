"""Table-driven tests for ``app.storage.yaml_loader``.

Each test writes a case YAML into ``tmp_path`` and exercises one §4.1
schema rule. ``categories`` is built from ``_default_categories()``,
which mirrors the §4.5 seed (``bug_regression`` + ``extension``) plus
the legacy dash form ``bug-regression`` used by these test fixtures —
kept narrow so we can also verify the "category not in whitelist" path
without false negatives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.yaml_loader import (
    Case,
    CaseValidationError,
    CategoryMeta,
    ExpectClause,
    Step,
    load_case,
)


def _default_categories() -> dict[str, CategoryMeta]:
    """The §4.5-seed CategoryMeta dict + the dash-form alias the test
    fixtures below historically use.

    Real production cases use ``bug_regression`` (underscore); the
    dash-form key is here purely so the test-only ``_minimal_yaml()``
    helper keeps working without rewriting every fixture.
    """
    bug_statuses = frozenset({"open", "fixed", "wontfix", "stub"})
    ext_statuses = frozenset({"stable", "experimental", "deprecated", "stub"})
    return {
        "bug_regression": CategoryMeta(
            name="bug_regression",
            id_prefix="bug-",
            status_whitelist=bug_statuses,
        ),
        "bug-regression": CategoryMeta(
            name="bug-regression",
            id_prefix="bug-",
            status_whitelist=bug_statuses,
        ),
        "extension": CategoryMeta(
            name="extension",
            id_prefix="ext-",
            status_whitelist=ext_statuses,
        ),
    }


DEFAULT_WHITELIST = _default_categories()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _minimal_yaml(case_id: str = "bug-0001-demo") -> str:
    """Return a minimal valid case YAML matching §4.1 (M1 slice)."""
    return f"""\
id: {case_id}
category: bug-regression
title: demo case
description: |
  verify the demo bug is fixed.
procedure: |
  1. run select.
  2. observe result.
expected: |
  exit_code 0.
sessions:
  s1:
    driver: sql
steps:
  - id: q1
    on: s1
    driver: sql
    run: SELECT 1
    expect:
      - scalar_eq: 1
"""


def _write(tmp_path: Path, content: str, stem: str = "bug-0001-demo") -> Path:
    p = tmp_path / f"{stem}.yaml"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_happy_path_minimal(tmp_path: Path) -> None:
    path = _write(tmp_path, _minimal_yaml())
    case = load_case(path, DEFAULT_WHITELIST)
    assert isinstance(case, Case)
    assert case.id == "bug-0001-demo"
    assert case.category == "bug-regression"
    assert case.title == "demo case"
    assert case.status == "open"  # default
    assert case.destructive is False  # default
    assert case.external_deps == []  # default
    assert case.sessions == {"s1": {"driver": "sql"}}
    assert len(case.steps) == 1
    step = case.steps[0]
    assert isinstance(step, Step)
    assert step.id == "q1"
    assert step.on == "s1"
    assert step.driver == "sql"
    assert step.run == "SELECT 1"
    assert step.timeout_ms is None
    assert step.continue_on_fail is False
    assert len(step.expect) == 1
    assert isinstance(step.expect[0], ExpectClause)
    assert step.expect[0].key == "scalar_eq"
    assert step.expect[0].value == 1


# ---------------------------------------------------------------------------
# missing required top-level fields (one parametrized case per field)
# "sessions" is now optional (auto-derived), so it is excluded from this list.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_to_drop",
    [
        "id",
        "category",
        "title",
        "description",
        "procedure",
        "expected",
        "steps",
    ],
)
def test_missing_required_top_level_field(tmp_path: Path, field_to_drop: str) -> None:
    """Drop one required field at a time and assert the error mentions it."""
    src = _minimal_yaml()
    # Remove only the YAML line(s) that start the given key. For block scalars
    # (description / procedure / expected) we also drop the following indented
    # body lines so the YAML stays well-formed.
    lines = src.splitlines(keepends=True)
    out: list[str] = []
    skip_block = False
    for ln in lines:
        if skip_block:
            if ln.startswith(" ") or ln.startswith("\t"):
                # still inside the block-scalar body — skip
                continue
            skip_block = False
        if ln.startswith(f"{field_to_drop}:"):
            # If the value starts a block scalar ('|'), also skip its body.
            if ln.rstrip().endswith("|"):
                skip_block = True
            continue
        # Drop nested-list/mapping body of sessions / steps too.
        out.append(ln)

    # For nested mapping/list fields (sessions, steps) we also need to drop
    # the children — the simplest reliable approach is to drop until the next
    # top-level key.
    if field_to_drop in ("sessions", "steps"):
        cleaned: list[str] = []
        dropping = False
        for ln in src.splitlines(keepends=True):
            if ln.startswith(f"{field_to_drop}:"):
                dropping = True
                continue
            if dropping:
                # next top-level key (no leading space, contains ':')
                if ln and not ln.startswith((" ", "\t")) and ":" in ln:
                    dropping = False
                    cleaned.append(ln)
                # else: still inside the children — skip
                continue
            cleaned.append(ln)
        out = cleaned

    path = _write(tmp_path, "".join(out))
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    assert field_to_drop in str(exc_info.value)
    assert str(path) in str(exc_info.value)


def test_missing_sessions_is_valid(tmp_path: Path) -> None:
    """sessions is optional; when absent a default session is auto-derived."""
    # Build a minimal YAML without any sessions block and without "on:".
    # The step uses the auto-derived "default" session.
    yaml_src = (
        "id: bug-0001-demo\n"
        "category: bug-regression\n"
        "title: demo case\n"
        "description: |\n  verify the demo bug is fixed.\n"
        "procedure: |\n  1. run select.\n"
        "expected: |\n  exit_code 0.\n"
        "steps:\n"
        "  - id: q1\n"
        "    driver: sql\n"
        "    run: SELECT 1\n"
    )
    path = _write(tmp_path, yaml_src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.sessions == {"default": {"driver": "sql"}}


def test_empty_list_sessions_is_valid(tmp_path: Path) -> None:
    """Per §5.5.6 canonical default shape `sessions: []`, an empty list is
    equivalent to omitting the field (auto-derive default). M3a-10 dogfood
    spec gap fix — previously this raised 'sessions must be a non-empty mapping'."""
    yaml_src = (
        "id: bug-0001-demo\n"
        "category: bug-regression\n"
        "title: demo case\n"
        "description: |\n  verify.\n"
        "procedure: |\n  1.\n"
        "expected: |\n  ok.\n"
        "sessions: []\n"
        "steps:\n"
        "  - id: q1\n"
        "    driver: sql\n"
        "    run: SELECT 1\n"
    )
    path = _write(tmp_path, yaml_src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.sessions == {"default": {"driver": "sql"}}


def test_empty_mapping_sessions_is_valid(tmp_path: Path) -> None:
    """Symmetric with empty list: empty mapping `sessions: {}` also derives default."""
    yaml_src = (
        "id: bug-0001-demo\n"
        "category: bug-regression\n"
        "title: demo case\n"
        "description: |\n  verify.\n"
        "procedure: |\n  1.\n"
        "expected: |\n  ok.\n"
        "sessions: {}\n"
        "steps:\n"
        "  - id: q1\n"
        "    driver: sql\n"
        "    run: SELECT 1\n"
    )
    path = _write(tmp_path, yaml_src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.sessions == {"default": {"driver": "sql"}}


# ---------------------------------------------------------------------------
# category whitelist
# ---------------------------------------------------------------------------


def test_category_not_in_whitelist(tmp_path: Path) -> None:
    src = _minimal_yaml().replace("category: bug-regression", "category: unknown-cat")
    path = _write(tmp_path, src)
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    msg = str(exc_info.value)
    assert "whitelist" in msg
    assert "unknown-cat" in msg


def test_category_prefix_is_data_driven(tmp_path: Path) -> None:
    """The id_prefix enforced for a category is whatever the caller's
    CategoryMeta says — not a hardcoded module-level table. Register a
    hypothetical ``future-cat`` with prefix ``fc-`` and verify both the
    accept path (id starts with ``fc-``) and the reject path."""
    extra = dict(DEFAULT_WHITELIST)
    extra["future-cat"] = CategoryMeta(
        name="future-cat",
        id_prefix="fc-",
        status_whitelist=frozenset({"open"}),
    )

    # accept: id starts with the registered prefix
    src = _minimal_yaml(case_id="fc-0001-xyz")
    src = src.replace("category: bug-regression", "category: future-cat")
    path = _write(tmp_path, src, stem="fc-0001-xyz")
    case = load_case(path, extra)
    assert case.category == "future-cat"
    assert case.id == "fc-0001-xyz"


def test_category_underscore_form_accepted(tmp_path: Path) -> None:
    """The canonical §4.5 key is ``bug_regression`` (underscore). When
    only the underscore form is registered, a YAML using the underscore
    form loads cleanly."""
    src = _minimal_yaml().replace("category: bug-regression", "category: bug_regression")
    path = _write(tmp_path, src)
    case = load_case(
        path,
        {
            "bug_regression": CategoryMeta(
                name="bug_regression",
                id_prefix="bug-",
                status_whitelist=frozenset({"open", "fixed", "wontfix", "stub"}),
            )
        },
    )
    assert case.category == "bug_regression"


# ---------------------------------------------------------------------------
# id-prefix / filename-stem
# ---------------------------------------------------------------------------


def test_id_prefix_mismatch(tmp_path: Path) -> None:
    # category=bug-regression but id starts with 'lg-feat-' → mismatch
    src = _minimal_yaml(case_id="lg-feat-0001-demo")
    path = _write(tmp_path, src, stem="lg-feat-0001-demo")
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    assert "bug-" in str(exc_info.value)
    assert "id" in str(exc_info.value)


def test_id_not_equal_filename_stem(tmp_path: Path) -> None:
    src = _minimal_yaml(case_id="bug-0001-demo")
    # Write to a different filename stem on disk.
    path = _write(tmp_path, src, stem="bug-0001-other")
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    msg = str(exc_info.value)
    assert "filename stem" in msg
    assert "bug-0001-other" in msg


# ---------------------------------------------------------------------------
# step-level validation
# ---------------------------------------------------------------------------


def test_step_driver_invalid(tmp_path: Path) -> None:
    src = _minimal_yaml().replace(
        "driver: sql\n    run: SELECT 1", "driver: bogus\n    run: SELECT 1"
    )
    path = _write(tmp_path, src)
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    assert "bogus" in str(exc_info.value)
    assert "driver" in str(exc_info.value)


def test_step_on_not_in_sessions(tmp_path: Path) -> None:
    src = _minimal_yaml().replace("on: s1", "on: ghost_session")
    path = _write(tmp_path, src)
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    msg = str(exc_info.value)
    assert "ghost_session" in msg
    assert "on" in msg


@pytest.mark.parametrize("missing_field", ["driver", "run"])
def test_step_missing_required_field(tmp_path: Path, missing_field: str) -> None:
    """Drop one required field inside the step list element (under ``steps:``).

    Build the step block by hand so we strip *only* the step-level field —
    not the top-level ``id:`` nor the session's ``driver:`` config.

    Note: "id" is now auto-generated (step-NN) when absent, so it is no
    longer a required step field; "on" defaults to "default".  Only
    "driver"/"kind" and "run"/"sql"/"cmd" (for non-log_grep) are required.
    """
    step_fields = {
        "id": "id: q1",
        "on": "on: s1",
        "driver": "driver: sql",
        "run": "run: SELECT 1",
    }
    # First field in the list element needs the leading "- "; the rest are
    # indented 4 spaces.
    ordered = ["id", "on", "driver", "run"]
    kept_fields = [f for f in ordered if f != missing_field]
    step_lines: list[str] = []
    for i, f in enumerate(kept_fields):
        prefix = "  - " if i == 0 else "    "
        step_lines.append(f"{prefix}{step_fields[f]}")
    # Always keep an expect block so the rest of the schema parses.
    step_lines.append("    expect:")
    step_lines.append("      - exit_code: 0")
    step_block = "\n".join(step_lines) + "\n"

    yaml_src = (
        "id: bug-0001-demo\n"
        "category: bug-regression\n"
        "title: demo case\n"
        "description: |\n  desc\n"
        "procedure: |\n  proc\n"
        "expected: |\n  exp\n"
        "sessions:\n  s1:\n    driver: sql\n"
        "steps:\n" + step_block
    )

    path = _write(tmp_path, yaml_src)
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    assert missing_field in str(exc_info.value)
    assert "steps[0]" in str(exc_info.value)


def test_step_name_alias_accepted(tmp_path: Path) -> None:
    """Steps using 'name:' instead of 'id:' must load without error."""
    src = _minimal_yaml().replace("  - id: q1", "  - name: q1")
    path = _write(tmp_path, src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.steps[0].id == "q1"


def test_step_kind_alias_accepted(tmp_path: Path) -> None:
    """Steps using 'kind:' instead of 'driver:' must load without error."""
    src = _minimal_yaml().replace("    driver: sql", "    kind: sql")
    path = _write(tmp_path, src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.steps[0].driver == "sql"


def test_step_driver_restart_db_accepted(tmp_path: Path) -> None:
    """Schema accepts ``kind: restart_db`` (driver runner is deferred to M2;
    design.md §4.1 / §13.2 require the schema to whitelist the kind name
    so M3a record-entry skills can file the first restart_db case before
    the runner exists)."""
    src = _minimal_yaml().replace(
        "    driver: sql\n    run: SELECT 1",
        "    kind: restart_db\n    run: gpstop -ar",
    )
    path = _write(tmp_path, src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.steps[0].driver == "restart_db"


def test_step_sql_alias_accepted(tmp_path: Path) -> None:
    """Steps using 'sql:' instead of 'run:' must load without error."""
    src = _minimal_yaml().replace("    run: SELECT 1", "    sql: SELECT 1")
    path = _write(tmp_path, src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.steps[0].run == "SELECT 1"


def test_step_expect_dict_format(tmp_path: Path) -> None:
    """expect as a plain dict (real case format) is accepted."""
    src = _minimal_yaml().replace(
        "    expect:\n      - scalar_eq: 1\n",
        "    expect:\n      scalar_eq: 1\n      not_contains: ERROR\n",
    )
    path = _write(tmp_path, src)
    case = load_case(path, DEFAULT_WHITELIST)
    expect_keys = {c.key for c in case.steps[0].expect}
    assert "scalar_eq" in expect_keys
    assert "not_contains" in expect_keys


# ---------------------------------------------------------------------------
# destructive / status
# ---------------------------------------------------------------------------


def test_destructive_true_loads(tmp_path: Path) -> None:
    src = _minimal_yaml() + "destructive: true\n"
    path = _write(tmp_path, src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.destructive is True


def test_destructive_not_bool(tmp_path: Path) -> None:
    src = _minimal_yaml() + "destructive: yes-please\n"
    path = _write(tmp_path, src)
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    assert "destructive" in str(exc_info.value)


def test_status_invalid(tmp_path: Path) -> None:
    src = _minimal_yaml() + "status: bogus-status\n"
    path = _write(tmp_path, src)
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    assert "status" in str(exc_info.value)
    assert "bogus-status" in str(exc_info.value)


def test_status_stub_loads(tmp_path: Path) -> None:
    src = _minimal_yaml() + "status: stub\n"
    path = _write(tmp_path, src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.status == "stub"


# ---------------------------------------------------------------------------
# expect clauses
# ---------------------------------------------------------------------------


def test_expect_multiple_single_key_clauses(tmp_path: Path) -> None:
    """``- exit_code: 0`` / ``- scalar_eq: 5`` — each becomes one ExpectClause."""
    src = _minimal_yaml().replace(
        "    expect:\n      - scalar_eq: 1\n",
        "    expect:\n      - exit_code: 0\n      - scalar_eq: 5\n      - stdout_contains: hello\n",
    )
    path = _write(tmp_path, src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert [(c.key, c.value) for c in case.steps[0].expect] == [
        ("exit_code", 0),
        ("scalar_eq", 5),
        ("stdout_contains", "hello"),
    ]


def test_expect_entry_not_single_key_mapping(tmp_path: Path) -> None:
    src = _minimal_yaml().replace(
        "    expect:\n      - scalar_eq: 1\n",
        "    expect:\n      - exit_code: 0\n        scalar_eq: 5\n",
    )
    path = _write(tmp_path, src)
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    assert "expect" in str(exc_info.value)


# ---------------------------------------------------------------------------
# setup / teardown
# ---------------------------------------------------------------------------


def test_setup_teardown_list_of_strings(tmp_path: Path) -> None:
    """setup and teardown as list[str] are stored on the Case."""
    src = (
        _minimal_yaml()
        + "setup:\n  - DROP TABLE IF EXISTS t\n  - CREATE TABLE t (id int)\n"
        + "teardown:\n  - DROP TABLE IF EXISTS t\n"
    )
    path = _write(tmp_path, src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.setup == ["DROP TABLE IF EXISTS t", "CREATE TABLE t (id int)"]
    assert case.teardown == ["DROP TABLE IF EXISTS t"]


def test_setup_teardown_absent_defaults_to_empty(tmp_path: Path) -> None:
    path = _write(tmp_path, _minimal_yaml())
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.setup == []
    assert case.teardown == []


def test_setup_dict_entry_rejected(tmp_path: Path) -> None:
    """setup containing a dict is rejected per §4.1 (list[str] only).

    Pre-M1-cleanup-p1 the loader had a "forward compat" branch that
    silently extracted the first string value from a dict entry —
    contradicting §4.1 which mandates list[str].  Now it raises.
    """
    src = _minimal_yaml() + "setup:\n  - sql: DROP TABLE t\n"
    path = _write(tmp_path, src)
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    msg = str(exc_info.value)
    assert "must be a string" in msg


def test_step_name_field_takes_priority_over_id(tmp_path: Path) -> None:
    """When a step has BOTH ``name:`` and ``id:``, ``name:`` wins.

    ``name`` is the §4.1 canonical field; ``id`` is a back-compat alias.
    Real cases use ``name:``; the loader must surface that as ``step.id``
    even if a stray ``id:`` is also present.
    """
    src = _minimal_yaml().replace(
        "  - id: q1\n    on: s1\n    driver: sql",
        "  - name: canonical-name\n    id: legacy-id\n    on: s1\n    driver: sql",
    )
    path = _write(tmp_path, src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.steps[0].id == "canonical-name"


def test_step_kind_field_takes_priority_over_driver(tmp_path: Path) -> None:
    """When a step has BOTH ``kind:`` and ``driver:``, ``kind:`` wins.

    ``kind`` is the §4.1 canonical field; ``driver`` is a back-compat
    alias.  Real cases use ``kind:`` — the loader must route on it.
    """
    src = _minimal_yaml().replace(
        "    driver: sql\n    run: SELECT 1",
        "    kind: shell\n    driver: sql\n    run: echo hi",
    )
    path = _write(tmp_path, src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.steps[0].driver == "shell"


# ---------------------------------------------------------------------------
# YAML syntax error
# ---------------------------------------------------------------------------


def test_malformed_yaml(tmp_path: Path) -> None:
    # Unbalanced brackets / bad indent triggers yaml.YAMLError.
    src = "id: bug-0001-demo\ncategory: bug-regression\nsessions: [s1\n"
    path = _write(tmp_path, src)
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    msg = str(exc_info.value)
    assert "YAML syntax error" in msg
    assert str(path) in msg


# ---------------------------------------------------------------------------
# Data-driven status + id_prefix (post-M1-cleanup P0-A; §4.5 CategoryMeta)
# ---------------------------------------------------------------------------


def test_load_case_accepts_status_fixed_for_bug_regression(tmp_path: Path) -> None:
    """``status: fixed`` is legal for bug_regression per §4.5 seed —
    previously rejected because the loader's hardcoded _VALID_STATUSES
    only knew ``{open, closed, stub}``."""
    src = (
        _minimal_yaml().replace("category: bug-regression", "category: bug_regression")
        + "status: fixed\n"
    )
    path = _write(tmp_path, src)
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.status == "fixed"


def test_load_case_accepts_status_stable_for_extension(tmp_path: Path) -> None:
    """``category: extension`` + ``status: stable`` is legal per §4.5 —
    previously rejected because the loader had no ``extension`` entry in
    its hardcoded prefix map and ``stable`` was not in _VALID_STATUSES."""
    src = (
        _minimal_yaml(case_id="ext-pgvector-install").replace(
            "category: bug-regression", "category: extension"
        )
        + "status: stable\n"
    )
    path = _write(tmp_path, src, stem="ext-pgvector-install")
    case = load_case(path, DEFAULT_WHITELIST)
    assert case.category == "extension"
    assert case.id == "ext-pgvector-install"
    assert case.status == "stable"


def test_load_case_rejects_status_closed(tmp_path: Path) -> None:
    """``status: closed`` is REJECTED — it was a fabrication of the old
    hardcoded _VALID_STATUSES and is not present in either §4.5 seed."""
    # bug_regression rejects "closed"
    src_bug = (
        _minimal_yaml().replace("category: bug-regression", "category: bug_regression")
        + "status: closed\n"
    )
    path_bug = _write(tmp_path, src_bug)
    with pytest.raises(CaseValidationError, match=r"status 'closed' .* whitelist"):
        load_case(path_bug, DEFAULT_WHITELIST)

    # extension rejects "closed" too
    src_ext = (
        _minimal_yaml(case_id="ext-pgvector-install").replace(
            "category: bug-regression", "category: extension"
        )
        + "status: closed\n"
    )
    path_ext = _write(tmp_path, src_ext, stem="ext-pgvector-install")
    with pytest.raises(CaseValidationError, match=r"status 'closed' .* whitelist"):
        load_case(path_ext, DEFAULT_WHITELIST)


def test_load_case_enforces_lg_ext_prefix(tmp_path: Path) -> None:
    """``category: extension`` with an ``id: bug-...`` is REJECTED.
    Before the refactor the loader had no ``extension`` entry in its
    hardcoded prefix map and silently accepted any id stem."""
    src = _minimal_yaml(case_id="bug-1234-mislabeled").replace(
        "category: bug-regression", "category: extension"
    )
    path = _write(tmp_path, src, stem="bug-1234-mislabeled")
    with pytest.raises(CaseValidationError) as exc_info:
        load_case(path, DEFAULT_WHITELIST)
    msg = str(exc_info.value)
    assert "ext-" in msg
    assert "extension" in msg


# ---------------------------------------------------------------------------
# Real case round-trip tests (§4.1 dogfood — cases/bug-regression/*.yaml)
# ---------------------------------------------------------------------------

_CASES_DIR = Path(__file__).parent.parent.parent / "cases" / "bug-regression"
_REAL_CASE_FILES = sorted(_CASES_DIR.glob("*.yaml"))
_BUG_REGRESSION_CATEGORIES = {
    "bug_regression": CategoryMeta(
        name="bug_regression",
        id_prefix="bug-",
        status_whitelist=frozenset({"open", "fixed", "wontfix", "stub"}),
    )
}


@pytest.mark.parametrize(
    "case_path",
    _REAL_CASE_FILES,
    ids=[p.stem for p in _REAL_CASE_FILES],
)
def test_real_case_round_trip(case_path: Path) -> None:
    """All real case files in cases/bug-regression/ must load without raising."""
    case = load_case(case_path, _BUG_REGRESSION_CATEGORIES)
    assert isinstance(case, Case)
    assert case.id, "case.id must be a non-empty string"
    assert case.category == "bug_regression"
    assert len(case.steps) > 0, "case must have at least one step"
    # setup/teardown may be empty (some cases have none) — just assert it's a list
    assert isinstance(case.setup, list)
    assert isinstance(case.teardown, list)
