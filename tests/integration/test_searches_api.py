"""POST/GET /api/v1/searches against real Postgres.

The ARQ pool dependency is overridden with a fake that records the enqueued
job instead of requiring a live Redis + worker process — this test verifies
the API's own persistence and auth behaviour, not job execution (covered
separately by tests/integration/test_travelpayouts_search_job.py).
"""

import random
import string
import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.dependencies import get_arq_pool
from apps.api.main import app
from domain.users.passwords import hash_password
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models import Role, User
from infrastructure.postgres.models_search import CashObservation, Search, SearchState


class _FakeArqPool:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple]] = []

    async def enqueue_job(self, function: str, *args) -> None:
        self.enqueued.append((function, args))


def _search_body(**overrides) -> dict:
    body = {
        "origins": [{"code": "mxp", "weight": 100}],
        "destinations": [{"code": "nrt"}],
        "date_start": "2026-10-01",
        "date_end": "2026-10-05",
        "min_nights": 7,
        "max_nights": 10,
        "cabins": ["economy"],
        "budget": {"calls": 5},
    }
    body.update(overrides)
    return body


async def _create_user_and_login(client: AsyncClient, username: str) -> None:
    now = datetime.now(UTC)
    async with session_scope() as db:
        db.add(
            User(
                id=uuid.uuid4(),
                username=username,
                email=f"{username}@example.test",
                password_hash=hash_password("correct horse battery staple"),
                role=Role.USER,
                created_at=now,
                updated_at=now,
            )
        )
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "correct horse battery staple"},
    )
    assert response.status_code == 200


@pytest.mark.integration
async def test_create_search_enqueues_job_and_returns_pending() -> None:
    fake_pool = _FakeArqPool()
    app.dependency_overrides[get_arq_pool] = lambda: fake_pool
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _create_user_and_login(client, "search-api-1")

            response = await client.post("/api/v1/searches", json=_search_body())
            assert response.status_code == 202
            body = response.json()
            assert body["state"] == "pending"
            # 5 dates x 4 nights x 1 cabin = 20 tasks in the full expansion.
            assert body["space"]["total"] == 20
            assert body["space"]["explored"] == 0
            assert body["space"]["not_explored"] == 20
            assert body["budget"] == {"calls": 5, "spent": 0, "remaining": 5}

            assert fake_pool.enqueued == [("run_travelpayouts_search", (body["id"],))]
    finally:
        app.dependency_overrides.pop(get_arq_pool, None)


@pytest.mark.integration
async def test_create_search_omitting_budget_applies_default() -> None:
    fake_pool = _FakeArqPool()
    app.dependency_overrides[get_arq_pool] = lambda: fake_pool
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _create_user_and_login(client, "search-api-default-budget")

            body = _search_body()
            del body["budget"]
            response = await client.post("/api/v1/searches", json=body)
            assert response.status_code == 202
            assert response.json()["budget"]["calls"] > 0
    finally:
        app.dependency_overrides.pop(get_arq_pool, None)


@pytest.mark.integration
async def test_create_search_rejects_date_end_before_date_start() -> None:
    fake_pool = _FakeArqPool()
    app.dependency_overrides[get_arq_pool] = lambda: fake_pool
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _create_user_and_login(client, "search-api-2")

            response = await client.post(
                "/api/v1/searches",
                json=_search_body(date_start="2026-10-10", date_end="2026-10-01"),
            )
            assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_arq_pool, None)


@pytest.mark.integration
async def test_create_search_rejects_malformed_iata_code() -> None:
    fake_pool = _FakeArqPool()
    app.dependency_overrides[get_arq_pool] = lambda: fake_pool
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _create_user_and_login(client, "search-api-3")

            response = await client.post(
                "/api/v1/searches",
                json=_search_body(origins=[{"code": "not-a-code"}]),
            )
            assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_arq_pool, None)


