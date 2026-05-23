"""GET /cases + GET /cases/{id} (design.md §4.5 / §5.2).

Lists / fetches case YAML files from disk. Categories whitelist + their
`dir_path` are sourced from the `case_categories` table (§4.5) so adding
a new category is a DB migration, not a code change.

If a file fails §4.1 schema validation, we still include it in the list
with `status="invalid"` and an `error` message — the dispatch explicitly
requires "do not 500 the endpoint just because one file is malformed".
Single-case GET on an invalid file returns the partial parse + the error
so the UI can show what's broken without dropping into a generic 5xx.

Filter semantics:
  * `category` — exact match on the case's `category:` field (whitelist
    enforced; unknown categories yield empty).
  * `q` — case-insensitive substring match against either `id` or
    `title`.

CASES_ROOT env var overrides the on-disk root (default: `cases/` next to
the repo root). M1-11 uses the default; tests set it explicitly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.storage import sqlite_store
from app.storage.models import CaseCategory
from app.storage.yaml_loader import CaseValidationError, CategoryMeta, load_case

router = APIRouter(tags=["cases"])


DEFAULT_CASES_ROOT = Path("cases")


# ---------------------------------------------------------------------------
# Pydantic shapes
# ---------------------------------------------------------------------------


class CaseSummary(BaseModel):
    id: str
    category: str | None = None
    title: str | None = None
    status: str
    destructive: bool | None = None
    tags: list[str] | None = None
    error: str | None = None


class CaseDetail(BaseModel):
    id: str
    category: str | None = None
    title: str | None = None
    status: str
    destructive: bool | None = None
    tags: list[str] | None = None
    yaml_raw: str
    parsed: dict[str, Any] | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _cases_root() -> Path:
    """Resolve the on-disk cases root: env var first, then default.

    Returned as an absolute Path so subsequent globs are deterministic
    regardless of the test/server working directory.
    """
    raw = os.getenv("CASES_ROOT")
    if raw:
        return Path(raw).resolve()
    return DEFAULT_CASES_ROOT.resolve()


def _load_categories() -> list[CaseCategory]:
    """Read active `case_categories` rows. Used by both list + detail to
    know which dir_paths to scan and which whitelist names are legal."""
    with sqlite_store.get_session() as sess:
        stmt = (
            select(CaseCategory)
            .where(CaseCategory.is_active.is_(True))
            .order_by(CaseCategory.display_order.asc())
        )
        return list(sess.scalars(stmt).all())


def _build_category_meta(categories: list[CaseCategory]) -> dict[str, CategoryMeta]:
    """Project ``CaseCategory`` rows into the ``{name: CategoryMeta}`` shape
    the loader consumes (design.md §4.5 → loader contract).

    ``status_whitelist`` on the row is a TEXT column holding a JSON array
    string (e.g. ``'["open","fixed","wontfix","stub"]'``); we parse it
    here so the loader receives a plain ``frozenset[str]``.
    """
    out: dict[str, CategoryMeta] = {}
    for c in categories:
        try:
            whitelist_raw = json.loads(c.status_whitelist)
        except (TypeError, ValueError):
            # Defensive: a corrupted row shouldn't 500 the whole API; skip it.
            continue
        if not isinstance(whitelist_raw, list):
            continue
        out[c.name] = CategoryMeta(
            name=c.name,
            id_prefix=c.id_prefix,
            status_whitelist=frozenset(str(s) for s in whitelist_raw),
        )
    return out


def _safe_parse_raw(path: Path) -> tuple[str, dict[str, Any] | None, str | None]:
    """Read raw YAML text and best-effort parse it.

    Returns (raw_text, parsed_dict_or_None, error_or_None). YAML syntax
    errors yield (raw, None, "<message>"). Successful but non-mapping
    documents yield (raw, None, "<message>").
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as e:
        return ("", None, f"cannot read file: {e}")
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as e:
        return (raw_text, None, f"YAML syntax error: {e}")
    if not isinstance(data, dict):
        return (raw_text, None, "top-level YAML is not a mapping")
    return (raw_text, data, None)


