"""Time helpers for tz-aware UTC handling at the storage→response boundary.

Backend policy (post 2026-05-26 dogfood):
  - Every datetime write into the DB goes through ``datetime.now(UTC)`` so
    the wall-clock value stored is unambiguous.
  - Every datetime field on an API response model must serialize with a
    timezone suffix (``+00:00``) so frontend never has to defensively
    interpret naive ISO strings.

The gap closed by this helper:
  SQLAlchemy's default ``DateTime`` column on SQLite does NOT preserve
  ``tzinfo``. A tz-aware ``datetime.now(UTC)`` written through SQLAlchemy
  is stored as ISO without offset (e.g. ``2026-05-26 03:47:11.314501``)
  and reads back NAIVE. If we hand that naive ``datetime`` to Pydantic v2,
  it serializes without a ``+00:00`` suffix — browser then parses as
  local time and the UI shows e.g. "8h ago" on a UTC+8 client for a
  just-finished run.

  Fix: re-attach UTC ``tzinfo`` at the storage→response boundary.
  ``as_utc()`` is idempotent — already-aware datetimes pass through.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["as_utc"]


def as_utc(dt: datetime | None) -> datetime | None:
    """Re-attach UTC tzinfo to naive datetimes read from SQLite.

    SQLAlchemy's ``DateTime`` column on SQLite drops ``tzinfo`` on
    round-trip. Our write policy is "every datetime is UTC" (all writes
    go through ``datetime.now(UTC)``), so a naive datetime read from DB
    is by definition UTC — we just re-attach the tzinfo.

    Returns ``None`` unchanged. Tz-aware inputs pass through unchanged
    (idempotent — safe to call twice). Naive inputs get ``UTC`` tzinfo
    attached.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
