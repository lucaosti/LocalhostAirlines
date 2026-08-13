"""Login attempt rate limiting, per account and per source address (spec §78).

Fixed-window counters in Redis. Deliberately fails open: if Redis is
unreachable, login proceeds unthrottled rather than locking every user out
because a cache — not a source of truth (spec §82) — is down. Losing
brute-force protection for a few minutes is the acceptable side of that
trade-off; refusing legitimate logins because of it is not.
"""

import logging

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RateLimited(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds


async def _check_and_increment(
    client: redis.Redis, key: str, limit: int, window_seconds: int
) -> None:
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds)
        if count > limit:
            ttl = await client.ttl(key)
            raise RateLimited(retry_after_seconds=max(ttl, 1))
    except redis.RedisError:
        logger.warning("rate limiter unavailable, failing open", extra={"key_prefix": key[:20]})


async def check_login_rate_limit(
    client: redis.Redis,
    *,
    username: str,
    source_ip: str,
    account_limit: int,
    ip_limit: int,
    window_seconds: int,
) -> None:
    await _check_and_increment(
        client, f"ratelimit:login:account:{username}", account_limit, window_seconds
    )
    await _check_and_increment(client, f"ratelimit:login:ip:{source_ip}", ip_limit, window_seconds)
