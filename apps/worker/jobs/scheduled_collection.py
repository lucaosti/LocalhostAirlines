"""Scheduled re-collection of previously searched routes (spec §21,
docs/adr/0005 "the historical clock starts at M2").

M2 predates M8's user-facing watchlist — there is no "watch" object yet to
spend a recurring budget against (spec §28 describes that mechanism for
persistent searches, which do not exist until M8). Until then, the honest
minimal interpretation is: keep collecting, once daily, on every distinct
route a user has ever searched. This is deliberately simple, not a
placeholder watchlist implementation — M8 replaces "every route ever
searched" with real watch objects and per-watch budgets; it does not need
this job's internals to anticipate that shape.

The per-source circuit breaker is enforced inside run_travelpayouts_search
itself, not duplicated here — this job just
enqueues; a source with an open circuit fails each enqueued search fast
rather than this job trying to pre-filter routes by source health.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models_search import Search, SearchState

logger = logging.getLogger(__name__)


async def run_scheduled_collection(ctx: dict[str, Any]) -> None:
    async with session_scope() as db:
        # DISTINCT ON (Postgres): one row per route, the most recently
        # searched user_id as its nominal owner — see module docstring for
        # why this stand-in ownership is fine until M8's real watch objects.
        rows = (
            await db.execute(
                select(Search.origin, Search.destination, Search.depart_month, Search.user_id)
                .distinct(Search.origin, Search.destination, Search.depart_month)
                .order_by(
                    Search.origin,
                    Search.destination,
                    Search.depart_month,
                    Search.created_at.desc(),
                )
            )
        ).all()

    if not rows:
        logger.info("scheduled collection: no previously searched routes to re-collect")
        return

    redis = ctx["redis"]
    now = datetime.now(UTC)
    enqueued = 0

    for origin, destination, depart_month, user_id in rows:
        search_id = uuid.uuid4()
        # Committed before enqueueing, in its own transaction: the worker
        # that picks up run_travelpayouts_search could start before this
        # function's own loop finishes, and it needs the row to already
        # exist when it does.
        async with session_scope() as db:
            db.add(
                Search(
                    id=search_id,
                    user_id=user_id,
                    origin=origin,
                    destination=destination,
                    depart_month=depart_month,
                    state=SearchState.PENDING,
                    created_at=now,
                )
            )
        await redis.enqueue_job("run_travelpayouts_search", str(search_id))
        enqueued += 1

    logger.info("scheduled collection: enqueued %d re-collection searches", enqueued)
