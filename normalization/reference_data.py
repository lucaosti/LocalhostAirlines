"""Merges OurAirports and OpenFlights into canonical airport/airline records.

The only layer aware of both providers' shapes at once (spec §5). Implements
the timezone resolution chain documented in docs/providers.md ("OurAirports
§ Timezone resolution"):

1. OpenFlights airports.dat's Olson column, matched by ICAO code.
2. timezonefinder resolving OurAirports' own coordinates, for anything
   OpenFlights doesn't cover or leaves blank.
3. Otherwise UNRESOLVED — never a guess (spec §36 quality gate rejects any
   itinerary touching an unresolved airport rather than risk a silently
   wrong duration).
"""

import logging
from dataclasses import dataclass

from timezonefinder import TimezoneFinder

# TimezoneResolution is defined once, on the persistence model, and reused
# here rather than redefined — two identically-shaped-but-distinct enums (one
# per layer) type-checked as incompatible with each other, which is exactly
# the kind of layering mistake mypy caught for real while wiring the
# ingestion job together.
from infrastructure.postgres.models_reference import TimezoneResolution
from providers.reference_data.openflights import OpenFlightsAirlineRow, OpenFlightsAirportRow
from providers.reference_data.ourairports import OurAirportsRow

logger = logging.getLogger(__name__)

_finder = TimezoneFinder()


@dataclass(frozen=True)
class CanonicalAirport:
    icao_code: str
    iata_code: str
    name: str
    airport_type: str
    municipality: str
    iso_country: str
    latitude: float
    longitude: float
    timezone: str | None
    timezone_resolution: TimezoneResolution


@dataclass(frozen=True)
class CanonicalAirline:
    icao_code: str
    iata_code: str | None
    name: str
    country: str | None
    active: bool


def normalize_airports(
    ourairports_rows: list[OurAirportsRow],
    openflights_rows: list[OpenFlightsAirportRow],
) -> list[CanonicalAirport]:
    timezone_by_icao = {r.icao_code: r.timezone for r in openflights_rows if r.timezone}

    result = []
    for row in ourairports_rows:
        timezone = timezone_by_icao.get(row.icao_code)
        resolution = TimezoneResolution.OPENFLIGHTS

        if timezone is None:
            # timezonefinder returns None over open ocean or where its
            # offline shapefiles have no coverage — that is a genuine
            # UNRESOLVED, not a bug to work around.
            timezone = _finder.timezone_at(lat=row.latitude, lng=row.longitude)
            resolution = (
                TimezoneResolution.COORDINATES if timezone else TimezoneResolution.UNRESOLVED
            )

        result.append(
            CanonicalAirport(
                icao_code=row.icao_code,
                iata_code=row.iata_code,
                name=row.name,
                airport_type=row.airport_type,
                municipality=row.municipality,
                iso_country=row.iso_country,
                latitude=row.latitude,
                longitude=row.longitude,
                timezone=timezone,
                timezone_resolution=resolution,
            )
        )
    return result


def normalize_airlines(rows: list[OpenFlightsAirlineRow]) -> list[CanonicalAirline]:
    # OpenFlights' community-maintained airlines.dat genuinely has multiple
    # distinct rows sharing one ICAO code — confirmed against the live feed,
    # not a hypothetical (~30+ codes, e.g. "ABX", "AGO"). icao_code is our
    # primary key (models_reference.py), so this must be resolved here, in
    # the layer whose job is producing one canonical fact per real-world
    # entity, rather than left to collide on insert. First occurrence wins,
    # deterministically; every drop is logged rather than silently lost.
    seen: dict[str, CanonicalAirline] = {}
    for r in rows:
        if r.icao_code in seen:
            logger.warning(
                "duplicate ICAO code in OpenFlights airlines.dat, keeping first",
                extra={"icao_code": r.icao_code, "kept": seen[r.icao_code].name, "dropped": r.name},
            )
            continue
        seen[r.icao_code] = CanonicalAirline(
            icao_code=r.icao_code,
            iata_code=r.iata_code,
            name=r.name,
            country=r.country,
            active=r.active,
        )
    return list(seen.values())
