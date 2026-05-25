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
import logging
from datetime import date, datetime

import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.auth import get_current_user
from app.runner.step_kinds import STEP_KINDS
from app.storage import sqlite_store
from app.storage.models import CaseCategory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Auth gate (v1.17+): mutation endpoints use `Depends(get_current_user)`
# from app.api.auth. The legacy `ADMIN_PASSWORD` env + `X-Admin-Password`
# header pattern (M6-4 PR #115) is replaced.
# ---------------------------------------------------------------------------


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
    dependencies=[Depends(get_current_user)],
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
    dependencies=[Depends(get_current_user)],
)
def delete_skip_list_entry(entry_id: int) -> None:
    """Remove a skip-list entry by id. 404 if missing."""
    with sqlite_store.get_session() as sess:
        removed = sqlite_store.delete_skip_list_entry(sess, entry_id)
        if not removed:
            raise HTTPException(status_code=404, detail=f"skip-list entry {entry_id} not found")
        sess.commit()


# NOTE: /admin/settings list + PUT endpoints (M6-4 PR #115) were removed
# 2026-05-25. The 3 keys that endpoint allowlisted (jinja_context /
# dut_hosts / server_log_path) had near-zero real consumers:
#   - dut_hosts moved to external/dut.yml (post-Settings refactor, this PR)
#   - jinja_context never used in any case YAML (M6-5 external_deps_loader
#     supplanted it for the only real use case = injecting external svc URLs)
#   - server_log_path: cases write `server_log_path:` per-case in YAML
# The system_settings table + storage helpers (sqlite_store.get_setting /
# set_setting / list_settings) remain for future use but have no callers.


# ---------------------------------------------------------------------------
# Delete case (v1.16+ post-Settings refactor)
#
# Deletes the case's YAML file from disk. case_results / runs rows are
# untouched — historical run data is independent of case definition.
# Path traversal protected: case_id must match `_iter_case_files` stem.
# Educational note in confirm dialog (frontend): skip-list handles
# temporary disable; delete is for permanent removal only.
# ---------------------------------------------------------------------------


@router.delete(
    "/cases/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_current_user)],
)
def delete_case(case_id: str) -> None:
    """Remove a case YAML file from disk. 404 if no file matches.

    Historical runs are preserved automatically (case_results rows hold
    case_id as a string, no FK). Caller is expected to `git rm + commit +
    push` after — the endpoint only touches the working tree.
    """
    # Resolve via the same iter that powers /cases — ensures we never
    # walk outside CASES_ROOT (§14 R26 single source).
    from app.api.cases import _iter_case_files, _load_categories

    categories = _load_categories()
    for path, _cat_name in _iter_case_files(categories):
        if path.stem != case_id:
            continue
        # Defense-in-depth: even though _iter_case_files only returns
        # files under each category's dir_path, double-check that the
        # resolved path is inside CASES_ROOT before unlinking.
        from app.api.cases import _cases_root

        try:
            path.resolve().relative_to(_cases_root().resolve())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"case file {path} resolved outside cases root",
            ) from None
        try:
            path.unlink()
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"failed to delete {path}: {e}") from None
        logger.info("admin delete_case: removed %s (case_id=%s)", path, case_id)
        return
    raise HTTPException(status_code=404, detail=f"case {case_id!r} not found in any category dir")


# ---------------------------------------------------------------------------
# Read-only external/<svc>.yml browser (v1.15+ post-Settings refactor)
# ---------------------------------------------------------------------------


class ExternalServiceOut(BaseModel):
    """One row in the /admin/external-services response.

    `content` is the raw YAML text — not parsed — so the UI can render
    it verbatim (preserves comments, blank lines, etc.). Frontend does
    not edit; if a user wants to change a value, they edit the file
    directly + commit (single source of truth = `external/<svc>.yml`
    on disk, git-tracked).
    """

    name: str  # svc name = filename stem (e.g. `elasticsearch`)
    filename: str  # `<svc>.yml`
    size_bytes: int
    modified_at: datetime
    content: str  # raw YAML
    parse_error: str | None = None  # set if YAML is malformed


@router.get("/external-services", response_model=list[ExternalServiceOut])
def list_external_services() -> list[ExternalServiceOut]:
    """List all `external/<svc>.yml` files with their raw YAML content.

    Read-only on purpose: the file is the source of truth, edits go via
    `vi external/<svc>.yml` + git commit. Web UI is just a discovery /
    sanity-check view (e.g. "what does ES URL look like right now?").

    Honors `EXTERNAL_DEPS_DIR` env var like the loader. Missing dir →
    empty list (no error; first-time setup is OK).
    """
    # Reuse the loader's resolver so this endpoint + runner runtime
    # always look at the same directory (§14 R26 dual-code-path).
    from app.runner import external_deps_loader

    base_dir = external_deps_loader._resolve_dir()
    if not base_dir.is_dir():
        return []

    out: list[ExternalServiceOut] = []
    for child in sorted(base_dir.iterdir()):
        if not child.is_file() or child.suffix not in (".yml", ".yaml"):
            continue
        try:
            stat = child.stat()
            content = child.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("external-services: failed to read %s: %s", child, e)
            continue
        # Validate parse — surface as `parse_error` not as endpoint error,
        # so a malformed file doesn't hide the others.
        parse_error: str | None = None
        try:
            parsed = yaml.safe_load(content)
            if not isinstance(parsed, dict):
                parse_error = f"top-level must be a YAML mapping; got {type(parsed).__name__}"
        except yaml.YAMLError as e:
            parse_error = f"YAML parse error: {e}"
        out.append(
            ExternalServiceOut(
                name=child.stem,
                filename=child.name,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime),
                content=content,
                parse_error=parse_error,
            )
        )
    return out
