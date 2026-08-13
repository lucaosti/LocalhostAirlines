# Dev-only image: the Vite dev server, bind-mounted and hot-reloading.
# There is no production target here — in production the static build is
# baked into the Caddy image instead (infrastructure/caddy/Dockerfile), so
# there is no long-running Node process at all (docs/adr/0004).
#
# Context is apps/web/ itself — unlike api/worker/scraper this app has no
# dependency on the repo-root Python packages.

FROM node:22-slim
WORKDIR /app
# The official image already ships a UID-1000 `node` user; adding another one
# at the same UID fails outright, so this reuses it rather than creating one.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN chown -R node:node /app
USER node
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
