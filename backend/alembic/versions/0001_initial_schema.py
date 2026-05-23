"""initial schema: runs / case_results / case_skip_list / system_settings / case_categories

Revision ID: 0001
Revises:
Create Date: 2026-05-23

Authoritative spec: design.md §4.2 (runs / case_results) + §4.3 (case_skip_list)
+ §4.4 (system_settings) + §4.5 (case_categories + seed two rows).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- runs (§4.2) ----
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("triggered_by", sa.Text, nullable=True),
        sa.Column("target_version", sa.Text, nullable=True),
        sa.Column("total", sa.Integer, nullable=True),
        sa.Column("passed", sa.Integer, nullable=True),
        sa.Column("failed", sa.Integer, nullable=True),
        sa.Column("skipped", sa.Integer, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
    )
    # Partial UNIQUE INDEX: at most one row with status='running' (§4.2 v0.5).
    # Use raw SQL because the partial-index WHERE clause is dialect-specific.
    op.execute(
        "CREATE UNIQUE INDEX uniq_runs_running ON runs(status) "
        "WHERE status = 'running'"
    )

    # ---- case_results (§4.2) ----
    op.create_table(
        "case_results",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("case_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=True),
        sa.Column("skip_reason", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("stdout", sa.Text, nullable=True),
        sa.Column("stderr", sa.Text, nullable=True),
        sa.Column("expect_detail", sa.Text, nullable=True),
        sa.Column("artifacts_path", sa.Text, nullable=True),
    )
    op.create_index("idx_case_results_run", "case_results", ["run_id"])
    op.create_index("idx_case_results_case", "case_results", ["case_id"])

    # ---- case_skip_list (§4.3) ----
    op.create_table(
        "case_skip_list",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("case_id", sa.Text, nullable=False),
        sa.Column("applies_to_version", sa.Text, nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("upstream_issue", sa.Text, nullable=True),
        sa.Column("until_date", sa.Date, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text, nullable=True),
    )
    op.create_index("idx_skip_case", "case_skip_list", ["case_id"])

    # ---- system_settings (§4.4) ----
    op.create_table(
        "system_settings",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("value_type", sa.Text, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Text, nullable=True),
    )

    # ---- case_categories (§4.5) ----
    op.create_table(
        "case_categories",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("id_prefix", sa.Text, nullable=False, unique=True),
        sa.Column("dir_path", sa.Text, nullable=False, unique=True),
        sa.Column("status_whitelist", sa.Text, nullable=False),
        sa.Column("default_status", sa.Text, nullable=False),
        sa.Column(
            "display_order",
            sa.Integer,
            server_default=sa.text("100"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text, nullable=True),
    )

    # Seed two categories (§4.5; new categories add a new migration).
    op.execute(
        """
        INSERT INTO case_categories (
            name, display_name, description, id_prefix, dir_path,
            status_whitelist, default_status, display_order, created_by
        ) VALUES
            (
                'bug_regression',
                'BUG 回归',
                '历史 BUG 的复现 / 修复验证用例。来源主要是飞书 LG 历史 BUG 文档。',
                'lg-bug-',
                'bug-regression',
                '["open","fixed","wontfix","stub"]',
                'open',
                10,
                'seed:0001'
            ),
            (
                'extension',
                'Extension 集成测试',
                '周边 extension（pgvector / postgis / pgcrypto / ...）的安装 + 基础功能 + 关键边界验证。',
                'lg-ext-',
                'extension',
                '["stable","experimental","deprecated","stub"]',
                'stable',
                20,
                'seed:0001'
            )
        """
    )


def downgrade() -> None:
    op.drop_table("case_categories")
    op.drop_table("system_settings")
    op.drop_index("idx_skip_case", table_name="case_skip_list")
    op.drop_table("case_skip_list")
    op.drop_index("idx_case_results_case", table_name="case_results")
    op.drop_index("idx_case_results_run", table_name="case_results")
    op.drop_table("case_results")
    op.execute("DROP INDEX IF EXISTS uniq_runs_running")
    op.drop_table("runs")
