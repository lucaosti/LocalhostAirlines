"""Alembic environment.

Reads DATABASE_URL from the application's own Settings rather than duplicating it
in alembic.ini, so there is exactly one place the connection string is configured
(spec §6: configuration comes from .env only).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config

from infrastructure.postgres.base import Base
from infrastructure.postgres.models import *  # noqa: F401,F403  # registers models on Base.metadata
from infrastructure.postgres.models_fx import *  # noqa: F401,F403
from infrastructure.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    # asyncpg is the runtime driver; Alembic's sync-style API still needs a
    # synchronous-looking connection, so we drive it through the async engine
    # below rather than swapping drivers here.
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connectable = async_engine_from_config(configuration, prefix="sqlalchemy.")

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
