"""domain/collection/partition_bounds.py — pure, no I/O, no database."""

from datetime import date

from domain.collection.partition_bounds import months_from, partition_for_month


def test_partition_name_and_bounds() -> None:
    bounds = partition_for_month("cash_observations", 2026, 10)
    assert bounds.name == "cash_observations_p2026_10"
    assert bounds.lower == date(2026, 10, 1)
    assert bounds.upper == date(2026, 11, 1)


def test_december_rolls_over_to_next_year() -> None:
    bounds = partition_for_month("raw_payloads", 2026, 12)
    assert bounds.name == "raw_payloads_p2026_12"
    assert bounds.lower == date(2026, 12, 1)
    assert bounds.upper == date(2027, 1, 1)


def test_months_from_generates_consecutive_pairs() -> None:
    assert months_from(date(2026, 11, 15), 4) == [
        (2026, 11),
        (2026, 12),
        (2027, 1),
        (2027, 2),
    ]


def test_months_from_zero_count_is_empty() -> None:
    assert months_from(date(2026, 1, 1), 0) == []
