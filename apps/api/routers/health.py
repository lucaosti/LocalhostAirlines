"""Health endpoint.

Reports PostgreSQL and Redis reachability separately, because they are not
equally important: only PostgreSQL is a hard dependency (spec §82). Losing Redis
degrades the application — sessions and history stay readable, jobs queue until
it returns — so the endpoint reports that as `degraded`, not `error`.

Deliberately un-versioned (`/health`, not `/api/v1/health`): it is infrastructure
plumbing for load balancers and container orchestration, not a resource in the
domain contract that docs/api.md governs.
"""

import time
from typing import Literal

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_redis_client, get_session

router = APIRouter()

CheckStatus = Literal["ok", "error"]
OverallStatus = Literal["ok", "degraded", "error"]


class Check(BaseModel):
    status: CheckStatus
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: OverallStatus
    checks: dict[str, Check]


async def _check_database(session: AsyncSession) -> Check:
    start = time.monotonic()
    try:
        await session.execute(text("SELECT 1"))
        return Check(status="ok", latency_ms=round((time.monotonic() - start) * 1000, 2))
    except Exception as exc:  # noqa: BLE001 — a health check must not raise
        return Check(status="error", error=str(exc))


async def _check_redis(client: redis.Redis) -> Check:
    start = time.monotonic()
    try:
        await client.ping()
        return Check(status="ok", latency_ms=round((time.monotonic() - start) * 1000, 2))
    except Exception as exc:  # noqa: BLE001
        return Check(status="error", error=str(exc))


@router.get("/health", response_model=HealthResponse)
async def health(
    session: AsyncSession = Depends(get_session),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> HealthResponse:
    database = await _check_database(session)
    cache = await _check_redis(redis_client)

    if database.status == "error":
        overall: OverallStatus = "error"
    elif cache.status == "error":
        overall = "degraded"
    else:
        overall = "ok"

    return HealthResponse(status=overall, checks={"database": database, "redis": cache})
