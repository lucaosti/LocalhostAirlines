"""FlightOffer <-> plain-dict conversion. Pure, no I/O.

Used by issue #43's persistence layer to store a FlightOffer as JSONB (see
infrastructure/postgres/models_search.py for why) and by the API layer to
read it back into the same dataclass shape rather than working with a bare
dict past the boundary where it was written.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from domain.flight.model import Confidence, FlightOffer, FreshnessState, Segment, Slice


def offer_to_dict(offer: FlightOffer) -> dict[str, Any]:
    return {
        "offer_id": offer.offer_id,
        "itinerary_id": offer.itinerary_id,
        "source": offer.source,
        "source_offer_id": offer.source_offer_id,
        "price_minor": offer.price_minor,
        "taxes_minor": offer.taxes_minor,
        "currency": offer.currency,
        "validating_carrier": offer.validating_carrier,
        "cabin": offer.cabin,
        "fare_brand": offer.fare_brand,
        "slices": [
            {
                "segments": [
                    {
                        "origin": s.origin,
                        "destination": s.destination,
                        "departure_utc": s.departure_utc.isoformat(),
                        "arrival_utc": s.arrival_utc.isoformat() if s.arrival_utc else None,
                        "marketing_carrier": s.marketing_carrier,
                        "flight_number": s.flight_number,
                        "operating_carrier": s.operating_carrier,
                        "aircraft": s.aircraft,
                        "booking_class": s.booking_class,
                        "cabin": s.cabin,
                    }
                    for s in slice_.segments
                ]
            }
            for slice_ in offer.slices
        ],
        "baggage": offer.baggage,
        "changeability": offer.changeability,
        "refundability": offer.refundability,
        "booking_link": offer.booking_link,
        "retrieved_at": offer.retrieved_at.isoformat(),
        "expires_at": offer.expires_at.isoformat() if offer.expires_at else None,
        "freshness": offer.freshness.value,
        "confidence": offer.confidence.value,
        "limitations": list(offer.limitations),
    }


def offer_from_dict(data: dict[str, Any]) -> FlightOffer:
    return FlightOffer(
        offer_id=data["offer_id"],
        itinerary_id=data["itinerary_id"],
        source=data["source"],
        source_offer_id=data["source_offer_id"],
        price_minor=data["price_minor"],
        taxes_minor=data["taxes_minor"],
        currency=data["currency"],
        validating_carrier=data["validating_carrier"],
        cabin=data["cabin"],
        fare_brand=data["fare_brand"],
        slices=tuple(
            Slice(
                segments=tuple(
                    Segment(
                        origin=seg["origin"],
                        destination=seg["destination"],
                        departure_utc=datetime.fromisoformat(seg["departure_utc"]),
                        arrival_utc=(
                            datetime.fromisoformat(seg["arrival_utc"])
                            if seg["arrival_utc"]
                            else None
                        ),
                        marketing_carrier=seg["marketing_carrier"],
                        flight_number=seg["flight_number"],
                        operating_carrier=seg["operating_carrier"],
                        aircraft=seg["aircraft"],
                        booking_class=seg["booking_class"],
                        cabin=seg["cabin"],
                    )
                    for seg in slice_["segments"]
                )
            )
            for slice_ in data["slices"]
        ),
        baggage=data["baggage"],
        changeability=data["changeability"],
        refundability=data["refundability"],
        booking_link=data["booking_link"],
        retrieved_at=datetime.fromisoformat(data["retrieved_at"]),
        expires_at=datetime.fromisoformat(data["expires_at"]) if data["expires_at"] else None,
        freshness=FreshnessState(data["freshness"]),
        confidence=Confidence(data["confidence"]),
        limitations=tuple(data.get("limitations", ())),
    )
