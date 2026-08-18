.DEFAULT_GOAL := help
UV ?= uv
COMPOSE ?= docker compose
DEV_COMPOSE ?= docker compose -f compose.dev.yaml
# The PostgreSQL-only test suite needs a disposable database; this one is created by `make db-up`.
TEST_DATABASE_URL ?= postgresql+psycopg://billwatcher:billwatcher@127.0.0.1:55432/billwatcher_test
# Upstream serves an incomplete certificate chain; see docs/upstream.md and `make ca-bundle`.
UPSTREAM_INTERMEDIATE_URL ?= http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt
SYSTEM_CA_BUNDLE ?= /etc/ssl/certs/ca-certificates.crt
BACKUP_DIR ?=
BLOB_BACKUP_DEST ?=
RESTORE_PATH ?=
BLOB_RESTORE_PATH ?=

.PHONY: help quickstart env ca-bundle db-up db-down db-reset seed test-pg setup lock format lint typecheck test test-live check serve migrate scrape scrape-full status doctor reparse reextract rechunk reembed retention evaluate semantic-index verify-storage prune-blobs fixtures-refresh docker-build compose-up compose-down logs backup backup-blobs restore restore-blobs

help: ## Show available targets
	@echo "Start here:  make quickstart   (env + database + migrations + fixture data + server)"
	@echo ""
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_-]+:.*## / {printf "%-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

quickstart: setup env db-up migrate seed ## One command from a fresh clone to a running site
	@echo ""
	@echo "Ready. The site is at http://127.0.0.1:8000 with fixture data loaded."
	@echo "Stop the server with Ctrl-C; stop the database with 'make db-down'."
	@echo ""
	$(MAKE) serve

env: ## Create .env from the development defaults if it does not exist
	@if [ -f .env ]; then \
		echo ".env already exists; leaving it alone"; \
	else \
		cp .env.development .env; \
		echo "created .env from .env.development"; \
	fi

db-up: ## Start the local development PostgreSQL and wait for it
	$(DEV_COMPOSE) up -d --wait
	@$(DEV_COMPOSE) exec -T db psql -q -U billwatcher -d billwatcher \
		-c "CREATE DATABASE billwatcher_test" 2>/dev/null || true

db-down: ## Stop the local development database, keeping its volume
	$(DEV_COMPOSE) down

db-reset: ## Delete the local development database and its data
	@test "$$CONFIRM_RESET" = "yes" || { echo "Set CONFIRM_RESET=yes to delete dev data"; exit 2; }
	$(DEV_COMPOSE) down -v

ca-bundle: ## Build a trust bundle containing the intermediate the site fails to send
	@mkdir -p var
	@echo "Fetching the intermediate named by the leaf certificate's AIA extension..."
	curl -fsS $(UPSTREAM_INTERMEDIATE_URL) -o var/upstream-intermediate.crt
	@openssl x509 -inform DER -in var/upstream-intermediate.crt -out var/upstream-intermediate.pem 2>/dev/null \
		|| openssl x509 -in var/upstream-intermediate.crt -out var/upstream-intermediate.pem
	@openssl x509 -in var/upstream-intermediate.pem -noout -subject -enddate
	cat $(SYSTEM_CA_BUNDLE) var/upstream-intermediate.pem > var/upstream-ca.pem
	@echo ""
	@echo "Wrote var/upstream-ca.pem. Set this in .env:"
	@echo "  UPSTREAM_CA_BUNDLE=$(CURDIR)/var/upstream-ca.pem"
	@echo "Re-run this if the intermediate expires, and drop it once upstream fixes its chain."

seed: ## Ingest the committed fixtures offline; never contacts Parliament
	$(UV) run billwatcher load-fixtures

test-pg: ## Run the full suite including the PostgreSQL-only tests
	BILLWATCHER_TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(UV) run pytest

setup: ## Install the exact locked development environment
	$(UV) sync --locked --all-groups

lock: ## Validate uv.lock without changing it
	$(UV) lock --check

format: ## Format Python sources
	$(UV) run ruff format src tests migrations

lint: ## Run Ruff checks
	$(UV) run ruff check src tests migrations

typecheck: ## Run strict mypy
	$(UV) run mypy src

test: ## Run all offline tests
	$(UV) run pytest

test-live: ## Run tiny live tests only with BILLWATCHER_LIVE_TEST=1
	@test "$$BILLWATCHER_LIVE_TEST" = "1" || { echo "Set BILLWATCHER_LIVE_TEST=1 to opt in"; exit 2; }
	$(UV) run pytest -m live -q

