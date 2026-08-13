# MUST be built with the repository root as context (`-f apps/worker/Dockerfile .`)
# — same monorepo reasoning as apps/api/Dockerfile.

FROM python:3.13-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 app

FROM base AS development
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e '.[dev]'
COPY . .
USER app
CMD ["arq", "apps.worker.main.WorkerSettings", "--watch", "."]

FROM base AS production
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY apps ./apps
COPY domain ./domain
COPY infrastructure ./infrastructure
COPY providers ./providers
COPY normalization ./normalization
RUN chown -R app:app /app
USER app
CMD ["arq", "apps.worker.main.WorkerSettings"]
