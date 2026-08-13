"""domain/reliability/circuit_breaker.py — pure, no I/O, no database."""

from datetime import UTC, datetime, timedelta

from domain.reliability.circuit_breaker import (
    COOLDOWN,
    FAILURE_THRESHOLD,
    CircuitSnapshot,
    CircuitState,
    initial_snapshot,
    may_attempt,
    next_state_after_failure,
    next_state_after_success,
)

NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)


def test_initial_snapshot_is_closed() -> None:
    snap = initial_snapshot()
    assert snap.state == CircuitState.CLOSED
    assert snap.consecutive_failures == 0
    assert snap.opened_at is None


def test_stays_closed_below_threshold() -> None:
    snap = initial_snapshot()
    for _ in range(FAILURE_THRESHOLD - 1):
        snap = next_state_after_failure(snap, NOW)
    assert snap.state == CircuitState.CLOSED


def test_opens_at_threshold() -> None:
    snap = initial_snapshot()
    for _ in range(FAILURE_THRESHOLD):
        snap = next_state_after_failure(snap, NOW)
    assert snap.state == CircuitState.OPEN
    assert snap.opened_at == NOW


def test_success_fully_resets() -> None:
    snap = initial_snapshot()
    for _ in range(FAILURE_THRESHOLD):
        snap = next_state_after_failure(snap, NOW)
    assert snap.state == CircuitState.OPEN

    reset = next_state_after_success(snap)
    assert reset == initial_snapshot()


def test_open_blocks_calls_before_cooldown() -> None:
    opened = CircuitSnapshot(state=CircuitState.OPEN, consecutive_failures=3, opened_at=NOW)
    allowed, snapshot = may_attempt(opened, NOW + timedelta(minutes=1))
    assert allowed is False
    assert snapshot == opened  # unchanged — no premature half-open


def test_open_admits_one_trial_after_cooldown() -> None:
    opened = CircuitSnapshot(state=CircuitState.OPEN, consecutive_failures=3, opened_at=NOW)
    allowed, snapshot = may_attempt(opened, NOW + COOLDOWN)
    assert allowed is True
    assert snapshot.state == CircuitState.HALF_OPEN


def test_half_open_trial_failure_reopens_and_restarts_cooldown() -> None:
    half_open = CircuitSnapshot(state=CircuitState.HALF_OPEN, consecutive_failures=3, opened_at=NOW)
    later = NOW + COOLDOWN + timedelta(minutes=5)
    reopened = next_state_after_failure(half_open, later)
    assert reopened.state == CircuitState.OPEN
    assert reopened.opened_at == later  # cooldown restarts from the new failure


def test_half_open_trial_success_fully_resets() -> None:
    half_open = CircuitSnapshot(state=CircuitState.HALF_OPEN, consecutive_failures=3, opened_at=NOW)
    assert next_state_after_success(half_open) == initial_snapshot()


def test_closed_always_allows() -> None:
    allowed, snapshot = may_attempt(initial_snapshot(), NOW)
    assert allowed is True
    assert snapshot == initial_snapshot()
