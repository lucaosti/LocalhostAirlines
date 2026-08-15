"""Full ingestion job against real Postgres, with fetchers injected — real
upsert, soft-delete and grouping logic, never a real network call
(CLAUDE.md §6).
"""

import httpx
import pytest
from sqlalchemy import select

from apps.worker.jobs.reference_data import ingest_reference_data
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models_reference import Airline, Airport, AirportGroupMember
from providers.reference_data.openflights import OpenFlightsAirlineRow, OpenFlightsAirportRow
from providers.reference_data.ourairports import OurAirportsRow

MXP = OurAirportsRow(
    "LIMC", "MXP", "Milano Malpensa", "large_airport", "Milano/Varese", "IT", 45.6306, 8.7281
)
LIN = OurAirportsRow(
    "LIML", "LIN", "Milano Linate", "medium_airport", "Milano", "IT", 45.4451, 9.2767
)
FCO = OurAirportsRow(
    "LIRF", "FCO", "Roma Fiumicino", "large_airport", "Roma", "IT", 41.8003, 12.2389
)

AF = OpenFlightsAirlineRow(
    iata_code="AF", icao_code="AFR", name="Air France", country="France", active=True
)


async def _round_one(client: httpx.AsyncClient) -> list[OurAirportsRow]:
    return [MXP, LIN, FCO]


async def _round_two(client: httpx.AsyncClient) -> list[OurAirportsRow]:
    return [MXP, LIN]  # FCO disappears upstream


async def _empty_timezones(client: httpx.AsyncClient) -> list[OpenFlightsAirportRow]:
    return []


async def _airlines_round_one(client: httpx.AsyncClient) -> list[OpenFlightsAirlineRow]:
    return [AF]


async def _airlines_round_two(client: httpx.AsyncClient) -> list[OpenFlightsAirlineRow]:
    return []  # AF disappears upstream


@pytest.mark.integration
async def test_ingestion_upserts_resolves_timezones_and_groups() -> None:
    await ingest_reference_data(
        {},
        _fetch_ourairports=_round_one,
        _fetch_airport_timezones=_empty_timezones,
        _fetch_airlines=_airlines_round_one,
    )

    async with session_scope() as db:
        airports = {a.icao_code: a for a in (await db.execute(select(Airport))).scalars()}
        airlines = {a.icao_code: a for a in (await db.execute(select(Airline))).scalars()}

        # Read group membership inside the session — AirportGroup.members is
        # a lazy relationship, and accessing it after the session closes
        # raises DetachedInstanceError. Querying the join table directly
        # sidesteps that rather than fighting session lifetime.
        members = (await db.execute(select(AirportGroupMember))).scalars().all()

    assert airports["LIMC"].timezone == "Europe/Rome"
    assert airports["LIMC"].active is True
    assert airports["LIRF"].active is True

    # Exactly one group is expected (Milan: MXP+LIN). FCO stays ungrouped
    # (no other groupable airport within range), so the whole join table is
    # this one group's membership.
    group_ids = {m.group_id for m in members}
    assert len(group_ids) == 1
    assert {m.airport_icao_code for m in members} == {"LIMC", "LIML"}

    assert airlines["AFR"].active is True


@pytest.mark.integration
async def test_disappearing_codes_are_deactivated_not_deleted() -> None:
    await ingest_reference_data(
        {},
        _fetch_ourairports=_round_one,
        _fetch_airport_timezones=_empty_timezones,
        _fetch_airlines=_airlines_round_one,
    )
    await ingest_reference_data(
        {},
        _fetch_ourairports=_round_two,
        _fetch_airport_timezones=_empty_timezones,
        _fetch_airlines=_airlines_round_two,
    )

    async with session_scope() as db:
        fco = await db.get(Airport, "LIRF")
        afr = await db.get(Airline, "AFR")

    # Deactivated, never hard-deleted — the row still exists for anything
    # that already references it.
    assert fco is not None
    assert fco.active is False
    assert afr is not None
    assert afr.active is False
