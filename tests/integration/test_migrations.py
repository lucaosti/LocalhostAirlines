"""Migration round-trip test.

Requires a live PostgreSQL reachable at DATABASE_URL — provided as a service
container in CI (see .github/workflows/ci.yml) and started manually for local runs.
Deliberately not mocked: a fake database cannot catch what this test exists to
catch, which is real DDL failures like the ENUM-type-not-dropped bug this exact
test found during development.
"""

import subprocess

import pytest

from infrastructure.postgres.database import get_engine


def run_alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["alembic", *args], capture_output=True, text=True, check=False, cwd=".")


@pytest.mark.integration
async def test_migration_round_trips_twice() -> None:
    """Upgrade, downgrade, upgrade again. A migration whose downgrade leaves
    residue (like a Postgres ENUM type Alembic doesn't drop automatically) fails
    on the second upgrade, not the first — so a single upgrade is not enough to
    trust a downgrade.
    """
    for _ in range(2):
        upgrade = run_alembic("upgrade", "head")
        assert upgrade.returncode == 0, upgrade.stderr

        downgrade = run_alembic("downgrade", "base")
        assert downgrade.returncode == 0, downgrade.stderr

    # Leave the schema applied for any test that runs after this one.
    final = run_alembic("upgrade", "head")
    assert final.returncode == 0, final.stderr

    # This subprocess round-trip DROPs and CREATEs Postgres types (the `role`
    # and `pointsrelationship` ENUMs) outside the app's own connection pool.
    # asyncpg caches type OIDs per connection and never notices the DDL
    # underneath it, so a pooled connection reused by a later test fails with
    # "cache lookup failed for type <old-oid>" the moment it tries to encode
    # or decode an enum column. Disposing the pool forces fresh connections
    # with correct type OIDs for whatever runs next in this pytest session.
    await get_engine().dispose()
