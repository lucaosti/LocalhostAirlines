"""Per-source circuit breaker, backed by SourceHealth (spec §21, §25).

Bridges the pure decision logic in domain/reliability/circuit_breaker.py to
persistence, and decides which spec §26 error kinds are circuit-relevant in
the first place — a source being temporarily hostile (RATE_LIMIT, BLOCKED,
UPSTREAM_ERROR, TIMEOUT) is a different fact from our own request being
wrong (BAD_REQUEST, AUTHENTICATION) or the payload not matching what we
expected (SCHEMA_CHANGE) or the source legitimately having nothing to say
(NOT_AVAILABLE) — none of those mean the source itself is struggling, so
none of them should trip a breaker that exists to protect the source from
an access pattern that's too aggressive (spec §21).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from domain.reliability.circuit_breaker import (
    CircuitSnapshot,
    CircuitState,
    initial_snapshot,
    may_attempt,
    next_state_after_failure,
    next_state_after_success,
)
from infrastructure.postgres.models_health import SourceHealth
from providers.errors import SourceErrorKind

CIRCUIT_RELEVANT_KINDS = frozenset(
    {
        SourceErrorKind.RATE_LIMIT,
        SourceErrorKind.BLOCKED,
        SourceErrorKind.UPSTREAM_ERROR,
        SourceErrorKind.TIMEOUT,
    }
)


async def may_call(db: AsyncSession, source: str) -> bool:
    """Whether `source` may be called right now. Persists the OPEN ->
    HALF_OPEN transition immediately if the cooldown has elapsed, so a
    concurrent caller sees the same admitted trial rather than both
    independently deciding to try."""
    health = await db.get(SourceHealth, source)
    snapshot = _snapshot_from_row(health)

    allowed, next_snapshot = may_attempt(snapshot, datetime.now(UTC))
    if next_snapshot != snapshot:
        await _persist(db, source, next_snapshot)
    return allowed


async def record_success(db: AsyncSession, source: str) -> None:
    health = await db.get(SourceHealth, source)
    snapshot = _snapshot_from_row(health)
    await _persist(db, source, next_state_after_success(snapshot), success=True)


async def record_failure(db: AsyncSession, source: str, kind: SourceErrorKind) -> None:
    if kind not in CIRCUIT_RELEVANT_KINDS:
        return
    health = await db.get(SourceHealth, source)
    snapshot = _snapshot_from_row(health)
    await _persist(
        db, source, next_state_after_failure(snapshot, datetime.now(UTC)), failure_kind=kind
    )


def _snapshot_from_row(health: SourceHealth | None) -> CircuitSnapshot:
    if health is None:
        return initial_snapshot()
    return CircuitSnapshot(
        state=CircuitState(health.state),
        consecutive_failures=health.consecutive_failures,
        opened_at=health.opened_at,
    )


async def _persist(
    db: AsyncSession,
    source: str,
    snapshot: CircuitSnapshot,
    *,
    success: bool = False,
    failure_kind: SourceErrorKind | None = None,
) -> None:
    now = datetime.now(UTC)
    health = await db.get(SourceHealth, source)
    if health is None:
        health = SourceHealth(source=source, state=snapshot.state.value, updated_at=now)
        db.add(health)

    health.state = snapshot.state.value
    health.consecutive_failures = snapshot.consecutive_failures
    health.opened_at = snapshot.opened_at
    health.updated_at = now
    if success:
        health.last_success_at = now
    if failure_kind is not None:
        health.last_failure_at = now
        health.last_failure_reason = failure_kind.value
