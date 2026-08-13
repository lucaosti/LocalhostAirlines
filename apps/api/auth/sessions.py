"""Session lifecycle: create, look up, and touch server-side session rows.

State lives in PostgreSQL, not Redis (spec §78) — the cookie carries only the
session id (a UUID, opaque to the client), and every request resolves it back
to a UserSession row here. Losing Redis never invalidates a session.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, TypedDict

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from infrastructure.postgres.models import User, UserSession
from infrastructure.settings import get_settings

SESSION_COOKIE_NAME = "session_id"


class CookieKwargs(TypedDict):
    key: str
    httponly: bool
    samesite: Literal["lax", "strict", "none"]
    secure: bool
    path: str


async def create_session(db: DbSession, user: User) -> UserSession:
    now = datetime.now(UTC)
    session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        created_at=now,
        expires_at=now + timedelta(hours=get_settings().session_ttl_hours),
        last_seen_at=now,
    )
    db.add(session)
    await db.flush()
    return session


async def get_valid_session(db: DbSession, session_id: uuid.UUID) -> UserSession | None:
    session = await db.get(UserSession, session_id)
    if session is None:
        return None
    if session.expires_at < datetime.now(UTC):
        return None
    session.last_seen_at = datetime.now(UTC)
    return session


async def delete_session(db: DbSession, session_id: uuid.UUID) -> None:
    await db.execute(delete(UserSession).where(UserSession.id == session_id))


def cookie_kwargs() -> CookieKwargs:
    """Shared Set-Cookie attributes for both setting and clearing the cookie."""
    settings = get_settings()
    return {
        "key": SESSION_COOKIE_NAME,
        "httponly": True,
        "samesite": "strict",
        "secure": settings.cookie_secure,
        "path": "/",
    }
