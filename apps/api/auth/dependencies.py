"""FastAPI dependencies for authenticated and role-gated routes."""

import uuid

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.sessions import SESSION_COOKIE_NAME, get_valid_session
from apps.api.dependencies import get_session
from apps.api.errors import ForbiddenProblem, UnauthorizedProblem
from infrastructure.postgres.models import Role, User


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> User:
    raw_session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_session_id is None:
        raise UnauthorizedProblem("no session cookie presented")

    try:
        session_id = uuid.UUID(raw_session_id)
    except ValueError as exc:
        raise UnauthorizedProblem("malformed session cookie") from exc

    session = await get_valid_session(db, session_id)
    if session is None:
        raise UnauthorizedProblem("session missing or expired")

    user = await db.get(User, session.user_id)
    if user is None:
        # The user was deleted after the session was created. Treat exactly
        # like any other invalid session rather than a 500.
        raise UnauthorizedProblem("session missing or expired")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.ADMIN:
        raise ForbiddenProblem("admin role required")
    return user
