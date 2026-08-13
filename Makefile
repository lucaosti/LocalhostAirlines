.PHONY: up down dev dev-down build logs ps migrate backup

# Production: exactly docker-compose.yml, six always-on services.
up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

# Development: adds docker-compose.dev.yml (bind mounts, --reload) and the
# dev-only Vite server, both requiring the explicit flags below rather than
# Compose's silent auto-merge (see docker-compose.dev.yml).
dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev up --build

dev-down:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile dev down

logs:
	docker compose logs -f

ps:
	docker compose ps

migrate:
	docker compose exec api alembic upgrade head

# Nightly dump target, invoked by cron/systemd on the host — not run inside
# any container, so BACKUP_TARGET (spec §81) can point anywhere reachable
# from the host regardless of container lifecycle.
backup:
	docker compose exec -T postgres pg_dump -U $${POSTGRES_USER} $${POSTGRES_DB} | gzip > "$${BACKUP_TARGET}/localhostairlines-$$(date +%Y%m%d-%H%M%S).sql.gz"
