"""FX rate ingestion and lookup against real Postgres.

Uses fictional currency codes (ZZx) per test, never a real ISO code — this
table is never truncated between tests (matching the existing convention in
test_travellers.py of unique-per-test identifiers instead of teardown), and a
real code could collide with rows a manual `ingest_fx_rates` run against the
live ECB feed leaves behind in a shared dev database.
"""

from datetime import date

import pytest
from sqlalchemy import select

from apps.worker.jobs.fx_rates import ingest_fx_rates
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.fx_rates import rate_as_of
from infrastructure.postgres.models_fx import FxRate

# Deliberately skips a weekend (2026-08-15/16, Sat/Sun) exactly like the real
# ECB feed does — this is the fixture the fallback logic is tested against.
FIXTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                  xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-08-17">
      <Cube currency="ZZA" rate="1.2000"/>
    </Cube>
    <Cube time="2026-08-14">
      <Cube currency="ZZA" rate="1.1000"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


async def _fetch_fixture() -> str:
    return FIXTURE_XML


@pytest.mark.integration
async def test_ingest_inserts_rows_and_never_overwrites() -> None:
    ctx: dict = {}
    await ingest_fx_rates(ctx, _fetch=_fetch_fixture)

    async with session_scope() as db:
        row = (
            await db.execute(
                select(FxRate).where(
                    FxRate.quote_currency == "ZZA", FxRate.rate_date == date(2026, 8, 17)
                )
            )
        ).scalar_one()
        assert str(row.rate) == "1.200000"
        original_retrieved_at = row.retrieved_at

    # Re-running with a fixture carrying a *different* rate for the same date
    # must not change the stored row — a published ECB rate is immutable.
    async def _fetch_conflicting() -> str:
        return FIXTURE_XML.replace('rate="1.2000"', 'rate="9.9999"')

    await ingest_fx_rates(ctx, _fetch=_fetch_conflicting)

    async with session_scope() as db:
        row = (
            await db.execute(
                select(FxRate).where(
                    FxRate.quote_currency == "ZZA", FxRate.rate_date == date(2026, 8, 17)
                )
            )
        ).scalar_one()
        assert str(row.rate) == "1.200000"  # unchanged
        assert row.retrieved_at == original_retrieved_at


@pytest.mark.integration
async def test_ingest_is_idempotent_on_overlapping_reingest() -> None:
    ctx: dict = {}
    await ingest_fx_rates(ctx, _fetch=_fetch_fixture)
    await ingest_fx_rates(ctx, _fetch=_fetch_fixture)  # same window again

    async with session_scope() as db:
        count = (
            (
                await db.execute(
                    select(FxRate).where(
                        FxRate.quote_currency == "ZZA", FxRate.rate_date == date(2026, 8, 17)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(count) == 1


@pytest.mark.integration
async def test_rate_as_of_falls_back_to_preceding_published_date() -> None:
    ctx: dict = {}
    await ingest_fx_rates(ctx, _fetch=_fetch_fixture)

    async with session_scope() as db:
        # Exact match: 2026-08-17 was published directly.
        exact = await rate_as_of(db, "ZZA", date(2026, 8, 17))
        assert exact is not None
        assert exact.effective_date == date(2026, 8, 17)
        assert exact.requested_date == date(2026, 8, 17)
        assert str(exact.rate) == "1.200000"

        # Weekend gap: no row for 2026-08-16 (Sunday) — falls back to the
        # preceding published date, 2026-08-14, and that fallback is recorded.
        fallback = await rate_as_of(db, "ZZA", date(2026, 8, 16))
        assert fallback is not None
        assert fallback.effective_date == date(2026, 8, 14)
        assert fallback.requested_date == date(2026, 8, 16)
        assert str(fallback.rate) == "1.100000"


@pytest.mark.integration
async def test_rate_as_of_returns_none_before_any_published_rate() -> None:
    ctx: dict = {}
    await ingest_fx_rates(ctx, _fetch=_fetch_fixture)

    async with session_scope() as db:
        result = await rate_as_of(db, "ZZA", date(2000, 1, 1))
        assert result is None


@pytest.mark.integration
async def test_ingest_skips_empty_feed_without_error() -> None:
    async def _fetch_empty() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" '
            'xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">'
            "<Cube></Cube></gesmes:Envelope>"
        )

    ctx: dict = {}
    await ingest_fx_rates(ctx, _fetch=_fetch_empty)  # must not raise
