"""OpenFlights adapter (docs/providers.md "OpenFlights"). PUBLIC_DATA class.

Two files, both headerless CSV with `\\N` as the NULL marker:

- airports.dat: the primary source for airport IANA timezones (column 12),
  used before falling back to coordinate lookup (docs/providers.md, "OurAirports
  § Timezone resolution").
- airlines.dat: airline reference data.

Known weakness carried over from docs/providers.md: OpenFlights is not
actively maintained at the pace airlines change, so it is never authoritative
for alliance membership — only for resolving codes to names and airports to
timezones.
"""

import csv
import re
from dataclasses import dataclass

import httpx

AIRPORTS_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
AIRLINES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"

# Positional columns per OpenFlights' documented schema. Named indices, not
# magic numbers scattered through the parser.
_AIRPORT_IATA = 4
_AIRPORT_ICAO = 5
_AIRPORT_TIMEZONE = 11

_AIRLINE_NAME = 1
_AIRLINE_IATA = 3
_AIRLINE_ICAO = 4
_AIRLINE_COUNTRY = 6
_AIRLINE_ACTIVE = 7


def _null_or(value: str) -> str | None:
    value = value.strip()
    # "N/A" is a real value in the live feed, not documented anywhere: two
    # distinct placeholder rows (id -1 "Unknown" and id 1 "Private flight")
    # both carry the literal string "N/A" as their ICAO code, which collided
    # on the airlines table's primary key the first time this ran against
    # real data rather than fixtures. Treated as null like the documented
    # \N marker, so both placeholder rows are correctly dropped by the
    # "no ICAO code" filter in parse_airlines() rather than colliding.
    return None if value in ("", "\\N", "N/A") else value


# Airport codes and airline codes follow different, real aviation length
# conventions: airport ICAO is 4 characters (LIMC), airline ICAO is 3 (AFR);
# airport IATA is 3 (MXP), airline IATA is 2 (AF). Conflating airport and
# airline patterns into one was a bug this file's own tests caught for
# real: it rejected every valid 4-character airport ICAO code as malformed.
_AIRPORT_ICAO_PATTERN = re.compile(r"^[A-Z0-9]{4}$")
_AIRPORT_IATA_PATTERN = re.compile(r"^[A-Z0-9]{3}$")
_AIRLINE_ICAO_PATTERN = re.compile(r"^[A-Z0-9]{3}$")
_AIRLINE_IATA_PATTERN = re.compile(r"^[A-Z0-9]{2}$")


def _valid_code(value: str | None, pattern: re.Pattern[str]) -> str | None:
    """Rejects a code that doesn't match ICAO/IATA's own format instead of
    trusting whatever a field happens to contain. Found for real: one row in
    the live airlines.dat feed carries a corrupted escape sequence ("\\'\\")
    where its ICAO code should be — csv.reader parses it "successfully" as a
    literal string, which is exactly why the *content* still needs
    validating, not just the field's presence.
    """
    if value is None:
        return None
    return value if pattern.match(value) else None


@dataclass(frozen=True)
class OpenFlightsAirportRow:
    iata_code: str
    icao_code: str
    timezone: str | None


@dataclass(frozen=True)
class OpenFlightsAirlineRow:
    iata_code: str | None
    # Never None in practice: parse_airlines() filters out any row without
    # one before constructing this. Typed non-optional so downstream code
    # (normalization/reference_data.py) doesn't need to re-guard against a
    # case the adapter already ruled out.
    icao_code: str
    name: str
    country: str | None
    active: bool


def parse_airports(raw: str) -> list[OpenFlightsAirportRow]:
    rows = []
    for record in csv.reader(raw.splitlines()):
        if len(record) <= _AIRPORT_TIMEZONE:
            continue
        iata = _valid_code(_null_or(record[_AIRPORT_IATA]), _AIRPORT_IATA_PATTERN)
        icao = _valid_code(_null_or(record[_AIRPORT_ICAO]), _AIRPORT_ICAO_PATTERN)
        if not iata or not icao:
            continue
        rows.append(
            OpenFlightsAirportRow(
                iata_code=iata, icao_code=icao, timezone=_null_or(record[_AIRPORT_TIMEZONE])
            )
        )
    return rows


def parse_airlines(raw: str) -> list[OpenFlightsAirlineRow]:
    rows = []
    for record in csv.reader(raw.splitlines()):
        if len(record) <= _AIRLINE_ACTIVE:
            continue
        icao = _valid_code(_null_or(record[_AIRLINE_ICAO]), _AIRLINE_ICAO_PATTERN)
        if not icao:
            continue
        rows.append(
            OpenFlightsAirlineRow(
                iata_code=_valid_code(_null_or(record[_AIRLINE_IATA]), _AIRLINE_IATA_PATTERN),
                icao_code=icao,
                name=record[_AIRLINE_NAME],
                country=_null_or(record[_AIRLINE_COUNTRY]),
                active=record[_AIRLINE_ACTIVE].strip().upper() == "Y",
            )
        )
    return rows


async def fetch_airport_timezones(client: httpx.AsyncClient) -> list[OpenFlightsAirportRow]:
    response = await client.get(AIRPORTS_URL, timeout=30.0)
    response.raise_for_status()
    return parse_airports(response.text)


async def fetch_airlines(client: httpx.AsyncClient) -> list[OpenFlightsAirlineRow]:
    response = await client.get(AIRLINES_URL, timeout=30.0)
    response.raise_for_status()
    return parse_airlines(response.text)
