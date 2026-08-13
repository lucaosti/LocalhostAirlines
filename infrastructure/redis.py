"""Redis client factory.

Redis is a cache and a job queue, never a source of truth (spec §82). Sessions
live in PostgreSQL specifically so that this client being unreachable degrades
the application rather than logging everyone out.
"""

from functools import lru_cache

import redis.asyncio as redis

from infrastructure.settings import get_settings


@lru_cache
def get_redis() -> redis.Redis:
    client: redis.Redis = redis.from_url(get_settings().redis_url, decode_responses=True)
    return client
