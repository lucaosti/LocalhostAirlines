"""Collapses search-space batching down to what a real source can answer in
one call, and counts the resulting {total, explored, not_explored} space
docs/api.md §5 "Retrieve" reports (spec §28 point 5, §32). Pure, no I/O.

Travelpayouts' price-calendar endpoint answers one (origin, destination,
month) combination per call — it does not vary by cabin or trip length at
all (docs/providers.md). `BatchGroup` (domain/search/expansion.py) already
collapses the departure-date dimension per (origin, destination, month,
cabin, trip_length); this module collapses one step further, because for
this source cabin and trip length cost nothing extra — one call answers
every `BatchGroup` sharing the same (origin, destination, month). This is
specific to what Travelpayouts can answer, not a general truth about every
source: a future source that genuinely varies its response by cabin would
need its own fetch granularity, not this one reused unmodified.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.search.expansion import BatchGroup, SearchTask


@dataclass(frozen=True)
class FetchGroup:
    """One real network call's worth of work — the unit the query budget
    (domain/search/budget.py) actually spends against for this source."""

    origin: str
    destination: str
    month: str  # "YYYY-MM"
    batch_groups: tuple[BatchGroup, ...]

    @property
    def task_count(self) -> int:
        return sum(len(group.tasks) for group in self.batch_groups)

    @property
    def representative_task(self) -> SearchTask:
        """A single task standing in for the whole group, for budget scoring
        (domain/search/budget.py needs one departure date per candidate).
        The earliest departure date in the group is a deterministic,
        arbitrary-but-consistent choice — any task in the group shares the
        same origin/destination/month, so only the date-proximity term of
        the gain formula actually varies by which one is picked."""
        all_tasks = [task for group in self.batch_groups for task in group.tasks]
        return min(all_tasks, key=lambda task: task.departure_date)


def collapse_to_fetch_groups(batch_groups: list[BatchGroup]) -> list[FetchGroup]:
    grouped: dict[tuple[str, str, str], list[BatchGroup]] = {}
    for group in batch_groups:
        key = (group.origin, group.destination, group.month)
        grouped.setdefault(key, []).append(group)

    return [
        FetchGroup(origin=origin, destination=destination, month=month, batch_groups=tuple(groups))
        for (origin, destination, month), groups in grouped.items()
    ]


@dataclass(frozen=True)
class SpaceCounts:
    total: int
    explored: int
    not_explored: int


def count_space(
    all_tasks: list[SearchTask], executed_fetch_groups: list[FetchGroup]
) -> SpaceCounts:
    """`total` is the raw expansion (domain/search/expansion.py's `expand`),
    matching spec §28's "roughly 2,200 combinations" as a property of the
    unbatched space. `explored` sums the task counts of only the fetch
    groups the budget actually paid for — a fetch group that ran but whose
    quality gate rejected every offer is still "explored", because the
    space count answers "did we ask", not "did we get a result" (spec §32:
    NOT_EXPLORED is never confused with "asked and found nothing")."""
    total = len(all_tasks)
    explored = sum(group.task_count for group in executed_fetch_groups)
    return SpaceCounts(total=total, explored=explored, not_explored=total - explored)
