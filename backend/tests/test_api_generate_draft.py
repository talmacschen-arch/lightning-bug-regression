"""Tests for POST /cases/generate-draft (design.md §5.4 / §13.13 M7).

These tests mock ``anthropic.Anthropic`` so they don't burn real API
quota and don't require ``ANTHROPIC_API_KEY`` to be set in CI.

Coverage:
  * Bearer-auth contract (no token → 401, valid token → 200)
  * Happy path: 1 call returns valid YAML → attempts=1
  * Retry-on-schema-invalid:
      - call 1 returns malformed YAML, call 2 returns valid → attempts=2
      - **wiring assertion (§13.13 D)**: call 2's prompt body MUST contain
        the previous validation error string verbatim
      - both calls malformed → attempts=3 + validation_errors non-empty
        (HTTP 200, business state)
  * Anthropic API error mapping (no retry on these per §13.13 C-2):
      - 429 (RateLimitError) → HTTP 429
      - 5xx (InternalServerError) → HTTP 502
      - timeout (APITimeoutError) → HTTP 504
  * Missing ANTHROPIC_API_KEY → 503 + body indicates reason
  * description > 8 KB → 413
"""

from __future__ import annotations

import json
import textwrap
from unittest.mock import MagicMock, patch

import anthropic
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import seed_admin_if_missing
from app.main import app
from app.storage import sqlite_store
from app.storage.models import Base, CaseCategory

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Fresh in-memory DB with seeded admin user + active categories.

    Each test also gets ``ANTHROPIC_API_KEY=test-key-fake`` set so the
    endpoint passes the env-var gate; tests that exercise the missing-key
    path override this explicitly.
    """
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

    # Seed categories (needed for status_whitelist injection into prompt)
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
        sess.add(
            CaseCategory(
                name="extension",
                display_name="Extension",
                description=None,
                id_prefix="lg-ext-",
                dir_path="extension",
                status_whitelist=json.dumps(["stable", "experimental", "deprecated", "stub"]),
                default_status="stable",
                display_order=20,
                is_active=True,
            )
        )
        sess.commit()
    seed_admin_if_missing()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-fake")

    with TestClient(app) as c:
        yield c

    Base.metadata.drop_all(engine)
    engine.dispose()


def _login_token(client: TestClient) -> str:
    """Helper: log in and return a fresh Bearer token."""
    resp = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _auth_headers(client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login_token(client)}"}


# ---------------------------------------------------------------------------
# YAML fixtures returned by the mocked LLM
# ---------------------------------------------------------------------------


def _valid_minimal_yaml() -> str:
    """A YAML that passes yaml_loader.load_case + normalize_case."""
    return textwrap.dedent(
        """\
        id: lg-bug-9999-mock
        category: bug_regression
        title: mocked draft
        description: mocked LLM output for /cases/generate-draft test
        procedure: do a thing
        expected: returns 1
        status: open
        steps:
          - name: trivial
            kind: sql
            sql: SELECT 1
        """
    )


def _malformed_yaml() -> str:
    """YAML that LOOKS like a case but fails normalization (unknown kind)."""
    return textwrap.dedent(
        """\
        id: lg-bug-9998-mock
        category: bug_regression
        title: bogus draft
        description: this should fail normalize_case because of bogus kind
        procedure: do a thing
        expected: returns 1
        status: open
        steps:
          - name: bogus
            kind: not_a_real_kind_at_all
            sql: SELECT 1
        """
    )


def _make_mock_message(text: str) -> MagicMock:
    """Build a MagicMock that quacks like ``anthropic.types.Message``.

    The endpoint code reads ``.content`` (a list of blocks, each with
    ``.type=='text'`` + ``.text``) plus ``.usage.input_tokens`` /
    ``.usage.output_tokens``.
    """
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text
    msg = MagicMock()
    msg.content = [text_block]
    msg.usage = MagicMock(input_tokens=123, output_tokens=456)
    return msg


# ---------------------------------------------------------------------------
# auth contract
# ---------------------------------------------------------------------------


def test_no_bearer_auth_returns_401(client: TestClient) -> None:
    """§13.13 amendment A: endpoint requires Bearer auth.

    Even though we have ANTHROPIC_API_KEY set and a valid payload,
    omitting the Authorization header MUST 401 BEFORE the endpoint
    reaches its body — so we don't even need to mock Anthropic here.
    """
    resp = client.post(
        "/cases/generate-draft",
        json={"description": "anything", "category": "bug_regression"},
    )
    assert resp.status_code == 401, resp.text


def test_invalid_bearer_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/cases/generate-draft",
        json={"description": "anything"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_happy_path_valid_yaml_first_try(client: TestClient) -> None:
    """LLM returns valid YAML on first call → attempts=1 + yaml_draft set."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_message(_valid_minimal_yaml())
    with patch("anthropic.Anthropic", return_value=mock_client):
        resp = client.post(
            "/cases/generate-draft",
            json={
                "description": "Some kind of bug about hashjoin and ORCA",
                "category": "bug_regression",
            },
            headers=_auth_headers(client),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attempts"] == 1
    assert body["validation_errors_during_retry"] == []
    assert "id: lg-bug-9999-mock" in body["yaml_draft"]
    # SDK invoked exactly once
    assert mock_client.messages.create.call_count == 1
    call = mock_client.messages.create.call_args
    # Asserted shape: model + max_tokens pinned per §13.13 amendment B/D1
    assert call.kwargs["model"] == "claude-opus-4-7"
    assert call.kwargs["max_tokens"] == 2000


def test_happy_path_strips_markdown_fences(client: TestClient) -> None:
    """Defensive: model sometimes wraps in ```yaml ... ```; we still parse."""
    fenced = "```yaml\n" + _valid_minimal_yaml() + "\n```"
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_message(fenced)
    with patch("anthropic.Anthropic", return_value=mock_client):
        resp = client.post(
            "/cases/generate-draft",
            json={"description": "x"},
            headers=_auth_headers(client),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attempts"] == 1
    # The fences should be stripped from yaml_draft
    assert not body["yaml_draft"].startswith("```")
    assert "id: lg-bug-9999-mock" in body["yaml_draft"]


def test_prompt_has_cache_control_marker(client: TestClient) -> None:
    """§13.13 amendment G: schema + few-shot prefix MUST carry
    ``cache_control: {"type": "ephemeral"}`` so prompt caching engages.
    """
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_message(_valid_minimal_yaml())
    with patch("anthropic.Anthropic", return_value=mock_client):
        resp = client.post(
            "/cases/generate-draft",
            json={"description": "test"},
            headers=_auth_headers(client),
        )
    assert resp.status_code == 200
    call = mock_client.messages.create.call_args
    system_blocks = call.kwargs["system"]
    assert isinstance(system_blocks, list) and system_blocks
    block = system_blocks[0]
    assert block.get("cache_control") == {"type": "ephemeral"}
    # Sanity check: schema + few-shot examples actually present
    text = block["text"]
    assert "id: lg-bug-0001-hashjoin-right-table" in text
    assert "id: lg-ext-pgvector-ivfflat-basic" in text
    assert "id: lg-bug-0008-pax-toast-vacuum-analyze-crash" in text
    # E-1: gpadmin default declared
    assert "gpadmin" in text
    # E-2: §4.1.2 psql -c iron rule declared
    assert "VACUUM" in text
    assert "psql -c" in text
    # R4b: allowed categories injected (not hardcoded)
    assert "bug_regression" in text
    assert "extension" in text


# ---------------------------------------------------------------------------
# retry on schema-invalid
# ---------------------------------------------------------------------------


def test_retry_on_invalid_then_valid(client: TestClient) -> None:
    """Attempt 1 returns malformed YAML, attempt 2 returns valid.

    After this test runs, ``call_count == 2`` (the endpoint retried once)
    and the response body shows ``attempts=2``.
    """
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _make_mock_message(_malformed_yaml()),
        _make_mock_message(_valid_minimal_yaml()),
    ]
    with patch("anthropic.Anthropic", return_value=mock_client):
        resp = client.post(
            "/cases/generate-draft",
            json={"description": "test retry"},
            headers=_auth_headers(client),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attempts"] == 2, body
    assert len(body["validation_errors_during_retry"]) == 1
    assert "id: lg-bug-9999-mock" in body["yaml_draft"]
    assert mock_client.messages.create.call_count == 2


def test_retry_prompt_contains_previous_validation_error(
    client: TestClient,
) -> None:
    """**§13.13 amendment D — wiring assertion**:

    The retry call's prompt body MUST literally contain the previous
    attempt's validation error string. Not just "retry happened" — the
    feedback loop only works if the model SEES the error.
    """
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _make_mock_message(_malformed_yaml()),
        _make_mock_message(_valid_minimal_yaml()),
    ]
    with patch("anthropic.Anthropic", return_value=mock_client):
        resp = client.post(
            "/cases/generate-draft",
            json={"description": "retry-wiring test"},
            headers=_auth_headers(client),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attempts"] == 2

    # The validation error string surfaced in the response …
    err_str = body["validation_errors_during_retry"][0]
    assert err_str, "validation_errors_during_retry must be non-empty"

    # … must appear verbatim in the SECOND messages.create call's prompt.
    calls = mock_client.messages.create.call_args_list
    assert len(calls) == 2
    second_call_messages = calls[1].kwargs["messages"]
    assert second_call_messages and isinstance(second_call_messages, list)
    second_user_msg: str = second_call_messages[0]["content"]
    assert err_str in second_user_msg, (
        f"retry prompt did NOT contain previous validation error.\n"
        f"err_str={err_str!r}\n"
        f"second_user_msg={second_user_msg!r}"
    )

    # And the FIRST call must NOT have any previous-error block (sanity).
    first_user_msg: str = calls[0].kwargs["messages"][0]["content"]
    assert "Previous attempt FAILED validation" not in first_user_msg


def test_max_retries_exhausted_returns_200_attempts_3(
    client: TestClient,
) -> None:
    """Both initial + 2 retries return malformed YAML.

    Per §13.13 amendment error map: this is a business state (NOT an
    error) — endpoint returns HTTP 200 with empty yaml_draft, attempts=3,
    and non-empty validation_errors_during_retry.
    """
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _make_mock_message(_malformed_yaml()),
        _make_mock_message(_malformed_yaml()),
        _make_mock_message(_malformed_yaml()),
    ]
    with patch("anthropic.Anthropic", return_value=mock_client):
        resp = client.post(
            "/cases/generate-draft",
            json={"description": "guaranteed-to-loop test"},
            headers=_auth_headers(client),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attempts"] == 3, body
    assert body["yaml_draft"] == ""
    assert len(body["validation_errors_during_retry"]) == 3
    assert mock_client.messages.create.call_count == 3


# ---------------------------------------------------------------------------
# Anthropic API errors (no retry — §13.13 C-2)
# ---------------------------------------------------------------------------


def _make_anthropic_error(
    exc_cls: type[Exception], message: str = "boom", status_code: int | None = None
) -> Exception:
    """Build an instance of an anthropic SDK error.

    Most ``APIStatusError`` subclasses need ``(message, response, body)``
    constructor args; we bypass by instantiating ``Exception`` and
    monkey-patching attributes ``status_code`` for endpoint to read.
    """
    # APITimeoutError / APIConnectionError accept (request=) but our endpoint
    # only catches the class; construct via __new__ to skip the picky __init__.
    obj = exc_cls.__new__(exc_cls)
    Exception.__init__(obj, message)
    if status_code is not None:
        obj.status_code = status_code  # type: ignore[attr-defined]
    return obj


def test_anthropic_rate_limit_returns_429_no_retry(
    client: TestClient,
) -> None:
    """RateLimitError → HTTP 429 transparent passthrough, no retry."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _make_anthropic_error(
        anthropic.RateLimitError, "rate-limited"
    )
    with patch("anthropic.Anthropic", return_value=mock_client):
        resp = client.post(
            "/cases/generate-draft",
            json={"description": "x"},
            headers=_auth_headers(client),
        )
    assert resp.status_code == 429, resp.text
    # Crucially: NO retry attempted on API errors (§13.13 C-2)
    assert mock_client.messages.create.call_count == 1


def test_anthropic_5xx_returns_502_no_retry(client: TestClient) -> None:
    """InternalServerError (5xx) → HTTP 502, no retry."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _make_anthropic_error(
        anthropic.InternalServerError, "boom", status_code=500
    )
    with patch("anthropic.Anthropic", return_value=mock_client):
        resp = client.post(
            "/cases/generate-draft",
            json={"description": "x"},
            headers=_auth_headers(client),
        )
    assert resp.status_code == 502, resp.text
    assert mock_client.messages.create.call_count == 1


def test_anthropic_timeout_returns_504_no_retry(client: TestClient) -> None:
    """APITimeoutError → HTTP 504, no retry."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _make_anthropic_error(
        anthropic.APITimeoutError, "timed out"
    )
    with patch("anthropic.Anthropic", return_value=mock_client):
        resp = client.post(
            "/cases/generate-draft",
            json={"description": "x"},
            headers=_auth_headers(client),
        )
    assert resp.status_code == 504, resp.text
    assert mock_client.messages.create.call_count == 1


def test_anthropic_network_error_returns_504_no_retry(
    client: TestClient,
) -> None:
    """APIConnectionError (network) → HTTP 504, no retry."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = _make_anthropic_error(
        anthropic.APIConnectionError, "connreset"
    )
    with patch("anthropic.Anthropic", return_value=mock_client):
        resp = client.post(
            "/cases/generate-draft",
            json={"description": "x"},
            headers=_auth_headers(client),
        )
    assert resp.status_code == 504, resp.text
    assert mock_client.messages.create.call_count == 1


