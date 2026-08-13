"""Nightly flight_price_daily aggregation job (issue #55; spec §57).

Full recompute each run: at M2's projected observation volume (~2M rows/year,
docs/adr/0007-observation-volume-estimate.md), reprocessing everything
nightly is cheap and avoids incremental-update staleness bugs — an honest
simplification for now, not a permanent architectural commitment. Percentile
queries and history (M4) read this table; detail queries read observations
directly (spec §57).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from domain.aggregation.daily_price import ObservationPeriod, compute_daily_aggregates
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models_aggregates import FlightPriceDaily
from infrastructure.postgres.models_search import CashObservation

logger = logging.getLogger(__name__)


async def compute_flight_price_daily(ctx: dict[str, Any]) -> None:
    async with session_scope() as db:
        rows = (await db.execute(select(CashObservation))).scalars().all()

    periods = [
        ObservationPeriod(
            route=f"{row.origin}-{row.destination}",
            # offer["cabin"]/["fare_brand"] are the FlightOffer-level fields
            # (domain/flight/serialization.py), currently always None for
            # Travelpayouts (docs/providers.md) — "" is this table's
            # not-stated sentinel (models_aggregates.py), not the same
            # three-state absence/unavailability spec P3 governs for
            # user-facing values.
            cabin=row.offer.get("cabin") or "",
            fare_family=row.offer.get("fare_brand") or "",
            source=row.source,
            currency=row.currency,
            price_minor=row.price_minor,
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
        )
        for row in rows
    ]
    aggregates = compute_daily_aggregates(periods)

    now = datetime.now(UTC)
    async with session_scope() as db:
        # Full replace, not a diff — see module docstring on why recompute
        # is cheap enough to make an incremental update unnecessary for now.
        await db.execute(delete(FlightPriceDaily))
        for agg in aggregates:
            db.add(
                FlightPriceDaily(
                    id=uuid.uuid4(),
                    aggregate_date=agg.key.aggregate_date,
                    route=agg.key.route,
                    cabin=agg.key.cabin,
                    fare_family=agg.key.fare_family,
                    source=agg.key.source,
                    currency=agg.key.currency,
                    minimum_price_minor=agg.minimum_price_minor,
                    median_price_minor=agg.median_price_minor,
                    maximum_price_minor=agg.maximum_price_minor,
                    observation_count=agg.observation_count,
                    computed_at=now,
                )
            )

    logger.info(
        "flight_price_daily: recomputed %d aggregate rows from %d observations",
        len(aggregates),
        len(periods),
    )
