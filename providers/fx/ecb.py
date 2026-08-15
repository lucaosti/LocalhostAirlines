"""ECB FX reference rates adapter (spec §82).

Same fetch/parse split as the other providers/ adapters: `fetch_fx_rates()`
does the network call, `parse_fx_rates()` is pure and independently
unit-testable against a saved fixture. Real feed verified by hand against
https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml before
writing this parser (spec §21 — never trust an assumed shape).

The 90-day history feed is used rather than the daily-only feed: same XML
shape, same daily publication cadence, but it gives real historical depth
from the very first ingestion run with no separate backfill mechanism. ECB
publishes only on TARGET business days, so the feed has no row at all for a
given currency on a day it didn't publish (weekends, ECB holidays) — this is
"unavailable", not a value to be invented, and callers must apply the
preceding-rate fallback themselves (see infrastructure/postgres/fx_rates.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

ECB_HIST_90D_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"

# The feed's namespace changes rarely but does exist; find()/findall() need it
# spelled out since ElementTree doesn't do namespace wildcards. Note the host
# is ecb.int here, not ecb.europa.eu (which is where the feed itself is
# served from) — confirmed against the live document, not assumed; guessing
# ecb.europa.eu here silently parsed to zero rows instead of erroring.
_NS = {
    "gesmes": "http://www.gesmes.org/xml/2002-08-01",
    "ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref",
}


@dataclass(frozen=True)
class EcbRateRow:
    quote_currency: str
    rate_date: date
    rate: Decimal


async def fetch_fx_rates(url: str = ECB_HIST_90D_URL) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def parse_fx_rates(xml_text: str) -> list[EcbRateRow]:
    """Parse the nested <Cube time=...><Cube currency=... rate=.../></Cube> feed.

    Skips (with a warning, never a raise) any per-currency Cube whose rate
    isn't parseable as a Decimal — a malformed row should not take down
    ingestion for every other currency on every other date, matching the
    tolerant-parsing precedent set by the reference-data providers.
    """
    root = ElementTree.fromstring(xml_text)  # noqa: S314 — fixed, trusted ECB source
    rows: list[EcbRateRow] = []

    date_cubes = root.findall(".//ecb:Cube[@time]", _NS)
    for date_cube in date_cubes:
        time_attr = date_cube.get("time")
        if time_attr is None:
            continue
        try:
            rate_date = date.fromisoformat(time_attr)
        except ValueError:
            logger.warning("ECB feed: unparseable date %r, skipping", time_attr)
            continue

        for currency_cube in date_cube.findall("ecb:Cube", _NS):
            currency = currency_cube.get("currency")
            rate_str = currency_cube.get("rate")
            if not currency or not rate_str:
                continue
            try:
                rate = Decimal(rate_str)
            except InvalidOperation:
                logger.warning(
                    "ECB feed: unparseable rate %r for %s on %s, skipping",
                    rate_str,
                    currency,
                    rate_date,
                )
                continue
            rows.append(EcbRateRow(quote_currency=currency, rate_date=rate_date, rate=rate))

    return rows
