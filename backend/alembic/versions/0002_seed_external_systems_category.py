"""seed third case category: external_systems

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-24

Adds a third row to ``case_categories`` (§4.5) for cases that depend on
**external service components** outside PG itself — Hive metastore, HDFS,
Kerberos KDC, Elasticsearch, object storage, etc. — typified by
``datalake_fdw`` / ``hive_connector`` / ``PXF`` / ``zombodb``.

Distinct from ``extension`` (which assumes ``CREATE EXTENSION foo`` is
self-contained), an ``external_systems`` case is only runnable when the
external services it lists in ``external_deps`` are reachable + credentials
+ profile.d are wired through. Default ``status: awaiting_env`` makes this
explicit — cases land green-fielded with the YAML written but the cluster
environment not yet provisioned; flip to ``stable`` once the target
cluster proves it can run them.

Authoritative spec: docs/plans/external-systems-category.md
(written 2026-05-24, user-approved decisions: dir=external-systems,
id_prefix=lg-xs-, status_whitelist=[stable, awaiting_env, deprecated,
stub], default=awaiting_env, display_order=30).

Per design.md §4.5 + §14 R4b, adding this row is the ONLY required code
change — the API / loader / orchestrator / frontend are all data-driven
off ``case_categories``.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO case_categories (
            name, display_name, description, id_prefix, dir_path,
            status_whitelist, default_status, display_order, created_by
        ) VALUES
            (
                'external_systems',
                '外部系统集成测试',
                '依赖外部组件（datalake_fdw / hive_connector / PXF / zombodb 等）的集成测试用例。与 extension 不同：外部服务进程必须可达 + 凭据/网络/profile.d 已就绪，case 才能跑；环境未就绪时 status 应为 awaiting_env。',
                'lg-xs-',
                'external-systems',
                '["stable","awaiting_env","deprecated","stub"]',
                'awaiting_env',
                30,
                'seed:0002'
            )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM case_categories WHERE name = 'external_systems'")
