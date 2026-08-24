"""Operator authentication — persistent sessions, bcrypt (D4).

Sessions are stored in SQLite (survive restarts). Only the token hash is
stored — never the raw session token. Passwords hashed with bcrypt.
First-run: default admin operator with must_change_password=True.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models.operator import Operator, OperatorAuditLog
from .models.operator_session import OperatorSession  # noqa: F401
from .models.operator_session import (
    cleanup_expired_sessions as cleanup_expired_sessions,  # noqa: F401
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Session token cookie name
SESSION_COOKIE = "agentos_session"
# Session lifetime in seconds (7 days)
SESSION_MAX_AGE = 7 * 24 * 60 * 60


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class OperatorOut(BaseModel):
    id: str
    username: str
    must_change_password: bool


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_token(token: str) -> str:
    """Hash a session token for storage. Only the hash is persisted."""
    return hashlib.sha256(token.encode()).hexdigest()


def extract_session_token(request: Request) -> str | None:
    """Extract the session token from the cookie or Authorization: Bearer header."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        return token
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


async def get_operator_from_session(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Operator | None:
    """Extract the operator from a persisted session. Returns None if not authenticated."""
    token = extract_session_token(request)
    if not token:
        return None

    token_hash = _hash_token(token)
    result = await db.execute(
        select(OperatorSession).where(OperatorSession.token_hash == token_hash)
    )
    session = result.scalar_one_or_none()

    if session is None:
        return None

    # Check expiry (SQLite may return naive datetimes — treat as UTC)
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        return None

    # Capture operator_id before any commit/rollback — after rollback,
    # accessing session attributes triggers a lazy load that fails with
    # MissingGreenlet in async context.
    operator_id = session.operator_id

    # Update last_seen_at at most once per minute to avoid write contention on SQLite.
    # This write is non-critical — if the DB is locked, skip it rather than failing
    # the entire request (which would make the app unusable under write contention).
    # IMPORTANT: commit immediately so the write lock is released before the
    # request handler runs (which may take 30s for a chat message).
    last_seen = session.last_seen_at
    if last_seen is not None and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    if last_seen is None or (datetime.now(UTC) - last_seen).total_seconds() > 60:
        try:
            session.last_seen_at = datetime.now(UTC)
            await db.commit()
        except OperationalError:
            await db.rollback()

    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    return result.scalar_one_or_none()


async def require_operator(request: Request, db: AsyncSession = Depends(get_db)) -> Operator:
    """FastAPI dependency: require an authenticated operator."""
    operator = await get_operator_from_session(request, db)
    if operator is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return operator


async def _create_session(db: AsyncSession, operator_id: str, token: str) -> None:
    """Persist a new session token hash."""
    session = OperatorSession(
        id=str(uuid.uuid4()),
        token_hash=_hash_token(token),
        operator_id=operator_id,
        expires_at=datetime.now(UTC) + timedelta(seconds=SESSION_MAX_AGE),
        last_seen_at=datetime.now(UTC),
    )
    db.add(session)
    await db.commit()


async def _delete_session(db: AsyncSession, token: str) -> None:
    """Delete a session by token."""
    token_hash = _hash_token(token)
    result = await db.execute(
        select(OperatorSession).where(OperatorSession.token_hash == token_hash)
    )
    session = result.scalar_one_or_none()
    if session:
        await db.delete(session)
        await db.commit()


@router.post("/login")
async def login(
    data: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Operator).where(Operator.username == data.username))
    operator = result.scalar_one_or_none()

    if operator is None or not verify_password(data.password, operator.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_session_token()
    await _create_session(db, operator.id, token)

    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )

    return {
        "operator": OperatorOut(
            id=operator.id,
            username=operator.username,
            must_change_password=operator.must_change_password,
        ),
        "must_change_password": operator.must_change_password,
        "session_token": token,
    }


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    token = extract_session_token(request)
    if token:
        await _delete_session(db, token)
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "logged_out"}


@router.get("/me")
async def me(operator: Operator = Depends(require_operator)) -> OperatorOut:
    return OperatorOut(
        id=operator.id,
        username=operator.username,
        must_change_password=operator.must_change_password,
    )


@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not verify_password(data.old_password, operator.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    operator.password_hash = hash_password(data.new_password)
    operator.must_change_password = False

    # Audit log
    audit = OperatorAuditLog(
        id=str(uuid.uuid4()),
        operator_id=operator.id,
        action="change_password",
        target=operator.id,
    )
    db.add(audit)
    await db.commit()
    return {"status": "password_changed"}
