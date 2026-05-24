"""SqlSessionPool DSN map builder — shared by dogfood CLI + API path.

Walks normalized cases, collects every distinct `on:` session name (which
encodes the target database name via `default:<db>` convention from
`case_normalizer._normalize_one_step`), and emits the libpq DSN string
SqlSessionPool needs.

This module exists for the same reason as case_normalizer.py: the M1
dogfood script had its own inline `build_dsn_map`, the API path didn't
build any DSN map at all, and the result was that POST /runs invoked
orchestrator.run_suite without a sql_pool → every SQL step errored with
"sql step requires sql_pool to be configured" (orchestrator.py
_execute_one_step early-return). M2 dogfood + followup, 2026-05-24.
"""

from __future__ import annotations

import os
from typing import Any

# Defaults align with §3.1 cluster-access convention: mdw box runs the
# coordinator + the API server on localhost; psql works as `gpadmin` via
# pg_hba `trust` over TCP (no password needed for local→local).
_DEFAULT_PGHOST = "127.0.0.1"
_DEFAULT_PGPORT = 5432
_DEFAULT_PGUSER = "gpadmin"
# 2026-05-24 user decision: default DB = gpadmin (owner-home on Synxdb/
# Cloudberry, not "postgres" PG-convention). See memory
# default-database-gpadmin and README "起本机 dev 服务".
_DEFAULT_PGDATABASE = "gpadmin"


def build_dsn_map(
    cases: list[dict[str, Any]],
    *,
    pghost: str,
    pgport: int,
    pguser: str,
    pgdatabase: str,
) -> dict[str, str]:
    """Walk normalized cases, return {session_name: libpq DSN}.

    Session names are emitted by `case_normalizer._normalize_one_step`:
    - `default` (no per-step database override) → pgdatabase
    - `default:<dbname>` (per-step `database:` override) → <dbname>

    `default` and `default:<pgdatabase>` are always present (in case a
    case skipped normalization or used the bare `default` literal).
    """
    sessions: set[str] = {"default", f"default:{pgdatabase}"}
    for case in cases:
        for bucket in ("setup", "steps", "teardown"):
            for step in case.get(bucket) or []:
                on = step.get("on")
                if on:
                    sessions.add(str(on))

    dsn_map: dict[str, str] = {}
    for session in sessions:
        if session == "default":
            dbname = pgdatabase
        elif session.startswith("default:"):
            dbname = session[len("default:") :]
        else:
            # Custom session name — fall back to pgdatabase. (Today only
            # `default` / `default:<db>` shapes are produced by normalize_case.)
            dbname = pgdatabase
        dsn_map[session] = f"postgresql://{pguser}@{pghost}:{pgport}/{dbname}"
    return dsn_map


def dsn_map_from_env(cases: list[dict[str, Any]]) -> dict[str, str]:
    """Convenience wrapper for API path: read libpq-style env vars + build.

    Env vars (PGHOST, PGPORT, PGUSER, PGDATABASE) match psycopg / psql
    conventions so dev/admin can override without touching code:

        export PGHOST=synxdb-1234 PGUSER=gpadmin PGDATABASE=postgres
        # then uvicorn picks them up

    Defaults are tuned for the M0 single-node "API on mdw" deployment
    (§3.1): localhost + gpadmin + postgres. PGPASSWORD or ~/.pgpass
    handles auth out-of-band per psycopg / libpq standard.
    """
    return build_dsn_map(
        cases,
        pghost=os.getenv("PGHOST", _DEFAULT_PGHOST),
        pgport=int(os.getenv("PGPORT", str(_DEFAULT_PGPORT))),
        pguser=os.getenv("PGUSER", _DEFAULT_PGUSER),
        pgdatabase=os.getenv("PGDATABASE", _DEFAULT_PGDATABASE),
    )
