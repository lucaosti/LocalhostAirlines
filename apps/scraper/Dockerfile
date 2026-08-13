# MUST be built with the repository root as context (`-f apps/scraper/Dockerfile .`)
# — same monorepo reasoning as apps/api/Dockerfile.
#
# Heavier than the other images by necessity: Chromium plus its OS-level
# dependencies. Isolated in its own container specifically so this weight
# never has to be paid by api or worker (CLAUDE.md §6).

FROM python:3.13-slim AS base
WORKDIR /app
RUN useradd --create-home --uid 1000 app

FROM base AS deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e '.[dev,scraper]'
# Playwright's default browser cache is under the *installing* user's home,
# but this stage installs as root while the container later runs as `app` —
# without a fixed, user-independent path, the app user wouldn't find the
# browser binaries root just installed. PLAYWRIGHT_BROWSERS_PATH pins it.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# --with-deps installs the OS packages Chromium needs (fonts, codecs, X11
# libs) so the final image needs no further apt-get at runtime.
RUN playwright install --with-deps chromium && chmod -R a+rX /ms-playwright

FROM deps AS development
COPY . .
USER app
CMD ["arq", "apps.scraper.main.WorkerSettings", "--watch", "."]

FROM deps AS production
COPY apps ./apps
COPY domain ./domain
COPY infrastructure ./infrastructure
COPY providers ./providers
COPY normalization ./normalization
RUN chown -R app:app /app
USER app
CMD ["arq", "apps.scraper.main.WorkerSettings"]
