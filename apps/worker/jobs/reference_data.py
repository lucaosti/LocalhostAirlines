"""Reference data ingestion job (spec §12, §36).

fetch -> normalize -> upsert -> soft-delete missing -> recompute groups, run
monthly by the scheduler (apps/worker/main.py). Registered as a real ARQ
function rather than only a cron job, so it can also be triggered on demand
(e.g. from an admin endpoint later) without duplicating the logic.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select

from domain.reference_data.grouping import GroupableAirport, derive_groups
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models_reference import (
    Airline,
    Airport,
    AirportGroup,
    AirportGroupMember,
    TimezoneResolution,
)
from normalization.reference_data import (
    CanonicalAirline,
    CanonicalAirport,
    normalize_airlines,
    normalize_airports,
)
from providers.reference_data.openflights import (
    OpenFlightsAirlineRow,
    OpenFlightsAirportRow,
    fetch_airlines,
    fetch_airport_timezones,
)
from providers.reference_data.ourairports import OurAirportsRow
from providers.reference_data.ourairports import fetch_airports as fetch_ourairports

logger = logging.getLogger(__name__)

SOURCE = "ourairports+openflights"

# Injectable so tests exercise the real upsert/soft-delete/grouping logic
# against live Postgres using small fixture rows, never a real network call
# (CLAUDE.md §6: "CI never reaches an external source").
FetchOurAirports = Callable[[httpx.AsyncClient], Awaitable[list[OurAirportsRow]]]
FetchAirportTimezones = Callable[[httpx.AsyncClient], Awaitable[list[OpenFlightsAirportRow]]]
FetchAirlines = Callable[[httpx.AsyncClient], Awaitable[list[OpenFlightsAirlineRow]]]


async def _upsert_airports(canonical: list[CanonicalAirport], now: datetime) -> None:
    seen_codes = {a.icao_code for a in canonical}

    async with session_scope() as db:
        existing = {a.icao_code: a for a in (await db.execute(select(Airport))).scalars()}

        for row in canonical:
            current = existing.get(row.icao_code)
            if current is None:
                db.add(
                    Airport(
                        icao_code=row.icao_code,
                        iata_code=row.iata_code,
                        name=row.name,
                        airport_type=row.airport_type,
                        municipality=row.municipality,
                        iso_country=row.iso_country,
                        latitude=row.latitude,
                        longitude=row.longitude,
                        timezone=row.timezone,
                        timezone_resolution=row.timezone_resolution,
                        active=True,
                        source=SOURCE,
                        retrieved_at=now,
                    )
                )
            else:
                current.iata_code = row.iata_code
                current.name = row.name
                current.airport_type = row.airport_type
                current.municipality = row.municipality
                current.iso_country = row.iso_country
                current.latitude = row.latitude
                current.longitude = row.longitude
                current.timezone = row.timezone
                current.timezone_resolution = row.timezone_resolution
                current.active = True
                current.retrieved_at = now

        # Soft delete: a code no longer present upstream is deactivated, not
        # dropped, so anything that already references it stays valid.
        for icao_code, current in existing.items():
            if icao_code not in seen_codes and current.active:
                current.active = False
                logger.info(
                    "airport no longer present upstream, deactivated",
                    extra={"icao_code": icao_code, "iata_code": current.iata_code},
                )


async def _upsert_airlines(canonical: list[CanonicalAirline], now: datetime) -> None:
    seen_codes = {a.icao_code for a in canonical}

    async with session_scope() as db:
        existing = {a.icao_code: a for a in (await db.execute(select(Airline))).scalars()}

        for row in canonical:
            current = existing.get(row.icao_code)
            if current is None:
                db.add(
                    Airline(
                        icao_code=row.icao_code,
                        iata_code=row.iata_code,
                        name=row.name,
                        country=row.country,
                        active_in_source=row.active,
                        active=True,
                        source="openflights",
                        retrieved_at=now,
                    )
                )
            else:
                current.iata_code = row.iata_code
                current.name = row.name
                current.country = row.country
                current.active_in_source = row.active
                current.active = True
                current.retrieved_at = now

        for icao_code, current in existing.items():
            if icao_code not in seen_codes and current.active:
                current.active = False
                logger.info(
                    "airline no longer present upstream, deactivated",
                    extra={"icao_code": icao_code, "iata_code": current.iata_code},
                )


async def _recompute_groups(canonical: list[CanonicalAirport]) -> None:
    groupable = [
        GroupableAirport(
            icao_code=a.icao_code,
            iata_code=a.iata_code,
            airport_type=a.airport_type,
            municipality=a.municipality,
            latitude=a.latitude,
            longitude=a.longitude,
        )
        for a in canonical
    ]
    groups = derive_groups(groupable)

    async with session_scope() as db:
        # Groups are wholly derived data (docstring, models_reference.py):
        # recomputed from scratch each run rather than diffed incrementally.
        for member in (await db.execute(select(AirportGroupMember))).scalars():
            await db.delete(member)
        for existing_group in (await db.execute(select(AirportGroup))).scalars():
            await db.delete(existing_group)
        await db.flush()

        for group in groups:
            db.add(
                AirportGroup(
                    name=group.name,
                    anchor_icao_code=group.anchor_icao_code,
                    members=[
                        AirportGroupMember(airport_icao_code=code)
                        for code in sorted(group.member_icao_codes)
                    ],
                )
            )

    logger.info("airport groups recomputed", extra={"group_count": len(groups)})


async def ingest_reference_data(
    ctx: dict[str, Any],
    *,
    _fetch_ourairports: FetchOurAirports = fetch_ourairports,
    _fetch_airport_timezones: FetchAirportTimezones = fetch_airport_timezones,
    _fetch_airlines: FetchAirlines = fetch_airlines,
) -> None:
    now = datetime.now(UTC)
    async with httpx.AsyncClient() as client:
        ourairports_rows = await _fetch_ourairports(client)
        openflights_timezones = await _fetch_airport_timezones(client)
        openflights_airlines = await _fetch_airlines(client)

    canonical_airports = normalize_airports(ourairports_rows, openflights_timezones)
    canonical_airlines = normalize_airlines(openflights_airlines)

    await _upsert_airports(canonical_airports, now)
    await _upsert_airlines(canonical_airlines, now)
    await _recompute_groups(canonical_airports)

    unresolved = sum(
        1 for a in canonical_airports if a.timezone_resolution == TimezoneResolution.UNRESOLVED
    )
    logger.info(
        "reference data ingestion complete",
        extra={
            "airports": len(canonical_airports),
            "airlines": len(canonical_airlines),
            "timezone_unresolved": unresolved,
        },
    )
