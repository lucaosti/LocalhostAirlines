"""Nightly flight_price_daily aggregation (issue #55; spec §57). Pure, no I/O.

"A day is covered by every observation whose [first_seen_at, last_seen_at]
interval intersects it, so a price that held for a week contributes to all
seven days exactly once each — which is what 'the price on that day' means"
(spec §57). Depends on issue #54's material-change dedup: computing this
over one-row-per-fetch data would double-count polling frequency, the exact
failure spec §56 exists to prevent — the same failure would just move one
layer up into the aggregate instead of being fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class ObservationPeriod:
    route: str  # "MXP-NRT"
    cabin: str  # "" means not stated by the source — see module note below
    fare_family: str
    source: str
    currency: str
    price_minor: int
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class DailyAggregateKey:
    aggregate_date: date
    route: str
    cabin: str
    fare_family: str
    source: str
    currency: str


@dataclass(frozen=True)
class DailyAggregate:
    key: DailyAggregateKey
    minimum_price_minor: int
    median_price_minor: int
    maximum_price_minor: int
    observation_count: int


def compute_daily_aggregates(periods: list[ObservationPeriod]) -> list[DailyAggregate]:
    """Currency is part of the grouping key — averaging minor units across
    different currencies would be meaningless, so each aggregate is
    currency-pure by construction rather than needing a later conversion
    pass to stay correct."""
    buckets: dict[DailyAggregateKey, list[int]] = {}
    for period in periods:
        for day in _dates_covered(period):
            key = DailyAggregateKey(
                aggregate_date=day,
                route=period.route,
                cabin=period.cabin,
                fare_family=period.fare_family,
                source=period.source,
                currency=period.currency,
            )
            buckets.setdefault(key, []).append(period.price_minor)

    return [
        DailyAggregate(
            key=key,
            minimum_price_minor=prices[0],
            median_price_minor=_median(prices),
            maximum_price_minor=prices[-1],
            observation_count=len(prices),
        )
        for key, raw_prices in buckets.items()
        for prices in (sorted(raw_prices),)
    ]


def _dates_covered(period: ObservationPeriod) -> list[date]:
    start = period.first_seen_at.date()
    end = period.last_seen_at.date()
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _median(sorted_values: list[int]) -> int:
    n = len(sorted_values)
    mid = n // 2
    if n % 2 == 1:
        return sorted_values[mid]
    # Even count: no interpolation mandated by spec §57 — averaging the two
    # middle values and truncating keeps the result an integer minor-unit
    # price (spec P1: money is integer minor units, never a float) rather
    # than introducing fractional cents.
    return (sorted_values[mid - 1] + sorted_values[mid]) // 2
