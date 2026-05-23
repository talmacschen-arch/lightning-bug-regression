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

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.runner import orchestrator
from app.runner.case_normalizer import normalize_case
from app.runner.dsn_builder import dsn_map_from_env
from app.runner.sql_driver import SqlSessionPool
from app.storage import sqlite_store
from app.storage.models import CaseCategory
from app.storage.yaml_loader import CaseValidationError, CategoryMeta, load_case

logger = logging.getLogger(__name__)

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


class ValidateRequest(BaseModel):
    yaml: str


class ValidateErrorItem(BaseModel):
    where: str  # e.g. "steps[0].kind", "top-level", "yaml_syntax", "normalize"
    reason: str


class ValidateResponse(BaseModel):
    ok: bool
    errors: list[ValidateErrorItem]


class TryRequest(BaseModel):
    yaml: str


class StepResultOut(BaseModel):
    step_id: str
    kind: str
    status: str  # "pass" | "fail" | "error" | "skipped"
    duration_ms: int | None = None
    stderr_preview: str | None = None  # first 500 chars
    error: str | None = None


class TryResponse(BaseModel):
    ok: bool
    yaml_sha256: str  # for M3a-3.5 cache lookup later
    step_results: list[StepResultOut]
    # validation_errors populated only when validate stage failed; in that
    # case step_results is [] (we never reached run_case). Shape mirrors
    # ValidateErrorItem (where/reason) for UI symmetry.
    validation_errors: list[dict[str, str]] = []


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


def _validate_yaml_text(
    text: str,
) -> tuple[bool, list[ValidateErrorItem], dict[str, Any] | None]:
    """Shared validation core for ``/cases/validate`` and ``/cases/try``.

    Returns ``(ok, errors, parsed_dict_or_None)``:

    * ``ok`` is True iff schema + normalize both passed.
    * ``errors`` is the list shown to the user.
    * ``parsed_dict_or_None`` is the ``yaml.safe_load`` result — returned
      so the Try endpoint can hand it to ``normalize_case`` + the
      orchestrator without re-parsing. ``None`` when YAML syntax / top-level
      mapping check failed.

    Algorithm (design.md §13.7 M3a-1):

    1. ``yaml.safe_load`` — capture syntax errors as ``where="yaml_syntax"``.
    2. Top-level mapping check — non-dict → ``where="top-level"``.
    3. Build the same ``CategoryMeta`` whitelist the GET path uses.
    4. Write the raw YAML to a tempfile, call ``load_case`` against it,
       and surface ``CaseValidationError`` as a single error entry whose
       ``where`` is best-effort parsed from the loader's
       ``<file>:<key>: <reason>`` format.
    5. If the schema layer accepted the doc, also run ``normalize_case``
       on the parsed dict to catch step-kind / required-field violations
       the schema permits (e.g. log_grep without ``pattern:``); these
       surface with ``where="normalize"``.

    §14 R26: visibly delegates to :func:`yaml_loader.load_case` +
    :func:`case_normalizer.normalize_case` — inline copies of either
    module's logic would be a dual-code-path violation.
    """
    errors: list[ValidateErrorItem] = []

    # 1. YAML syntax.
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return False, [ValidateErrorItem(where="yaml_syntax", reason=str(e))], None

    # 2. Top-level must be a mapping.
    if not isinstance(parsed, dict):
        return (
            False,
            [ValidateErrorItem(where="top-level", reason="YAML document must be a mapping")],
            None,
        )

    # 3. Reuse the category whitelist the GET path uses.
    categories = _load_categories()
    category_meta = _build_category_meta(categories)

    # 4. Delegate to yaml_loader.load_case via a tempfile (load_case takes
    #    a Path, not a dict; we deliberately do NOT copy its checks inline —
    #    that would be a §14 R26 dual-code-path violation).
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            # Filename stem matters for the loader's `id == path.stem` check.
            # Use the parsed `id` value when present so a well-formed case
            # doesn't trip that rule purely on a random tempfile name.
            tmp.write(text)
            tmp_path = Path(tmp.name)

        # If the parsed dict carries an `id`, rename the tmpfile so its
        # stem matches; otherwise leave it — the loader will raise an
        # informative error which is exactly what the caller wants to see.
        case_id = parsed.get("id")
        if isinstance(case_id, str) and case_id:
            renamed = tmp_path.with_name(f"{case_id}.yaml")
            try:
                tmp_path.rename(renamed)
                tmp_path = renamed
            except OSError:
                # Best-effort; if rename fails just let load_case complain.
                pass

        try:
            load_case(tmp_path, category_meta)
        except CaseValidationError as e:
            # load_case messages are "<file_path>:<where>: <reason>".
            # Best-effort parse to recover the field name without
            # leaking the tempfile path into the API response.
            msg = str(e)
            prefix = f"{tmp_path}:"
            where = "schema"
            reason = msg
            if msg.startswith(prefix):
                rest = msg[len(prefix) :]
                if ": " in rest:
                    where, reason = rest.split(": ", 1)
                else:
                    reason = rest
            errors.append(ValidateErrorItem(where=where, reason=reason))
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    # 5. Even if schema validation passed, run the normalizer — it catches
    #    things the schema layer permits (e.g. unknown step kinds the
    #    normalizer's VALID_KINDS set rejects, or missing sql/cmd fields).
    #    We always run it when schema passed; if schema already failed we
    #    skip normalize so the caller fixes the more fundamental error first.
    if not errors:
        try:
            normalize_case(parsed)
        except (KeyError, ValueError, TypeError) as e:
            errors.append(ValidateErrorItem(where="normalize", reason=str(e)))

    return (len(errors) == 0), errors, parsed


