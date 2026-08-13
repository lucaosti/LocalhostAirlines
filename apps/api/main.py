"""FastAPI application factory.

Conventions from docs/api.md §1 are enforced here, once, rather than per router:
every domain route lives under /api/v1, every error response is
application/problem+json (apps/api/errors.py), and every log line is structured
JSON with sensitive fields redacted (infrastructure/logging.py).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from apps.api.errors import register_error_handlers
from apps.api.routers import auth, health, travellers
from infrastructure.logging import configure_logging
from infrastructure.settings import get_settings

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("application startup", extra={"base_currency": settings.base_currency})
        yield
        logger.info("application shutdown")

    app = FastAPI(title="LocalhostAirlines", version="0.1.0", lifespan=lifespan)
    register_error_handlers(app)

    # Health is infrastructure plumbing, not a versioned domain resource
    # (apps/api/routers/health.py), so it is mounted at the root rather than
    # under the v1 prefix.
    app.include_router(health.router)

    v1 = APIRouter(prefix="/api/v1")
    # Domain routers attach to `v1` as they land in their own issues, keeping
    # the version boundary in exactly one place.
    v1.include_router(auth.router)
    v1.include_router(travellers.router)
    app.include_router(v1)

    return app


app = create_app()
