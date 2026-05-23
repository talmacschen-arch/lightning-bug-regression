"""GET /healthz — liveness + DB ping (design.md §5.2; smoke / monitoring).

Returns 200 always (the endpoint itself is up). The `db` field reports
"ok" / "fail" so monitoring can distinguish "API alive but DB down" from
"whole service down". A failed DB ping does NOT cause a 5xx — the
endpoint is informational, not gated.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.storage import sqlite_store

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    db: str


@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    db_status = "ok"
    try:
        with sqlite_store.get_session() as sess:
            sess.execute(text("SELECT 1")).scalar_one()
    except Exception:
        db_status = "fail"
    return HealthResponse(status="ok", db=db_status)
