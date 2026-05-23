"""Tests for POST /cases/try (design.md §13.7 M3a-2 / §14 R26).

The endpoint MUST visibly delegate to four backend modules so we don't
get a dual-code-path divergence from POST /runs (§14 R26):

  * ``app.runner.case_normalizer.normalize_case`` — same transform runs.py
    applies before invoking orchestrator
  * ``app.runner.dsn_builder.dsn_map_from_env`` — same DSN builder runs.py
    uses to construct ``SqlSessionPool``
  * ``app.runner.sql_driver.SqlSessionPool`` — same pool class
  * ``app.runner.orchestrator.run_case`` — same per-case orchestrator
    entry point ``run_suite`` calls (Try just skips the DB write)

These tests mock ``run_case`` (and ``SqlSessionPool``) at module level so
the test doesn't need a live Postgres — what we're proving is that the
endpoint *wires* to the real modules, not that psycopg works.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import cases as cases_api
from app.main import app
from app.runner import orchestrator
from app.runner.types import StepResult, StepStatus
from app.storage import sqlite_store
from app.storage.models import Base, CaseCategory

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """In-memory DB seeded with the §4.5 ``bug_regression`` category so
    ``_validate_yaml_text`` (which reuses GET-path category metadata) has
    a whitelist to validate against."""
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, class_=Session
    )
    monkeypatch.setattr(sqlite_store, "_engine", engine, raising=False)
    monkeypatch.setattr(sqlite_store, "_SessionLocal", SessionLocal, raising=False)
    monkeypatch.setattr(sqlite_store, "init_engine", lambda url: None)

    with SessionLocal() as sess:
        sess.add(
            CaseCategory(
                name="bug_regression",
                display_name="BUG 回归",
                description=None,
                id_prefix="lg-bug-",
                dir_path="bug-regression",
                status_whitelist=json.dumps(["open", "fixed", "wontfix", "stub"]),
                default_status="open",
                display_order=10,
                is_active=True,
            )
        )
        sess.commit()

    # Reset the Try-pass cache between tests — app.state persists across
    # TestClient invocations within a session, and other test modules
    # (e.g. test_api_submit) may have left entries.
    app.state.try_pass_cache.clear()

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# helpers — fake SqlSessionPool + stubbed run_case
# ---------------------------------------------------------------------------


class _FakePool:
    """Stand-in for SqlSessionPool: records construction args + has a
    no-op async close_all so the endpoint's finally-block teardown works.

    We don't subclass SqlSessionPool because we want to assert the pool was
    *constructed* with the dsn_map we expect (R26: dsn_builder must be
    visibly called). The endpoint imports SqlSessionPool by name then
    instantiates it — monkeypatching the symbol on the cases module
    intercepts construction.
    """

    instances: list[_FakePool] = []

    def __init__(self, dsn_per_session: dict[str, str]):
        self.dsn_per_session = dict(dsn_per_session)
        self.closed = False
        _FakePool.instances.append(self)

    async def close_all(self) -> None:
        self.closed = True


@dataclass
class _StubInvocation:
    """Records the args run_case was called with so tests can assert
    R26 wiring (e.g. that the case dict was normalized, that sql_pool
    was passed through)."""

    case: dict[str, Any] = field(default_factory=dict)
    kwargs: dict[str, Any] = field(default_factory=dict)


def _install_run_case_stub(
    monkeypatch: pytest.MonkeyPatch,
    result: orchestrator.CaseExecutionResult,
) -> _StubInvocation:
    """Monkeypatch ``orchestrator.run_case`` to return ``result``; also
    expose the actually-received arguments to the test.

    Patches both the orchestrator module's symbol AND
    ``cases_api.orchestrator.run_case`` so it doesn't matter which
    binding the endpoint resolves through.
    """
    invocation = _StubInvocation()

    async def fake_run_case(case: dict[str, Any], run_id: int, **kwargs: Any):
        invocation.case = case
        invocation.kwargs = dict(kwargs)
        invocation.kwargs["run_id"] = run_id
        return result

    monkeypatch.setattr(orchestrator, "run_case", fake_run_case)
    return invocation


def _passing_step(step_id: str = "step-00", driver: str = "sql") -> StepResult:
    return StepResult(
        status=StepStatus.PASS,
        step_id=step_id,
        driver=driver,
        started_at="2026-05-24T00:00:00",
        ended_at="2026-05-24T00:00:01",
        duration_ms=12,
        stdout="1",
        stderr="",
        scalar=1,
        row_count=1,
    )


def _failing_step(step_id: str = "step-00", driver: str = "sql") -> StepResult:
    sr = StepResult(
        status=StepStatus.FAIL,
        step_id=step_id,
        driver=driver,
        started_at="2026-05-24T00:00:00",
        ended_at="2026-05-24T00:00:01",
        duration_ms=15,
        stdout="",
        stderr="NOTICE:  something went sideways\n",
        scalar=0,
        row_count=1,
    )
    sr.assertions.append(("scalar", False, "expected 1 got 0"))
    return sr


def _case_result(
    case_id: str,
    status: StepStatus,
    steps: list[StepResult],
) -> orchestrator.CaseExecutionResult:
    return orchestrator.CaseExecutionResult(
        case_id=case_id,
        status=status,
        duration_ms=sum(s.duration_ms for s in steps) or 1,
        step_results=steps,
    )


def _minimal_valid_yaml() -> str:
    """A case that passes both schema (yaml_loader) and normalizer."""
    return textwrap.dedent(
        """\
        id: lg-bug-9999-test-try
        category: bug_regression
        title: try endpoint smoke
        description: minimal valid case for /cases/try test
        procedure: run one trivial sql
        expected: returns 1
        status: open
        steps:
          - name: trivial
            kind: sql
            sql: SELECT 1
            expect:
              - scalar: 1
        """
    )


@pytest.fixture(autouse=True)
def _reset_fake_pool_instances() -> None:
    _FakePool.instances.clear()


@pytest.fixture
def patch_pool(monkeypatch: pytest.MonkeyPatch) -> type[_FakePool]:
    """Intercept SqlSessionPool construction inside the cases module so
    the endpoint runs without hitting psycopg."""
    monkeypatch.setattr(cases_api, "SqlSessionPool", _FakePool)
    return _FakePool


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_try_happy_path_one_passing_sql_step(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    patch_pool: type[_FakePool],
) -> None:
    """Valid YAML + run_case returns one passing step → ok=true,
    step_results has one pass, yaml_sha256 matches sha256 of payload."""
    raw = _minimal_valid_yaml()
    cer = _case_result("lg-bug-9999-test-try", StepStatus.PASS, [_passing_step()])
    inv = _install_run_case_stub(monkeypatch, cer)

    resp = client.post("/cases/try", json={"yaml": raw})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["validation_errors"] == []
    assert body["yaml_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert len(body["step_results"]) == 1
    only = body["step_results"][0]
    assert only["status"] == "pass"
    assert only["kind"] == "sql"
    assert only["duration_ms"] == 12
    assert only["error"] is None

    # §14 R26 wiring proof: normalize_case must have been applied
    # (raw `steps[0].name` becomes `id` in normalized output).
    assert inv.case.get("id") == "lg-bug-9999-test-try"
    normalized_step = inv.case["steps"][0]
    assert normalized_step["kind"] == "sql"
    assert normalized_step["id"] == "trivial"  # was YAML `name:`

    # SqlSessionPool was constructed (R26: dsn_builder + pool both wired)
    # and torn down via close_all.
    assert len(_FakePool.instances) == 1
    pool = _FakePool.instances[0]
    assert pool.closed is True
    # dsn_map_from_env returns at least the `default` + `default:<db>`
    # entries even for a case that didn't set per-step `database:`.
    assert "default" in pool.dsn_per_session


# ---------------------------------------------------------------------------
# validate stage failure paths
# ---------------------------------------------------------------------------


def test_try_yaml_syntax_error_short_circuits(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    patch_pool: type[_FakePool],
) -> None:
    """Malformed YAML must fail validate stage before run_case is even
    constructed; step_results=[] + validation_errors populated."""
    # Sentinel: run_case must NOT be called.
    called = {"n": 0}

    async def must_not_call(*args: Any, **kwargs: Any) -> Any:
        called["n"] += 1
        raise AssertionError("run_case should not be invoked when validate fails")

    monkeypatch.setattr(orchestrator, "run_case", must_not_call)

    bad = "foo: : :"
    resp = client.post("/cases/try", json={"yaml": bad})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["step_results"] == []
    assert body["yaml_sha256"] == hashlib.sha256(bad.encode("utf-8")).hexdigest()
    assert len(body["validation_errors"]) >= 1
    assert body["validation_errors"][0]["where"] == "yaml_syntax"
    assert called["n"] == 0
    # No pool should have been constructed either.
    assert _FakePool.instances == []


def test_try_top_level_not_mapping_short_circuits(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    patch_pool: type[_FakePool],
) -> None:
    """YAML list at top level → ok=false, where='top-level'."""

    async def must_not_call(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("run_case should not be invoked")

    monkeypatch.setattr(orchestrator, "run_case", must_not_call)

    resp = client.post("/cases/try", json={"yaml": "- a\n- b\n"})
    body = resp.json()
    assert resp.status_code == 200
    assert body["ok"] is False
    assert body["step_results"] == []
    assert body["validation_errors"][0]["where"] == "top-level"


# ---------------------------------------------------------------------------
# step-failure path
# ---------------------------------------------------------------------------


def test_try_step_failure_yields_ok_false(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    patch_pool: type[_FakePool],
) -> None:
    """A passing validate stage + a failing step → ok=false; stderr
    preview is populated and truncated to 500 chars."""
    long_stderr = "x" * 1500
    failing = _failing_step()
    failing.stderr = long_stderr
    cer = _case_result("lg-bug-9999-test-try", StepStatus.FAIL, [failing])
    _install_run_case_stub(monkeypatch, cer)

    resp = client.post("/cases/try", json={"yaml": _minimal_valid_yaml()})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["validation_errors"] == []
    assert len(body["step_results"]) == 1
    sr = body["step_results"][0]
    assert sr["status"] == "fail"
    assert sr["stderr_preview"] is not None
    assert len(sr["stderr_preview"]) == 500  # 500-char preview cap
    assert sr["stderr_preview"] == "x" * 500


def test_try_error_step_carries_error_string(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    patch_pool: type[_FakePool],
) -> None:
    """A step with status=error + a non-empty `error` field surfaces
    that string verbatim in the response."""
    err_step = StepResult(
        status=StepStatus.ERROR,
        step_id="boom",
        driver="sql",
        started_at="2026-05-24T00:00:00",
        ended_at="2026-05-24T00:00:00",
        duration_ms=2,
        error="connection refused",
    )
    cer = _case_result("lg-bug-9999-test-try", StepStatus.ERROR, [err_step])
    _install_run_case_stub(monkeypatch, cer)

    resp = client.post("/cases/try", json={"yaml": _minimal_valid_yaml()})
    body = resp.json()
    assert body["ok"] is False
    only = body["step_results"][0]
    assert only["status"] == "error"
    assert only["error"] == "connection refused"


# ---------------------------------------------------------------------------
# yaml_sha256 stability
# ---------------------------------------------------------------------------


def test_try_yaml_sha256_stable_across_calls(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    patch_pool: type[_FakePool],
) -> None:
    """Same yaml string → same sha256 hash (M3a-3.5 will gate /cases/submit
    on this hash being in the per-app try-pass cache)."""
    cer = _case_result("lg-bug-9999-test-try", StepStatus.PASS, [_passing_step()])
    _install_run_case_stub(monkeypatch, cer)

    raw = _minimal_valid_yaml()
    r1 = client.post("/cases/try", json={"yaml": raw}).json()
    r2 = client.post("/cases/try", json={"yaml": raw}).json()
    assert r1["yaml_sha256"] == r2["yaml_sha256"]
    # And matches the algorithm spelled out in design.md §13.7 M3a-2.
    assert r1["yaml_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_try_yaml_sha256_differs_for_different_payloads(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    patch_pool: type[_FakePool],
) -> None:
    """Different yaml text → different hash. Trivially true given sha256
    but we assert it so a future bug where the endpoint hashes the wrong
    thing (e.g. parsed dict repr) is caught."""
    cer = _case_result("lg-bug-9999-test-try", StepStatus.PASS, [_passing_step()])
    _install_run_case_stub(monkeypatch, cer)

    # First payload validates fine.
    r1 = client.post("/cases/try", json={"yaml": _minimal_valid_yaml()}).json()
    # Second is structurally identical but with extra whitespace — same
    # parsed dict, different raw text → DIFFERENT sha (M3a-3.5 cache key
    # is raw text, not normalized form, so that "fix a typo + re-Try" is
    # always required).
    r2 = client.post("/cases/try", json={"yaml": _minimal_valid_yaml() + "\n# trailing\n"}).json()
    assert r1["yaml_sha256"] != r2["yaml_sha256"]


# ---------------------------------------------------------------------------
# Try-pass cache wiring (§13.7 M3a-3.5)
#
# On overall pass, /cases/try MUST write yaml_sha256 → now(UTC) into
# app.state.try_pass_cache. Without this write the cache stays empty and
# the §6.2 three-gate on /cases/submit rejects every payload — the cache
# is dead infrastructure. The fixed cases.py wires this in stage 4 of
# try_case; these tests pin that wiring.
# ---------------------------------------------------------------------------


def test_try_pass_writes_to_app_state_cache(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    patch_pool: type[_FakePool],
) -> None:
    """A passing /cases/try must populate app.state.try_pass_cache with
    yaml_sha256 → datetime.now(UTC). Submit's three-gate reads from
    exactly this dict, so the wiring closes the loop end-to-end.
    """
    raw = _minimal_valid_yaml()
    cer = _case_result("lg-bug-9999-test-try", StepStatus.PASS, [_passing_step()])
    _install_run_case_stub(monkeypatch, cer)

    # Cache starts empty (fixture clears it).
    assert app.state.try_pass_cache == {}
    before = datetime.now(UTC)
    resp = client.post("/cases/try", json={"yaml": raw})
    after = datetime.now(UTC)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True

    # Cache MUST now contain the YAML's sha256 keyed entry.
    expected_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert expected_hash in app.state.try_pass_cache, (
        "Try-pass cache was not written on pass — submit's three-gate would reject everything"
    )

    # And the timestamp must be a tz-aware datetime within the test window
    # (within the last 5 seconds is the spec — we tighten to "between
    # before and after" so a slow CI doesn't blur the bound).
    ts = app.state.try_pass_cache[expected_hash]
    assert isinstance(ts, datetime)
    assert ts.tzinfo is not None, "cache must store tz-aware datetimes (UTC)"
    assert before <= ts <= after, f"cache ts {ts} not within [{before}, {after}]"
    # Within the last 5 seconds (matches the dispatch's stated tolerance).
    assert (datetime.now(UTC) - ts) <= timedelta(seconds=5)


def test_try_fail_does_not_write_to_cache(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    patch_pool: type[_FakePool],
) -> None:
    """A failing /cases/try (step failure) must NOT write to the cache.
    Otherwise submit's gate would accept payloads that never passed Try.
    """
    raw = _minimal_valid_yaml()
    cer = _case_result("lg-bug-9999-test-try", StepStatus.FAIL, [_failing_step()])
    _install_run_case_stub(monkeypatch, cer)

    assert app.state.try_pass_cache == {}
    resp = client.post("/cases/try", json={"yaml": raw})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False

    expected_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert expected_hash not in app.state.try_pass_cache
    assert app.state.try_pass_cache == {}


def test_try_validate_fail_does_not_write_to_cache(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    patch_pool: type[_FakePool],
) -> None:
    """A validate-stage failure (e.g. YAML syntax error) must NOT write
    to the cache either — the endpoint short-circuits before run_case so
    overall_ok stays False and the cache stays empty.
    """
    bad = "foo: : :"

    # run_case must not be called; install a sentinel that would crash if it is.
    async def must_not_call(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("run_case should not be invoked when validate fails")

    monkeypatch.setattr(orchestrator, "run_case", must_not_call)

    assert app.state.try_pass_cache == {}
    resp = client.post("/cases/try", json={"yaml": bad})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False

    expected_hash = hashlib.sha256(bad.encode("utf-8")).hexdigest()
    assert expected_hash not in app.state.try_pass_cache


# ---------------------------------------------------------------------------
# R26 visibility — endpoint must import + use the shared modules
# ---------------------------------------------------------------------------


def test_r26_imports_present_on_cases_module() -> None:
    """§14 R26 self-check: the four shared runner modules MUST be visible
    on ``app.api.cases``. If any of these attribute lookups fail, the
    endpoint has gone back to inline-recreating the runner stack.
    """
    # Names imported at module top — reviewer's grep pattern relies on these.
    assert hasattr(cases_api, "normalize_case")
    assert hasattr(cases_api, "dsn_map_from_env")
    assert hasattr(cases_api, "SqlSessionPool")
    assert hasattr(cases_api, "orchestrator")
    # And the orchestrator symbol must be the real module exposing run_case.
    assert hasattr(cases_api.orchestrator, "run_case")
