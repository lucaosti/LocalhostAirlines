"""ARQ worker: scheduled jobs, cron schedules, Telegram polling (CLAUDE.md §6).

Empty function and cron lists are correct for M0 — the scheduler and Telegram
bot are asyncio loops added here as their own issues land (#14, #15, and the
M8 Telegram work). An ARQ worker with no jobs registered still runs, connects
to Redis, and is a real, checkable deployment target rather than a stub.
"""

import logging
from typing import Any

from arq.connections import RedisSettings
from arq.cron import cron

from infrastructure.logging import configure_logging
from infrastructure.settings import get_settings

logger = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().log_level)
    logger.info("worker startup")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker shutdown")


async def heartbeat(ctx: dict[str, Any]) -> None:
    # ARQ refuses to start a Worker with zero functions or cron_jobs
    # registered, so this earns its place as more than a placeholder: it is
    # the liveness signal picked up by the monitoring dashboard (spec §80)
    # once that exists, and every real job (#14, #15, ...) lands alongside it
    # in the same `cron_jobs` list below.
    logger.info("worker heartbeat")


class WorkerSettings:
    """Consumed by the `arq` CLI (`arq apps.worker.main.WorkerSettings`), which
    builds the actual Worker instance — not instantiated directly here.
    """

    functions: list[Any] = []
    cron_jobs: list[Any] = [cron(heartbeat, minute=set(range(0, 60, 5)))]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
