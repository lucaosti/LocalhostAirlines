"""ECB FX rate ingestion job (issue #15).

Same injectable-fetcher pattern as apps/worker/jobs/reference_data.py: the
real network fetch is a keyword-only default so tests can substitute a
fixture-backed stub and never touch the network, while production code takes
the default and hits the real ECB feed.

Insert-or-skip on (quote_currency, rate_date): ECB never revises a published
rate, so once a row exists for a date it is a settled historical fact and is
never overwritten (spec P2/P3). Re-running the job over a date range that
overlaps previously-ingested rows is therefore idempotent by construction,
not by a separate dedup step.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models_fx import FxRate
from providers.fx.ecb import EcbRateRow, fetch_fx_rates, parse_fx_rates

logger = logging.getLogger(__name__)


async def ingest_fx_rates(
    ctx: dict[str, Any],
    *,
    _fetch: Any = fetch_fx_rates,
) -> None:
    xml_text = await _fetch()
    rows: list[EcbRateRow] = parse_fx_rates(xml_text)
    logger.info("ECB feed parsed: %d rate rows", len(rows))

    if not rows:
        # A genuinely empty feed is a source-side problem, not something to
        # paper over — log loudly and stop rather than silently no-op every
        # run, which would look identical to "already fully ingested".
        logger.warning("ECB feed returned zero parseable rows, skipping ingestion")
        return

    retrieved_at = datetime.now(UTC)
    inserted = 0
    async with session_scope() as session:
        for row in rows:
            stmt = (
                pg_insert(FxRate)
                .values(
                    quote_currency=row.quote_currency,
                    rate_date=row.rate_date,
                    base_currency="EUR",
                    rate=row.rate,
                    source="ecb",
                    retrieved_at=retrieved_at,
                )
                .on_conflict_do_nothing(index_elements=["quote_currency", "rate_date"])
            )
            result = await session.execute(stmt)
            inserted += result.rowcount or 0  # type: ignore[attr-defined]  # CursorResult at runtime

    logger.info(
        "ECB ingestion: %d new rows inserted (%d already present)",
        inserted,
        len(rows) - inserted,
    )
