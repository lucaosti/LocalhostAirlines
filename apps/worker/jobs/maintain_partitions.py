"""Partition maintenance and raw-payload retention job (issue #53; spec §55).

Runs monthly: extends both partitioned tables' rolling window forward, and
drops `raw_payloads` partitions past the 12-month retention window.
`cash_observations` is retained indefinitely (spec §55) — no retention call
for it here, by design, not an oversight.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from infrastructure.postgres.database import session_scope
from infrastructure.postgres.partitions import drop_partitions_older_than, maintain_partitions

logger = logging.getLogger(__name__)

AHEAD_MONTHS = 3
RETENTION_MONTHS = 12


async def run_partition_maintenance(ctx: dict[str, Any]) -> None:
    today = datetime.now(UTC).date()

    async with session_scope() as db:
        created_obs = await maintain_partitions(
            db, "cash_observations", from_month=today, ahead=AHEAD_MONTHS
        )
        created_raw = await maintain_partitions(
            db, "raw_payloads", from_month=today, ahead=AHEAD_MONTHS
        )

    cutoff = _months_before(today, RETENTION_MONTHS)
    async with session_scope() as db:
        dropped = await drop_partitions_older_than(db, "raw_payloads", cutoff)

    logger.info(
        "partition maintenance: ensured %d cash_observations + %d raw_payloads "
        "partitions; dropped %d expired raw_payloads partitions",
        len(created_obs),
        len(created_raw),
        len(dropped),
    )


def _months_before(today: date, months: int) -> date:
    year, month = today.year, today.month
    for _ in range(months):
        month -= 1
        if month < 1:
            month = 12
            year -= 1
    return date(year, month, 1)
