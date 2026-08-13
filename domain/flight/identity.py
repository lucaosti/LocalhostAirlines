"""Itinerary fingerprinting (spec §15). Pure, no I/O.

The same physical journey arrives from several sources at different prices;
this is what lets the system present one itinerary with several observations
instead of several unrelated flights (spec §16).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SegmentIdentity:
    """The identity-relevant slice of a Segment (spec §15).

    Deliberately excludes price, operating carrier, fare brand and booking
    class — those vary between sources describing the same journey, which is
    precisely what deduplication must see through.
    """

    marketing_carrier: str
    flight_number: str
    departure_date_local: date
    origin: str
    destination: str


def fingerprint(segments: list[SegmentIdentity]) -> str:
    """Hash of the ordered tuple of identity fields, per segment (spec §15).

    Order matters — two itineraries with the same segments in a different
    order are a different journey (e.g. outbound vs inbound swapped), so the
    input order is preserved rather than sorted before hashing.
    """
    if not segments:
        raise ValueError("fingerprint requires at least one segment")

    canonical = "|".join(
        f"{s.marketing_carrier}{s.flight_number}:{s.departure_date_local.isoformat()}:"
        f"{s.origin}-{s.destination}"
        for s in segments
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