def _summary_from_raw(
    path: Path,
    raw_dict: dict[str, Any] | None,
    parse_err: str | None,
    category_meta: dict[str, CategoryMeta],
) -> CaseSummary:
    """Build a CaseSummary from a raw YAML dict.

    Tries §4.1 validation via `load_case`. If validation passes we mark
    the summary's status from the YAML (default 'open'). If validation
    fails we still return a summary with status='invalid' + the error —
    the spec requires the endpoint to keep going.
    """
    case_id_fallback = path.stem
    if raw_dict is None:
        return CaseSummary(
            id=case_id_fallback,
            status="invalid",
            error=parse_err or "could not parse YAML",
        )

    # Try strict validation. On success we trust the parsed fields.
    try:
        case = load_case(path, category_meta)
        tags_raw = raw_dict.get("tags")
        tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else None
        return CaseSummary(
            id=case.id,
            category=case.category,
            title=case.title,
            status=case.status,
            destructive=case.destructive,
            tags=tags,
        )
    except CaseValidationError as e:
        # Salvage what we can from the raw dict so the UI can still render
        # an entry (id + title + category) even though the file is broken.
        tags_raw = raw_dict.get("tags")
        tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else None
        return CaseSummary(
            id=str(raw_dict.get("id") or case_id_fallback),
            category=str(raw_dict.get("category")) if raw_dict.get("category") else None,
            title=str(raw_dict.get("title")) if raw_dict.get("title") else None,
            status="invalid",
            destructive=raw_dict.get("destructive")
            if isinstance(raw_dict.get("destructive"), bool)
            else None,
            tags=tags,
            error=str(e),
        )


def _iter_case_files(categories: list[CaseCategory]) -> list[tuple[Path, str]]:
    """Yield (yaml_path, category_name) for every *.yaml under each
    category's dir_path. Categories whose dir_path doesn't exist on disk
    are silently skipped (M1-11 dogfood will populate them)."""
    root = _cases_root()
    out: list[tuple[Path, str]] = []
    for cat in categories:
        cat_dir = root / cat.dir_path
        if not cat_dir.is_dir():
            continue
        for p in sorted(cat_dir.glob("*.yaml")):
            out.append((p, cat.name))
    return out


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.get("/cases", response_model=list[CaseSummary])
def list_cases(category: str | None = None, q: str | None = None) -> list[CaseSummary]:
    """Scan cases/ on disk and return a summary per file.

    Filters:
      * `category`: exact match (case-sensitive — categories are stable
        identifiers, not free text).
      * `q`: case-insensitive substring against id OR title.

    Invalid YAML files are included with `status="invalid"` and `error`
    populated; the endpoint never 500s on a single bad file.
    """
    categories = _load_categories()
    category_meta = _build_category_meta(categories)

    # category filter narrows which dirs we scan.
    scanning = [c for c in categories if c.name == category] if category is not None else categories

    summaries: list[CaseSummary] = []
    for path, _cat_name in _iter_case_files(scanning):
        raw_text, raw_dict, parse_err = _safe_parse_raw(path)
        del raw_text  # not needed for list endpoint
        summary = _summary_from_raw(path, raw_dict, parse_err, category_meta)

        # category filter: drop entries whose parsed category doesn't match
        # (we already narrowed by dir_path above, but a malformed file
        # might claim a different category; trust the dir's category
        # binding by skipping mismatched-but-valid entries only).
        if category is not None and summary.category and summary.category != category:
            continue

        if q:
            needle = q.lower()
            hay = f"{summary.id or ''} {summary.title or ''}".lower()
            if needle not in hay:
                continue

        summaries.append(summary)
    return summaries


@router.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: str) -> CaseDetail:
    """Return the full YAML text + parsed fields for one case.

    404 if the case_id is not found under any active category's
    dir_path. Invalid YAML still returns 200 with `status="invalid"` and
    the raw text + error — the UI editor needs the raw text to let a
    human fix it.
    """
    categories = _load_categories()
    category_meta = _build_category_meta(categories)

    for path, _cat_name in _iter_case_files(categories):
        if path.stem != case_id:
            continue
        raw_text, raw_dict, parse_err = _safe_parse_raw(path)
        # Try strict load — if it succeeds we report status from YAML.
        try:
            case = load_case(path, category_meta)
            tags_raw = (raw_dict or {}).get("tags")
            tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else None
            return CaseDetail(
                id=case.id,
                category=case.category,
                title=case.title,
                status=case.status,
                destructive=case.destructive,
                tags=tags,
                yaml_raw=raw_text,
                parsed=raw_dict,
            )
        except CaseValidationError as e:
            tags_raw = (raw_dict or {}).get("tags")
            tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else None
            return CaseDetail(
                id=str((raw_dict or {}).get("id") or case_id),
                category=str((raw_dict or {}).get("category"))
                if (raw_dict or {}).get("category")
                else None,
                title=str((raw_dict or {}).get("title")) if (raw_dict or {}).get("title") else None,
                status="invalid",
                destructive=(raw_dict or {}).get("destructive")
                if isinstance((raw_dict or {}).get("destructive"), bool)
                else None,
                tags=tags,
                yaml_raw=raw_text,
                parsed=raw_dict,
                error=str(e),
            )
    raise HTTPException(status_code=404, detail=f"case {case_id!r} not found")


__all__ = ["router"]
