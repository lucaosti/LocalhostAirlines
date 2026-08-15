"""Circuit breaker decision logic (spec §21, §25). Pure, no I/O.

"Repeated BLOCKED classifications reduce the access rate automatically
rather than triggering retries" (spec §26, restated for Google Flights but
general to every fragile source). This module decides CLOSED/OPEN/HALF_OPEN
from a small state snapshot; persistence lives in
infrastructure/postgres/source_health.py, which is also the layer that
decides which spec §26 error kinds count as a circuit-relevant failure.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta


class CircuitState(enum.StrEnum):
    CLOSED = "closed"  # normal operation
    OPEN = "open"  # tripped — calls blocked until cooldown elapses
    HALF_OPEN = "half_open"  # cooldown elapsed, exactly one trial call allowed


# Three consecutive circuit-relevant failures trip the breaker; a fifteen
# minute cooldown before the next trial. Both are conservative defaults —
# tuning these against real failure patterns is a later concern, not a
# reason to leave the mechanism unbuilt now.
FAILURE_THRESHOLD = 3
COOLDOWN = timedelta(minutes=15)


@dataclass(frozen=True)
class CircuitSnapshot:
    state: CircuitState
    consecutive_failures: int
    opened_at: datetime | None


def initial_snapshot() -> CircuitSnapshot:
    return CircuitSnapshot(state=CircuitState.CLOSED, consecutive_failures=0, opened_at=None)


def next_state_after_failure(snapshot: CircuitSnapshot, now: datetime) -> CircuitSnapshot:
    failures = snapshot.consecutive_failures + 1

    if snapshot.state == CircuitState.HALF_OPEN:
        # The trial call itself failed — back to fully open, cooldown restarts.
        return CircuitSnapshot(
            state=CircuitState.OPEN, consecutive_failures=failures, opened_at=now
        )

    if failures >= FAILURE_THRESHOLD:
        return CircuitSnapshot(
            state=CircuitState.OPEN,
            consecutive_failures=failures,
            opened_at=snapshot.opened_at or now,
        )

    return CircuitSnapshot(state=CircuitState.CLOSED, consecutive_failures=failures, opened_at=None)


def next_state_after_success(snapshot: CircuitSnapshot) -> CircuitSnapshot:
    # Any success — including the half-open trial call — fully resets the
    # breaker. A source that recovers doesn't need to "earn back" trust
    # gradually; spec §21's concern is stopping an aggressive access
    # pattern, not rate-limiting a healthy source.
    return initial_snapshot()


def may_attempt(snapshot: CircuitSnapshot, now: datetime) -> tuple[bool, CircuitSnapshot]:
    """Whether a call may proceed, and the snapshot to persist afterward.

    Moves OPEN -> HALF_OPEN once the cooldown has elapsed, admitting exactly
    one trial call. The caller is responsible for reporting that call's
    outcome via next_state_after_success/failure — this function only
    decides whether to let the call happen.
    """
    if snapshot.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN):
        return True, snapshot

    # OPEN
    assert snapshot.opened_at is not None, "OPEN snapshot must carry opened_at"
    if now - snapshot.opened_at >= COOLDOWN:
        return True, CircuitSnapshot(
            state=CircuitState.HALF_OPEN,
            consecutive_failures=snapshot.consecutive_failures,
            opened_at=snapshot.opened_at,
        )
    return False, snapshot
