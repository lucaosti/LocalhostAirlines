"""Hard filters versus preferences (spec §37). Pure, no I/O.

"Hard filters eliminate candidates. Preferences reorder them. The
distinction is presented explicitly in the interface" (spec §37) — and it
has to be structural here, not a UI label glued on afterward, or a filter
could silently start reordering instead of eliminating (or vice versa)
without anything catching it. `apply_hard_filters` can only shrink the
candidate list; `apply_preferences` can only permute it — the type
signatures make the second incapable of removing anything.

Scoring itself (bands, weighted breakdown) is M9 (docs/adr/0006); this
module is only the elimination/reorder split preferences plug into once
that scoring function exists.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import time

from domain.flight.model import FlightOffer

HardPredicate = Callable[[FlightOffer], bool]  # True = survives, False = eliminated
PreferenceScore = Callable[[FlightOffer], float]  # higher = ranked first; never eliminates


@dataclass(frozen=True)
class HardFilter:
    name: str  # shown to the user verbatim when it is the reason for zero results
    predicate: HardPredicate


@dataclass(frozen=True)
class Preference:
    name: str
    score: PreferenceScore


@dataclass(frozen=True)
class FilterOutcome:
    name: str
    removed_count: int


@dataclass(frozen=True)
class HardFilterResult:
    survivors: tuple[FlightOffer, ...]
    outcomes: tuple[FilterOutcome, ...]

    @property
    def eliminated_by(self) -> tuple[FilterOutcome, ...]:
        """The filters that actually removed something, in application
        order. When `survivors` is empty, this is what the interface names
        as the cause (spec §37: "the interface names the filter and how
        many results it removed") — distinct from a search that legitimately
        found nothing before any filter ran."""
        return tuple(outcome for outcome in self.outcomes if outcome.removed_count > 0)


def apply_hard_filters(
    offers: Sequence[FlightOffer], filters: Sequence[HardFilter]
) -> HardFilterResult:
    """Applies filters sequentially so each `FilterOutcome.removed_count` is
    that filter's own contribution — an offer eliminated by an earlier
    filter is not double-counted against a later one it never reached."""
    remaining: list[FlightOffer] = list(offers)
    outcomes = []
    for hard_filter in filters:
        before = len(remaining)
        remaining = [offer for offer in remaining if hard_filter.predicate(offer)]
        outcomes.append(FilterOutcome(name=hard_filter.name, removed_count=before - len(remaining)))
    return HardFilterResult(survivors=tuple(remaining), outcomes=tuple(outcomes))


def apply_preferences(
    offers: Sequence[FlightOffer], preferences: Sequence[Preference]
) -> tuple[FlightOffer, ...]:
    """Reorders by the summed preference score, stable on ties (Python's
    sort is stable, so equally-scored offers keep their incoming relative
    order rather than an arbitrary one). Cannot remove an offer — there is
    no code path here that produces a shorter sequence than it received."""

    def total_score(offer: FlightOffer) -> float:
        return sum(preference.score(offer) for preference in preferences)

    return tuple(sorted(offers, key=total_score, reverse=True))


# --- Concrete hard filters -------------------------------------------------
#
# Only the ones the canonical FlightOffer model (domain/flight/model.py) can
# actually answer. "No self-transfer" from spec §37's own example table is
# deliberately not built here: distinguishing a through-ticketed connection
# from a self-transfer requires a field the model does not carry yet (no
# provider normalized into one). Adding it here would mean guessing at
# every offer's self-transfer status, which is exactly the false precision
# spec P4 forbids — it belongs in domain/flight/model.py first, as real
# data, not invented inside a filter.


def cabin_filter(required_cabin: str) -> HardFilter:
    """Missing cabin data does not pass a cabin filter — the filter cannot
    confirm the requirement is met, and admitting an unverifiable offer
    would silently weaken what the user asked to exclude."""
    return HardFilter(
        name=f"cabin={required_cabin}",
        predicate=lambda offer: offer.cabin == required_cabin,
    )


def max_stops_filter(max_stops: int) -> HardFilter:
    """Stops counted per slice (segments - 1), and an offer must satisfy the
    limit on every slice — a one-stop outbound with a nonstop return is
    still a "maximum 1 stop" itinerary; a two-stop outbound is not, even if
    its return is nonstop."""

    def predicate(offer: FlightOffer) -> bool:
        return all(len(slice_.segments) - 1 <= max_stops for slice_ in offer.slices)

    return HardFilter(name=f"max_stops={max_stops}", predicate=predicate)


def arrive_before_filter(cutoff: time, *, slice_index: int = 0) -> HardFilter:
    """Arrival time of the last segment of the given slice (default: the
    outbound), in that segment's own departure_utc timezone... actually
    UTC — arrival_utc is the only arrival time the model carries. A missing
    arrival_utc (spec P4: a legitimately absent value) cannot be compared
    against the cutoff, so it does not pass — the same fail-closed choice
    as `cabin_filter`, for the same reason."""

    def predicate(offer: FlightOffer) -> bool:
        if slice_index >= len(offer.slices):
            return False
        last_segment = offer.slices[slice_index].segments[-1]
        if last_segment.arrival_utc is None:
            return False
        return last_segment.arrival_utc.time() <= cutoff

    return HardFilter(name=f"arrive_before={cutoff.isoformat()}", predicate=predicate)


# --- Concrete preferences ---------------------------------------------------


def airline_preference(weights: dict[str, int]) -> Preference:
    """Prefers offers whose validating carrier has a higher configured
    weight (spec §27's own rule reused here: weights rank, they never
    filter — an airline absent from `weights` scores 0, not excluded)."""

    def score(offer: FlightOffer) -> float:
        if offer.validating_carrier is None:
            return 0.0
        return float(weights.get(offer.validating_carrier, 0))

    return Preference(name="airline", score=score)


def directness_preference(weight: float = 1.0) -> Preference:
    """Prefers fewer total stops across all slices, scaled by `weight` so it
    can be balanced against other preferences without being a hard cutoff —
    a one-stop itinerary is still shown, just ranked below a nonstop one."""

    def score(offer: FlightOffer) -> float:
        total_stops = sum(len(slice_.segments) - 1 for slice_ in offer.slices)
        return -weight * total_stops

    return Preference(name="directness", score=score)


def time_of_day_preference(
    preferred_start: time, preferred_end: time, weight: float = 1.0
) -> Preference:
    """Prefers a departure time falling inside [preferred_start,
    preferred_end] (e.g. "morning departure") on the first slice's first
    segment. An offer with no stated departure time cannot occur — departure
    is required, unlike arrival — so this never needs a missing-data case."""

    def score(offer: FlightOffer) -> float:
        if not offer.slices or not offer.slices[0].segments:
            return 0.0
        departure = offer.slices[0].segments[0].departure_utc.time()
        return weight if preferred_start <= departure <= preferred_end else 0.0

    return Preference(name="time_of_day", score=score)
