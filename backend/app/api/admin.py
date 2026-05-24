"""Admin endpoints (design.md §4.5 / §5.2 / §5.5.7).

`/admin/categories` (M1-10) backs the frontend dashboard tab and the
skill's category grounding (which prefixes / statuses / dir_paths are
legal).

`/admin/step-kinds` (M3b-1) backs the `add-test-case` skill's step-kind
grounding — without it the skill would have to hard-code the kind list
and drift from `app.runner.step_kinds.STEP_KINDS` (§14 R26 dual-code-path).

Future M2+ work expands this router with `/admin/settings`,
`/admin/skip-list`, `/admin/reload`.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.runner.step_kinds import STEP_KINDS
from app.storage import sqlite_store
from app.storage.models import CaseCategory

router = APIRouter(prefix="/admin", tags=["admin"])


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
