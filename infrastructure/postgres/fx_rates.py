"""FX rate lookups (spec P2 provenance).

`rate_as_of` is the one place that implements "convert using the rate in
effect on a given date, falling back to the preceding available date on
weekends/holidays" — every caller (search evaluation, presentation) goes
through this instead of querying FxRate directly, so the fallback and its
provenance are applied consistently everywhere money gets converted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.postgres.models_fx import FxRate


@dataclass(frozen=True)
class FxRateResult:
    """A rate together with the provenance of which date it actually applies to.

    `effective_date` differs from the date the caller asked for exactly when
    the fallback kicked in — every converted value must record this (spec P2),
    not just the requested date, so a report can show "rate as of Friday" next
    to a Saturday transaction rather than implying a Saturday rate exists.
    """

    quote_currency: str
    rate: Decimal
    requested_date: date
    effective_date: date
    source: str


async def rate_as_of(
    session: AsyncSession, quote_currency: str, target_date: date
) -> FxRateResult | None:
    """Most recent EUR->quote_currency rate on or before target_date.

    Returns None if no rate exists at or before that date at all — this is
    "unavailable", not "0" or "1": callers must handle the absence explicitly
    rather than a fallback value inventing a conversion (spec P3/P4).
    """
    stmt = (
        select(FxRate)
        .where(FxRate.quote_currency == quote_currency, FxRate.rate_date <= target_date)
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None

    return FxRateResult(
        quote_currency=row.quote_currency,
        rate=row.rate,
        requested_date=target_date,
        effective_date=row.rate_date,
        source=row.source,
    )
