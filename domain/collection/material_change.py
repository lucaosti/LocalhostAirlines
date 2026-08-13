"""Material-change decision for observation writes (issue #54; spec §56).
Pure, no I/O.

"An observation row represents a period during which a value held, not a
single poll... An identical repeat poll extends last_seen_at and increments
poll_count instead of writing a row" (spec §56). This is required for
percentile correctness, not merely a space optimisation: a route polled
hourly must not outweigh one polled daily in a later percentile calculation.

Spec §56 names price, availability, cabin, fare, schedule, award points and
award availability as material. Scoped here to what Travelpayouts'
price-calendar endpoint actually states — price and currency — since
comparing fields a source never provides would be comparing None to None
and calling it "unchanged" by accident. Cabin/fare/availability comparisons
are added when a source that states them lands, not guessed at now.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObservedValue:
    price_minor: int
    currency: str


def is_material_change(previous: ObservedValue | None, current: ObservedValue) -> bool:
    """True if `current` should close the previous period and open a new one."""
    if previous is None:
        return True
    return previous.price_minor != current.price_minor or previous.currency != current.currency
