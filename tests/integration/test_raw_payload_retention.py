"""Raw payload retention against real Postgres (issue #52).

The key property under test: the raw payload survives even when
normalization fails on it — that is the entire point of retaining it
(spec §4's reprocessing guarantee would be worthless otherwise).
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from apps.worker.jobs.travelpayouts_search import run_travelpayouts_search
from domain.users.passwords import hash_password
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models import Role, User
from infrastructure.postgres.models_raw import RawPayload
from infrastructure.postgres.models_reference import Airport, TimezoneResolution
from infrastructure.postgres.models_search import Search, SearchState
from infrastructure.postgres.raw_payloads import load_raw_payload

VALID_BODY = {
    "success": True,
    "data": {
        "2026-10-01": {
            "origin": "MXS",
            "destination": "NRT",
            "price": 612,
            "transfers": 0,
            "airline": "LH",
            "flight_number": 510,
            "departure_at": "2026-10-01T09:15:00Z",
            "return_at": None,
            "expires_at": None,
        }
    },
}

# Well-formed envelope, malformed entry — passes the client's own envelope
# check but fails normalization (missing "price").
MALFORMED_ENTRY_BODY = {
    "success": True,
    "data": {"2026-10-01": {"origin": "MXS", "destination": "NRT"}},
}


async def _seed_airport(iata_code: str) -> None:
    async with session_scope() as db:
        db.add(
            Airport(
                icao_code=f"Z{iata_code}",
                iata_code=iata_code,
                name=f"{iata_code} test airport",
                airport_type="large_airport",
                municipality="test",
                iso_country="IT",
                latitude=45.0,
                longitude=9.0,
                timezone="Europe/Rome",
                timezone_resolution=TimezoneResolution.OPENFLIGHTS,
                source="test",
                retrieved_at=datetime.now(UTC),
            )
        )


async def _seed_user_and_search(origin: str, destination: str) -> uuid.UUID:
    now = datetime.now(UTC)
    user_id = uuid.uuid4()
    search_id = uuid.uuid4()
    async with session_scope() as db:
        db.add(
            User(
                id=user_id,
                username=f"raw-payload-{search_id.hex[:8]}",
                email=f"{search_id.hex[:8]}@example.test",
                password_hash=hash_password("correct horse battery staple"),
                role=Role.USER,
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            Search(
                id=search_id,
                user_id=user_id,
                origin=origin,
                destination=destination,
                depart_month="2026-10",
                state=SearchState.PENDING,
                created_at=now,
            )
        )
    return search_id


@pytest.mark.integration
async def test_successful_search_retains_raw_payload(monkeypatch) -> None:
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "test-token")
    from infrastructure.settings import get_settings

    get_settings.cache_clear()

    await _seed_airport("MXS")
    search_id = await _seed_user_and_search("MXS", "NRT")

    async def fetch(request, token):
        return VALID_BODY

    await run_travelpayouts_search({}, str(search_id), _fetch=fetch)

    async with session_scope() as db:
        rows = (
            (
                await db.execute(
                    select(RawPayload).where(RawPayload.request_key == "MXS-NRT:2026-10")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].source == "travelpayouts"
        assert load_raw_payload(rows[0]) == VALID_BODY

    get_settings.cache_clear()


@pytest.mark.integration
async def test_raw_payload_survives_normalization_failure(monkeypatch) -> None:
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "test-token")
    from infrastructure.settings import get_settings

    get_settings.cache_clear()

    await _seed_airport("MXT")
    search_id = await _seed_user_and_search("MXT", "NRT")

    async def fetch(request, token):
        return MALFORMED_ENTRY_BODY

    await run_travelpayouts_search({}, str(search_id), _fetch=fetch)

    async with session_scope() as db:
        search = await db.get(Search, search_id)
        # The job itself correctly failed on the malformed entry...
        assert search.state == SearchState.FAILED
        assert search.failure_reason == "schema_change"

        # ...but the raw payload that caused the failure is still there,
        # exactly the case spec §4 exists for: a parser fix can be re-run
        # against it without recontacting the source.
        rows = (
            (
                await db.execute(
                    select(RawPayload).where(RawPayload.request_key == "MXT-NRT:2026-10")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert load_raw_payload(rows[0]) == MALFORMED_ENTRY_BODY

    get_settings.cache_clear()
