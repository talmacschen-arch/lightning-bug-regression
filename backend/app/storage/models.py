"""SQLAlchemy 2.0 declarative models for the five business tables.

Source of truth: `backend/alembic/versions/0001_initial_schema.py` and
design.md §4.2 / §4.3 / §4.4 / §4.5. Where the M1-3 dispatch spec disagreed
with the alembic migration (newer dispatch wording assumed extra fields like
`suite_id`, `server_commit`, `step_results` JSON, `notes`, `expires_at`),
**the alembic migration wins** — it is the schema that actually ships, and
the dispatch explicitly instructed: "if any disagreement, follow alembic
migration as the source of truth."

Columns mirror the migration 1:1. Indexes and the partial-unique
`uniq_runs_running` are also declared on the model so that test-time
`Base.metadata.create_all(engine)` produces a schema indistinguishable from
`alembic upgrade head` (verified by `test_metadata_matches_alembic_schema`).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all storage models."""


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        # Partial UNIQUE INDEX: at most one row with status='running'
        # (design.md §4.2 v0.5). SQLite supports partial indexes via the
        # WHERE clause; SQLAlchemy emits this via sqlite_where.
        Index(
            "uniq_runs_running",
            "status",
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
    )


class CaseResult(Base):
    __tablename__ = "case_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("runs.id"), nullable=False)
    case_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    expect_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifacts_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_case_results_run", "run_id"),
        Index("idx_case_results_case", "case_id"),
    )


class CaseSkipList(Base):
    __tablename__ = "case_skip_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(Text, nullable=False)
    applies_to_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    upstream_issue: Mapped[str | None] = mapped_column(Text, nullable=True)
    until_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("idx_skip_case", "case_id"),)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_by: Mapped[str | None] = mapped_column(Text, nullable=True)


class CaseCategory(Base):
    __tablename__ = "case_categories"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    id_prefix: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    dir_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status_whitelist: Mapped[str] = mapped_column(Text, nullable=False)
    default_status: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(
        Integer,
        server_default=text("100"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("1"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Authentication (v1.17 — single-user login module)
# ---------------------------------------------------------------------------


class User(Base):
    """One user row. Project ships with single admin user seeded at
    startup; multi-user not in scope. Password stored as bcrypt hash."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    # NULL = never changed (admin/admin still in effect). Frontend uses
    # this to show "请改密码" red banner until user updates it once.
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuthToken(Base):
    """Opaque bearer tokens for active sessions.

    Token stored as sha256 hash (not raw), so a DB dump doesn't enable
    immediate session replay. Token has no expiry — only invalidated by
    explicit logout (DELETE) or `change-password` flow. Multiple rows
    per user OK (multi-device login).
    """

    __tablename__ = "auth_tokens"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
