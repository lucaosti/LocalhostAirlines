"""infrastructure/postgres/partitions.py against real Postgres (issue #53)."""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from domain.collection.partition_bounds import partition_for_month
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models_raw import RawPayload
from infrastructure.postgres.partitions import (
    drop_partitions_older_than,
    ensure_partition,
    maintain_partitions,
)


async def _partition_exists(table: str, partition_name: str) -> bool:
    async with session_scope() as db:
        result = await db.execute(
            text(
                "SELECT 1 FROM pg_inherits i "
                "JOIN pg_class c ON c.oid = i.inhrelid "
                "JOIN pg_class p ON p.oid = i.inhparent "
                "WHERE p.relname = :table AND c.relname = :partition"
            ),
            {"table": table, "partition": partition_name},
        )
        return result.first() is not None


@pytest.mark.integration
async def test_ensure_partition_creates_and_is_idempotent() -> None:
    # A far-future month, unlikely to collide with the migration's own
    # bootstrap partitions or another test's month.
    bounds = partition_for_month("raw_payloads", 2031, 6)
    async with session_scope() as db:
        await ensure_partition(db, "raw_payloads", bounds)
        await ensure_partition(db, "raw_payloads", bounds)  # must not raise

    assert await _partition_exists("raw_payloads", bounds.name)


@pytest.mark.integration
async def test_maintain_partitions_creates_a_rolling_window() -> None:
    start = date(2031, 9, 1)
    async with session_scope() as db:
        created = await maintain_partitions(db, "cash_observations", from_month=start, ahead=3)

    assert created == [
        "cash_observations_p2031_09",
        "cash_observations_p2031_10",
        "cash_observations_p2031_11",
    ]
    for name in created:
        assert await _partition_exists("cash_observations", name)


@pytest.mark.integration
async def test_insert_routes_to_the_correct_partition() -> None:
    # A real insert whose first_seen_at falls outside every existing
    # partition would fail with "no partition of relation found for row" —
    # a successful insert is itself proof of correct routing, not just
    # proof the table accepts writes.
    bounds = partition_for_month("raw_payloads", 2031, 3)
    async with session_scope() as db:
        await ensure_partition(db, "raw_payloads", bounds)

    when = datetime(2031, 3, 15, 12, 0, tzinfo=UTC)
    async with session_scope() as db:
        db.add(
            RawPayload(
                id=uuid.uuid4(),
                source="test",
                request_key="test-partition-routing",
                content_encoding="gzip",
                payload=b"x",
                retrieved_at=when,
            )
        )

    async with session_scope() as db:
        result = await db.execute(
            text(f'SELECT count(*) FROM "{bounds.name}" WHERE request_key = :key'),
            {"key": "test-partition-routing"},
        )
        assert result.scalar_one() == 1


@pytest.mark.integration
async def test_drop_partitions_older_than_cutoff_removes_only_expired_ones() -> None:
    # drop_partitions_older_than sweeps EVERY partition of the table older
    # than cutoff, not just ones this test created — so both the cutoff and
    # both test months must sit entirely *before* the migration's real
    # 2026-08..2027-02 bootstrap window (and every other test's fixture
    # months, all 2031+). A cutoff anywhere near or after 2026 silently
    # sweeps up that real bootstrap data too, which is exactly what
    # happened the first two times this test was written (2030 cutoff, then
    # a "safer-looking" 2032 one that was still later than 2026) — both
    # deleted the bootstrap partitions and cascaded into unrelated test
    # failures elsewhere in the suite. Using the past, not just "far
    # enough forward", is the only way this is actually safe.
    keep = partition_for_month("raw_payloads", 2021, 12)
    drop = partition_for_month("raw_payloads", 2019, 1)
    async with session_scope() as db:
        await ensure_partition(db, "raw_payloads", keep)
        await ensure_partition(db, "raw_payloads", drop)

    async with session_scope() as db:
        dropped = await drop_partitions_older_than(db, "raw_payloads", date(2020, 1, 1))

    assert drop.name in dropped
    assert keep.name not in dropped
    assert await _partition_exists("raw_payloads", keep.name)
    assert not await _partition_exists("raw_payloads", drop.name)
