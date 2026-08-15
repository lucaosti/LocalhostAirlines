"""Search-space expansion and batch collapsing (issue #62; spec §27, §28).
Pure, no I/O.

"The naive expansion is origins × destinations × departure dates × trip
lengths × cabins. For the query [in spec §27's example] that is roughly
2,200 combinations — far beyond any source's tolerance" (spec §28). This
module produces that full expansion and then collapses what one batch-
capable source call can answer at once, before the budget (issue #63)
decides what actually gets spent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class WeightedLocation:
    code: str  # IATA
    # 0-100, influences ranking only — weights never filter (spec §27's own
    # rule: "Weights influence ranking; they do not filter").
    weight: int = 0


@dataclass(frozen=True)
class SearchQuery:
    origins: tuple[WeightedLocation, ...]
    destinations: tuple[WeightedLocation, ...]
    date_start: date
    date_end: date
    min_nights: int
    max_nights: int
    cabins: tuple[str, ...]


@dataclass(frozen=True)
class SearchTask:
    """One (origin, destination, departure_date, trip_length, cabin)
    combination — the atomic unit of the logical search space."""

    origin: str
    destination: str
    departure_date: date
    trip_length_nights: int
    cabin: str

    @property
    def return_date(self) -> date:
        return self.departure_date + timedelta(days=self.trip_length_nights)


def expand(query: SearchQuery) -> list[SearchTask]:
    """Every task the search space could produce, before batching or budget
    reduce it. Deliberately not deduplicated or filtered — that is exactly
    what makes the count itself meaningful (spec §28's "roughly 2,200
    combinations" is a property of this raw expansion)."""
    tasks = []
    for origin in query.origins:
        for destination in query.destinations:
            for departure_date in _dates_in_range(query.date_start, query.date_end):
                for nights in range(query.min_nights, query.max_nights + 1):
                    for cabin in query.cabins:
                        tasks.append(
                            SearchTask(
                                origin=origin.code,
                                destination=destination.code,
                                departure_date=departure_date,
                                trip_length_nights=nights,
                                cabin=cabin,
                            )
                        )
    return tasks


def _dates_in_range(start: date, end: date) -> list[date]:
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


@dataclass(frozen=True)
class BatchGroup:
    """Every task answerable by one source call, per spec §22's
    `batch_query` capability — "a source answering a whole month of dates
    in one call collapses the search-space explosion" (docs/providers.md
    "Adapter contract"). Collapses only the departure-date dimension within
    a month, since that is specifically what spec §28 describes; cabin and
    trip length stay distinct because a genuinely batch-capable source
    *could* vary by those even though Travelpayouts (the only adopted
    source, issue #41) does not — collapsing further than a source actually
    supports is that source adapter's own decision, not this domain
    function's to assume for every source.
    """

    origin: str
    destination: str
    month: str  # "YYYY-MM"
    cabin: str
    trip_length_nights: int
    tasks: tuple[SearchTask, ...]


def collapse_batchable(tasks: list[SearchTask]) -> list[BatchGroup]:
    groups: dict[tuple[str, str, str, str, int], list[SearchTask]] = {}
    for task in tasks:
        key = (
            task.origin,
            task.destination,
            f"{task.departure_date.year:04d}-{task.departure_date.month:02d}",
            task.cabin,
            task.trip_length_nights,
        )
        groups.setdefault(key, []).append(task)

    return [
        BatchGroup(
            origin=origin,
            destination=destination,
            month=month,
            cabin=cabin,
            trip_length_nights=trip_length_nights,
            tasks=tuple(group_tasks),
        )
        for (origin, destination, month, cabin, trip_length_nights), group_tasks in groups.items()
    ]
