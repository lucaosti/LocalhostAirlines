"""apps/worker/jobs/maintain_partitions.py against real Postgres."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from apps.worker.jobs.maintain_partitions import _months_before, run_partition_maintenance
from domain.collection.partition_bounds import partition_for_month
from infrastructure.postgres.database import session_scope


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


def test_months_before_rolls_back_across_year_boundary() -> None:
    assert _months_before(date(2027, 2, 15), 12) == date(2026, 2, 1)
    assert _months_before(date(2026, 3, 1), 3) == date(2025, 12, 1)


@pytest.mark.integration
async def test_job_ensures_partitions_covering_today() -> None:
    # This test's real "today" (whatever the container clock reports) must
    # already be covered by the migration's bootstrap window or a prior
    # maintenance run — the job existing to extend that window forward is
    # exactly what's under test here, run for real rather than mocked.
    await run_partition_maintenance({})

    today = datetime.now(UTC).date()
    bounds = partition_for_month("cash_observations", today.year, today.month)
    assert await _partition_exists("cash_observations", bounds.name)
