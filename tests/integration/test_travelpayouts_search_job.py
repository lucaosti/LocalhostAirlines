"""apps/worker/jobs/travelpayouts_search.py against real Postgres (issue #43).

Network-free: the job's _fetch is injected, same pattern as every other job
in this project (apps/worker/jobs/reference_data.py, fx_rates.py).
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from apps.worker.jobs.travelpayouts_search import run_travelpayouts_search
from domain.users.passwords import hash_password
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models import Role, User
from infrastructure.postgres.models_reference import Airport, TimezoneResolution
from infrastructure.postgres.models_search import CashObservation, Search, SearchState

FIXTURE_BODY = {
    "success": True,
    "data": {
        "2026-10-01": {
            "origin": "MXP",
            "destination": "NRT",
            "price": 612,
            "transfers": 0,
            "airline": "LH",
            "flight_number": 510,
            "departure_at": "2026-10-01T09:15:00Z",
            "return_at": None,
            "expires_at": "2026-08-20T00:00:00Z",
        },
        "2026-10-02": {
            "origin": "MXP",
            "destination": "NRT",
            "price": 700,
            "transfers": 2,  # not normalizable — must be silently excluded, not error
            "airline": "LH",
            "flight_number": 511,
            "departure_at": "2026-10-02T09:15:00Z",
            "return_at": None,
            "expires_at": None,
        },
    },
}


async def _fetch_fixture(request, token):
    return FIXTURE_BODY


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
                username=f"search-job-{search_id.hex[:8]}",
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
async def test_job_normalizes_and_persists_nonstop_only(monkeypatch) -> None:
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "test-token")
    from infrastructure.settings import get_settings

    get_settings.cache_clear()

    await _seed_airport("MXQ")  # distinct code per test, avoids cross-test collisions
    search_id = await _seed_user_and_search("MXQ", "NRT")

    await run_travelpayouts_search({}, str(search_id), _fetch=_fetch_fixture)

    async with session_scope() as db:
        search = await db.get(Search, search_id)
        assert search.state == SearchState.READY
        assert search.completed_at is not None

        rows = (
            (
                await db.execute(
                    select(CashObservation).where(CashObservation.search_id == search_id)
                )
            )
            .scalars()
            .all()
        )
        # Only the transfers=0 entry normalizes (see normalization/travelpayouts.py).
        assert len(rows) == 1
        assert rows[0].price_minor == 61200
        # The fixture's payload states "MXP" regardless of the requested
        # origin ("MXQ") — normalization reads what the source said, not
        # what was asked for, so "MXP" here is correct, not a typo.
        assert rows[0].offer["slices"][0]["segments"][0]["origin"] == "MXP"

    get_settings.cache_clear()


@pytest.mark.integration
async def test_job_fails_search_cleanly_when_token_missing(monkeypatch) -> None:
    monkeypatch.delenv("TRAVELPAYOUTS_TOKEN", raising=False)
    from infrastructure.settings import get_settings

    get_settings.cache_clear()

    await _seed_airport("MXR")
    search_id = await _seed_user_and_search("MXR", "NRT")

    await run_travelpayouts_search({}, str(search_id), _fetch=_fetch_fixture)

    async with session_scope() as db:
        search = await db.get(Search, search_id)
        assert search.state == SearchState.FAILED
        assert search.failure_reason == "authentication"

    get_settings.cache_clear()


@pytest.mark.integration
async def test_job_fails_search_cleanly_when_origin_timezone_unresolved(monkeypatch) -> None:
    monkeypatch.setenv("TRAVELPAYOUTS_TOKEN", "test-token")
    from infrastructure.settings import get_settings

    get_settings.cache_clear()

    # No airport seeded for this origin at all — mirrors an unresolved
    # reference-data row (spec §36's quality gate applies here too).
    search_id = await _seed_user_and_search("ZZZ", "NRT")

    await run_travelpayouts_search({}, str(search_id), _fetch=_fetch_fixture)

    async with session_scope() as db:
        search = await db.get(Search, search_id)
        assert search.state == SearchState.FAILED
        assert search.failure_reason == "not_available"

    get_settings.cache_clear()
