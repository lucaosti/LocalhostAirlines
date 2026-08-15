"""domain/search/orchestration.py — pure, no I/O, no database."""

from datetime import date

from domain.search.expansion import SearchQuery, WeightedLocation, collapse_batchable, expand
from domain.search.orchestration import collapse_to_fetch_groups, count_space


def _query(**overrides) -> SearchQuery:
    defaults = dict(
        origins=(WeightedLocation("MXP"),),
        destinations=(WeightedLocation("NRT"),),
        date_start=date(2026, 10, 1),
        date_end=date(2026, 10, 5),
        min_nights=7,
        max_nights=8,
        cabins=("economy", "business"),
    )
    defaults.update(overrides)
    return SearchQuery(**defaults)


def test_fetch_groups_collapse_cabin_and_trip_length() -> None:
    tasks = expand(_query())
    batch_groups = collapse_batchable(tasks)
    fetch_groups = collapse_to_fetch_groups(batch_groups)
    # 5 dates x 2 nights x 2 cabins = 20 tasks, but every task shares the
    # same (origin, destination, month) — one fetch group for all of them.
    assert len(fetch_groups) == 1
    assert fetch_groups[0].task_count == 20


def test_fetch_groups_split_by_month() -> None:
    tasks = expand(_query(date_start=date(2026, 10, 28), date_end=date(2026, 11, 3)))
    fetch_groups = collapse_to_fetch_groups(collapse_batchable(tasks))
    months = {group.month for group in fetch_groups}
    assert months == {"2026-10", "2026-11"}


def test_fetch_groups_split_by_route() -> None:
    tasks = expand(
        _query(
            origins=(WeightedLocation("MXP"), WeightedLocation("LIN")),
            destinations=(WeightedLocation("NRT"),),
        )
    )
    fetch_groups = collapse_to_fetch_groups(collapse_batchable(tasks))
    routes = {(group.origin, group.destination) for group in fetch_groups}
    assert routes == {("MXP", "NRT"), ("LIN", "NRT")}


def test_representative_task_is_earliest_departure() -> None:
    tasks = expand(_query())
    fetch_group = collapse_to_fetch_groups(collapse_batchable(tasks))[0]
    assert fetch_group.representative_task.departure_date == date(2026, 10, 1)


def test_space_counts_all_executed() -> None:
    tasks = expand(_query())
    fetch_groups = collapse_to_fetch_groups(collapse_batchable(tasks))
    counts = count_space(tasks, fetch_groups)
    assert counts.total == 20
    assert counts.explored == 20
    assert counts.not_explored == 0


def test_space_counts_none_executed() -> None:
    tasks = expand(_query())
    counts = count_space(tasks, [])
    assert counts.total == 20
    assert counts.explored == 0
    assert counts.not_explored == 20


def test_space_counts_partial_execution() -> None:
    tasks = expand(
        _query(
            origins=(WeightedLocation("MXP"), WeightedLocation("LIN")),
            destinations=(WeightedLocation("NRT"),),
        )
    )
    fetch_groups = collapse_to_fetch_groups(collapse_batchable(tasks))
    executed = [group for group in fetch_groups if group.origin == "MXP"]
    counts = count_space(tasks, executed)
    assert counts.explored == 20
    assert counts.not_explored == 20
    assert counts.total == 40
