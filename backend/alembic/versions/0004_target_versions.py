"""create target_versions registry + seed initial row

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-26

Adds a backend-managed registry of valid `target_version` values so the
frontend's "Trigger New Run -> Target version" picker can be a dropdown
sourced from this table instead of a free-text input.

Per user-decisions on this feature:
  1. POST /runs stays permissive — backend does NOT validate
     `runs.target_version` against this catalog. CLI / CI scripts still
     work with arbitrary strings; the catalog only sources the UI
     dropdown.
  2. Hard DELETE of a version row refuses if any `runs.target_version`
     row references its `name` (admin can override with ?force=true).
     Enforced in the API layer (sqlite has no FK from `runs` because
     historical free-text rows must not be coerced into FK constraints).
  3. `is_default` is "at most one" — 0 or 1 rows can have it set.
     First install can have zero. Setting one row's `is_default=true`
     clears other rows' `is_default` in the same transaction (enforced
     in `sqlite_store.add_target_version` / `update_target_version`).
  4. `display_order` is a plain integer — admin maintains by hand,
     no drag/drop server-side reordering.
  5. `name` has no format regex — any non-empty string accepted.

Seed: one row `SynxDB-4.5.0-build130` (`display_order=100`,
`is_active=1`, `is_default=1`) — matches the current value used across
the test suite / dispatches.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "target_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "display_order",
            sa.Integer(),
            server_default=sa.text("100"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uniq_target_versions_name"),
    )

    # Seed initial version — matches the SynxDB build under test today.
    op.execute(
        "INSERT INTO target_versions (name, display_order, is_active, is_default) "
        "VALUES ('SynxDB-4.5.0-build130', 100, 1, 1)"
    )


def downgrade() -> None:
    op.drop_table("target_versions")
