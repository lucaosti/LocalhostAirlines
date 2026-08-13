"""ECB feed parsing — pure, no network (spec §21: contract-tested against a fixture)."""

from datetime import date
from decimal import Decimal

from providers.fx.ecb import EcbRateRow, parse_fx_rates

# Trimmed but structurally real fixture: two publication dates, mirrors the
# actual eurofxref-hist-90d.xml shape confirmed by hand against the live feed
# (nested per-date Cube, each holding one Cube per currency).
FIXTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                  xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time="2026-08-13">
      <Cube currency="USD" rate="1.1534"/>
      <Cube currency="GBP" rate="0.8623"/>
      <Cube currency="JPY" rate="171.42"/>
    </Cube>
    <Cube time="2026-08-12">
      <Cube currency="USD" rate="1.1521"/>
      <Cube currency="GBP" rate="0.8619"/>
      <Cube currency="JPY" rate="171.10"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


def test_parses_every_currency_on_every_date() -> None:
    rows = parse_fx_rates(FIXTURE_XML)
    assert len(rows) == 6
    assert (
        EcbRateRow(quote_currency="USD", rate_date=date(2026, 8, 13), rate=Decimal("1.1534"))
        in rows
    )
    assert (
        EcbRateRow(quote_currency="JPY", rate_date=date(2026, 8, 12), rate=Decimal("171.10"))
        in rows
    )


def test_skips_unparseable_rate_without_raising() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                      xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
      <Cube>
        <Cube time="2026-08-13">
          <Cube currency="USD" rate="not-a-number"/>
          <Cube currency="GBP" rate="0.8623"/>
        </Cube>
      </Cube>
    </gesmes:Envelope>
    """
    rows = parse_fx_rates(xml)
    assert len(rows) == 1
    assert rows[0].quote_currency == "GBP"


def test_skips_currency_cube_missing_rate_attribute() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                      xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
      <Cube>
        <Cube time="2026-08-13">
          <Cube currency="USD"/>
        </Cube>
      </Cube>
    </gesmes:Envelope>
    """
    assert parse_fx_rates(xml) == []


def test_empty_feed_parses_to_empty_list() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                      xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
      <Cube></Cube>
    </gesmes:Envelope>
    """
    assert parse_fx_rates(xml) == []
