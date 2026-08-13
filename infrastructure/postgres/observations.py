"""Observation writes with material-change dedup (issue #54; spec §56).

Bridges the pure decision in domain/collection/material_change.py to
persistence: finds the current open period for (itinerary_id, source), if
any, and either extends it or closes it and opens a new one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.collection.material_change import ObservedValue, is_material_change
from domain.flight.model import FlightOffer
from domain.flight.serialization import offer_to_dict
from infrastructure.postgres.models_search import CashObservation


async def write_observation(
    db: AsyncSession,
    *,
    offer: FlightOffer,
    origin: str,
    destination: str,
    depart_month: str,
    retrieved_at: datetime,
    search_id: uuid.UUID | None,
) -> None:
    latest = (
        await db.execute(
            select(CashObservation)
            .where(
                CashObservation.itinerary_id == offer.itinerary_id,
                CashObservation.source == offer.source,
            )
            .order_by(CashObservation.last_seen_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    current = ObservedValue(price_minor=offer.price_minor, currency=offer.currency)
    previous = (
        ObservedValue(price_minor=latest.price_minor, currency=latest.currency)
        if latest is not None
        else None
    )

    if latest is not None and not is_material_change(previous, current):
        latest.last_seen_at = retrieved_at
        latest.poll_count += 1
        latest.last_search_id = search_id
        # Refresh the detail snapshot too (freshness/confidence/offer) —
        # this is still "the same period", but the most recent poll's
        # provenance is the more accurate one to show for it.
        latest.freshness = offer.freshness.value
        latest.confidence = offer.confidence.value
        latest.offer = offer_to_dict(offer)
        return

    db.add(
        CashObservation(
            id=uuid.uuid4(),
            itinerary_id=offer.itinerary_id,
            source=offer.source,
            origin=origin,
            destination=destination,
            depart_month=depart_month,
            price_minor=offer.price_minor,
            currency=offer.currency,
            freshness=offer.freshness.value,
            confidence=offer.confidence.value,
            offer=offer_to_dict(offer),
            first_seen_at=retrieved_at,
            last_seen_at=retrieved_at,
            poll_count=1,
            last_search_id=search_id,
        )
    )
