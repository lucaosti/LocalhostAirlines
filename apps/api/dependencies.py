"""FastAPI dependencies shared across routers."""

from collections.abc import AsyncGenerator

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.postgres.database import get_session
from infrastructure.redis import get_redis

__all__ = ["get_session", "get_redis_client"]


async def get_redis_client() -> AsyncGenerator[redis.Redis]:
    yield get_redis()


# Re-exported so routers import everything they need from one place.
DbSession = AsyncSession
