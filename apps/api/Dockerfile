# Multi-stage: a shared base, then a development target (bind-mounted source,
# --reload) and a production target (source baked in, no reload). Compose
# selects the target per docker-compose.yml / docker-compose.override.yml.
#
# MUST be built with the repository root as context (`-f apps/api/Dockerfile .`)
# — it copies domain/, infrastructure/, providers/ and normalization/ from
# outside apps/api/, since this is a monorepo where those packages are shared
# across api, worker and scraper.

FROM python:3.13-slim AS base
WORKDIR /app
# libpq is needed at runtime by asyncpg's C extension build step and by psql-
# adjacent tooling; kept minimal deliberately (spec §4: storage is cheap,
# but there is no reason to bloat the image with a compiler toolchain nobody
# needs after install).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 app

FROM base AS development
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e '.[dev]'
# Source is bind-mounted by docker-compose.override.yml; this COPY is a
# fallback so the image is still runnable standalone (e.g. `docker build` in
# CI) without a mount.
COPY . .
USER app
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS production
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY apps ./apps
COPY domain ./domain
COPY infrastructure ./infrastructure
COPY providers ./providers
COPY normalization ./normalization
COPY alembic.ini ./
COPY infrastructure/postgres/alembic ./infrastructure/postgres/alembic
COPY infrastructure/docker/api-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && chown -R app:app /app
USER app
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
