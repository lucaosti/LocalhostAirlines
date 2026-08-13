"""End-to-end traveller profile and companion flow against real Postgres."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from domain.users.passwords import hash_password
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models import Role, User


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


MINIMAL_PROFILE = {
    "display_name": "Primary",
    "passport_countries": ["it"],
}


@pytest.mark.integration
async def test_create_and_fetch_traveller_normalizes_passport_case() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _create_user_and_login(client, "traveller-owner-1")

        created = await client.post("/api/v1/travellers", json=MINIMAL_PROFILE)
        assert created.status_code == 201
        body = created.json()
        assert body["passport_countries"] == ["IT"]  # lowercase input, uppercased

        fetched = await client.get(f"/api/v1/travellers/{body['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["display_name"] == "Primary"


@pytest.mark.integration
async def test_traveller_requires_at_least_one_passport() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _create_user_and_login(client, "traveller-owner-2")

        response = await client.post(
            "/api/v1/travellers",
            json={"display_name": "No passport", "passport_countries": []},
        )
        assert response.status_code == 422


@pytest.mark.integration
async def test_travellers_are_not_visible_across_users() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _create_user_and_login(client, "traveller-owner-3")
        created = await client.post("/api/v1/travellers", json=MINIMAL_PROFILE)
        traveller_id = created.json()["id"]

        await client.post("/api/v1/auth/logout")
        await _create_user_and_login(client, "traveller-owner-4")

        response = await client.get(f"/api/v1/travellers/{traveller_id}")
        assert response.status_code == 404


@pytest.mark.integration
async def test_companion_requires_explicit_points_relationship() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _create_user_and_login(client, "companion-owner-1")
        primary = (await client.post("/api/v1/travellers", json=MINIMAL_PROFILE)).json()
        companion = (
            await client.post(
                "/api/v1/travellers",
                json={"display_name": "Companion", "passport_countries": ["IT"]},
            )
        ).json()

        # No points_relationship in the body at all — must be rejected, not
        # defaulted (issue #13's central acceptance criterion).
        missing_field = await client.post(
            f"/api/v1/travellers/{primary['id']}/companions",
            json={"companion_id": companion["id"]},
        )
        assert missing_field.status_code == 422

        explicit = await client.post(
            f"/api/v1/travellers/{primary['id']}/companions",
            json={"companion_id": companion["id"], "points_relationship": "NOT_COMBINABLE"},
        )
        assert explicit.status_code == 201
        assert explicit.json()["points_relationship"] == "NOT_COMBINABLE"


@pytest.mark.integration
async def test_duplicate_companion_pair_is_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _create_user_and_login(client, "companion-owner-2")
        primary = (await client.post("/api/v1/travellers", json=MINIMAL_PROFILE)).json()
        companion = (
            await client.post(
                "/api/v1/travellers",
                json={"display_name": "Companion", "passport_countries": ["IT"]},
            )
        ).json()

        body = {"companion_id": companion["id"], "points_relationship": "TRANSFERABLE"}
        first = await client.post(f"/api/v1/travellers/{primary['id']}/companions", json=body)
        second = await client.post(f"/api/v1/travellers/{primary['id']}/companions", json=body)

        assert first.status_code == 201
        assert second.status_code == 409


@pytest.mark.integration
async def test_companion_cannot_be_self() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _create_user_and_login(client, "companion-owner-3")
        primary = (await client.post("/api/v1/travellers", json=MINIMAL_PROFILE)).json()

        response = await client.post(
            f"/api/v1/travellers/{primary['id']}/companions",
            json={"companion_id": primary["id"], "points_relationship": "SHAREABLE"},
        )
        assert response.status_code == 422
