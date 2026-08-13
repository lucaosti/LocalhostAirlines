"""ARQ worker: scheduled jobs, cron schedules, Telegram polling (CLAUDE.md §6).

Reference data ingestion (#14) and FX rate ingestion (#15) are the first real
scheduled jobs here; the M8 Telegram bot is still an asyncio loop to be added
later, the same way.
"""

import logging
from typing import Any

from arq.connections import RedisSettings
from arq.cron import cron

from apps.worker.jobs.fx_rates import ingest_fx_rates
from apps.worker.jobs.reference_data import ingest_reference_data
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

    # Both registered as functions too, not only cron jobs, so either can be
    # triggered on demand later (e.g. an admin "refresh now" endpoint)
    # without duplicating the ingestion logic.
    functions: list[Any] = [ingest_reference_data, ingest_fx_rates]
    cron_jobs: list[Any] = [
        cron(heartbeat, minute=set(range(0, 60, 5))),
        # Monthly, matching docs/providers.md's stated refresh cadence for
        # OurAirports and OpenFlights — both change slowly.
        cron(ingest_reference_data, day=1, hour=3, minute=0),
        # ECB publishes once per TARGET business day around 16:00 CET; running
        # a bit after that covers the publication with margin. The job
        # re-fetches the whole 90-day window every time (insert-or-skip), so
        # a missed run is self-healing on the next one rather than needing a
        # backfill.
        cron(ingest_fx_rates, hour=17, minute=0),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
