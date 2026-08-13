"""OurAirports adapter (docs/providers.md "OurAirports"). PUBLIC_DATA class.

Knows the HTTP endpoint and the CSV shape. Yields raw rows; normalization
(assigning provenance, resolving timezones, building canonical records) is a
separate layer's job (spec §5) so a parser fix can be tested without a
network call.
"""

import csv
import io
from dataclasses import dataclass

import httpx

OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"


@dataclass(frozen=True)
class OurAirportsRow:
    icao_code: str
    iata_code: str
    name: str
    airport_type: str
    municipality: str
    iso_country: str
    latitude: float
    longitude: float


def parse_csv(raw: str) -> list[OurAirportsRow]:
    """Parses the OurAirports CSV. Only rows with a non-blank IATA code are
    kept: this project's domain is commercial flight search, and the tens of
    thousands of general-aviation strips and heliports OurAirports also
    carries are noise for that purpose, not signal.
    """
    reader = csv.DictReader(io.StringIO(raw))
    rows: list[OurAirportsRow] = []
    for record in reader:
        iata = (record.get("iata_code") or "").strip()
        icao = (record.get("icao_code") or "").strip()
        if not iata or not icao:
            continue
        try:
            latitude = float(record["latitude_deg"])
            longitude = float(record["longitude_deg"])
        except (KeyError, ValueError):
            continue
        rows.append(
            OurAirportsRow(
                icao_code=icao,
                iata_code=iata,
                name=record.get("name", ""),
                airport_type=record.get("type", ""),
                municipality=record.get("municipality", ""),
                iso_country=record.get("iso_country", ""),
                latitude=latitude,
                longitude=longitude,
            )
        )
    return rows


async def fetch_airports(client: httpx.AsyncClient) -> list[OurAirportsRow]:
    response = await client.get(OURAIRPORTS_URL, timeout=30.0)
    response.raise_for_status()
    return parse_csv(response.text)
