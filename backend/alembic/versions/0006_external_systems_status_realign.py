"""external_systems status_whitelist 改造：加入 BUG 修复维度

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-26

v1.10 落地 external_systems 类别时 status_whitelist 只覆盖了"环境就绪
度"一个维度 (stable / awaiting_env / deprecated / stub)，与项目主目的
"BUG 回归测试"语义不符——external_systems 与 extension 拆分是因为依赖
**外部服务进程**，但本质仍是 BUG 复现 case (PXF / Hive / Datalake FDW
/ Zombodb 这类外部组件触发的 PG/Greenplum BUG)。BUG 修复状态本应跟
``bug_regression`` 一致用 open / fixed / wontfix / stub 表达。

本 migration 把 ``external_systems`` 的 ``status_whitelist`` 从

    [stable, awaiting_env, deprecated, stub]

改为

    [open, fixed, wontfix, stub, awaiting_env]

``default_status`` 从 ``awaiting_env`` 改为 ``open`` (与 bug_regression
对齐——新 case 默认 "BUG 未修复" 状态)。

``awaiting_env`` **保留** 作为辅助 lifecycle 值，表达"外部服务尚未部署
所以暂时无法跑"——这与 BUG 修复状态正交，不应与 open 混淆。``stable``
和 ``deprecated`` 在历史 case (lg-xs-pxf-hdfs-order-by-writable /
lg-xs-pxf-hive-fdw-encoding-utf8 / lg-xs-zombodb-partition-text-search)
里曾被使用，本 migration 同时把 3 个旧 case YAML 的 ``status: stable``
改为对应的 ``fixed`` / ``open``——3 个 case 都是 BUG 复现性质，stable
在新白名单不再合法。

Up:
  * UPDATE case_categories SET status_whitelist=..., default_status=...,
    description=... WHERE name='external_systems'

Down:
  * 反向 UPDATE 回 v1.10 的 [stable, awaiting_env, deprecated, stub]
    + default=awaiting_env + 原 description。注意：downgrade 后 3 个
    现存 case YAML 的 status (fixed/open) 与白名单不符，loader 会拒绝
    加载——需要同时 git revert 配套的 case YAML 改动。

Authoritative spec: design.md §16.4 (v1.21 修订) +
docs/plans/external-systems-category.md §9 (2026-05-26 status 语义补强)。
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_WHITELIST = '["open","fixed","wontfix","stub","awaiting_env"]'
_OLD_WHITELIST = '["stable","awaiting_env","deprecated","stub"]'

_NEW_DESCRIPTION = (
    "依赖外部组件（datalake_fdw / hive_connector / PXF / zombodb 等）的"
    "集成测试用例。status 主维度为 BUG 修复状态 (open/fixed/wontfix/stub，"
    "与 bug_regression 对齐)；awaiting_env 作为辅助 lifecycle 值，表达"
    "外部服务尚未部署的占位状态——与 BUG 修复状态正交，不混用。"
)

_OLD_DESCRIPTION = (
    "依赖外部组件（datalake_fdw / hive_connector / PXF / zombodb 等）的"
    "集成测试用例。与 extension 不同：外部服务进程必须可达 + 凭据/网络/"
    "profile.d 已就绪，case 才能跑；环境未就绪时 status 应为 awaiting_env。"
)


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE case_categories
        SET status_whitelist = '{_NEW_WHITELIST}',
            default_status   = 'open',
            description      = '{_NEW_DESCRIPTION}'
        WHERE name = 'external_systems'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE case_categories
        SET status_whitelist = '{_OLD_WHITELIST}',
            default_status   = 'awaiting_env',
            description      = '{_OLD_DESCRIPTION}'
        WHERE name = 'external_systems'
        """
    )
