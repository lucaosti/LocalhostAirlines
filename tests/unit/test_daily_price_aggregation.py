"""domain/aggregation/daily_price.py — pure, no I/O, no database."""

from datetime import UTC, datetime

from domain.aggregation.daily_price import ObservationPeriod, compute_daily_aggregates


def _period(
    first_seen: datetime, last_seen: datetime, price_minor: int, route: str = "MXP-NRT"
) -> ObservationPeriod:
    return ObservationPeriod(
        route=route,
        cabin="",
        fare_family="",
        source="travelpayouts",
        currency="EUR",
        price_minor=price_minor,
        first_seen_at=first_seen,
        last_seen_at=last_seen,
    )


def test_single_day_period_produces_one_aggregate() -> None:
    day = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    aggregates = compute_daily_aggregates([_period(day, day, 61200)])
    assert len(aggregates) == 1
    assert aggregates[0].key.aggregate_date == day.date()
    assert aggregates[0].minimum_price_minor == 61200
    assert aggregates[0].median_price_minor == 61200
    assert aggregates[0].maximum_price_minor == 61200
    assert aggregates[0].observation_count == 1


def test_week_long_period_contributes_to_all_seven_days_once_each() -> None:
    first_seen = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    last_seen = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)
    aggregates = compute_daily_aggregates([_period(first_seen, last_seen, 50000)])

    assert len(aggregates) == 7
    dates = {a.key.aggregate_date for a in aggregates}
    assert dates == {first_seen.date().replace(day=d) for d in range(1, 8)}
    for agg in aggregates:
        assert agg.observation_count == 1
        assert agg.minimum_price_minor == agg.maximum_price_minor == 50000


def test_multiple_periods_same_day_aggregate_together() -> None:
    day = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    aggregates = compute_daily_aggregates(
        [_period(day, day, 100), _period(day, day, 300), _period(day, day, 200)]
    )
    assert len(aggregates) == 1
    agg = aggregates[0]
    assert agg.minimum_price_minor == 100
    assert agg.maximum_price_minor == 300
    assert agg.median_price_minor == 200
    assert agg.observation_count == 3


def test_even_count_median_truncates_rather_than_producing_a_float() -> None:
    day = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    aggregates = compute_daily_aggregates([_period(day, day, 100), _period(day, day, 201)])
    # (100 + 201) // 2 == 150 — an integer minor-unit price, never a float
    # (spec P1).
    assert aggregates[0].median_price_minor == 150


def test_different_currencies_never_share_an_aggregate() -> None:
    day = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    eur = ObservationPeriod(
        route="MXP-NRT",
        cabin="",
        fare_family="",
        source="travelpayouts",
        currency="EUR",
        price_minor=60000,
        first_seen_at=day,
        last_seen_at=day,
    )
    usd = ObservationPeriod(
        route="MXP-NRT",
        cabin="",
        fare_family="",
        source="travelpayouts",
        currency="USD",
        price_minor=65000,
        first_seen_at=day,
        last_seen_at=day,
    )
    aggregates = compute_daily_aggregates([eur, usd])
    assert len(aggregates) == 2
    currencies = {a.key.currency for a in aggregates}
    assert currencies == {"EUR", "USD"}


def test_different_routes_never_share_an_aggregate() -> None:
    day = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    aggregates = compute_daily_aggregates(
        [_period(day, day, 100, route="MXP-NRT"), _period(day, day, 100, route="LIN-HND")]
    )
    assert len(aggregates) == 2
