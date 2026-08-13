"""Monthly partition naming and bounds (issue #53; spec §55). Pure, no I/O.

Partitions are runtime objects maintained by a scheduled job, not
represented in migrations (spec §55's own stated split) — this module is
the naming/bounds logic that job (and the retention job) both build on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PartitionBounds:
    name: str
    lower: date  # inclusive
    upper: date  # exclusive


def partition_for_month(table: str, year: int, month: int) -> PartitionBounds:
    lower = date(year, month, 1)
    upper = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return PartitionBounds(name=f"{table}_p{year:04d}_{month:02d}", lower=lower, upper=upper)


def months_from(start: date, count: int) -> list[tuple[int, int]]:
    """`count` consecutive (year, month) pairs starting at `start`'s month."""
    year, month = start.year, start.month
    result = []
    for _ in range(count):
        result.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return result
