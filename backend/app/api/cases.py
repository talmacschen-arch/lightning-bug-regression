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
  * `q` — case-insensitive substring match against ``id``, ``title``,
    ``description``, or ``tags`` (joined). ``description`` is read from
    the parsed YAML dict and used for matching only; it is NOT surfaced
    on :class:`CaseSummary` to keep the list payload lean for the M3a
    ``/cases/new`` duplicate-check dropdown.

CASES_ROOT env var overrides the on-disk root (default: `cases/` next to
the repo root). M1-11 uses the default; tests set it explicitly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.api.auth import get_current_user
from app.api.llm_prompt import build_system_blocks, build_user_message
from app.runner import orchestrator
from app.runner.case_normalizer import normalize_case
from app.runner.dsn_builder import dsn_map_from_env
from app.runner.external_deps_loader import collect_external_deps, load_external_context
from app.runner.sql_driver import SqlSessionPool
from app.storage import sqlite_store
from app.storage.models import CaseCategory
from app.storage.yaml_loader import CaseValidationError, CategoryMeta, load_case
from app.utils.time import as_utc

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


class CaseRecentRunOut(BaseModel):
    """One row of `GET /cases/:id/recent-runs` (M5-3 cross-page link)."""

    run_id: int
    run_status: str  # "running" / "pass" / "fail" / etc. (per `runs.status`)
    started_at: datetime
    finished_at: datetime | None = None
    case_status: str | None = None  # this case's result in that run
    duration_ms: int | None = None
    target_version: str | None = None  # run's target version (M6-D3 Tier2)


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


class SubmitRequest(BaseModel):
    yaml: str
    case_id: str  # e.g. "bug-0006-foo"
    branch_name: str  # e.g. "case/bug-0006-foo"


class SubmitResponse(BaseModel):
    pr_url: str
    pr_number: int
    branch: str


# M7 LLM-draft generation (design.md §5.4 / §13.13 v1.25 amendment)


class GenerateDraftRequest(BaseModel):
    """Request shape for ``POST /cases/generate-draft`` (M7-1)."""

    description: str
    category: str | None = None


class GenerateDraftResponse(BaseModel):
    """Response shape for ``POST /cases/generate-draft`` (M7-1).

    Note ``yaml_draft`` may be the empty string when all retries failed
    schema validation; in that case ``attempts == 3`` and
    ``validation_errors_during_retry`` is non-empty. This is a business
    state, NOT an HTTP error — the endpoint returns 200 so the frontend
    can surface the errors to the user.
    """

    yaml_draft: str
    attempts: int
    validation_errors_during_retry: list[str]


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
      * `q`: case-insensitive substring against id, title, description,
        or tags (joined). The skill at ``.claude/skills/add-test-case``
        uses this to surface near-duplicate cases when authoring a new
        one — searching only id+title misses dups where the author chose
        a different phrasing in the title but the same domain words appear
        in description/tags.

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
            # description is read straight from the parsed YAML — we
            # deliberately do NOT expose it on CaseSummary (keeps the
            # /cases/new dropdown payload lean for M3a-2); it's used
            # for q-filtering only. tags already lives on summary.
            description = ""
            if raw_dict is not None:
                desc_raw = raw_dict.get("description")
                if isinstance(desc_raw, str):
                    description = desc_raw
            tags_joined = " ".join(summary.tags) if summary.tags else ""
            hay = " ".join(
                (
                    summary.id or "",
                    summary.title or "",
                    description,
                    tags_joined,
                )
            ).lower()
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


@router.get(
    "/cases/{case_id}/recent-runs",
    response_model=list[CaseRecentRunOut],
)
def get_case_recent_runs(case_id: str, limit: int = 20) -> list[CaseRecentRunOut]:
    """List most recent runs that touched this case (M5-3 cross-page link).

    Returns up to `limit` (default 20) `(case_result, run)` rows joined
    on `case_results.run_id = runs.id`, ordered by `runs.started_at` DESC.
    Empty list when the case has never appeared in any run — that's not
    an error.

    §14 R26: delegates to ``sqlite_store.list_recent_runs_for_case`` — no
    inline SQL. Storage module is the single source of truth for the
    `case_results` table queries.
    """
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    out: list[CaseRecentRunOut] = []
    with sqlite_store.get_session() as sess:
        rows = sqlite_store.list_recent_runs_for_case(sess, case_id, limit=limit)
        for case_result, run in rows:
            out.append(
                CaseRecentRunOut(
                    run_id=run.id,
                    run_status=run.status,
                    started_at=as_utc(run.started_at),
                    finished_at=as_utc(run.finished_at),
                    case_status=case_result.status,
                    duration_ms=case_result.duration_ms,
                    target_version=run.target_version,
                )
            )
    return out


