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
from apps.worker.jobs.travelpayouts_search import run_travelpayouts_search
from infrastructure.logging import configure_logging

# Every model module, imported here for its side effect of registering on
# Base.metadata — same reasoning as infrastructure/postgres/alembic/env.py.
# A job module only imports the tables it directly reads or writes (e.g.
# travelpayouts_search.py imports models_search and models_reference, never
# models.py), so a cross-module ForeignKey string reference like
# Search.user_id -> "users.id" fails to resolve at flush time unless
# something in this process has already imported models.py too. Discovered
# for real running issue #44's UI against this worker: the first search ever
# enqueued failed with NoReferencedTableError, not a fixture gap.
from infrastructure.postgres import (  # noqa: F401
    models,
    models_fx,
    models_raw,
    models_reference,
    models_search,
)
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
    # run_travelpayouts_search has no cron entry: it runs only on an
    # explicit user search request (spec §29), never on a schedule — CLAUDE.md
    # §6's "no user request ever blocks on a browser" applies here too, just
    # via an API-triggered enqueue rather than a scheduled one.
    functions: list[Any] = [ingest_reference_data, ingest_fx_rates, run_travelpayouts_search]
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
