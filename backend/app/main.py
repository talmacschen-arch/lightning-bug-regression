"""FastAPI application entry point (design.md §5.2 / M1-10).

Mounts the four routers (runs / cases / admin / healthz), wires the
storage engine in a lifespan handler, and registers permissive CORS for
M1 dev. M2 frontend will tighten origins.

Run locally with:

    uv run uvicorn app.main:app --reload

OpenAPI is auto-generated at `/openapi.json`; Swagger UI at `/docs`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin as admin_router
from app.api import cases as cases_router
from app.api import healthz as healthz_router
from app.api import runs as runs_router
from app.config import get_database_url
from app.storage import sqlite_store

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize the SQLite engine before the first request.

    `init_engine` is idempotent, so re-calling it on hot-reload is safe.
    Tests that need a custom engine wire it directly via
    `sqlite_store._engine` / `_SessionLocal` and skip this lifespan by
    using `TestClient(app)` after they've patched the module.
    """
    db_url = get_database_url()
    logger.info("initializing storage engine: %s", db_url)
    sqlite_store.init_engine(db_url)
    yield


app = FastAPI(
    title="Lightning Bug Regression",
    description=("HTTP API for the post-upgrade regression test runner (design.md §5.2)."),
    version="0.1.0",
    lifespan=lifespan,
)


# CORS — permissive for M1 dev. Tightened by M2 frontend dispatch.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(healthz_router.router)
app.include_router(runs_router.router)
app.include_router(cases_router.router)
app.include_router(admin_router.router)


__all__ = ["app"]
