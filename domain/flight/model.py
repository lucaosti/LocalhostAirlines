"""Canonical flight model (spec §11-§16). Pure data, no I/O, no framework imports.

Every provider normalizes into this one shape (spec §14) — no provider's own
model is ever the canonical model, including whichever provider is currently
the best source. This is the boundary domain rules and every downstream layer
(ENRICHMENT, EVALUATION, PRESENTATION) actually reason about.

Fields absent from a source are `None`, never a guessed value or a sentinel
like `0`/`""`/`False` (spec P3, P4, §45) — a missing duration must read as
"we don't know", not as "instant flight".
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class FreshnessState(enum.StrEnum):
    """spec §42. A refresh-policy outcome, not a property of the value itself."""

    LIVE = "live"
    FRESH = "fresh"
    RECENT = "recent"
    CACHED = "cached"
    STALE = "stale"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"


class Confidence(enum.StrEnum):
    """spec §43. Deterministic, derived from source authority/freshness/corroboration/
    directness — never an inferred score."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass(frozen=True)
class Segment:
    """spec §12. One flight number, one physical hop."""

    origin: str  # IATA
    destination: str  # IATA

    departure_utc: datetime  # authoritative for all arithmetic
    arrival_utc: datetime | None  # None when the source does not state it — never guessed

    marketing_carrier: str  # IATA airline code
    flight_number: str

    # Not always knowable from a source's summary-level data; None means
    # "not stated", not "same as marketing carrier" (spec §12 — a codeshare
    # assumed away here would be a false fact, not a missing one).
    operating_carrier: str | None = None

    aircraft: str | None = None
    booking_class: str | None = None
    cabin: str | None = None


@dataclass(frozen=True)
class Slice:
    """spec §11. One directional leg — outbound, inbound, or one leg of a multi-city trip."""

    segments: tuple[Segment, ...]


@dataclass(frozen=True)
class FlightOffer:
    """spec §14. What one source observed for one itinerary, at one point in time."""

    offer_id: str
    itinerary_id: str  # fingerprint, spec §15 — domain.flight.identity.fingerprint()
    source: str
    source_offer_id: str | None

    price_minor: int  # integer minor units — never a float (spec P1, "Money" in CLAUDE.md §5)
    taxes_minor: int | None
    currency: str  # ISO 4217

    validating_carrier: str | None
    cabin: str | None
    fare_brand: str | None

    slices: tuple[Slice, ...]

    baggage: str | None
    changeability: str | None
    refundability: str | None
    booking_link: str | None

    retrieved_at: datetime
    expires_at: datetime | None

    freshness: FreshnessState
    confidence: Confidence

    # Free-form notes on what this specific offer's source could not tell us
    # (spec §21 "fails loudly", but a partial-detail offer is not a failure —
    # it is a real observation with known gaps, and the gaps are worth naming
    # rather than leaving the reader to infer them from absent fields).
    limitations: tuple[str, ...] = field(default_factory=tuple)
