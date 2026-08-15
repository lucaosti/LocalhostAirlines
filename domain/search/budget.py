"""Query budget as a first-class domain object (spec §28). Pure, no I/O.

Every search declares how many source calls it may spend. This module scores
each candidate task by expected information gain and decides which ones are
worth spending budget on; the rest are `NOT_EXPLORED`, not "no results" —
that distinction is the entire point of spec §28 point 5: a route the system
chose not to probe is unknown, not empty, and the interface must say so (P3).

"Never observed" requires knowing what is already in cash_observations for
staleness scoring — that lookup belongs to the orchestrator, which has a
database session. This module only scores and allocates; it takes whatever
observation state the orchestrator already fetched as a plain argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from domain.search.expansion import SearchTask


@dataclass(frozen=True)
class GainWeights:
    """Configured, not hardcoded thresholds — spec's own non-negotiable
    (CLAUDE.md §5: "no mutable business fact as a code constant"). The
    values here are defaults a caller may override, not the only valid
    tuning; what the ordering guarantee in `score_task` does NOT depend
    on is any particular choice of these numbers (see its docstring)."""

    novelty: float = 10.0
    staleness: float = 5.0
    preference: float = 2.0
    proximity: float = 1.0


@dataclass(frozen=True)
class ObservationState:
    """What the orchestrator already knows about a task's itinerary before
    deciding whether it is worth a fresh call. `last_observed_at=None` means
    never observed — the strongest possible novelty signal, distinct from
    "observed a long time ago"."""

    last_observed_at: date | None


@dataclass(frozen=True)
class ScoredTask:
    task: SearchTask
    # The spec §28 weighted-sum formula, computed and exposed for
    # observability (e.g. explaining why a route was or wasn't explored) —
    # it is NOT what `rank_tasks` sorts by; see that function's docstring
    # for why a plain float sum cannot make the ordering guarantee alone.
    gain: float
    never_observed: bool
    normalized_age: float
    preference: float
    normalized_closeness: float


def score_task(
    task: SearchTask,
    observation: ObservationState,
    *,
    origin_weight: int,
    destination_weight: int,
    reference_date: date,
    max_staleness_days: int,
    weights: GainWeights = GainWeights(),
) -> ScoredTask:
    """Computes spec §28's gain formula for one task.

    `origin_weight`/`destination_weight` are the 0-100 values from
    `WeightedLocation` (domain/search/expansion.py) — ranking-only per spec
    §27, never a filter, which is exactly what this function does with them:
    they can only move a task up or down the order, never remove it.
    """
    last_observed_at = observation.last_observed_at
    never_observed = last_observed_at is None
    if last_observed_at is None:
        normalized_age = 0.0
    else:
        age_days = (reference_date - last_observed_at).days
        normalized_age = _clamp01(age_days / max_staleness_days) if max_staleness_days > 0 else 1.0

    normalized_closeness = _closeness(task.departure_date, reference_date)
    preference = _clamp01(origin_weight / 100) * _clamp01(destination_weight / 100)

    gain = (
        weights.novelty * (1.0 if never_observed else 0.0)
        + weights.staleness * normalized_age
        + weights.preference * preference
        + weights.proximity * normalized_closeness
    )

    return ScoredTask(
        task=task,
        gain=gain,
        never_observed=never_observed,
        normalized_age=normalized_age,
        preference=preference,
        normalized_closeness=normalized_closeness,
    )


def _closeness(departure_date: date, reference_date: date, horizon_days: int = 365) -> float:
    """1.0 for a departure date today, decaying to 0.0 at `horizon_days` out
    — a near-term date is more actionable than one a year away, all else
    equal. Dates in the past (should not occur for a live search, but a
    persistent watch's stale query might produce one) clamp to 0.0 rather
    than going negative."""
    days_out = (departure_date - reference_date).days
    if days_out <= 0:
        return 1.0 if days_out == 0 else 0.0
    return _clamp01(1.0 - days_out / horizon_days)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _rank_key(scored: ScoredTask, weights: GainWeights) -> tuple[int, float, float]:
    """The sort key spec §28 point 3 actually requires: "Never observed
    therefore outranks stale, which outranks recently observed, ... with
    user preference and date proximity breaking ties." That is a
    lexicographic guarantee, not a property a single weighted-sum float can
    provide — a caller free to tune weights could always set
    w_preference high enough to make a recently-observed, high-preference
    task outscore a stale, low-preference one under plain summation, which
    is precisely the ordering the acceptance criteria forbid.

    So ranking compares tiers first (never-observed, then staleness) and
    only falls back to a weights-scaled preference/proximity sum to break a
    tie *within* the same tier. `gain` above still reports the literal
    formula for observability; this tuple is what `rank_tasks` sorts by.
    """
    tie_break = (
        weights.preference * scored.preference + weights.proximity * scored.normalized_closeness
    )
    return (
        1 if scored.never_observed else 0,
        scored.normalized_age if not scored.never_observed else 0.0,
        tie_break,
    )


def rank_tasks(
    scored_tasks: list[ScoredTask], weights: GainWeights = GainWeights()
) -> list[ScoredTask]:
    """Descending by (never_observed, normalized_age, tie_break) — the
    lexicographic ordering spec §28 point 3 states in prose. See `_rank_key`
    for why this cannot be a sort on `gain` alone."""
    return sorted(scored_tasks, key=lambda s: _rank_key(s, weights), reverse=True)


@dataclass(frozen=True)
class BudgetAllocation:
    to_execute: tuple[SearchTask, ...]
    not_explored: tuple[SearchTask, ...]


def allocate_budget(
    scored_tasks: list[ScoredTask], *, budget: int, weights: GainWeights = GainWeights()
) -> BudgetAllocation:
    """Executes the highest-ranked tasks until `budget` calls are spent,
    marking the remainder `NOT_EXPLORED` (spec §28 points 4-5). One task
    costs one call — batch collapsing (domain/search/expansion.py's
    `collapse_batchable`) happens before this function runs, so by the time
    a task reaches here it is already the unit this budget counts."""
    if budget < 0:
        raise ValueError("budget must not be negative")

    ranked = rank_tasks(scored_tasks, weights)
    to_execute = ranked[:budget]
    not_explored = ranked[budget:]
    return BudgetAllocation(
        to_execute=tuple(s.task for s in to_execute),
        not_explored=tuple(s.task for s in not_explored),
    )
