"""domain/flight/identity.py — pure, no I/O, no database (CLAUDE.md §5)."""

from datetime import date

import pytest

from domain.flight.identity import SegmentIdentity, fingerprint

SEG = SegmentIdentity(
    marketing_carrier="LH",
    flight_number="510",
    departure_date_local=date(2026, 10, 1),
    origin="MXP",
    destination="NRT",
)


def test_same_segments_produce_same_fingerprint() -> None:
    a = fingerprint([SEG])
    b = fingerprint([SegmentIdentity(**vars(SEG))])
    assert a == b


def test_price_and_other_non_identity_fields_are_irrelevant_by_construction() -> None:
    # SegmentIdentity has no price/cabin/booking_class fields at all — this
    # test documents that omission is deliberate (spec §15), not an oversight.
    assert not hasattr(SEG, "price_minor")
    assert not hasattr(SEG, "cabin")


def test_different_flight_number_changes_fingerprint() -> None:
    other = SegmentIdentity(**{**vars(SEG), "flight_number": "511"})
    assert fingerprint([SEG]) != fingerprint([other])


def test_different_departure_date_changes_fingerprint() -> None:
    other = SegmentIdentity(**{**vars(SEG), "departure_date_local": date(2026, 10, 2)})
    assert fingerprint([SEG]) != fingerprint([other])


def test_segment_order_is_significant() -> None:
    outbound = SEG
    inbound = SegmentIdentity(**{**vars(SEG), "origin": "NRT", "destination": "MXP"})
    assert fingerprint([outbound, inbound]) != fingerprint([inbound, outbound])


def test_empty_segment_list_rejected() -> None:
    with pytest.raises(ValueError, match="at least one segment"):
        fingerprint([])
