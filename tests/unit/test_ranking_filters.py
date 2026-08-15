"""domain/ranking/filters.py — pure, no I/O, no database."""

from datetime import UTC, datetime, time

from domain.flight.model import Confidence, FlightOffer, FreshnessState, Segment, Slice
from domain.ranking.filters import (
    HardFilterResult,
    airline_preference,
    apply_hard_filters,
    apply_preferences,
    arrive_before_filter,
    cabin_filter,
    directness_preference,
    max_stops_filter,
    time_of_day_preference,
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


def _offer(*, offer_id="x", slices=None, cabin=None, validating_carrier=None) -> FlightOffer:
    return FlightOffer(
        offer_id=offer_id,
        itinerary_id=offer_id,
        source="test",
        source_offer_id=None,
        price_minor=1000,
        taxes_minor=None,
        currency="EUR",
        validating_carrier=validating_carrier,
        cabin=cabin,
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


def test_hard_filter_eliminates_non_matching_cabin() -> None:
    business = _offer(offer_id="a", cabin="business")
    economy = _offer(offer_id="b", cabin="economy")
    result = apply_hard_filters([business, economy], [cabin_filter("business")])
    assert result.survivors == (business,)
    assert result.outcomes[0].removed_count == 1


def test_hard_filter_missing_cabin_does_not_pass() -> None:
    unknown_cabin = _offer(cabin=None)
    result = apply_hard_filters([unknown_cabin], [cabin_filter("business")])
    assert result.survivors == ()


def test_max_stops_filter_counts_per_slice() -> None:
    nonstop = _offer(offer_id="nonstop", slices=(Slice(segments=(_segment(),)),))
    two_stop = _offer(
        offer_id="two-stop",
        slices=(
            Slice(
                segments=(
                    _segment(origin="MXP", destination="CDG"),
                    _segment(origin="CDG", destination="DXB"),
                    _segment(origin="DXB", destination="NRT"),
                )
            ),
        ),
    )
    result = apply_hard_filters([nonstop, two_stop], [max_stops_filter(1)])
    assert result.survivors == (nonstop,)
    assert result.outcomes[0].removed_count == 1


def test_arrive_before_filter_uses_last_segment_of_slice() -> None:
    early = _offer(
        offer_id="early",
        slices=(Slice(segments=(_segment(arrival_utc=datetime(2026, 10, 1, 10, 0, tzinfo=UTC)),)),),
    )
    late = _offer(
        offer_id="late",
        slices=(Slice(segments=(_segment(arrival_utc=datetime(2026, 10, 1, 22, 0, tzinfo=UTC)),)),),
    )
    result = apply_hard_filters([early, late], [arrive_before_filter(time(18, 0))])
    assert result.survivors == (early,)


def test_arrive_before_filter_missing_arrival_does_not_pass() -> None:
    offer = _offer(slices=(Slice(segments=(_segment(arrival_utc=None),)),))
    result = apply_hard_filters([offer], [arrive_before_filter(time(18, 0))])
    assert result.survivors == ()


def test_sequential_filters_report_own_contribution_only() -> None:
    business_early = _offer(
        offer_id="a",
        cabin="business",
        slices=(Slice(segments=(_segment(arrival_utc=datetime(2026, 10, 1, 10, 0, tzinfo=UTC)),)),),
    )
    economy_early = _offer(
        offer_id="b",
        cabin="economy",
        slices=(Slice(segments=(_segment(arrival_utc=datetime(2026, 10, 1, 10, 0, tzinfo=UTC)),)),),
    )
    economy_late = _offer(
        offer_id="c",
        cabin="economy",
        slices=(Slice(segments=(_segment(arrival_utc=datetime(2026, 10, 1, 22, 0, tzinfo=UTC)),)),),
    )
    result = apply_hard_filters(
        [business_early, economy_early, economy_late],
        [cabin_filter("economy"), arrive_before_filter(time(18, 0))],
    )
    # cabin filter removes business_early only; arrive_before then removes
    # economy_late from what's left — each outcome reflects only its own cut.
    assert result.outcomes[0].removed_count == 1
    assert result.outcomes[1].removed_count == 1
    assert result.survivors == (economy_early,)


def test_zero_survivors_names_eliminating_filters() -> None:
    offer = _offer(cabin="economy")
    result = apply_hard_filters([offer], [cabin_filter("business"), max_stops_filter(0)])
    assert isinstance(result, HardFilterResult)
    assert result.survivors == ()
    names = [outcome.name for outcome in result.eliminated_by]
    assert names == ["cabin=business"]


def test_empty_input_produces_no_eliminating_filters() -> None:
    # Zero results because nothing was searched, not because a filter
    # removed anything — eliminated_by must stay empty so the caller can
    # tell the two apart (spec §37, §45).
    result = apply_hard_filters([], [cabin_filter("business")])
    assert result.survivors == ()
    assert result.eliminated_by == ()


def test_preferences_never_change_survivor_count() -> None:
    a = _offer(offer_id="a", validating_carrier="LH")
    b = _offer(offer_id="b", validating_carrier="AF")
    reordered = apply_preferences([a, b], [airline_preference({"AF": 10})])
    assert len(reordered) == 2
    assert set(reordered) == {a, b}


def test_airline_preference_ranks_higher_weight_first() -> None:
    lufthansa = _offer(offer_id="lh", validating_carrier="LH")
    air_france = _offer(offer_id="af", validating_carrier="AF")
    reordered = apply_preferences(
        [lufthansa, air_france], [airline_preference({"AF": 10, "LH": 1})]
    )
    assert reordered[0] is air_france


def test_directness_preference_ranks_fewer_stops_first() -> None:
    nonstop = _offer(offer_id="nonstop", slices=(Slice(segments=(_segment(),)),))
    one_stop = _offer(
        offer_id="one-stop",
        slices=(
            Slice(
                segments=(
                    _segment(origin="MXP", destination="CDG"),
                    _segment(origin="CDG", destination="NRT"),
                )
            ),
        ),
    )
    reordered = apply_preferences([one_stop, nonstop], [directness_preference()])
    assert reordered[0] is nonstop


def test_time_of_day_preference_scores_within_window() -> None:
    morning = _offer(
        offer_id="morning",
        slices=(
            Slice(segments=(_segment(departure_utc=datetime(2026, 10, 1, 7, 0, tzinfo=UTC)),)),
        ),
    )
    evening = _offer(
        offer_id="evening",
        slices=(
            Slice(segments=(_segment(departure_utc=datetime(2026, 10, 1, 21, 0, tzinfo=UTC)),)),
        ),
    )
    reordered = apply_preferences(
        [evening, morning], [time_of_day_preference(time(6, 0), time(11, 0))]
    )
    assert reordered[0] is morning


def test_preferences_stable_on_tie() -> None:
    a = _offer(offer_id="a")
    b = _offer(offer_id="b")
    reordered = apply_preferences([a, b], [])
    assert reordered == (a, b)