# ---------------------------------------------------------------------------
# config / size guards
# ---------------------------------------------------------------------------


def test_missing_api_key_returns_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """When ANTHROPIC_API_KEY is unset, endpoint MUST return 503 + body
    indicating the reason (so frontend can surface "operator hasn't set key").
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # No SDK mock needed — we should 503 BEFORE we try to instantiate the client.
    resp = client.post(
        "/cases/generate-draft",
        json={"description": "x"},
        headers=_auth_headers(client),
    )
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert "ANTHROPIC_API_KEY" in body["detail"]


def test_description_over_8kb_returns_413(client: TestClient) -> None:
    """description > 8 KB → HTTP 413, no SDK call."""
    big_desc = "A" * (8 * 1024 + 1)  # one byte over the limit
    mock_client = MagicMock()
    # SDK MUST NOT be called even if we mock it
    with patch("anthropic.Anthropic", return_value=mock_client):
        resp = client.post(
            "/cases/generate-draft",
            json={"description": big_desc},
            headers=_auth_headers(client),
        )
    assert resp.status_code == 413, resp.text
    body = resp.json()
    assert "8 KB" in body["detail"] or "8192" in body["detail"]
    # Endpoint must short-circuit BEFORE constructing the SDK client.
    mock_client.messages.create.assert_not_called()


def test_description_exactly_8kb_succeeds(client: TestClient) -> None:
    """Boundary: exactly 8192 bytes is allowed; 8193 is not."""
    desc = "A" * (8 * 1024)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_message(_valid_minimal_yaml())
    with patch("anthropic.Anthropic", return_value=mock_client):
        resp = client.post(
            "/cases/generate-draft",
            json={"description": desc},
            headers=_auth_headers(client),
        )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# prompt structure (smoke — covers prompt-builder integration)
# ---------------------------------------------------------------------------


def test_prompt_injects_user_selected_category(client: TestClient) -> None:
    """When `category` is supplied in the request, it must appear in the
    user-turn so the LLM sticks to that category's whitelist."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_message(_valid_minimal_yaml())
    with patch("anthropic.Anthropic", return_value=mock_client):
        client.post(
            "/cases/generate-draft",
            json={"description": "x", "category": "extension"},
            headers=_auth_headers(client),
        )
    call = mock_client.messages.create.call_args
    user_msg = call.kwargs["messages"][0]["content"]
    assert "extension" in user_msg
    assert "User-selected category" in user_msg


def test_prompt_handles_no_category(client: TestClient) -> None:
    """No category → user-turn must say model picks one from allowed list."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_mock_message(_valid_minimal_yaml())
    with patch("anthropic.Anthropic", return_value=mock_client):
        client.post(
            "/cases/generate-draft",
            json={"description": "x"},
            headers=_auth_headers(client),
        )
    call = mock_client.messages.create.call_args
    user_msg = call.kwargs["messages"][0]["content"]
    assert "did NOT pre-select" in user_msg or "you choose" in user_msg
