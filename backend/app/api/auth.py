"""Single-user authentication module (v1.17).

API surface:
  POST /auth/login           — {username, password} → {token, must_change_password}
  POST /auth/logout          — invalidate current bearer token
  GET  /auth/me              — return {username, must_change_password} for the
                                current bearer token, or 401 if absent/invalid
  POST /auth/change-password — {current_password, new_password} → 200/401

Auth dependency:
  ``Depends(get_current_user)`` reads Authorization: Bearer <token>, hashes
  it, looks up auth_tokens row; raises 401 on miss. Use on every mutating
  endpoint (skip-list, delete-case, change-password itself).

Token storage:
  Client gets opaque token string at login (``secrets.token_urlsafe(32)``).
  Backend persists only sha256(token) — a DB dump doesn't enable session
  replay. Multiple rows per user OK (multi-device login).

Replaces ``ADMIN_PASSWORD`` env / ``X-Admin-Password`` header (PR #115).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime
from typing import Annotated

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.storage import sqlite_store
from app.storage.models import AuthToken, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"
TOKEN_BYTES = 32


# ---------------------------------------------------------------------------
# password + token helpers
# ---------------------------------------------------------------------------


def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_token(token: str) -> str:
    """Hash the opaque token before storing — DB dump doesn't enable replay."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


# ---------------------------------------------------------------------------
# seed (idempotent)
# ---------------------------------------------------------------------------


def seed_admin_if_missing() -> None:
    """Insert admin/admin if no user exists. Called at backend startup.

    Idempotent: skips if users table has any row. password_changed_at
    stays NULL so the frontend can flag "请改密码".
    """
    try:
        with sqlite_store.get_session() as sess:
            existing = sess.scalar(select(User).limit(1))
            if existing is not None:
                return
            sess.add(
                User(
                    username=DEFAULT_USERNAME,
                    password_hash=hash_password(DEFAULT_PASSWORD),
                    password_changed_at=None,
                )
            )
            sess.commit()
            logger.info("seeded default admin user (admin/admin) — change password ASAP")
    except Exception:  # noqa: BLE001 — startup; log + continue (alembic migration may not yet have run)
        logger.exception("seed_admin_if_missing failed (likely pre-migration); continuing")


# ---------------------------------------------------------------------------
# auth dependency
# ---------------------------------------------------------------------------


def get_current_user(
    authorization: str | None = Header(default=None),
) -> User:
    """FastAPI dependency: resolve bearer token → User, 401 on miss.

    Use on every mutating endpoint:
        @router.post(..., dependencies=[Depends(get_current_user)])

    Or to get the user object:
        def endpoint(user: User = Depends(get_current_user)): ...
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or malformed Authorization header",
        )
    token = authorization[len("bearer ") :].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="empty bearer token")
    t_hash = hash_token(token)
    with sqlite_store.get_session() as sess:
        row = sess.get(AuthToken, t_hash)
        if row is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
        # touch last_used_at — helps spot dead tokens if we ever want cleanup
        row.last_used_at = datetime.now(UTC)
        user = sess.get(User, row.user_id)
        if user is None:
            # token outlived its user (shouldn't happen with CASCADE FK)
            sess.delete(row)
            sess.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user gone")
        sess.commit()
        return user


# ---------------------------------------------------------------------------
# Pydantic shapes
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    must_change_password: bool


class MeResponse(BaseModel):
    username: str
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    """Validate credentials, mint a new token, return it.

    No rate limiting — single-user tool, attacker would need to brute-force
    bcrypt remote (slow by design). If exposed publicly later, add a
    middleware-level rate limit.
    """
    if not payload.username or not payload.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing credentials")
    with sqlite_store.get_session() as sess:
        user = sess.scalar(select(User).where(User.username == payload.username))
        if user is None or not verify_password(payload.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid username or password",
            )
        token = generate_token()
        sess.add(AuthToken(token_hash=hash_token(token), user_id=user.id))
        sess.commit()
        return LoginResponse(
            token=token,
            username=user.username,
            must_change_password=user.password_changed_at is None,
        )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(authorization: str | None = Header(default=None)) -> None:
    """Invalidate current token (idempotent: missing header → still 204).

    Doesn't use get_current_user dependency — even invalid/missing tokens
    should not error out logout (we want clients to be able to "clear"
    state reliably).
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return
    token = authorization[len("bearer ") :].strip()
    if not token:
        return
    t_hash = hash_token(token)
    with sqlite_store.get_session() as sess:
        row = sess.get(AuthToken, t_hash)
        if row is not None:
            sess.delete(row)
            sess.commit()


CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser) -> MeResponse:
    """Used by frontend to bootstrap state on page load + decide whether
    to show the "please change password" banner."""
    return MeResponse(
        username=user.username,
        must_change_password=user.password_changed_at is None,
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    user: CurrentUser,
) -> None:
    """Verify current_password → update password_hash + password_changed_at.

    Does NOT invalidate other active tokens (simple; user can manually
    logout other devices if needed). Frontend banner ("please change
    password") disappears once password_changed_at is set.

    Minimum new password length = 4 chars (lax; single-user tool, user
    knows their own strength preference).
    """
    if len(payload.new_password) < 4:
        raise HTTPException(status_code=400, detail="new password must be at least 4 characters")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="new password must differ from current")
    with sqlite_store.get_session() as sess:
        u = sess.get(User, user.id)
        if u is None or not verify_password(payload.current_password, u.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="current password is wrong",
            )
        u.password_hash = hash_password(payload.new_password)
        u.password_changed_at = datetime.now(UTC)
        sess.commit()


__all__ = ["router", "get_current_user", "seed_admin_if_missing", "CurrentUser"]
