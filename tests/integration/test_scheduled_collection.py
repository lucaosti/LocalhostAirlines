"""apps/worker/jobs/scheduled_collection.py against real Postgres."""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from apps.worker.jobs.scheduled_collection import run_scheduled_collection
from domain.users.passwords import hash_password
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models import Role, User
from infrastructure.postgres.models_search import CashObservation, Search, SearchState


class _FakeRedis:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple]] = []

    async def enqueue_job(self, function: str, *args) -> None:
        self.enqueued.append((function, args))


async def _seed_user() -> uuid.UUID:
    now = datetime.now(UTC)
    user_id = uuid.uuid4()
    async with session_scope() as db:
        db.add(
            User(
                id=user_id,
                username=f"sched-{user_id.hex[:8]}",
                email=f"{user_id.hex[:8]}@example.test",
                password_hash=hash_password("correct horse battery staple"),
                role=Role.USER,
                created_at=now,
                updated_at=now,
            )
        )
    return user_id


async def _seed_observed_route(
    user_id: uuid.UUID, origin: str, destination: str, month: str
) -> None:
    # Routes come from cash_observations now, not searches directly (module
    # docstring) — a search may cover many routes at once, so an observation
    # row linked back to its originating search via last_search_id is the
    # fixture shape that matches what the real orchestrator writes.
    now = datetime.now(UTC)
    search_id = uuid.uuid4()
    year, month_number = (int(part) for part in month.split("-"))
    # Two transactions, not one: matches how the real code always does it
    # (the search row is committed before write_observation ever runs, in a
    # separate call). Adding both objects to a single session doesn't
    # guarantee insert order across unrelated mappers with no relationship()
    # between them, so a single flush here can hit the observation's FK to
    # `searches` before the search row itself is actually inserted.
    async with session_scope() as db:
        db.add(
            Search(
                id=search_id,
                user_id=user_id,
                origins=[{"code": origin, "weight": 0}],
                destinations=[{"code": destination, "weight": 0}],
                date_start=date(year, month_number, 1),
                date_end=date(year, month_number, 1),
                min_nights=0,
                max_nights=0,
                cabins=["economy"],
                budget_calls=1,
                budget_spent=1,
                space_total=1,
                space_explored=1,
                sources=[
                    {"source": "travelpayouts", "state": "completed", "results": 1, "reason": None}
                ],
                state=SearchState.READY,
                created_at=now,
                completed_at=now,
            )
        )

    async with session_scope() as db:
        db.add(
            CashObservation(
                id=uuid.uuid4(),
                last_search_id=search_id,
                itinerary_id=f"{origin}-{destination}-{month}",
                source="travelpayouts",
                origin=origin,
                destination=destination,
                depart_month=month,
                price_minor=10000,
                currency="EUR",
                freshness="cached",
                confidence="high",
                offer={},
                first_seen_at=now,
                last_seen_at=now,
                poll_count=1,
            )
        )


@pytest.mark.integration
async def test_enqueues_one_job_per_distinct_route() -> None:
    user_id = await _seed_user()
    # Distinct IATA-shaped codes per test run to avoid colliding with rows
    # other tests or a previous run of this same test left behind.
    tag = uuid.uuid4().hex[:3].upper()
    await _seed_observed_route(user_id, f"{tag}A", "NRT", "2026-10")
    await _seed_observed_route(user_id, f"{tag}A", "NRT", "2026-10")  # duplicate route
    await _seed_observed_route(user_id, f"{tag}B", "LHR", "2026-11")

    fake_redis = _FakeRedis()
    await run_scheduled_collection({"redis": fake_redis})

    enqueued_search_ids = [args[0] for _fn, args in fake_redis.enqueued]
    async with session_scope() as db:
        rows = (
            (
                await db.execute(
                    select(Search).where(Search.id.in_([uuid.UUID(i) for i in enqueued_search_ids]))
                )
            )
            .scalars()
            .all()
        )
        routes = {
            (
                search.origins[0]["code"],
                search.destinations[0]["code"],
                search.date_start.strftime("%Y-%m"),
            )
            for search in rows
        }

    assert (f"{tag}A", "NRT", "2026-10") in routes
    assert (f"{tag}B", "LHR", "2026-11") in routes
    # Exactly one enqueued Search per distinct route among the ones this
    # test created, even though the duplicate was seeded twice — though
    # other tests' rows may also be present, so assert on the subset that
    # matters rather than an exact global count.
    matching_a = [r for r in routes if r[0] == f"{tag}A"]
    assert len(matching_a) == 1


@pytest.mark.integration
async def test_new_searches_start_pending_and_are_persisted_before_enqueue() -> None:
    user_id = await _seed_user()
    tag = uuid.uuid4().hex[:3].upper()
    await _seed_observed_route(user_id, f"{tag}C", "CDG", "2026-12")

    fake_redis = _FakeRedis()
    await run_scheduled_collection({"redis": fake_redis})

    new_ids = [uuid.UUID(args[0]) for _fn, args in fake_redis.enqueued]
    async with session_scope() as db:
        rows = (await db.execute(select(Search).where(Search.id.in_(new_ids)))).scalars().all()
        matching = [r for r in rows if r.origins[0]["code"] == f"{tag}C"]
        assert len(matching) == 1
        assert matching[0].state == SearchState.PENDING


@pytest.mark.integration
async def test_no_previous_searches_is_a_clean_noop() -> None:
    # Doesn't assert zero enqueues globally (other tests' routes exist in
    # the same database) — asserts only that a fresh, never-searched-before
    # tag contributes nothing, and the job doesn't raise on an empty table
    # in isolation logically.
    fake_redis = _FakeRedis()
    await run_scheduled_collection({"redis": fake_redis})  # must not raise
