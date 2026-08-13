"""apps/worker/jobs/daily_aggregates.py against real Postgres (issue #55)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from apps.worker.jobs.daily_aggregates import compute_flight_price_daily
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models_aggregates import FlightPriceDaily
from infrastructure.postgres.models_search import CashObservation

MINIMAL_OFFER = {
    "offer_id": "x",
    "itinerary_id": "x",
    "source": "travelpayouts",
    "source_offer_id": None,
    "price_minor": 0,
    "taxes_minor": None,
    "currency": "EUR",
    "validating_carrier": None,
    "cabin": None,
    "fare_brand": None,
    "slices": [],
    "baggage": None,
    "changeability": None,
    "refundability": None,
    "booking_link": None,
    "retrieved_at": "2026-08-13T12:00:00+00:00",
    "expires_at": None,
    "freshness": "cached",
    "confidence": "high",
    "limitations": [],
}


async def _seed_observation(
    route_tag: str, price_minor: int, first_seen: datetime, last_seen: datetime
) -> None:
    async with session_scope() as db:
        db.add(
            CashObservation(
                id=uuid.uuid4(),
                itinerary_id=f"test-{uuid.uuid4().hex}",
                source="travelpayouts",
                origin=route_tag,
                destination="NRT",
                depart_month="2026-10",
                price_minor=price_minor,
                currency="EUR",
                freshness="cached",
                confidence="high",
                offer={**MINIMAL_OFFER, "price_minor": price_minor},
                first_seen_at=first_seen,
                last_seen_at=last_seen,
                poll_count=1,
                last_search_id=None,
            )
        )


@pytest.mark.integration
async def test_job_recomputes_aggregates_from_observations() -> None:
    tag = f"Z{uuid.uuid4().hex[:2].upper()}"
    day = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    await _seed_observation(tag, 60000, day, day)
    await _seed_observation(tag, 70000, day, day)

    await compute_flight_price_daily({})

    async with session_scope() as db:
        rows = (
            (
                await db.execute(
                    select(FlightPriceDaily).where(FlightPriceDaily.route == f"{tag}-NRT")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].minimum_price_minor == 60000
        assert rows[0].maximum_price_minor == 70000
        assert rows[0].observation_count == 2
        assert rows[0].aggregate_date == day.date()


@pytest.mark.integration
async def test_job_is_a_full_replace_not_an_accumulation() -> None:
    tag = f"Z{uuid.uuid4().hex[:2].upper()}"
    day = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    await _seed_observation(tag, 60000, day, day)

    await compute_flight_price_daily({})
    await compute_flight_price_daily({})  # run twice — must not double-count

    async with session_scope() as db:
        rows = (
            (
                await db.execute(
                    select(FlightPriceDaily).where(FlightPriceDaily.route == f"{tag}-NRT")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].observation_count == 1


@pytest.mark.integration
async def test_multi_day_period_covers_every_intersected_day() -> None:
    tag = f"Z{uuid.uuid4().hex[:2].upper()}"
    first_seen = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    last_seen = first_seen + timedelta(days=2)
    await _seed_observation(tag, 60000, first_seen, last_seen)

    await compute_flight_price_daily({})

    async with session_scope() as db:
        rows = (
            (
                await db.execute(
                    select(FlightPriceDaily)
                    .where(FlightPriceDaily.route == f"{tag}-NRT")
                    .order_by(FlightPriceDaily.aggregate_date)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 3
        assert [r.aggregate_date for r in rows] == [
            first_seen.date(),
            first_seen.date() + timedelta(days=1),
            first_seen.date() + timedelta(days=2),
        ]
