"""Authentication endpoints (docs/api.md §2).

POST /auth/login, POST /auth/logout, GET /auth/session — session-based, no
bearer tokens, no client-side token storage (spec §78).
"""

import logging
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.dependencies import get_current_user
from apps.api.auth.rate_limit import RateLimited, check_login_rate_limit
from apps.api.auth.sessions import (
    SESSION_COOKIE_NAME,
    cookie_kwargs,
    create_session,
    delete_session,
)
from apps.api.dependencies import get_redis_client, get_session
from apps.api.errors import RateLimitProblem, UnauthorizedProblem
from domain.users.passwords import verify_password
from infrastructure.postgres.models import Role, User
from infrastructure.schema import UtcDatetime
from infrastructure.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: Role
    created_at: UtcDatetime


def _to_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
        created_at=user.created_at,
    )


@router.post("/login", response_model=UserResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> UserResponse:
    settings = get_settings()
    source_ip = request.client.host if request.client else "unknown"

    try:
        await check_login_rate_limit(
            redis_client,
            username=body.username,
            source_ip=source_ip,
            account_limit=settings.login_rate_limit_per_account,
            ip_limit=settings.login_rate_limit_per_ip,
            window_seconds=settings.login_rate_limit_window_seconds,
        )
    except RateLimited as exc:
        raise RateLimitProblem(
            "too many login attempts", retry_after_seconds=exc.retry_after_seconds
        ) from exc

    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    # Deliberately identical error for "no such user" and "wrong password" —
    # distinguishing them would let an attacker enumerate valid usernames.
    if user is None or not verify_password(body.password, user.password_hash):
        logger.info("failed login attempt", extra={"username": body.username})
        raise UnauthorizedProblem("invalid username or password")

    session = await create_session(db, user)
    await db.commit()

    response.set_cookie(value=str(session.id), **cookie_kwargs())
    return _to_response(user)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> None:
    raw_session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_session_id is not None:
        try:
            await delete_session(db, uuid.UUID(raw_session_id))
            await db.commit()
        except ValueError:
            pass  # malformed cookie; nothing to delete server-side

    response.delete_cookie(**cookie_kwargs())


@router.get("/session", response_model=UserResponse)
async def get_session_info(user: User = Depends(get_current_user)) -> UserResponse:
    return _to_response(user)
