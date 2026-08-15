"""infrastructure/postgres/observations.py against real Postgres."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from domain.flight.model import Confidence, FlightOffer, FreshnessState, Segment, Slice
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models_search import CashObservation
from infrastructure.postgres.observations import write_observation


def _offer(itinerary_id: str, price_minor: int) -> FlightOffer:
    return FlightOffer(
        offer_id=f"travelpayouts:{itinerary_id}",
        itinerary_id=itinerary_id,
        source="travelpayouts",
        source_offer_id=None,
        price_minor=price_minor,
        taxes_minor=None,
        currency="EUR",
        validating_carrier=None,
        cabin=None,
        fare_brand=None,
        slices=(
            Slice(
                segments=(
                    Segment(
                        origin="MXP",
                        destination="NRT",
                        departure_utc=datetime(2026, 10, 1, 9, 15, tzinfo=UTC),
                        arrival_utc=None,
                        marketing_carrier="LH",
                        flight_number="510",
                    ),
                )
            ),
        ),
        baggage=None,
        changeability=None,
        refundability=None,
        booking_link=None,
        retrieved_at=datetime.now(UTC),
        expires_at=None,
        freshness=FreshnessState.CACHED,
        confidence=Confidence.HIGH,
    )


@pytest.mark.integration
async def test_first_write_creates_a_new_row() -> None:
    itinerary_id = f"test-{uuid.uuid4().hex}"
    now = datetime.now(UTC)
    async with session_scope() as db:
        await write_observation(
            db,
            offer=_offer(itinerary_id, 61200),
            origin="MXP",
            destination="NRT",
            depart_month="2026-10",
            retrieved_at=now,
            search_id=None,
        )

    async with session_scope() as db:
        rows = (
            (
                await db.execute(
                    select(CashObservation).where(CashObservation.itinerary_id == itinerary_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].poll_count == 1
        assert rows[0].first_seen_at == rows[0].last_seen_at == now


@pytest.mark.integration
async def test_unchanged_repoll_extends_the_same_row() -> None:
    itinerary_id = f"test-{uuid.uuid4().hex}"
    first_seen = datetime.now(UTC)
    later = first_seen + timedelta(hours=6)

    async with session_scope() as db:
        await write_observation(
            db,
            offer=_offer(itinerary_id, 61200),
            origin="MXP",
            destination="NRT",
            depart_month="2026-10",
            retrieved_at=first_seen,
            search_id=None,
        )
    async with session_scope() as db:
        await write_observation(
            db,
            offer=_offer(itinerary_id, 61200),  # same price
            origin="MXP",
            destination="NRT",
            depart_month="2026-10",
            retrieved_at=later,
            search_id=None,
        )

    async with session_scope() as db:
        rows = (
            (
                await db.execute(
                    select(CashObservation).where(CashObservation.itinerary_id == itinerary_id)
                )
            )
            .scalars()
            .all()
        )
        # Still exactly one row — this is the whole point of spec §56:
        # a route polled repeatedly must not outweigh one polled once.
        assert len(rows) == 1
        assert rows[0].poll_count == 2
        assert rows[0].first_seen_at == first_seen
        assert rows[0].last_seen_at == later


@pytest.mark.integration
async def test_price_change_opens_a_new_row() -> None:
    itinerary_id = f"test-{uuid.uuid4().hex}"
    first_seen = datetime.now(UTC)
    later = first_seen + timedelta(hours=6)

    async with session_scope() as db:
        await write_observation(
            db,
            offer=_offer(itinerary_id, 61200),
            origin="MXP",
            destination="NRT",
            depart_month="2026-10",
            retrieved_at=first_seen,
            search_id=None,
        )
    async with session_scope() as db:
        await write_observation(
            db,
            offer=_offer(itinerary_id, 65000),  # price changed
            origin="MXP",
            destination="NRT",
            depart_month="2026-10",
            retrieved_at=later,
            search_id=None,
        )

    async with session_scope() as db:
        rows = (
            (
                await db.execute(
                    select(CashObservation)
                    .where(CashObservation.itinerary_id == itinerary_id)
                    .order_by(CashObservation.first_seen_at)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        assert rows[0].price_minor == 61200
        assert rows[0].poll_count == 1
        assert rows[1].price_minor == 65000
        assert rows[1].poll_count == 1
        assert rows[1].first_seen_at == later
