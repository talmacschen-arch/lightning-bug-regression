"""Admin endpoints (design.md §4.5 / §5.2 / §5.5.7 / §13.12 M6-4).

`/admin/categories` (M1-10) backs the frontend dashboard tab and the
skill's category grounding (which prefixes / statuses / dir_paths are
legal).

`/admin/step-kinds` (M3b-1) backs the `add-test-case` skill's step-kind
grounding — without it the skill would have to hard-code the kind list
and drift from `app.runner.step_kinds.STEP_KINDS` (§14 R26 dual-code-path).

`/admin/skip-list` + `/admin/settings` (M6-4) — CRUD UI for the
single-user runtime tunables. Mutating endpoints (POST/PUT/DELETE) are
gated by `X-Admin-Password` header against env `ADMIN_PASSWORD`; GETs
are open. If `ADMIN_PASSWORD` is unset, no auth required (dev mode).
Not a full auth system — design.md §13.12 explicitly says "防 accident,
user 单人模式".
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.runner.step_kinds import STEP_KINDS
from app.storage import sqlite_store
from app.storage.models import CaseCategory

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# M6-4 lightweight auth guard
# ---------------------------------------------------------------------------


def require_admin_password(
    x_admin_password: str | None = Header(default=None),
) -> None:
    """Reject mutations when ADMIN_PASSWORD is set but header doesn't match.

    If ADMIN_PASSWORD env is unset / empty → no-op (dev mode).
    Use as `Depends(require_admin_password)` on mutating endpoints.
    """
    expected = os.getenv("ADMIN_PASSWORD")
    if not expected:
        return
    if x_admin_password != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-Admin-Password",
        )


class CategoryOut(BaseModel):
    name: str
    display_name: str
    description: str | None
    id_prefix: str
    dir_path: str
    status_whitelist: list[str]
    default_status: str
    display_order: int


@router.get("/categories", response_model=list[CategoryOut])
def list_categories() -> list[CategoryOut]:
    """List active case categories ordered by `display_order ASC`.

    `status_whitelist` is stored as a JSON text blob in SQLite (§4.5); we
    parse it here so the response is a clean JSON array. Malformed JSON
    is surfaced as an empty list rather than crashing — the row is then
    visibly broken in the UI and a human can fix it.
    """
    out: list[CategoryOut] = []
    with sqlite_store.get_session() as sess:
        stmt = (
            select(CaseCategory)
            .where(CaseCategory.is_active.is_(True))
            .order_by(CaseCategory.display_order.asc())
        )
        rows = list(sess.scalars(stmt).all())
        for row in rows:
            try:
                wl = json.loads(row.status_whitelist)
                if not isinstance(wl, list):
                    wl = []
            except (json.JSONDecodeError, TypeError):
                wl = []
            out.append(
                CategoryOut(
                    name=row.name,
                    display_name=row.display_name,
                    description=row.description,
                    id_prefix=row.id_prefix,
                    dir_path=row.dir_path,
                    status_whitelist=wl,
                    default_status=row.default_status,
                    display_order=row.display_order,
                )
            )
    return out


class StepKindOut(BaseModel):
    """One entry in the `/admin/step-kinds` response.

    Mirrors `app.runner.step_kinds.StepKindMeta` — the skill reads this
    to ground its prompt about which step kinds (and which fields per
    kind) are legal. No DB lookup; static registry.
    """

    kind: str
    description: str
    required_fields: list[str]
    optional_fields: list[str]


@router.get("/step-kinds", response_model=list[StepKindOut])
def list_step_kinds() -> list[StepKindOut]:
    """Return the static step-kind registry in declared order.

    Order is preserved from `STEP_KINDS` so the skill can rely on
    positional references in its prompt template.
    """
    return [
        StepKindOut(
            kind=meta.kind,
            description=meta.description,
            required_fields=list(meta.required_fields),
            optional_fields=list(meta.optional_fields),
        )
        for meta in STEP_KINDS
    ]


# ---------------------------------------------------------------------------
# M6-4 skip-list CRUD
# ---------------------------------------------------------------------------


class SkipListEntryOut(BaseModel):
    id: int
    case_id: str
    reason: str
    applies_to_version: str | None = None
    upstream_issue: str | None = None
    until_date: date | None = None


class SkipListCreate(BaseModel):
    case_id: str
    reason: str
    applies_to_version: str | None = None
    upstream_issue: str | None = None
    until_date: date | None = None


@router.get("/skip-list", response_model=list[SkipListEntryOut])
def list_skip_list_entries() -> list[SkipListEntryOut]:
    """List all skip-list entries (ordered by id)."""
    with sqlite_store.get_session() as sess:
        rows = sqlite_store.get_skip_list(sess)
        return [
            SkipListEntryOut(
                id=r.id,
                case_id=r.case_id,
                reason=r.reason,
                applies_to_version=r.applies_to_version,
                upstream_issue=r.upstream_issue,
                until_date=r.until_date,
            )
            for r in rows
        ]


@router.post(
    "/skip-list",
    response_model=SkipListEntryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_password)],
)
def create_skip_list_entry(payload: SkipListCreate) -> SkipListEntryOut:
    """Add a new skip-list entry. Idempotent on duplicate (case_id, version)?
    No — duplicates are allowed; the orchestrator's matching rule will
    take any of them (first match wins per §5.3 contract)."""
    if not payload.case_id.strip():
        raise HTTPException(status_code=400, detail="case_id is required")
    if not payload.reason.strip():
        raise HTTPException(status_code=400, detail="reason is required")
    with sqlite_store.get_session() as sess:
        row = sqlite_store.add_skip_list_entry(
            sess,
            case_id=payload.case_id.strip(),
            reason=payload.reason.strip(),
            applies_to_version=payload.applies_to_version,
            upstream_issue=payload.upstream_issue,
            until_date=payload.until_date,
        )
        sess.commit()
        return SkipListEntryOut(
            id=row.id,
            case_id=row.case_id,
            reason=row.reason,
            applies_to_version=row.applies_to_version,
            upstream_issue=row.upstream_issue,
            until_date=row.until_date,
        )


@router.delete(
    "/skip-list/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin_password)],
)
def delete_skip_list_entry(entry_id: int) -> None:
    """Remove a skip-list entry by id. 404 if missing."""
    with sqlite_store.get_session() as sess:
        removed = sqlite_store.delete_skip_list_entry(sess, entry_id)
        if not removed:
            raise HTTPException(status_code=404, detail=f"skip-list entry {entry_id} not found")
        sess.commit()


# ---------------------------------------------------------------------------
# M6-4 settings list/update
# ---------------------------------------------------------------------------


class SettingOut(BaseModel):
    key: str
    value: object  # JSON-decoded value (dict / list / scalar wrapped)
    value_type: str
    updated_at: datetime


class SettingUpdate(BaseModel):
    value: object  # any JSON-serializable


# Allowlist of keys that the Admin UI can edit. Other keys (e.g. internal
# bookkeeping) are exposed as read-only via GET but PUT rejects them. This
# avoids accidentally clobbering things like `jinja_context` shape that
# the runner depends on without a guided schema.
ADMIN_EDITABLE_SETTINGS = {
    "dev_db_url",
    "cluster_topology",
    "jinja_context",
    "dut_hosts",
    "server_log_path",
}


@router.get("/settings", response_model=list[SettingOut])
def list_admin_settings() -> list[SettingOut]:
    """List all system_settings rows. Caller filters as needed."""
    with sqlite_store.get_session() as sess:
        rows = sqlite_store.list_settings(sess)
        out: list[SettingOut] = []
        for r in rows:
            try:
                v: object = json.loads(r.value)
            except (ValueError, TypeError):
                v = r.value
            out.append(
                SettingOut(
                    key=r.key,
                    value=v,
                    value_type=r.value_type,
                    updated_at=r.updated_at,
                )
            )
        return out


@router.put(
    "/settings/{key}",
    response_model=SettingOut,
    dependencies=[Depends(require_admin_password)],
)
def update_admin_setting(key: str, payload: SettingUpdate) -> SettingOut:
    """Upsert one setting. Key must be in the editable allowlist.

    Value must be a JSON object (dict). Top-level scalars and arrays
    are rejected so existing consumers (runs.py, etc.) that read
    settings as dicts don't break — the storage layer stores anything
    JSON-serializable but the schema across consumers is "value is a
    dict". Wrap scalars at the call site if you want them in a setting.
    """
    if key not in ADMIN_EDITABLE_SETTINGS:
        raise HTTPException(
            status_code=400,
            detail=f"key {key!r} is not in the admin-editable allowlist",
        )
    if not isinstance(payload.value, dict):
        raise HTTPException(
            status_code=400,
            detail="value must be a JSON object (dict); wrap scalars/lists if needed",
        )
    with sqlite_store.get_session() as sess:
        sqlite_store.set_setting(sess, key, payload.value)
        sess.commit()
        rows = sqlite_store.list_settings(sess)
        row = next((r for r in rows if r.key == key), None)
        assert row is not None  # we just wrote it
        try:
            v: object = json.loads(row.value)
        except (ValueError, TypeError):
            v = row.value
        return SettingOut(
            key=row.key,
            value=v,
            value_type=row.value_type,
            updated_at=row.updated_at,
        )
