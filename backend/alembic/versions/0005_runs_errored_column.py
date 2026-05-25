"""add `errored` column to `runs` so error verdicts aren't lost

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-26

Dogfood 2026-05-26 surfaced a missing piece of the run summary: run #25
had 17 total cases with `passed=15 / failed=0 / skipped=1` but
`15 + 0 + 1 = 16 ≠ 17` — the 17th case (`lg-xs-zombodb-partition-text-search`)
finished with status `error` (Jinja UndefinedError before main steps).
The orchestrator already counts the four statuses (pass / fail / error /
skip — `SuiteSummary.errored` exists) but the `runs` row only had columns
for three of them, so the error count was silently dropped at write
time. The PASS/FAIL `runVerdict()` on the frontend then reported the
run as PASS because `failed > 0` was false. Math didn't add up; users
noticed.

Up:
  * Add `runs.errored INTEGER NULL` (mirrors the existing
    total / passed / failed / skipped shape — `Integer NULL`, NOT
    `Integer NOT NULL DEFAULT 0`. The NULL convention preserves the
    "this run never reached aggregation" signal for crashed-mid-run rows
    which is why migration 0001 made the others nullable.)
  * Backfill from `case_results` for rows that already aggregated
    (`total IS NOT NULL`): COUNT(*) WHERE status = 'error'. Half-baked
    rows (orchestrator never reached finish_run) keep NULL.

Down:
  * Drop the column. SQLite supports `ALTER TABLE ... DROP COLUMN` since
    3.35 (released 2021-03), but we go through `batch_alter_table` so
    the table-recreate path is exercised on older SQLite versions /
    other dialects.

The companion frontend PR (PR-E) adds an `error` verdict to
`runVerdict()` and a 5th counter column to the runs list — both depend
on this column existing and showing up in the OpenAPI schema as
`errored: int | None`.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(sa.Column("errored", sa.Integer(), nullable=True))

    # Backfill from case_results for runs that have already aggregated
    # (total IS NOT NULL). Rows that never finished aggregation stay NULL,
    # matching the existing convention for passed/failed/skipped.
    op.execute(
        """
        UPDATE runs SET errored = (
            SELECT COUNT(*) FROM case_results
            WHERE case_results.run_id = runs.id
              AND case_results.status = 'error'
        )
        WHERE total IS NOT NULL
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("errored")
