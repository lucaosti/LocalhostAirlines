"""ARQ worker consuming the dedicated `scraping` queue only (CLAUDE.md §6).

Isolated from `worker` deliberately: headless browser work runs at bounded
concurrency with a hard memory cap, in its own container, so a stuck or heavy
scrape can never starve the ordinary job queue or crash the containers running
everything else. Empty `functions` is correct for M0 — real scraping adapters
land behind the source spikes in #2, #3 and #4.
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
    logger.info("scraper startup")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("scraper shutdown")


async def heartbeat(ctx: dict[str, Any]) -> None:
    # ARQ refuses to start a Worker with zero functions or cron_jobs
    # registered (same reasoning as apps/worker/main.py).
    logger.info("scraper heartbeat")


class WorkerSettings:
    """Consumed by the `arq` CLI (`arq apps.scraper.main.WorkerSettings`)."""

    queue_name = "scraping"
    # Headless jobs run one at a time by default (spec §24); raise only once
    # real memory behaviour under load has been observed.
    max_jobs = 1
    functions: list[Any] = []
    cron_jobs: list[Any] = [cron(heartbeat, minute=set(range(0, 60, 5)))]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