@pytest.mark.integration
async def test_get_search_not_owned_by_caller_is_404() -> None:
    fake_pool = _FakeArqPool()
    app.dependency_overrides[get_arq_pool] = lambda: fake_pool
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _create_user_and_login(client, "search-api-owner")
            created = await client.post("/api/v1/searches", json=_search_body())
            search_id = created.json()["id"]

        transport2 = ASGITransport(app=app)
        async with AsyncClient(transport=transport2, base_url="http://test") as client2:
            await _create_user_and_login(client2, "search-api-stranger")
            response = await client2.get(f"/api/v1/searches/{search_id}")
            assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_arq_pool, None)


@pytest.mark.integration
async def test_results_reflect_stored_observations_with_provenance() -> None:
    fake_pool = _FakeArqPool()
    app.dependency_overrides[get_arq_pool] = lambda: fake_pool
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _create_user_and_login(client, "search-api-results")
            # Results are queried by route, not by search_id (spec §56) — a
            # route unique to this test avoids picking up other tests'
            # observations for a common fixture route. Letters only: the
            # API's IATA validator rejects digits, which a hex-derived code
            # would sometimes contain.
            origin = "Z" + "".join(random.choices(string.ascii_uppercase, k=2))
            created = await client.post(
                "/api/v1/searches",
                json=_search_body(origins=[{"code": origin}]),
            )
            search_id = created.json()["id"]

            # Simulate what the worker job would have written, without
            # running the real job (that path is tested separately).
            async with session_scope() as db:
                search = await db.get(Search, uuid.UUID(search_id))
                search.state = SearchState.READY
                now = datetime.now(UTC)
                db.add(
                    CashObservation(
                        id=uuid.uuid4(),
                        last_search_id=search.id,
                        itinerary_id="deadbeef",
                        source="travelpayouts",
                        origin=origin,
                        destination="NRT",
                        depart_month="2026-10",
                        price_minor=61200,
                        currency="EUR",
                        freshness="cached",
                        confidence="high",
                        first_seen_at=now,
                        last_seen_at=now,
                        poll_count=1,
                        offer={
                            "offer_id": "travelpayouts:MXP-NRT:2026-10-01",
                            "itinerary_id": "deadbeef",
                            "source": "travelpayouts",
                            "source_offer_id": None,
                            "price_minor": 61200,
                            "taxes_minor": None,
                            "currency": "EUR",
                            "validating_carrier": None,
                            "cabin": None,
                            "fare_brand": None,
                            "slices": [
                                {
                                    "segments": [
                                        {
                                            "origin": origin,
                                            "destination": "NRT",
                                            "departure_utc": "2026-10-01T09:15:00+00:00",
                                            "arrival_utc": None,
                                            "marketing_carrier": "LH",
                                            "flight_number": "510",
                                            "operating_carrier": None,
                                            "aircraft": None,
                                            "booking_class": None,
                                            "cabin": None,
                                        }
                                    ]
                                }
                            ],
                            "baggage": None,
                            "changeability": None,
                            "refundability": None,
                            "booking_link": None,
                            "retrieved_at": "2026-08-13T12:00:00+00:00",
                            "expires_at": None,
                            "freshness": "cached",
                            "confidence": "high",
                            "limitations": ["arrival time and duration not provided"],
                        },
                    )
                )

            response = await client.get(f"/api/v1/searches/{search_id}/results")
            assert response.status_code == 200
            results = response.json()
            assert len(results) == 1
            assert results[0]["price"]["value"]["amount_minor"] == 61200
            assert results[0]["price"]["state"] == "AVAILABLE"
            assert results[0]["price"]["freshness"] == "cached"
            assert results[0]["slices"][0]["segments"][0]["origin"] == origin
            assert results[0]["limitations"]

            search_response = await client.get(f"/api/v1/searches/{search_id}")
            assert search_response.json()["result_count"] == 1
    finally:
        app.dependency_overrides.pop(get_arq_pool, None)
