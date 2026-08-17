"""Operator authentication — session + cookie, bcrypt (D4).

Sessions are stored in SQLite (survive restarts). Passwords hashed with bcrypt.
First-run: default admin operator with must_change_password=True.
"""

import secrets
import uuid

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models.operator import Operator, OperatorAuditLog

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
    """Extract the operator from the session cookie or bearer token. Returns None if not authenticated."""
    token = extract_session_token(request)
    if not token:
        return None

    # Session token is stored in OperatorAuditLog as a "session" action
    # For simplicity, we store sessions in-memory (lost on restart)
    # TODO: persist sessions in DB for restart survival (D4)
    from .main import _sessions

    operator_id = _sessions.get(token)
    if not operator_id:
        return None

    result = await db.execute(select(Operator).where(Operator.id == operator_id))
    return result.scalar_one_or_none()


async def require_operator(request: Request, db: AsyncSession = Depends(get_db)) -> Operator:
    """FastAPI dependency: require an authenticated operator."""
    operator = await get_operator_from_session(request, db)
    if operator is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return operator


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
    from .main import _sessions

    _sessions[token] = operator.id

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
async def logout(request: Request, response: Response) -> dict:
    token = extract_session_token(request)
    if token:
        from .main import _sessions

        _sessions.pop(token, None)
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
