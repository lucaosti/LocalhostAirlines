# Multi-stage: builds the SPA, then bakes the static output into a Caddy
# image. Caddy is the only container that serves the frontend in production —
# there is no long-running Node process (docs/adr/0004).
#
# MUST be built with the repository root as context
# (`-f infrastructure/caddy/Dockerfile .`): the builder stage needs apps/web/.

FROM node:22-slim AS web-builder
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM caddy:2-alpine
COPY infrastructure/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=web-builder /web/dist /srv/www
