# BillWatcherNext: Parliament's bills, downloaded as files, read into markdown, published as a
# graph. Every target below is re-runnable, and only `download` touches the network.
#
#   make setup     once, on a fresh clone
#   make download  the live crawl — hours, resumable, safe to interrupt
#   make build     everything else, offline, from the corpus to a complete docs/

.DEFAULT_GOAL := help

UV ?= uv
# pnpm 7 is pinned by web/package.json's `packageManager` field and fetched by corepack, so the
# frontend builds identically regardless of which pnpm happens to be on PATH.
PNPM ?= COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack pnpm
WEB ?= web

# Upstream serves an incomplete certificate chain; see documentation/upstream.md.
UPSTREAM_INTERMEDIATE_URL ?= http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt
SYSTEM_CA_BUNDLE ?= /etc/ssl/certs/ca-certificates.crt

# LANG_CODE, not LANG: `LANG` is the shell's own locale variable, so a bare `make` would silently
# forward en_US.UTF-8 as the document language.
LANG_CODE ?= ms

# Where `make coverage` writes its report. Tracked rather than under var/, because the point of a
# Markdown report is that `git diff` shows coverage moving between two runs.
COVERAGE_MD ?= documentation/coverage.md

.PHONY: help setup env \
        download download-listings download-documents \
        markdown import-markdown import-crosscheck cross-reference \
        handoff akn graph \
        publish site build rebuild \
        coverage verify check test lint typecheck format \
        web-lint web-typecheck web-test web-format web-format-check dev \
        ca-bundle clean clean-site

help: ## Show available targets
	@echo "Fresh clone:   make setup && make build"
	@echo "Live crawl:    make download        (hours; resumable; needs approval)"
	@echo ""
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_-]+:.*## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# --- setup ---------------------------------------------------------------------------------

setup: env ## Install both locked toolchains: Python via uv, frontend via pnpm
	$(UV) sync --locked --all-groups
	cd $(WEB) && $(PNPM) install --frozen-lockfile

env: ## Create .env from the development defaults if it does not exist
	@if [ -f .env ]; then \
		echo ".env already exists; leaving it alone"; \
	else \
		cp .env.development .env; \
		echo "created .env from .env.development"; \
	fi

# --- stage 1: download (the only live stage) -------------------------------------------------

download: download-listings download-documents coverage ## The whole corpus: listings, bills, every PDF
	@echo ""
	@echo "corpus downloaded; run 'make build' to read and publish it"

download-listings: ## Fetch and parse the listings and the whole archive tree; live
	$(UV) run billwatcher fetch-listings --approve-live $(ARGS)
	$(UV) run billwatcher parse-listings

download-documents: ## Download every document PDF named in the bills; live, resumable
	$(UV) run billwatcher fetch-documents --approve-live $(ARGS)

# --- stage 2: markdown -----------------------------------------------------------------------

markdown: ## Read every stored PDF locally into markdown; offline, no model; LANG_CODE=ms
	@# LANG_CODE is the fallback only: each document is read in the language of the listing that
	@# named it (ADR-040), which the corpus records per document.
	$(UV) run billwatcher extract-markdown --language "$(LANG_CODE)" $(ARGS)

import-markdown: ## Record a reading produced elsewhere; SRC=path LANG_CODE=ms TOOL=name
	$(UV) run billwatcher import-markdown --source "$(SRC)" --language "$(LANG_CODE)" \
		--tool "$(TOOL)" $(ARGS)

import-crosscheck: ## Record a second reading beside the first; SRC=path TOOL=name
	$(UV) run billwatcher import-crosscheck --source "$(SRC)" --tool "$(TOOL)" $(ARGS)

cross-reference: ## Compare each document's two readings and name where they disagree; offline
	$(UV) run billwatcher cross-reference $(ARGS)

# --- stage 3: the semantic graph -------------------------------------------------------------

handoff: ## Write one structure work packet per document, for an agent or a person; OUT=dir
	@test -n "$(OUT)" || { echo "OUT=<directory> is required"; exit 2; }
	$(UV) run billwatcher structure-handoff --out "$(OUT)" $(ARGS)

