"""Scheduled re-collection of previously observed routes (spec §21,
docs/adr/0005 "the historical clock starts at M2").

M2 predates M8's user-facing watchlist — there is no "watch" object yet to
spend a recurring budget against (spec §28 describes that mechanism for
persistent searches, which do not exist until M8). Until then, the honest
minimal interpretation is: keep collecting, once daily, on every distinct
route ever observed. This is deliberately simple, not a placeholder
watchlist implementation — M8 replaces "every route ever observed" with
real watch objects and per-watch budgets; it does not need this job's
internals to anticipate that shape.

Routes come from `cash_observations`, not from `searches` directly — a
search may now cover many routes at once (spec §27's full query model), so
the observation table's own denormalized origin/destination/depart_month is
the only place "one distinct route" is still a natural grouping (see
infrastructure/postgres/models_search.py's module docstring).

The per-source circuit breaker is enforced inside run_travelpayouts_search
itself, not duplicated here — this job just enqueues; a source with an open
circuit fails each enqueued search fast rather than this job trying to
pre-filter routes by source health.
"""

from __future__ import annotations

import calendar
import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models_search import CashObservation, Search, SearchState

logger = logging.getLogger(__name__)

# One fetch group covers a whole (route, month) — spec §22's batch_query,
# reused by domain/search/orchestration.py — so re-collecting one route
# never needs more than one call.
_RECOLLECTION_BUDGET_CALLS = 1


async def run_scheduled_collection(ctx: dict[str, Any]) -> None:
    async with session_scope() as db:
        # DISTINCT ON (Postgres): one row per route, the most recently
        # searched user_id as its nominal owner — see module docstring for
        # why this stand-in ownership is fine until M8's real watch objects.
        rows = (
            await db.execute(
                select(
                    CashObservation.origin,
                    CashObservation.destination,
                    CashObservation.depart_month,
                    Search.user_id,
                )
                .join(Search, Search.id == CashObservation.last_search_id)
                .distinct(
                    CashObservation.origin,
                    CashObservation.destination,
                    CashObservation.depart_month,
                )
                .order_by(
                    CashObservation.origin,
                    CashObservation.destination,
                    CashObservation.depart_month,
                    CashObservation.last_seen_at.desc(),
                )
            )
        ).all()

    if not rows:
        logger.info("scheduled collection: no previously observed routes to re-collect")
        return

    redis = ctx["redis"]
    now = datetime.now(UTC)
    enqueued = 0

    for origin, destination, depart_month, user_id in rows:
        search_id = uuid.uuid4()
        date_start, date_end = _month_bounds(depart_month)
        # Committed before enqueueing, in its own transaction: the worker
        # that picks up run_travelpayouts_search could start before this
        # function's own loop finishes, and it needs the row to already
        # exist when it does.
        async with session_scope() as db:
            db.add(
                Search(
                    id=search_id,
                    user_id=user_id,
                    origins=[{"code": origin, "weight": 0}],
                    destinations=[{"code": destination, "weight": 0}],
                    date_start=date_start,
                    date_end=date_end,
                    min_nights=0,
                    max_nights=0,
                    # Travelpayouts' calendar never varies by cabin (spec
                    # §20, docs/providers.md) — a single placeholder is
                    # enough for domain/search/expansion.py's cabins
                    # dimension to expand without multiplying by zero.
                    cabins=["economy"],
                    budget_calls=_RECOLLECTION_BUDGET_CALLS,
                    budget_spent=0,
                    space_total=0,
                    space_explored=0,
                    sources=[],
                    state=SearchState.PENDING,
                    created_at=now,
                )
            )
        await redis.enqueue_job("run_travelpayouts_search", str(search_id))
        enqueued += 1

    logger.info("scheduled collection: enqueued %d re-collection searches", enqueued)


def _month_bounds(depart_month: str) -> tuple[date, date]:
    year, month = (int(part) for part in depart_month.split("-"))
    _, last_day = calendar.monthrange(year, month)
    return date(year, month, 1), date(year, month, last_day)
