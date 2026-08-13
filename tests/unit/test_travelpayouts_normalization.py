"""normalization/travelpayouts.py — pure, fixture-based, no network (spec §21)."""

from datetime import UTC, datetime

import pytest

from normalization.travelpayouts import normalize_price_calendar
from providers.errors import SourceError, SourceErrorKind

RETRIEVED_AT = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)

NONSTOP_BODY = {
    "success": True,
    "data": {
        "2026-10-01": {
            "origin": "MXP",
            "destination": "NRT",
            "price": 612,
            "transfers": 0,
            "airline": "LH",
            "flight_number": 510,
            "departure_at": "2026-10-01T09:15:00Z",
            "return_at": None,
            "expires_at": "2026-08-20T00:00:00Z",
        }
    },
}


def test_nonstop_entry_normalizes_fully() -> None:
    offers = normalize_price_calendar(
        NONSTOP_BODY, origin_timezone="Europe/Rome", currency="eur", retrieved_at=RETRIEVED_AT
    )
    assert len(offers) == 1
    offer = offers[0]

    assert offer.source == "travelpayouts"
    assert offer.price_minor == 61200  # 612.00 EUR in minor units
    assert offer.currency == "EUR"
    assert offer.freshness.value == "cached"
    assert offer.confidence.value == "high"
    assert len(offer.slices) == 1
    assert len(offer.slices[0].segments) == 1

    segment = offer.slices[0].segments[0]
    assert segment.origin == "MXP"
    assert segment.destination == "NRT"
    assert segment.marketing_carrier == "LH"
    assert segment.flight_number == "510"
    assert segment.departure_utc == datetime(2026, 10, 1, 9, 15, tzinfo=UTC)
    # Not provided by this source — must stay None, never a guessed duration.
    assert segment.arrival_utc is None


def test_departure_date_local_uses_origin_timezone_not_utc_date() -> None:
    # 09:15 UTC on 2026-10-01 is still 2026-10-01 in Europe/Rome (UTC+2), so
    # this fixture alone can't distinguish a timezone bug from a UTC-date
    # bug — use a departure just after UTC midnight against a
    # negative-offset timezone so the local date rolls back a day.
    body = {
        "success": True,
        "data": {
            "2026-10-01": {
                "origin": "JFK",
                "destination": "MXP",
                "price": 500,
                "transfers": 0,
                "airline": "DL",
                "flight_number": 100,
                "departure_at": "2026-10-01T02:00:00Z",  # 2026-09-30 22:00 in New York
                "return_at": None,
                "expires_at": None,
            }
        },
    }
    offers = normalize_price_calendar(
        body, origin_timezone="America/New_York", currency="usd", retrieved_at=RETRIEVED_AT
    )
    assert len(offers) == 1
    # itinerary_id is derived from the *local* departure date — recompute it
    # independently and compare, rather than asserting an opaque hash.
    from datetime import date

    from domain.flight.identity import SegmentIdentity, fingerprint

    expected_id = fingerprint(
        [
            SegmentIdentity(
                marketing_carrier="DL",
                flight_number="100",
                departure_date_local=date(2026, 9, 30),
                origin="JFK",
                destination="MXP",
            )
        ]
    )
    assert offers[0].itinerary_id == expected_id


def test_connecting_itinerary_is_skipped_not_fabricated() -> None:
    body = {
        "success": True,
        "data": {
            "2026-10-01": {
                "origin": "MXP",
                "destination": "NRT",
                "price": 612,
                "transfers": 1,
                "airline": "LH",
                "flight_number": 510,
                "departure_at": "2026-10-01T09:15:00Z",
                "return_at": None,
                "expires_at": None,
            }
        },
    }
    offers = normalize_price_calendar(
        body, origin_timezone="Europe/Rome", currency="eur", retrieved_at=RETRIEVED_AT
    )
    assert offers == []


def test_missing_data_key_raises_schema_change() -> None:
    with pytest.raises(SourceError) as exc_info:
        normalize_price_calendar(
            {"success": True},
            origin_timezone="Europe/Rome",
            currency="eur",
            retrieved_at=RETRIEVED_AT,
        )
    assert exc_info.value.kind == SourceErrorKind.SCHEMA_CHANGE


def test_entry_missing_required_field_raises_schema_change() -> None:
    body = {
        "success": True,
        "data": {
            "2026-10-01": {"origin": "MXP", "destination": "NRT"}
        },  # no price, no airline, ...
    }
    with pytest.raises(SourceError) as exc_info:
        normalize_price_calendar(
            body, origin_timezone="Europe/Rome", currency="eur", retrieved_at=RETRIEVED_AT
        )
    assert exc_info.value.kind == SourceErrorKind.SCHEMA_CHANGE


def test_limitations_are_recorded_on_the_offer() -> None:
    offers = normalize_price_calendar(
        NONSTOP_BODY, origin_timezone="Europe/Rome", currency="eur", retrieved_at=RETRIEVED_AT
    )
    assert offers[0].limitations  # non-empty: this source's real gaps are named, not hidden
