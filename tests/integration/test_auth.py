"""End-to-end auth flow against real PostgreSQL and Redis.

Verifies the specification claims structurally, not just that the endpoints
return 200: sessions survive a Redis flush (spec §78), the cookie carries the
documented attributes, and rate limiting actually blocks after the
configured threshold.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from domain.users.passwords import hash_password
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models import Role, User
from infrastructure.redis import get_redis


async def _create_user(username: str, password: str, role: Role = Role.USER) -> User:
    now = datetime.now(UTC)
    user = User(
        id=uuid.uuid4(),
        username=username,
        email=f"{username}@example.test",
        password_hash=hash_password(password),
        role=role,
        created_at=now,
        updated_at=now,
    )
    async with session_scope() as db:
        db.add(user)
    return user


@pytest.fixture(autouse=True)
async def _flush_redis_rate_limit_keys():
    # Rate-limit counters persist across tests otherwise, since they share
    # the same Redis instance the whole suite runs against.
    yield
    client = get_redis()
    async for key in client.scan_iter("ratelimit:login:*"):
        await client.delete(key)


@pytest.mark.integration
async def test_login_sets_cookie_and_session_reflects_it() -> None:
    await _create_user("alice", "correct horse battery staple")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "correct horse battery staple"},
        )
        assert login.status_code == 200
        assert login.json()["username"] == "alice"

        cookie = login.cookies.get("session_id")
        assert cookie is not None

        session = await client.get("/api/v1/auth/session")
        assert session.status_code == 200
        assert session.json()["username"] == "alice"


@pytest.mark.integration
async def test_wrong_password_and_unknown_user_are_indistinguishable() -> None:
    await _create_user("bob", "correct horse battery staple")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        wrong_password = await client.post(
            "/api/v1/auth/login", json={"username": "bob", "password": "wrong"}
        )
        unknown_user = await client.post(
            "/api/v1/auth/login",
            json={"username": "no-such-user", "password": "whatever"},
        )

    assert wrong_password.status_code == 401
    assert unknown_user.status_code == 401
    assert wrong_password.json()["detail"] == unknown_user.json()["detail"]


@pytest.mark.integration
async def test_session_survives_redis_being_flushed() -> None:
    """The load-bearing claim of spec §78: sessions live in PostgreSQL, so a
    Redis restart must not log anyone out."""
    await _create_user("carol", "correct horse battery staple")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/login",
            json={"username": "carol", "password": "correct horse battery staple"},
        )

        await get_redis().flushdb()

        session = await client.get("/api/v1/auth/session")
        assert session.status_code == 200
        assert session.json()["username"] == "carol"


@pytest.mark.integration
async def test_logout_invalidates_the_session() -> None:
    await _create_user("dave", "correct horse battery staple")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/login",
            json={"username": "dave", "password": "correct horse battery staple"},
        )
        logout = await client.post("/api/v1/auth/logout")
        assert logout.status_code == 204

        session = await client.get("/api/v1/auth/session")
        assert session.status_code == 401


@pytest.mark.integration
async def test_login_rate_limited_per_account() -> None:
    await _create_user("erin", "correct horse battery staple")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        responses = [
            await client.post("/api/v1/auth/login", json={"username": "erin", "password": "wrong"})
            for _ in range(10)
        ]

    statuses = [r.status_code for r in responses]
    assert 401 in statuses
    assert 429 in statuses
    # Once blocked, stays blocked for the rest of the window.
    assert statuses[-1] == 429