akn: ## Markdown -> Akoma Ntoso XML, gated. FROM=<handoff dir> to read answers back
	$(UV) run billwatcher convert-to-akn $(if $(FROM),--from-handoff "$(FROM)",) $(ARGS)

graph: ## Akoma Ntoso -> ELI JSON-LD + RDF N-Quads; offline
	$(UV) run billwatcher generate-semantic

# --- stage 4: publish ------------------------------------------------------------------------

publish: ## Write the gate-passing dataset into docs/; additive, never deletes
	$(UV) run billwatcher publish $(ARGS)

site: ## Build the React frontend into docs/, beside the dataset
	cd $(WEB) && $(PNPM) run build

build: markdown graph publish site coverage ## The replicable build: corpus in, complete docs/ out
	@echo ""
	@echo "docs/ is complete. Commit it to publish; GitHub Pages serves this repository's docs/."
	@echo "Coverage after this build is in $(COVERAGE_MD)."

rebuild: ## Same as build, but also delete dataset files that are no longer published
	$(MAKE) markdown akn graph
	$(UV) run billwatcher publish --prune
	$(MAKE) site

dev: ## Run the frontend against the published tree, with hot reload
	cd $(WEB) && $(PNPM) run dev

# --- quality ---------------------------------------------------------------------------------

coverage: ## Report what the corpus holds and what is missing; offline, read-only, never fails
	$(UV) run billwatcher coverage --markdown "$(COVERAGE_MD)" >/dev/null

verify: ## Re-hash the corpus against its own sidecars, provenance and gate verdicts
	$(UV) run billwatcher verify $(ARGS)

check: lint typecheck test web-lint web-typecheck web-test web-format-check ## Every offline quality gate

lint: ## Ruff checks
	$(UV) run ruff check src tests

typecheck: ## Strict mypy
	$(UV) run mypy src

test: ## The offline Python suite
	$(UV) run pytest

format: ## Format both toolchains
	$(UV) run ruff format src tests
	cd $(WEB) && $(PNPM) run format

web-lint: ## oxlint
	cd $(WEB) && $(PNPM) run lint

web-typecheck: ## tsc, both project references
	cd $(WEB) && $(PNPM) run typecheck

web-test: ## The frontend suite: does the page built from the dataset actually render
	cd $(WEB) && $(PNPM) run test

web-format-check: ## oxfmt, without writing
	cd $(WEB) && $(PNPM) run format:check

# --- utilities ---------------------------------------------------------------------------------

ca-bundle: ## Build a trust bundle containing the intermediate upstream fails to send
	@mkdir -p var
	curl -fsS $(UPSTREAM_INTERMEDIATE_URL) -o var/upstream-intermediate.crt
	@openssl x509 -inform DER -in var/upstream-intermediate.crt -out var/upstream-intermediate.pem \
		2>/dev/null || openssl x509 -in var/upstream-intermediate.crt -out var/upstream-intermediate.pem
	@openssl x509 -in var/upstream-intermediate.pem -noout -subject -enddate
	cat $(SYSTEM_CA_BUNDLE) var/upstream-intermediate.pem > var/upstream-ca.pem
	@echo ""
	@echo "Wrote var/upstream-ca.pem. Set this in .env:"
	@echo "  UPSTREAM_CA_BUNDLE=$(CURDIR)/var/upstream-ca.pem"

clean: ## Remove build scratch. Never touches corpus/ or docs/
	rm -rf .pytest_cache .mypy_cache .ruff_cache $(WEB)/node_modules/.tmp $(WEB)/node_modules/.vite
	find src tests -name '__pycache__' -type d -prune -exec rm -rf {} +

clean-site: ## Remove ONLY the frontend's own output from docs/, leaving the dataset
	@test "$$CONFIRM_CLEAN" = "yes" || { echo "Set CONFIRM_CLEAN=yes to delete built site files"; exit 2; }
	rm -rf docs/assets docs/index.html docs/404.html
