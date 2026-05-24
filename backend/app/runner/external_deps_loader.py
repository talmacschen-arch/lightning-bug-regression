"""External services config loader (M6-5, design.md §13.12 / §5.3.2).

Each case YAML declares `external_deps: [svc_name, ...]`. At run time we
load `external/<svc>.yml` for each declared svc and stuff it into the
Jinja context as `external.<svc>.*`, so case YAMLs can write
`{{ external.elasticsearch.host }}`, `{{ external.hive.extras.principal }}`,
etc.

File format (free-form YAML mapping):

    # external/elasticsearch.yml
    host: 192.168.195.203
    port: 9200
    extras:
      api_key: ${ES_API_KEY}   # not auto-expanded; consumer can embed if needed

Why a single module:
  - § 14 R26 (dual-code-path) — the API path (`_execute_run`) and the
    on-cluster dogfood CLI both need the same external context loaded
    the same way. Centralizing here means there's only one code site to
    audit / extend (e.g., adding env var expansion later).
  - Tests can swap the dir via the `EXTERNAL_DEPS_DIR` env var without
    monkeypatching imports.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_DIR = "external"


def _resolve_dir() -> Path:
    """Resolve external/ dir to an absolute Path.

    Honors env `EXTERNAL_DEPS_DIR` (absolute or relative to CWD). Falls
    back to repo-root `./external/`. Relative paths are interpreted
    relative to the **current working directory at process start**; the
    backend's uvicorn is normally launched from repo root, so the default
    points there.
    """
    p = Path(os.getenv("EXTERNAL_DEPS_DIR", DEFAULT_DIR))
    return p.resolve()


def _load_one_svc(svc: str, base_dir: Path) -> dict[str, Any] | None:
    """Load external/<svc>.yml. Returns None on missing/unreadable/invalid file.

    Validation:
      - top-level must be a YAML mapping (dict) — required so
        `{{ external.<svc>.<key> }}` works without per-svc shape variants
      - if file exists but parses to non-dict → warning + None (case
        author bug; surfaces visibly as undefined-variable in Jinja)
    """
    candidate = base_dir / f"{svc}.yml"
    if not candidate.is_file():
        logger.warning(
            "external_deps: %s not found (case YAML references but no config exists)",
            candidate,
        )
        return None
    try:
        raw = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        logger.warning("external_deps: failed to read %s: %s", candidate, e)
        return None
    if not isinstance(raw, dict):
        logger.warning(
            "external_deps: %s top-level must be a mapping, got %s",
            candidate,
            type(raw).__name__,
        )
        return None
    return raw


def collect_external_deps(cases: list[dict[str, Any]]) -> list[str]:
    """Union of `external_deps` across all cases, deduplicated + sorted.

    Used by callers to know what svc YAML files to load up front.
    """
    seen: set[str] = set()
    for case in cases:
        deps = case.get("external_deps") or []
        if isinstance(deps, list):
            for d in deps:
                if isinstance(d, str) and d:
                    seen.add(d)
    return sorted(seen)


def load_external_context(svc_names: list[str], *, base_dir: Path | None = None) -> dict[str, Any]:
    """Load YAML configs for the requested svc list.

    Returns `{"<svc>": {...config...}, ...}` for each svc whose
    YAML was found. Missing/unreadable svc files are warned but DO NOT
    raise — the case will surface an UndefinedError when its template
    references `external.<missing>.<key>`, which is the clearer failure
    mode (author fixes either the YAML file or the case template).

    Caller is expected to wrap the return value under the `external`
    key in the Jinja context, e.g. `jinja_context["external"] = ...`.
    """
    d = base_dir if base_dir is not None else _resolve_dir()
    out: dict[str, Any] = {}
    if not d.is_dir():
        if svc_names:
            logger.warning(
                "external_deps: dir %s does not exist; %d svc(s) will be unresolved: %s",
                d,
                len(svc_names),
                svc_names,
            )
        return out
    for svc in svc_names:
        cfg = _load_one_svc(svc, d)
        if cfg is not None:
            out[svc] = cfg
    return out
