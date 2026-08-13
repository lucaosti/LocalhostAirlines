"""infrastructure/postgres/source_health.py against real Postgres (issue #56)."""

import uuid

import pytest

from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models_health import SourceHealth
from infrastructure.postgres.source_health import may_call, record_failure, record_success
from providers.errors import SourceErrorKind


def _source() -> str:
    # Unique per test — this table has no per-test teardown, matching the
    # existing convention (test_travellers.py, test_fx_rates.py) of unique
    # identifiers instead of truncation.
    return f"test-source-{uuid.uuid4().hex[:8]}"


@pytest.mark.integration
async def test_unknown_source_may_call_without_writing_a_row() -> None:
    # A source with no history is implicitly CLOSED (may_attempt returns the
    # snapshot unchanged), so no row is written — only a state *transition*
    # is worth persisting. Asserting a row must exist here would be
    # asserting the wrong thing: "healthy and untouched" is not itself a
    # fact that needs recording.
    source = _source()
    async with session_scope() as db:
        assert await may_call(db, source) is True
        health = await db.get(SourceHealth, source)
        assert health is None


@pytest.mark.integration
async def test_circuit_relevant_failures_open_the_circuit() -> None:
    source = _source()
    async with session_scope() as db:
        for _ in range(3):
            await record_failure(db, source, SourceErrorKind.UPSTREAM_ERROR)

        health = await db.get(SourceHealth, source)
        assert health.state == "open"
        assert health.consecutive_failures == 3
        assert health.last_failure_reason == "upstream_error"

        assert await may_call(db, source) is False


@pytest.mark.integration
async def test_non_circuit_relevant_failures_never_open_it() -> None:
    source = _source()
    async with session_scope() as db:
        for kind in (
            SourceErrorKind.NOT_AVAILABLE,
            SourceErrorKind.AUTHENTICATION,
            SourceErrorKind.BAD_REQUEST,
            SourceErrorKind.SCHEMA_CHANGE,
        ):
            await record_failure(db, source, kind)

        health = await db.get(SourceHealth, source)
        # No row was ever created — every one of these kinds is a no-op
        # by design (module docstring: none of them mean the source itself
        # is struggling).
        assert health is None
        assert await may_call(db, source) is True


@pytest.mark.integration
async def test_success_resets_an_open_circuit() -> None:
    source = _source()
    async with session_scope() as db:
        for _ in range(3):
            await record_failure(db, source, SourceErrorKind.TIMEOUT)
        assert await may_call(db, source) is False

        await record_success(db, source)
        health = await db.get(SourceHealth, source)
        assert health.state == "closed"
        assert health.consecutive_failures == 0
        assert health.last_success_at is not None

        assert await may_call(db, source) is True
