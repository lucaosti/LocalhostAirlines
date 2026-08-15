"""domain/search/expansion.py — pure, no I/O, no database."""

from datetime import date

from domain.search.expansion import (
    SearchQuery,
    WeightedLocation,
    collapse_batchable,
    expand,
)


def _query(**overrides) -> SearchQuery:
    defaults = dict(
        origins=(WeightedLocation("MXP", 100),),
        destinations=(WeightedLocation("NRT", 0),),
        date_start=date(2026, 10, 1),
        date_end=date(2026, 10, 3),
        min_nights=3,
        max_nights=4,
        cabins=("business",),
    )
    defaults.update(overrides)
    return SearchQuery(**defaults)


def test_expansion_produces_the_full_cartesian_product() -> None:
    tasks = expand(_query())
    # 1 origin * 1 destination * 3 dates * 2 trip lengths (3,4) * 1 cabin = 6
    assert len(tasks) == 6


def test_multi_origin_destination_multiplies_correctly() -> None:
    tasks = expand(
        _query(
            origins=(WeightedLocation("MXP"), WeightedLocation("LIN"), WeightedLocation("FCO")),
            destinations=(WeightedLocation("NRT"), WeightedLocation("HND")),
            date_start=date(2026, 10, 1),
            date_end=date(2026, 10, 1),
            min_nights=3,
            max_nights=3,
            cabins=("business", "economy"),
        )
    )
    # 3 origins * 2 destinations * 1 date * 1 trip length * 2 cabins = 12
    assert len(tasks) == 12


def test_weights_are_carried_but_never_filter() -> None:
    tasks = expand(_query(origins=(WeightedLocation("FCO", weight=0),)))
    # A zero-weight origin still produces tasks — weight influences ranking,
    # never elimination (spec §27's own explicit rule).
    assert all(t.origin == "FCO" for t in tasks)
    assert len(tasks) > 0


def test_return_date_is_departure_plus_trip_length() -> None:
    tasks = expand(
        _query(date_start=date(2026, 10, 1), date_end=date(2026, 10, 1), min_nights=5, max_nights=5)
    )
    assert tasks[0].return_date == date(2026, 10, 6)


def test_collapse_batchable_groups_by_month_ignoring_day() -> None:
    tasks = expand(
        _query(date_start=date(2026, 10, 1), date_end=date(2026, 10, 3), min_nights=3, max_nights=3)
    )
    groups = collapse_batchable(tasks)
    # All three dates fall in the same month, same cabin, same trip length —
    # one batch group, not three.
    assert len(groups) == 1
    assert len(groups[0].tasks) == 3


def test_collapse_batchable_keeps_different_months_separate() -> None:
    tasks = expand(
        _query(
            date_start=date(2026, 10, 30), date_end=date(2026, 11, 2), min_nights=3, max_nights=3
        )
    )
    groups = collapse_batchable(tasks)
    months = {g.month for g in groups}
    assert months == {"2026-10", "2026-11"}


def test_collapse_batchable_keeps_different_cabins_separate() -> None:
    tasks = expand(
        _query(
            date_start=date(2026, 10, 1),
            date_end=date(2026, 10, 1),
            min_nights=3,
            max_nights=3,
            cabins=("business", "economy"),
        )
    )
    groups = collapse_batchable(tasks)
    assert len(groups) == 2
    assert {g.cabin for g in groups} == {"business", "economy"}
