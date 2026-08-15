"""domain/search/budget.py — pure, no I/O, no database."""

from datetime import date, timedelta

import pytest

from domain.search.budget import (
    BudgetAllocation,
    GainWeights,
    ObservationState,
    allocate_budget,
    rank_tasks,
    score_task,
)
from domain.search.expansion import SearchTask

TODAY = date(2026, 8, 15)


def _task(**overrides) -> SearchTask:
    defaults = dict(
        origin="MXP",
        destination="NRT",
        departure_date=TODAY + timedelta(days=30),
        trip_length_nights=10,
        cabin="economy",
    )
    defaults.update(overrides)
    return SearchTask(**defaults)


def _scored(task, *, never_observed=True, age_days=None, origin_weight=0, destination_weight=0):
    observation = ObservationState(
        last_observed_at=None if never_observed else TODAY - timedelta(days=age_days)
    )
    return score_task(
        task,
        observation,
        origin_weight=origin_weight,
        destination_weight=destination_weight,
        reference_date=TODAY,
        max_staleness_days=90,
    )


def test_never_observed_scores_maximum_novelty() -> None:
    scored = _scored(_task(), never_observed=True)
    assert scored.never_observed is True
    assert scored.normalized_age == 0.0


def test_stale_observation_scores_near_one() -> None:
    scored = _scored(_task(), never_observed=False, age_days=90)
    assert scored.normalized_age == 1.0


def test_recent_observation_scores_near_zero() -> None:
    scored = _scored(_task(), never_observed=False, age_days=1)
    assert 0.0 < scored.normalized_age < 0.02


def test_zero_max_staleness_days_does_not_divide_by_zero() -> None:
    observation = ObservationState(last_observed_at=TODAY - timedelta(days=5))
    scored = score_task(
        _task(),
        observation,
        origin_weight=0,
        destination_weight=0,
        reference_date=TODAY,
        max_staleness_days=0,
    )
    assert scored.normalized_age == 1.0


def test_never_observed_outranks_stale_regardless_of_weight_tuning() -> None:
    never_observed = _scored(_task(origin="MXP"), never_observed=True, origin_weight=0)
    stale_but_preferred = _scored(
        _task(origin="LHR"),
        never_observed=False,
        age_days=89,
        origin_weight=100,
        destination_weight=100,
    )
    # Weights tuned to try to make preference dominate novelty.
    skewed_weights = GainWeights(novelty=0.01, staleness=0.01, preference=1000.0, proximity=1000.0)
    ranked = rank_tasks([stale_but_preferred, never_observed], skewed_weights)
    assert ranked[0].never_observed is True


def test_stale_outranks_recently_observed_regardless_of_weight_tuning() -> None:
    stale = _scored(_task(origin="MXP"), never_observed=False, age_days=89, origin_weight=0)
    recent_but_preferred = _scored(
        _task(origin="LHR"),
        never_observed=False,
        age_days=1,
        origin_weight=100,
        destination_weight=100,
    )
    skewed_weights = GainWeights(novelty=0.01, staleness=0.01, preference=1000.0, proximity=1000.0)
    ranked = rank_tasks([recent_but_preferred, stale], skewed_weights)
    assert ranked[0].normalized_age == stale.normalized_age


def test_preference_breaks_ties_within_same_tier() -> None:
    low_preference = _scored(
        _task(origin="MXP"), never_observed=True, origin_weight=0, destination_weight=0
    )
    high_preference = _scored(
        _task(origin="LHR"), never_observed=True, origin_weight=100, destination_weight=100
    )
    ranked = rank_tasks([low_preference, high_preference])
    assert ranked[0].preference > ranked[1].preference


def test_allocate_budget_splits_execute_and_not_explored() -> None:
    scored = [_scored(_task(destination=f"D{i}"), never_observed=True) for i in range(5)]
    allocation = allocate_budget(scored, budget=2)
    assert isinstance(allocation, BudgetAllocation)
    assert len(allocation.to_execute) == 2
    assert len(allocation.not_explored) == 3


def test_allocate_budget_zero_executes_nothing() -> None:
    scored = [_scored(_task(), never_observed=True)]
    allocation = allocate_budget(scored, budget=0)
    assert allocation.to_execute == ()
    assert len(allocation.not_explored) == 1


def test_allocate_budget_exceeding_task_count_executes_everything() -> None:
    scored = [_scored(_task(), never_observed=True)]
    allocation = allocate_budget(scored, budget=100)
    assert len(allocation.to_execute) == 1
    assert allocation.not_explored == ()


def test_negative_budget_rejected() -> None:
    with pytest.raises(ValueError, match="budget must not be negative"):
        allocate_budget([], budget=-1)


def test_closeness_departure_today_scores_one() -> None:
    scored = _scored(_task(departure_date=TODAY), never_observed=True)
    assert scored.normalized_closeness == 1.0


def test_closeness_far_future_departure_decays_toward_zero() -> None:
    scored = _scored(_task(departure_date=TODAY + timedelta(days=364)), never_observed=True)
    assert 0.0 <= scored.normalized_closeness < 0.01


def test_closeness_past_departure_clamps_to_zero() -> None:
    scored = _scored(_task(departure_date=TODAY - timedelta(days=10)), never_observed=True)
    assert scored.normalized_closeness == 0.0
