"""Data quality gates for normalized itineraries (spec §36).
Pure, no I/O — reference data (known airports/carriers) is supplied by the
caller, already resolved from the database, not looked up here.

"A failed gate is logged with the raw payload retained and the itinerary
discarded. Bad data never reaches history, because history is the one
store where a bad write is effectively permanent" (spec §36). This module
only decides pass/fail and why; persistence, logging and raw-payload
retention are the caller's job (already built for Travelpayouts's
store_raw_payload).

One check from spec §36's list is deliberately not implemented here: "stop
count matches segment count". The canonical FlightOffer model (domain/
flight/model.py) does not currently carry a source-stated stop count
distinct from len(segments) - it would be checking segment count against
itself. Every current normalizer (normalization/travelpayouts.py) already
builds segments directly from the source's stated stop count as part of
deciding whether to normalize at all, so the two can't presently diverge.
This becomes real once a normalizer exists that could construct segments
independently of a stated count, at which point it belongs here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from domain.flight.model import FlightOffer, Segment, Slice

_ISO_4217_PATTERN = re.compile(r"^[A-Z]{3}$")


class QualityGateFailure(Exception):
    """Raised with a human-readable reason on the first violation found.
    Does not accumulate every violation — the itinerary is discarded
    either way, and the gate's job is to reject the impossible outright,
    not to partially salvage it (spec §36)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class QualityGateContext:
    known_airports: frozenset[str]
    known_carriers: frozenset[str]
    # A configured minimum, not real minimum-connection-time data —
    # authoritative MCT is an airport-by-airport commercial dataset this
    # project does not have. This floor rejects the impossible; the merely
    # tight connection is the risk engine's job (spec §67), not this
    # gate's, to flag rather than discard.
    minimum_connection_minutes: int = 45


def check_itinerary(offer: FlightOffer, ctx: QualityGateContext) -> None:
    """Raises QualityGateFailure on the first violation."""
    if not _ISO_4217_PATTERN.match(offer.currency):
        raise QualityGateFailure(f"invalid ISO 4217 currency: {offer.currency!r}")

    if not offer.slices:
        raise QualityGateFailure("itinerary has no slices")

    for slice_ in offer.slices:
        _check_slice(slice_, ctx)


def _check_slice(slice_: Slice, ctx: QualityGateContext) -> None:
    segments = slice_.segments
    if not segments:
        raise QualityGateFailure("slice has no segments")

    for segment in segments:
        _check_segment(segment, ctx)

    for i in range(len(segments) - 1):
        current = segments[i]
        following = segments[i + 1]

        if current.destination != following.origin:
            raise QualityGateFailure(
                f"segment continuity broken: {current.destination} -> {following.origin}"
            )

        if current.arrival_utc is None:
            # Can't verify a connection without knowing when the first leg
            # actually lands — a missing arrival time is honestly reported
            # elsewhere (spec P4), but a multi-segment itinerary this gate
            # can't verify the connection safety of must not pass silently.
            raise QualityGateFailure(
                f"cannot verify connection after segment {i}: arrival time not stated"
            )

        connection = following.departure_utc - current.arrival_utc
        if connection < timedelta(0):
            raise QualityGateFailure(
                f"connection time is negative between segments {i} and {i + 1}"
            )
        if connection < timedelta(minutes=ctx.minimum_connection_minutes):
            raise QualityGateFailure(
                f"connection time {connection} below the configured floor of "
                f"{ctx.minimum_connection_minutes} minutes"
            )


def _check_segment(segment: Segment, ctx: QualityGateContext) -> None:
    if segment.origin not in ctx.known_airports:
        raise QualityGateFailure(f"unresolved origin airport: {segment.origin}")
    if segment.destination not in ctx.known_airports:
        raise QualityGateFailure(f"unresolved destination airport: {segment.destination}")
    if segment.marketing_carrier not in ctx.known_carriers:
        raise QualityGateFailure(f"unresolved carrier: {segment.marketing_carrier}")

    if segment.arrival_utc is not None and segment.arrival_utc <= segment.departure_utc:
        raise QualityGateFailure("arrival not after departure (UTC)")
