"""FastAPI dependencies shared across routers."""

from collections.abc import AsyncGenerator

import redis.asyncio as redis
from arq import ArqRedis
from arq.connections import RedisSettings, create_pool
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.postgres.database import get_session
from infrastructure.redis import get_redis
from infrastructure.settings import get_settings

__all__ = ["get_session", "get_redis_client", "get_arq_pool"]


async def get_redis_client() -> AsyncGenerator[redis.Redis]:
    yield get_redis()


_arq_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    """One ARQ connection pool per process, created lazily on first use.

    Distinct from `get_redis()` (a plain cache/session client): ARQ owns its
    own connection semantics for job dispatch, and mixing the two clients
    would couple this dependency to ARQ's internals leaking elsewhere.
    """
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _arq_pool


# Re-exported so routers import everything they need from one place.
DbSession = AsyncSession
