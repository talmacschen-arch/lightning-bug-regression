"""Admin endpoints (design.md §4.5 / §5.2).

Only `/admin/categories` lands in M1-10 — it is needed by the frontend
dashboard tab and (more importantly) by the skill grounding step before
generating new cases (so the skill knows which categories + status
whitelists + dir_paths are legal).

Future M2+ work expands this router with `/admin/step-kinds`,
`/admin/settings`, `/admin/skip-list`, `/admin/reload`. Out of scope for
M1-10 per dispatch.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

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
