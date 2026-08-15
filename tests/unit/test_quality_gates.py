"""domain/quality/gates.py — pure, no I/O, no database."""

from datetime import UTC, datetime, timedelta

import pytest

from domain.flight.model import Confidence, FlightOffer, FreshnessState, Segment, Slice
from domain.quality.gates import QualityGateContext, QualityGateFailure, check_itinerary

CTX = QualityGateContext(
    known_airports=frozenset({"MXP", "NRT", "CDG"}),
    known_carriers=frozenset({"LH", "AF"}),
    minimum_connection_minutes=45,
)


def _segment(**overrides) -> Segment:
    defaults = dict(
        origin="MXP",
        destination="NRT",
        departure_utc=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
        arrival_utc=datetime(2026, 10, 1, 20, 0, tzinfo=UTC),
        marketing_carrier="LH",
        flight_number="510",
    )
    defaults.update(overrides)
    return Segment(**defaults)


def _offer(*, slices=None, currency="EUR") -> FlightOffer:
    return FlightOffer(
        offer_id="x",
        itinerary_id="x",
        source="test",
        source_offer_id=None,
        price_minor=1000,
        taxes_minor=None,
        currency=currency,
        validating_carrier=None,
        cabin=None,
        fare_brand=None,
        slices=slices if slices is not None else (Slice(segments=(_segment(),)),),
        baggage=None,
        changeability=None,
        refundability=None,
        booking_link=None,
        retrieved_at=datetime.now(UTC),
        expires_at=None,
        freshness=FreshnessState.CACHED,
        confidence=Confidence.HIGH,
    )


def test_valid_nonstop_offer_passes() -> None:
    check_itinerary(_offer(), CTX)  # must not raise


def test_invalid_currency_rejected() -> None:
    with pytest.raises(QualityGateFailure, match="currency"):
        check_itinerary(_offer(currency="euros"), CTX)


def test_no_slices_rejected() -> None:
    with pytest.raises(QualityGateFailure, match="no slices"):
        check_itinerary(_offer(slices=()), CTX)


def test_unresolved_origin_airport_rejected() -> None:
    offer = _offer(slices=(Slice(segments=(_segment(origin="ZZZ"),)),))
    with pytest.raises(QualityGateFailure, match="unresolved origin airport"):
        check_itinerary(offer, CTX)


def test_unresolved_carrier_rejected() -> None:
    offer = _offer(slices=(Slice(segments=(_segment(marketing_carrier="ZZ"),)),))
    with pytest.raises(QualityGateFailure, match="unresolved carrier"):
        check_itinerary(offer, CTX)


def test_arrival_before_departure_rejected() -> None:
    dep = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)
    arr = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)  # before departure
    offer = _offer(slices=(Slice(segments=(_segment(departure_utc=dep, arrival_utc=arr),)),))
    with pytest.raises(QualityGateFailure, match="arrival not after departure"):
        check_itinerary(offer, CTX)


def test_missing_arrival_on_nonstop_is_fine() -> None:
    # No connection to verify on a single-segment slice — a missing arrival
    # time is a legitimate absence (spec P4), not a gate failure, exactly
    # matching M1's real Travelpayouts offers, which never report it.
    offer = _offer(slices=(Slice(segments=(_segment(arrival_utc=None),)),))
    check_itinerary(offer, CTX)  # must not raise


def test_segment_continuity_broken_rejected() -> None:
    leg1 = _segment(origin="MXP", destination="NRT")
    leg2 = _segment(origin="CDG", destination="NRT")  # doesn't continue from NRT
    offer = _offer(slices=(Slice(segments=(leg1, leg2)),))
    with pytest.raises(QualityGateFailure, match="continuity broken"):
        check_itinerary(offer, CTX)


def test_missing_arrival_on_connecting_segment_rejected() -> None:
    leg1 = _segment(origin="MXP", destination="CDG", arrival_utc=None)
    leg2 = _segment(origin="CDG", destination="NRT")
    offer = _offer(slices=(Slice(segments=(leg1, leg2)),))
    with pytest.raises(QualityGateFailure, match="cannot verify connection"):
        check_itinerary(offer, CTX)


def test_negative_connection_time_rejected() -> None:
    leg1_arrival = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)
    leg1 = _segment(origin="MXP", destination="CDG", arrival_utc=leg1_arrival)
    leg2 = _segment(
        origin="CDG",
        destination="NRT",
        departure_utc=leg1_arrival - timedelta(minutes=10),  # before leg1 even lands
    )
    offer = _offer(slices=(Slice(segments=(leg1, leg2)),))
    with pytest.raises(QualityGateFailure, match="negative"):
        check_itinerary(offer, CTX)


def test_connection_below_floor_rejected() -> None:
    leg1_arrival = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)
    leg1 = _segment(origin="MXP", destination="CDG", arrival_utc=leg1_arrival)
    leg2_departure = leg1_arrival + timedelta(minutes=20)  # below the 45-minute floor
    leg2 = _segment(
        origin="CDG",
        destination="NRT",
        departure_utc=leg2_departure,
        arrival_utc=leg2_departure + timedelta(hours=11),
    )
    offer = _offer(slices=(Slice(segments=(leg1, leg2)),))
    with pytest.raises(QualityGateFailure, match="below the configured floor"):
        check_itinerary(offer, CTX)


def test_connection_above_floor_passes() -> None:
    leg1_arrival = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)
    leg1 = _segment(origin="MXP", destination="CDG", arrival_utc=leg1_arrival)
    leg2_departure = leg1_arrival + timedelta(minutes=90)
    leg2 = _segment(
        origin="CDG",
        destination="NRT",
        departure_utc=leg2_departure,
        arrival_utc=leg2_departure + timedelta(hours=11),
    )
    offer = _offer(slices=(Slice(segments=(leg1, leg2)),))
    check_itinerary(offer, CTX)  # must not raise