def _validate_yaml_text(
    text: str,
) -> tuple[bool, list[ValidateErrorItem], dict[str, Any] | None]:
    """Shared validation core for ``/cases/validate``, ``/cases/try``, and
    ``/cases/submit``.

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
    module's logic would be a dual-code-path violation. The submit
    endpoint (§6.2 three-gate) re-runs this exact validator before
    writing to disk for defense in depth.
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
async def try_case(req: TryRequest, request: Request) -> TryResponse:
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
    6. On overall pass, write ``yaml_sha256 → now(UTC)`` into the
       ``app.state.try_pass_cache`` so a subsequent ``/cases/submit`` with
       the same exact YAML can satisfy the §6.2 three-gate without
       re-running. Without this write the cache is dead infrastructure
       and submit's gate rejects everything.

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

    # Load external_deps context the same way POST /runs does — without this
    # Try would skip the loader and any `{{ external.<svc>.* }}` Jinja
    # reference in the case YAML raises UndefinedError → step error driver=jinja.
    # Dogfood 2026-05-26 xs-pxf-hdfs case: Try precondition-1 errored 0ms
    # because external.hadoop_simple was missing from the empty jinja_context.
    # Always include `dut` for cases that reference {{ external.dut.host }}.
    svc_names = sorted({"dut", *collect_external_deps([normalized])})
    external_ctx = load_external_context(svc_names)
    jinja_context: dict[str, Any] = {"external": external_ctx} if external_ctx else {}

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
                jinja_context=jinja_context,
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

    # --- stage 4: write to the Try-pass cache on overall pass (§13.7 M3a-3.5) ---
    # The cache gates /cases/submit; without this write submit would reject
    # every payload (cache is empty). Key is the sha256 of the raw YAML so
    # any whitespace-equivalent edit re-keys and forces a fresh Try.
    if overall_ok:
        cache: dict[str, datetime] = request.app.state.try_pass_cache
        cache[yaml_sha256] = datetime.now(UTC)

    return TryResponse(
        ok=overall_ok,
        yaml_sha256=yaml_sha256,
        step_results=step_results_out,
        validation_errors=[],
    )


# ---------------------------------------------------------------------------
# Try-pass cache + submit (§6.2 three-gate / §13.7 M3a-3 + M3a-3.5)
# ---------------------------------------------------------------------------


def _try_cache_is_fresh(
    cache: dict[str, datetime],
    yaml_sha256: str,
    max_age: timedelta = timedelta(hours=1),
) -> bool:
    """Return True iff ``yaml_sha256`` is in ``cache`` AND its timestamp
    is within ``max_age`` of *now* (UTC).

    The three-gate (§6.2) requires every submit to be backed by a recent
    successful Try of the *exact* same YAML — hashing on the raw text
    prevents whitespace-equivalent payloads from drift-bypassing the gate.
    Stale entries (> 1h) are treated as cache miss to force a re-Try after
    long edit pauses (catches the "I tried this an hour ago, then edited
    something, then forgot to re-Try" footgun).
    """
    ts = cache.get(yaml_sha256)
    if ts is None:
        return False
    # Use timezone-aware comparison; cache writers MUST store UTC datetimes.
    now = datetime.now(UTC)
    # Defensive: if a caller stored a naive datetime, attach UTC so
    # subtraction doesn't raise. The submit endpoint stores UTC; this
    # is a belt-and-suspenders guard for misuses.
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return (now - ts) <= max_age


def _resolve_repo_root() -> Path:
    """Resolve the repo root for git/gh subprocess invocations (§14 R27).

    Order of precedence:

    1. ``LBR_REPO_ROOT`` env var (operator override; must be absolute).
    2. Anchored to ``__file__``: ``cases.py`` lives at
       ``<repo>/backend/app/api/cases.py`` so 4 ``.parent`` hops reach
       ``<repo>``.

    Anchoring on ``__file__`` (rather than ``Path.cwd()``) is the §14 R27
    requirement — uvicorn's startup cwd is undefined and historically
    burned the M2 dogfood for 30 minutes.
    """
    raw = os.getenv("LBR_REPO_ROOT")
    if raw:
        return Path(raw).resolve()
    # cases.py = <repo>/backend/app/api/cases.py
    #   parent      = .../backend/app/api
    #   parent.parent = .../backend/app
    #   parent.parent.parent = .../backend
    #   parent.parent.parent.parent = <repo>
    return Path(__file__).resolve().parent.parent.parent.parent


@router.post("/cases/submit", response_model=SubmitResponse)
def submit_case(req: SubmitRequest, request: Request) -> SubmitResponse:
    """Submit a validated, recently-Try'd case YAML as a PR (§13.7 M3a-3).

    Algorithm:

    1. Hash the YAML (sha256) and check it against the Try-pass cache
       (§6.2 three-gate / §13.7 M3a-3.5). Missing/stale → 400.
    2. Re-validate via :func:`_validate_yaml_text` (defense in depth — the
       cache hit means *some* prior Try passed, but the YAML may have
       drifted since then via a different Try; re-validation closes the
       window where a stale hit is reused).
    3. Resolve `repo_root` via :func:`_resolve_repo_root` (§14 R27 — env
       override or `__file__`-anchored default, never cwd-implicit).
    4. Resolve `cases_root` via :func:`_cases_root`, look up the category's
       `dir_path` from the DB, and write the YAML to disk.
    5. DRY-RUN guard: if ``LBR_GITHUB_DRY_RUN=1``, return a fake response
       without touching git/gh — tests + dev env exercise the full path
       up to disk write without pushing to a real remote.
    6. Otherwise run the git+gh subprocess chain with explicit ``cwd=``
       (§14 R27), parse PR URL from `gh pr create` stdout, arm auto-merge.

    Failure modes are surfaced as HTTPException — never let a
    ``subprocess.CalledProcessError`` bubble as a 500 without context.
    """
    # 1. Three-gate (§6.2): the YAML must have been Try'd and passed within
    #    the last hour. yaml_sha256 keys the cache.
    yaml_sha256 = hashlib.sha256(req.yaml.encode("utf-8")).hexdigest()
    cache: dict[str, datetime] = request.app.state.try_pass_cache
    if not _try_cache_is_fresh(cache, yaml_sha256):
        raise HTTPException(
            status_code=400,
            detail="must Try and pass within last hour before submit",
        )

    # 2. Re-validate (defense in depth + cheap; the same module the GET
    #    + validate endpoints already use, §14 R26).
    validate_ok, validate_errors, parsed = _validate_yaml_text(req.yaml)
    if not validate_ok:
        raise HTTPException(
            status_code=400,
            detail={"errors": [e.model_dump() for e in validate_errors]},
        )

    # 3. ``parsed`` was returned by the validator (validation already proved
    #    it parses + is a dict + has a known category).
    if not isinstance(parsed, dict):  # pragma: no cover — guarded by validation
        raise HTTPException(status_code=400, detail="YAML parse drift after validation")
    category = parsed.get("category")
    if not isinstance(category, str) or not category:
        raise HTTPException(status_code=400, detail="category missing from YAML")

    # Look up the category's dir_path from DB (do NOT hardcode — §14 R4b).
    categories = _load_categories()
    cat_row = next((c for c in categories if c.name == category), None)
    if cat_row is None:
        raise HTTPException(
            status_code=400,
            detail=f"unknown category {category!r} (not in active case_categories)",
        )

    # 4. Resolve paths.
    repo_root = _resolve_repo_root()
    cases_root = _cases_root()
    target_dir = cases_root / cat_row.dir_path
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"{req.case_id}.yaml"
    target_file.write_text(req.yaml, encoding="utf-8")

    # 5. DRY-RUN guard (§14 R27 testing safety).
    if os.getenv("LBR_GITHUB_DRY_RUN") == "1":
        return SubmitResponse(
            pr_url="https://example.invalid/pr/dryrun",
            pr_number=0,
            branch=req.branch_name,
        )

    # 6. git + gh subprocess chain. EVERY .run() carries cwd=str(repo_root)
    #    explicitly — §14 R27 contract.
    # Compute path relative to repo_root for `git add`.
    try:
        file_relative = target_file.resolve().relative_to(repo_root.resolve())
    except ValueError:
        # CASES_ROOT pointed outside repo_root — refuse rather than
        # silently committing nothing.
        raise HTTPException(
            status_code=500,
            detail=(
                f"CASES_ROOT {cases_root} is not inside repo_root {repo_root}; "
                "set LBR_REPO_ROOT or CASES_ROOT consistently"
            ),
        ) from None

    # Transient network error signatures from gh CLI / underlying http client.
    # Hit live during M4a-1 dogfood (PR #70) when `gh pr create` got a TLS
    # handshake timeout to api.github.com — branch was already pushed, only
    # PR creation needed a retry.
    _TRANSIENT_GH_ERROR_HINTS = (
        "tls handshake timeout",
        "i/o timeout",
        "no such host",
        "connection refused",
        "connection reset",
        "request canceled while waiting",
        "context deadline exceeded",
        "temporary failure in name resolution",
        "could not resolve host",
    )

    def _is_transient_gh_error(stderr: str) -> bool:
        s = (stderr or "").lower()
        return any(hint in s for hint in _TRANSIENT_GH_ERROR_HINTS)

    def _run(step: str, argv: list[str]) -> subprocess.CompletedProcess[str]:
        """Run subprocess with retry for `gh` invocations on transient
        network errors (3 attempts, 5s back-off). git commands and other
        non-gh subprocesses fail-fast on first error (no network dependency
        once auth helper is configured)."""
        is_gh = bool(argv) and argv[0] == "gh"
        max_attempts = 3 if is_gh else 1
        last_err: subprocess.CalledProcessError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return subprocess.run(
                    argv,
                    cwd=str(repo_root),
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                last_err = e
                # Only retry on transient network errors, not logical errors
                # (auth fail, branch already exists, etc.) — those won't fix
                # themselves and burning 15s on retry is wasteful.
                if is_gh and _is_transient_gh_error(e.stderr) and attempt < max_attempts:
                    logger.warning(
                        "git/gh %s attempt %d/%d transient network error, retrying in 5s: %s",
                        step,
                        attempt,
                        max_attempts,
                        (e.stderr or "").strip()[:200],
                    )
                    time.sleep(5)
                    continue
                # Non-transient or max retries exhausted — raise with full
                # context. Branch may already be pushed; include hint so the
                # caller can manually `gh pr create` as fallback.
                detail = f"git/gh failed at {step}: stderr={e.stderr}"
                if step.startswith("gh "):
                    detail += (
                        f" (branch {req.branch_name!r} may already be pushed — "
                        f"caller can manually run: gh pr create --head {req.branch_name})"
                    )
                raise HTTPException(status_code=500, detail=detail) from e
        # Unreachable — loop returns or raises. Defensive:
        raise HTTPException(
            status_code=500,
            detail=f"git/gh failed at {step}: {last_err}",
        )

    _run("git checkout", ["git", "checkout", "-b", req.branch_name])
    _run("git add", ["git", "add", str(file_relative)])
    _run(
        "git commit",
        [
            "git",
            "commit",
            "-m",
            f"case({category}): add {req.case_id} via /cases/submit",
        ],
    )
    _run("git push", ["git", "push", "-u", "origin", req.branch_name])
    gh_proc = _run(
        "gh pr create",
        [
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            req.branch_name,
            "--title",
            f"case: {req.case_id}",
            "--body",
            "Auto-submitted via /cases/submit",
        ],
    )

    # Parse PR URL from gh's stdout (last non-empty line is the URL).
    pr_url = ""
    for line in reversed(gh_proc.stdout.splitlines()):
        candidate = line.strip()
        if candidate.startswith("https://"):
            pr_url = candidate
            break
    if not pr_url:
        raise HTTPException(
            status_code=500,
            detail=f"could not parse PR URL from gh stdout: {gh_proc.stdout!r}",
        )

    # gh PR URLs end with /<pr_number>. Parse the trailing integer.
    try:
        pr_number = int(pr_url.rstrip("/").rsplit("/", 1)[-1])
    except ValueError as e:
        raise HTTPException(
            status_code=500,
            detail=f"could not parse PR number from URL {pr_url!r}",
        ) from e

    _run(
        "gh pr merge",
        ["gh", "pr", "merge", str(pr_number), "--auto", "--squash"],
    )

    return SubmitResponse(pr_url=pr_url, pr_number=pr_number, branch=req.branch_name)


# ---------------------------------------------------------------------------
# POST /cases/generate-draft (M7-1, design.md §5.4 / §13.13 v1.25 amendment)
# ---------------------------------------------------------------------------

# Constants pulled out as module-level so tests can introspect them
# without re-deriving from prose.
_GENERATE_DRAFT_MAX_DESCRIPTION_BYTES = 8 * 1024  # 8 KB — §13.13 amendment B
_GENERATE_DRAFT_MAX_TOKENS = 2000  # §13.13 amendment B
_GENERATE_DRAFT_MODEL = "claude-opus-4-7"  # §13.13 amendment D1
_GENERATE_DRAFT_MAX_RETRIES_ON_SCHEMA_INVALID = 2  # §13.13 amendment C-1


def _categories_for_prompt() -> tuple[list[str], dict[str, list[str]]]:
    """Return (allowed_categories, status_whitelist_by_category).

    Reads active ``case_categories`` — the same source ``/admin/categories``
    uses (§14 R4b: no hardcoded category list in the prompt).
    """
    allowed: list[str] = []
    sw_map: dict[str, list[str]] = {}
    with sqlite_store.get_session() as sess:
        stmt = (
            select(CaseCategory)
            .where(CaseCategory.is_active.is_(True))
            .order_by(CaseCategory.display_order.asc())
        )
        for row in sess.scalars(stmt).all():
            allowed.append(row.name)
            try:
                wl = json.loads(row.status_whitelist)
                if isinstance(wl, list):
                    sw_map[row.name] = [str(s) for s in wl]
            except (json.JSONDecodeError, TypeError):
                # corrupted row — skip from prompt, surfaces visibly in
                # the LLM's output when it can't find the whitelist.
                continue
    return allowed, sw_map


def _strip_yaml_fences(text: str) -> str:
    """Strip markdown code-fence wrappers if the model emits them despite
    being told not to. Defensive — Anthropic models occasionally add
    ```yaml … ``` despite the explicit "no fences" instruction.

    Only strips a single leading + trailing fence block; bare YAML text
    passes through unchanged.
    """
    s = text.strip()
    if not s.startswith("```"):
        return s
    # Drop the first line (``` or ```yaml) and the trailing ``` if present.
    lines = s.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_response_text(message: object) -> str:
    """Pull the text content out of an Anthropic ``Message`` object.

    The SDK returns a ``Message`` with ``.content`` as a list of content
    blocks; the first ``TextBlock`` carries the model's reply text.
    Returns the empty string if no text block is present (shouldn't
    happen in practice but defensive).
    """
    content = getattr(message, "content", None)
    if not content:
        return ""
    for block in content:
        # TextBlock has .type=="text" and .text=<str>
        if getattr(block, "type", None) == "text":
            return getattr(block, "text", "") or ""
    return ""


@router.post(
    "/cases/generate-draft",
    response_model=GenerateDraftResponse,
    dependencies=[Depends(get_current_user)],  # §13.13 amendment A — Bearer auth required
)
def generate_draft(req: GenerateDraftRequest) -> GenerateDraftResponse:
    """Generate a §4.1-shaped YAML case draft from a free-text description.

    Design.md §5.4 + §13.13 v1.25 amendment. The endpoint is a thin
    contract layer:

    1. Validate `len(description) <= 8 KB` (413 on overflow).
    2. Resolve allowed categories + status_whitelists from
       ``case_categories`` and build the system prompt via
       :mod:`app.api.llm_prompt`.
    3. Call ``anthropic.Anthropic().messages.create`` with
       ``max_tokens=2000``, ``model="claude-opus-4-7"``.
       a. On a 5xx / 429 / timeout / network error → no retry, raise
          mapped HTTPException immediately (retrying just burns more
          quota).
       b. On a successful call whose body fails ``yaml_loader.load_case``
          + ``case_normalizer.normalize_case`` validation → retry with
          the previous validation error embedded in the next prompt's
          user-turn (capped at 2 retries, so 3 calls total).
    4. After max retries, return 200 with empty ``yaml_draft`` and the
       accumulated validation errors — that's a business state, not a
       5xx.

    §14 R26: validation goes through the same modules ``POST /cases/validate``
    uses (``_validate_yaml_text``). No inline schema check — if the
    contract drifts there, this endpoint inherits it for free.
    """
    # 1. size cap (§13.13 amendment B)
    desc_bytes = len(req.description.encode("utf-8"))
    if desc_bytes > _GENERATE_DRAFT_MAX_DESCRIPTION_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"description is {desc_bytes} bytes; max allowed is "
                f"{_GENERATE_DRAFT_MAX_DESCRIPTION_BYTES} (8 KB)"
            ),
        )

    # 2. ANTHROPIC_API_KEY presence (§13.13 amendment D3 / error map 503)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "ANTHROPIC_API_KEY env var is not set on the backend. "
                "This endpoint is unavailable until the operator configures "
                "the key (see README 'env vars 说明')."
            ),
        )

    # 3. build prompt blocks (cached prefix) + first user-turn.
    allowed_categories, status_whitelist_by_category = _categories_for_prompt()
    system_blocks = build_system_blocks(
        allowed_categories=allowed_categories,
        status_whitelist_by_category=status_whitelist_by_category,
    )

    # Import lazily so unit tests that monkeypatch the SDK at module
    # scope (or that lack the dep) still load cases.py.
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    previous_error: str | None = None
    validation_errors_during_retry: list[str] = []
    attempts = 0
    yaml_draft: str = ""

    # 4. retry loop — at most (1 + _MAX_RETRIES_ON_SCHEMA_INVALID) calls.
    for attempt in range(1, _GENERATE_DRAFT_MAX_RETRIES_ON_SCHEMA_INVALID + 2):
        attempts = attempt
        user_msg_text = build_user_message(
            description=req.description,
            category=req.category,
            previous_validation_error=previous_error,
        )

        t0 = time.monotonic()
        try:
            message = client.messages.create(
                model=_GENERATE_DRAFT_MODEL,
                max_tokens=_GENERATE_DRAFT_MAX_TOKENS,
                system=system_blocks,
                messages=[{"role": "user", "content": user_msg_text}],
            )
        except anthropic.APITimeoutError as e:
            logger.warning(
                "/cases/generate-draft: anthropic API timeout (no retry per §13.13 C-2): %s", e
            )
            raise HTTPException(status_code=504, detail="Anthropic SDK timed out") from e
        except anthropic.RateLimitError as e:
            logger.warning(
                "/cases/generate-draft: anthropic 429 rate-limit (no retry per §13.13 C-2): %s", e
            )
            raise HTTPException(status_code=429, detail="Anthropic API rate-limited") from e
        except anthropic.APIStatusError as e:
            # Catches 5xx (InternalServerError) + other non-rate-limit 4xx.
            code = getattr(e, "status_code", None)
            if isinstance(code, int) and 500 <= code < 600:
                logger.warning(
                    "/cases/generate-draft: anthropic 5xx (no retry per §13.13 C-2): %s", e
                )
                raise HTTPException(status_code=502, detail="Anthropic API 5xx") from e
            # Any other 4xx is a request-shape bug on our side; surface as 502
            # too rather than leaking the SDK's status into an HTTP-like passthrough.
            logger.warning("/cases/generate-draft: anthropic API status error: %s", e)
            raise HTTPException(status_code=502, detail=f"Anthropic API error: {e}") from e
        except anthropic.APIConnectionError as e:
            logger.warning(
                "/cases/generate-draft: anthropic network error (no retry per §13.13 C-2): %s", e
            )
            raise HTTPException(status_code=504, detail="Anthropic API connection error") from e

        latency_ms = int((time.monotonic() - t0) * 1000)

        # Extract usage stats for observability (§13.13 amendment F).
        usage = getattr(message, "usage", None)
        prompt_tokens = getattr(usage, "input_tokens", None) if usage else None
        completion_tokens = getattr(usage, "output_tokens", None) if usage else None

        raw_text = _extract_response_text(message)
        candidate_yaml = _strip_yaml_fences(raw_text)

        # Validate via the same helper /cases/validate uses (§14 R26).
        ok, errors, _parsed = _validate_yaml_text(candidate_yaml)

        # Observability line (every call gets one, success or fail).
        logger.info(
            "generate-draft attempt=%d ok=%s model=%s latency_ms=%d "
            "prompt_tokens=%s completion_tokens=%s validation_errors_count=%d",
            attempt,
            ok,
            _GENERATE_DRAFT_MODEL,
            latency_ms,
            prompt_tokens,
            completion_tokens,
            len(errors),
        )

        if ok:
            yaml_draft = candidate_yaml
            break

        # Bundle this attempt's errors into a flat string for both the
        # response payload and the next prompt's feedback injection.
        error_str = "; ".join(f"{e.where}: {e.reason}" for e in errors) or "validation failed"
        validation_errors_during_retry.append(error_str)
        previous_error = error_str
        # Loop: next attempt embeds previous_error in the prompt (the
        # wiring assertion in tests checks this string literally appears
        # in the next messages.create call's prompt body — §13.13 D).

    return GenerateDraftResponse(
        yaml_draft=yaml_draft,
        attempts=attempts,
        validation_errors_during_retry=validation_errors_during_retry,
    )


__all__ = ["router"]
