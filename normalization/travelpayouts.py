"""Travelpayouts payload -> canonical model (issue #42; spec §5, §14, §16).

Only this module knows the shape of a Travelpayouts `/v1/prices/calendar`
response. It converts that shape into `domain.flight.model.FlightOffer` and
nothing else — no loyalty, no ranking, no I/O against the source (that is
providers.travelpayouts.client's job, issue #41).

Pure and offline: takes the origin airport's IANA timezone as an argument
rather than looking it up, so this module never touches a database and stays
unit-testable against fixtures alone.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from domain.flight.identity import SegmentIdentity, fingerprint
from domain.flight.model import Confidence, FlightOffer, FreshnessState, Segment, Slice
from providers.errors import SourceError, SourceErrorKind

logger = logging.getLogger(__name__)

SOURCE_ID = "travelpayouts"

# This endpoint's summary-level fields (one airline, one flight_number) only
# describe a non-stop itinerary correctly. For transfers > 0 they describe an
# unknown chain of connecting flights the endpoint does not break out — a
# segment/fingerprint built on that would be a fabricated itinerary wearing a
# real-looking flight number, exactly what spec P3/P4 forbid. Those entries
# are skipped, not guessed at. Multi-stop detail from this source is left as
# a documented gap (docs/providers.md), not something this normalizer papers
# over with an invented topology.
_MAX_NORMALIZABLE_TRANSFERS = 0


def normalize_price_calendar(
    raw: dict,
    *,
    origin_timezone: str,
    currency: str,
    retrieved_at: datetime,
) -> list[FlightOffer]:
    """Convert one `/v1/prices/calendar` response into zero or more FlightOffers.

    `raw` is assumed to already have passed providers.travelpayouts.client's
    envelope validation (`success`/`data` present) — this function still
    defends against malformed entries *within* `data`, since the client only
    validates the envelope, not each entry.
    """
    data = raw.get("data")
    if not isinstance(data, dict):
        raise SourceError(
            SourceErrorKind.SCHEMA_CHANGE,
            f"'data' was not an object: {type(data).__name__}",
            source_id=SOURCE_ID,
        )

    tz = ZoneInfo(origin_timezone)
    offers: list[FlightOffer] = []

    for date_key, entry in data.items():
        try:
            offer = _normalize_entry(entry, tz=tz, currency=currency, retrieved_at=retrieved_at)
        except _SkipEntry as skip:
            logger.info("travelpayouts: skipping %s entry: %s", date_key, skip)
            continue
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError(
                SourceErrorKind.SCHEMA_CHANGE,
                f"malformed entry for {date_key}: {exc}",
                source_id=SOURCE_ID,
            ) from exc

        if offer is not None:
            offers.append(offer)

    return offers


class _SkipEntry(Exception):
    """An entry that is well-formed but outside this normalizer's honest
    coverage (see `_MAX_NORMALIZABLE_TRANSFERS`) — not a schema problem."""


def _normalize_entry(
    entry: dict, *, tz: ZoneInfo, currency: str, retrieved_at: datetime
) -> FlightOffer:
    transfers = entry["transfers"]
    if transfers > _MAX_NORMALIZABLE_TRANSFERS:
        raise _SkipEntry(f"{transfers} transfers — segment detail not derivable from this source")

    departure_utc = _parse_utc(entry["departure_at"])
    departure_local_date = departure_utc.astimezone(tz).date()

    marketing_carrier = entry["airline"]
    flight_number = str(entry["flight_number"])
    origin = entry["origin"]
    destination = entry["destination"]

    segment = Segment(
        origin=origin,
        destination=destination,
        departure_utc=departure_utc,
        # This endpoint states no arrival time at all — leaving it None is
        # the honest reading; a computed one would be a guessed duration
        # dressed up as a fact (spec P4).
        arrival_utc=None,
        marketing_carrier=marketing_carrier,
        flight_number=flight_number,
    )

    itinerary_id = fingerprint(
        [
            SegmentIdentity(
                marketing_carrier=marketing_carrier,
                flight_number=flight_number,
                departure_date_local=departure_local_date,
                origin=origin,
                destination=destination,
            )
        ]
    )

    expires_at = _parse_utc(entry["expires_at"]) if entry.get("expires_at") else None

    # Travelpayouts' documented examples show prices as bare integers with no
    # decimal point (e.g. "price": 35443 for RUB) — read here as whole
    # currency units, not minor units already. UNVERIFIED against a live
    # response (issue #41 is still pending a real token); re-check this
    # assumption during that live-verification pass before trusting displayed
    # prices.
    price_minor = round(entry["price"] * 100)

    return FlightOffer(
        offer_id=f"{SOURCE_ID}:{origin}-{destination}:{departure_local_date.isoformat()}",
        itinerary_id=itinerary_id,
        source=SOURCE_ID,
        source_offer_id=None,
        price_minor=price_minor,
        taxes_minor=None,
        currency=currency.upper(),
        validating_carrier=None,
        cabin=None,
        fare_brand=None,
        slices=(Slice(segments=(segment,)),),
        baggage=None,
        changeability=None,
        refundability=None,
        booking_link=None,
        retrieved_at=retrieved_at,
        expires_at=expires_at,
        # docs/providers.md "Critical limitation": this source is always
        # cached/aggregated, never live — presented as CACHED unconditionally
        # rather than computed from age, per that source's own contract.
        freshness=FreshnessState.CACHED,
        # OFFICIAL_API, directly stated by the source (spec §43) — full
        # multi-input confidence scoring is a later EVALUATION-layer concern,
        # not this normalizer's.
        confidence=Confidence.HIGH,
        limitations=(
            "arrival time and duration not provided by this source",
            "cabin, fare brand and baggage not provided by this source",
        ),
    )


def _parse_utc(value: str) -> datetime:
    # Travelpayouts timestamps are ISO 8601 with a trailing "Z" (spec:
    # "Dates and times are given in UTC"); fromisoformat needs "+00:00".
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
