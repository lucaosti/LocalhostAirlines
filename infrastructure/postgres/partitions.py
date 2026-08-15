"""Partition maintenance for declaratively partitioned tables (spec §55).

Creates the next N months of partitions (idempotent — safe to run every
invocation) and enforces raw-payload retention by detaching and dropping
whole partitions, O(1), rather than a row-by-row DELETE (spec §55's own
stated reasoning). `cash_observations` is retained indefinitely per spec
§55, so no retention path is implemented for it — that omission is the
correct behaviour, not a gap.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from domain.collection.partition_bounds import PartitionBounds, months_from, partition_for_month

logger = logging.getLogger(__name__)


async def ensure_partition(db: AsyncSession, table: str, bounds: PartitionBounds) -> None:
    # IF NOT EXISTS makes repeated calls for an already-existing month a
    # no-op rather than an error — required for the maintenance job to be
    # safely re-run on every scheduled invocation.
    #
    # Bounds are inlined as literals, not bind parameters: `CREATE TABLE ...
    # PARTITION OF ... FOR VALUES FROM (...) TO (...)` is DDL, and Postgres
    # does not accept parameters there at all — confirmed by running this
    # for real ("parameters are supported only in SELECT, INSERT, UPDATE,
    # DELETE, MERGE and VALUES statements"), not assumed from documentation.
    # Safe here because `bounds` is always produced by
    # domain/collection/partition_bounds.py from integers this project
    # controls, never from external input.
    await db.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{bounds.name}" '  # noqa: S608 — identifiers/dates are our own deterministic format, not external input
            f"PARTITION OF \"{table}\" FOR VALUES FROM ('{bounds.lower.isoformat()}') "
            f"TO ('{bounds.upper.isoformat()}')"
        )
    )


async def maintain_partitions(
    db: AsyncSession, table: str, *, from_month: date, ahead: int
) -> list[str]:
    created = []
    for year, month in months_from(from_month, ahead):
        bounds = partition_for_month(table, year, month)
        await ensure_partition(db, table, bounds)
        created.append(bounds.name)
    return created


async def drop_partitions_older_than(db: AsyncSession, table: str, cutoff: date) -> list[str]:
    """Detach and drop every partition of `table` whose upper bound is on or
    before `cutoff`. Partition names are parsed back to bounds rather than
    queried from Postgres catalog expressions — simpler, and correct as
    long as every partition was created by ensure_partition's own naming."""
    rows = (
        await db.execute(
            text(
                "SELECT c.relname FROM pg_inherits i "
                "JOIN pg_class c ON c.oid = i.inhrelid "
                "JOIN pg_class p ON p.oid = i.inhparent "
                "WHERE p.relname = :table"
            ),
            {"table": table},
        )
    ).fetchall()

    dropped = []
    prefix = f"{table}_p"
    for (partition_name,) in rows:
        if not partition_name.startswith(prefix):
            continue  # not one of ours — leave it alone
        ym = partition_name[len(prefix) :]
        try:
            year, month = int(ym[:4]), int(ym[5:7])
        except ValueError:
            logger.warning("partitions: skipping unparseable partition name %r", partition_name)
            continue

        bounds = partition_for_month(table, year, month)
        if bounds.upper <= cutoff:
            await db.execute(text(f'ALTER TABLE "{table}" DETACH PARTITION "{partition_name}"'))
            await db.execute(text(f'DROP TABLE "{partition_name}"'))
            dropped.append(partition_name)

    return dropped
