"""Timezone resolution chain (docs/providers.md "OurAirports § Timezone
resolution"). No network, no database.
"""

import normalization.reference_data as normalization
from normalization.reference_data import TimezoneResolution, normalize_airports
from providers.reference_data.openflights import OpenFlightsAirportRow
from providers.reference_data.ourairports import OurAirportsRow


def _airport(icao: str, iata: str, lat: float = 45.6, lon: float = 8.7) -> OurAirportsRow:
    return OurAirportsRow(
        icao_code=icao,
        iata_code=iata,
        name="Test Airport",
        airport_type="large_airport",
        municipality="Testville",
        iso_country="IT",
        latitude=lat,
        longitude=lon,
    )


def test_openflights_timezone_takes_priority() -> None:
    row = _airport("LIML", "MXP")
    openflights = [OpenFlightsAirportRow(iata_code="MXP", icao_code="LIML", timezone="Europe/Rome")]

    [result] = normalize_airports([row], openflights)

    assert result.timezone == "Europe/Rome"
    assert result.timezone_resolution == TimezoneResolution.OPENFLIGHTS


def test_falls_back_to_coordinates_when_openflights_has_no_match() -> None:
    row = _airport("LIML", "MXP", lat=45.6306, lon=8.7281)  # real Malpensa coordinates

    [result] = normalize_airports([row], openflights_rows=[])

    assert result.timezone == "Europe/Rome"  # verified against the real library
    assert result.timezone_resolution == TimezoneResolution.COORDINATES


def test_unresolved_when_neither_source_yields_a_timezone(monkeypatch) -> None:
    # A genuinely unresolvable real-world coordinate is hard to produce —
    # timezonefinder's Etc/GMT zones now cover the open ocean too. This
    # exercises the UNRESOLVED branch directly, which the quality gate
    # (spec §36) depends on staying correct even if it fires rarely in
    # practice.
    # TimezoneFinder is a C-extension type; its bound method can't be
    # monkeypatched on the instance ("attribute is read-only"). Replacing
    # the module-level `_finder` singleton with a stub sidesteps that.
    class _AlwaysUnresolved:
        def timezone_at(self, *, lat: float, lng: float) -> None:
            return None

    monkeypatch.setattr(normalization, "_finder", _AlwaysUnresolved())
    row = _airport("ZZZZ", "ZZZ")

    [result] = normalize_airports([row], openflights_rows=[])

    assert result.timezone is None
    assert result.timezone_resolution == TimezoneResolution.UNRESOLVED
