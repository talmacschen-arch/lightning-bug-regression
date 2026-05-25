"""create users + auth_tokens for single-user login (v1.17)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-25

Adds authentication backbone:
  - ``users`` — single admin user seeded with bcrypt-hashed password 'admin'
  - ``auth_tokens`` — opaque bearer tokens (sha256-hashed; raw token only
    ever returned to client at login)

Replaces the ``X-Admin-Password`` env-var-based gate (PR #115/#119) with
a real login flow. ``ADMIN_PASSWORD`` env is now unused; removed from the
backend code in the same PR.

Seed behaviour: idempotent — if no row in ``users`` table at startup,
``app.api.auth.seed_admin_if_missing()`` inserts admin/admin. Existing
deployments: migration runs, seed runs once, default credentials apply.

Per design.md spec for single-user mode:
  - One user (admin) — multi-user not in scope
  - Tokens are opaque + never expire (logout to invalidate)
  - Password hashed with bcrypt (industry-standard; see also: §14 R-1
    not applicable here, no plaintext storage)
"""

from __future__ import annotations

import bcrypt
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("username", name="uniq_users_username"),
    )

    op.create_table(
        "auth_tokens",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
    )

    # Seed admin/admin if no user exists. password_changed_at stays NULL
    # so the frontend can show "请改密码" banner until user updates it.
    initial_password = b"admin"
    pw_hash = bcrypt.hashpw(initial_password, bcrypt.gensalt()).decode("utf-8")
    op.execute(
        sa.text(
            "INSERT INTO users (username, password_hash, password_changed_at) "
            "SELECT 'admin', :pw_hash, NULL "
            "WHERE NOT EXISTS (SELECT 1 FROM users)"
        ).bindparams(pw_hash=pw_hash)
    )


def downgrade() -> None:
    op.drop_table("auth_tokens")
    op.drop_table("users")