check: lint typecheck test ## Run every offline quality gate

serve: ## Run the local development server
	$(UV) run billwatcher serve --reload

migrate: ## Upgrade the configured database to Alembic head
	$(UV) run billwatcher migrate

scrape: ## Explicitly run one approved live incremental crawl
	$(UV) run billwatcher scrape --approve-live

scrape-full: ## Explicitly run one approved live full crawl
	$(UV) run billwatcher scrape --full --approve-live

status: ## Print runtime coverage, queue, run, and pipeline status
	$(UV) run billwatcher status

doctor: ## Fail on critical anomalies or invariant/storage failures
	$(UV) run billwatcher doctor

reparse: ## Dry-run snapshot replay; pass ARGS=--apply to mutate
	$(UV) run billwatcher reparse $(ARGS)

reextract: ## Dry-run extraction backfill; pass ARGS=--apply to mutate
	$(UV) run billwatcher reextract $(ARGS)

rechunk: ## Dry-run chunk rebuild at the current chunker version; ARGS=--apply
	$(UV) run billwatcher rechunk $(ARGS)

reembed: ## Dry-run embedding backfill for the configured model; ARGS=--apply
	$(UV) run billwatcher reembed $(ARGS)

evaluate: ## Score the versioned retrieval/answer evaluation set offline
	$(UV) run billwatcher evaluate

semantic-index: ## Build the pgvector HNSW index; pass ARGS=--apply
	$(UV) run billwatcher semantic-index $(ARGS)

retention: ## Dry-run retention (transport log rollup, extraction pruning); ARGS=--apply
	$(UV) run billwatcher retention $(ARGS)

verify-storage: ## Verify every database blob reference on disk
	$(UV) run billwatcher verify-storage

prune-blobs: ## Dry-run unreferenced blob pruning; pass ARGS=--apply
	$(UV) run billwatcher prune-blobs $(ARGS)

fixtures-refresh: ## Validate stored snapshots offline without crawling
	$(UV) run billwatcher reparse

docker-build: ## Build the locked production image
	$(COMPOSE) build --pull

compose-up: ## Start the production-shaped stack without deleting volumes
	$(COMPOSE) up -d

compose-down: ## Stop the stack without deleting volumes
	$(COMPOSE) down

logs: ## Follow bounded application and worker logs
	$(COMPOSE) logs --tail=200 -f app worker

backup: ## Dump PostgreSQL; requires BACKUP_DIR
	@test -n "$(BACKUP_DIR)" || { echo "BACKUP_DIR is required"; exit 2; }
	@mkdir -p "$(BACKUP_DIR)"
	$(COMPOSE) exec -T db sh -c 'pg_dump -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -Fc' > "$(BACKUP_DIR)/billwatcher-$$(date -u +%Y%m%dT%H%M%SZ).dump"

backup-blobs: ## Copy blobs; requires BLOB_BACKUP_DEST
	@test -n "$(BLOB_BACKUP_DEST)" || { echo "BLOB_BACKUP_DEST is required"; exit 2; }
	$(COMPOSE) cp worker:/var/lib/billwatcher/blobs/. "$(BLOB_BACKUP_DEST)"

restore: ## Guarded DB restore; requires RESTORE_PATH and CONFIRM_RESTORE=yes
	@test -f "$(RESTORE_PATH)" || { echo "RESTORE_PATH must name a dump"; exit 2; }
	@test "$$CONFIRM_RESTORE" = "yes" || { echo "Set CONFIRM_RESTORE=yes"; exit 2; }
	$(COMPOSE) exec -T db sh -c 'pg_restore --clean --if-exists -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < "$(RESTORE_PATH)"

restore-blobs: ## Guarded blob restore; requires BLOB_RESTORE_PATH and CONFIRM_RESTORE=yes
	@test -d "$(BLOB_RESTORE_PATH)" || { echo "BLOB_RESTORE_PATH must name a directory"; exit 2; }
	@test "$$CONFIRM_RESTORE" = "yes" || { echo "Set CONFIRM_RESTORE=yes"; exit 2; }
	$(COMPOSE) cp --archive=false "$(BLOB_RESTORE_PATH)/." worker:/var/lib/billwatcher/blobs
	$(COMPOSE) exec -T --user 0 worker chown -R 10001:10001 /var/lib/billwatcher/blobs