@router.post("/cases/validate", response_model=ValidateResponse)
def validate_case(req: ValidateRequest) -> ValidateResponse:
    """Validate a raw YAML case payload without persisting anything.

    Delegates to the same modules the GET /cases path uses (§14 R26):

    * :func:`app.storage.yaml_loader.load_case` for §4.1 schema checks
    * :func:`app.runner.case_normalizer.normalize_case` for step-kind /
      template-field checks the schema layer doesn't catch.

    Inline copies of either module's logic would be a dual-code-path
    violation (§14 R26 — the bug this endpoint exists to prevent in the
    Web 录入 path); both modules are imported and visibly called below.

    The validation logic lives in :func:`_validate_yaml_text` which is
    also reused by ``/cases/try`` — two endpoints, one validator.
    """
    ok, errors, _parsed = _validate_yaml_text(req.yaml)
    return ValidateResponse(ok=ok, errors=errors)


@router.post("/cases/try", response_model=TryResponse)
async def try_case(req: TryRequest) -> TryResponse:
    """Trial-run a YAML case in-memory without writing to DB / cases/.

    Pipeline (design.md §13.7 M3a-2 + §14 R26):

    1. Hash the raw YAML (sha256) so M3a-3.5 can later cache "this
       payload was Try-PASSED at T" and gate ``/cases/submit`` on it.
    2. Validate via :func:`_validate_yaml_text` (the same helper
       ``/cases/validate`` uses — single validator, two callers). On
       failure: short-circuit, return ok=false + validation_errors,
       step_results=[].
    3. Reuse the same runner stack POST /runs uses (§14 R26):
       :func:`normalize_case` → :func:`dsn_map_from_env` →
       :class:`SqlSessionPool` → :func:`orchestrator.run_case`.
       Inline-recreating any of these would be a dual-code-path violation.
    4. Artifacts go to a tempdir that's wiped on return — Try never
       persists.
    5. Map :class:`CaseExecutionResult` → :class:`TryResponse`, truncating
       stderr to 500 chars per step (UI-friendly preview).

    NOTE: This endpoint deliberately calls ``orchestrator.run_case`` (NOT
    ``run_suite``). ``run_suite`` persists to ``case_results`` via
    ``insert_case_result_fn`` — we don't want Try output polluting the
    production DB. ``run_case`` is the same function ``run_suite`` calls
    internally, so we're exercising the identical execution code path
    minus the DB write.
    """
    yaml_sha256 = hashlib.sha256(req.yaml.encode("utf-8")).hexdigest()

    # --- stage 1: validate (reuse the same helper /cases/validate uses) ---
    ok, validation_errors, parsed = _validate_yaml_text(req.yaml)
    if not ok or parsed is None:
        return TryResponse(
            ok=False,
            yaml_sha256=yaml_sha256,
            step_results=[],
            validation_errors=[{"where": e.where, "reason": e.reason} for e in validation_errors],
        )

    # --- stage 2: normalize + build pool + run_case (same path as POST /runs) ---
    # normalize_case is the exact transformation runs.py applies before
    # invoking the orchestrator. Inlining would violate §14 R26.
    normalized = normalize_case(parsed)
    dsn_map = dsn_map_from_env([normalized])
    pool = SqlSessionPool(dsn_map)

    case_result: orchestrator.CaseExecutionResult
    try:
        with tempfile.TemporaryDirectory() as artdir:
            # run_case is the same orchestrator entrypoint run_suite calls
            # per case — same dispatch, same R9 fold-don't-bubble semantics.
            # run_id=0 is a sentinel: artifacts land under
            # <artdir>/0/<case_id>/ which gets wiped on TemporaryDirectory exit.
            case_result = await orchestrator.run_case(
                normalized,
                run_id=0,
                artifacts_root=Path(artdir),
                jinja_context={},
                dut_hosts=set(),
                sql_pool=pool,
            )
    finally:
        # Close pooled psycopg connections so the per-Try pool doesn't
        # leak; same teardown POST /runs does in its finally block.
        try:
            await pool.close_all()
        except Exception:  # noqa: BLE001
            logger.exception("/cases/try: pool.close_all failed")

    # --- stage 3: flatten StepResult → StepResultOut (500-char stderr preview) ---
    step_results_out: list[StepResultOut] = []
    for sr in case_result.step_results:
        step_results_out.append(
            StepResultOut(
                step_id=sr.step_id,
                kind=sr.driver,
                status=sr.status.value,
                duration_ms=sr.duration_ms,
                stderr_preview=(sr.stderr[:500] if sr.stderr else None),
                error=sr.error,
            )
        )

    overall_ok = bool(step_results_out) and all(s.status == "pass" for s in step_results_out)
    return TryResponse(
        ok=overall_ok,
        yaml_sha256=yaml_sha256,
        step_results=step_results_out,
        validation_errors=[],
    )


__all__ = ["router"]
