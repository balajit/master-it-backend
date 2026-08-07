# Makefile — master-it-backend
#
# Targets for managing the URL-to-PDF microservice Docker image and
# the full docker-compose stack.
#
# Usage:
#   make build-url-pdf         Build the url-pdf-service Docker image
#   make start-url-pdf         Start in local dev mode (hot-reload)
#   make start-url-pdf-prod    Start in local production mode
#   make up                    Start all infrastructure services
#   make up-url-pdf            Start url-pdf-service only (Docker)
#   make redeploy-url-pdf      Rebuild + force-recreate url-pdf-service
#   make logs-url-pdf          Tail url-pdf-service logs
#   make down                  Stop and remove all containers
#   make ps                    Show running containers

.PHONY: build-url-pdf start-url-pdf start-url-pdf-prod up up-url-pdf redeploy-url-pdf logs-url-pdf down ps

# ── URL-to-PDF microservice — local ──────────────────────────────────────────

## Start url-pdf-service locally in dev mode (hot-reload, port 8001)
start-url-pdf:
	./scripts/start_url_pdf_service.sh --dev

## Start url-pdf-service locally in production mode (4 workers, port 8001)
start-url-pdf-prod:
	./scripts/start_url_pdf_service.sh --production

# ── URL-to-PDF microservice — Docker ─────────────────────────────────────────

## Build the url-pdf-service Docker image
build-url-pdf:
	docker compose build url-pdf-service

## Start url-pdf-service container via Docker (build if image is missing)
up-url-pdf:
	docker compose up -d url-pdf-service

## Rebuild and force-recreate url-pdf-service (applies code changes)
redeploy-url-pdf:
	docker compose build url-pdf-service
	docker compose up -d --force-recreate url-pdf-service

## Tail url-pdf-service logs (Ctrl+C to exit)
logs-url-pdf:
	docker compose logs -f url-pdf-service

# ── Full stack ────────────────────────────────────────────────────────────────

## Start all infrastructure services (postgres, minio, url-pdf-service)
up:
	docker compose up -d

## Stop and remove all containers (data volumes are preserved)
down:
	docker compose down

## Show status of all containers
ps:
	docker compose ps
