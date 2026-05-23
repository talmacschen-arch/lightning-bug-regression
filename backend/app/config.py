"""Backend configuration.

Tier A bootstrap layer (design.md §10.2): DATABASE_URL from env, optional
~/.post_upgrade_test/env file (loaded by future caller via python-dotenv).
Tier B (system_settings table) is read at runtime by API handlers (M1+).
"""

from __future__ import annotations

import os

DEFAULT_DATABASE_URL = "sqlite:///./data/runs.db"


def get_database_url() -> str:
    """Return the DB URL, prefer DATABASE_URL env var; fall back to default."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
