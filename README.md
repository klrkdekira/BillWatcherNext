# BillWatcherNext

BillWatcherNext is a provenance-first, read-only index of Malaysian Parliament bills. It preserves
timestamped listing snapshots and private document bytes, exposes server-rendered browse/search
pages, and records every accepted document content state instead of overwriting it.

Parliament of Malaysia remains the authority. A normalized status is an index classification, and a
bill marked passed by a chamber is not represented as enacted or currently in force.

## Local development

Requirements: Python 3.12.5+, uv, and PostgreSQL 16 for full integration.

Copy .env.example to .env, replace placeholders, and set ENVIRONMENT=development for local HTTP.
Then run make setup, make migrate, make check, and make serve.

The public application is at http://127.0.0.1:8000. JavaScript is not required. Offline tests use
saved fixtures and SQLite and never contact Parliament. Behaviour that only exists on PostgreSQL
(the weighted tsvector, ranking, snippets, and pgvector retrieval) runs when
BILLWATCHER_TEST_DATABASE_URL names a disposable database, and skips otherwise. Live tests require
BILLWATCHER_LIVE_TEST=1 make test-live. A live crawl requires the explicit make scrape target.

Before crawling, complete the discovery gates in docs/upstream.md: review robots.txt, archive
request behavior, bilingual labels/statuses, TLS, and the configured contact identity. Live
crawling is disabled by default.

## Operations

make help lists the stable interface. Important targets include make check, make docker-build,
make compose-up, make status, make doctor, make verify-storage, make retention, dry-run-first
backfills, and guarded database/blob backup and restore targets.

## Optional Release 3 features

Semantic search and generated answers are behind SEMANTIC_SEARCH_ENABLED and RAG_ENABLED, both
off by default, and the site is complete without them. Neither can start without an explicitly
configured model: no embedding model or answer provider is chosen or defaulted here, because that
decision has not been made (see docs/decisions/ADR-008 and ADR-009). Before either flag is turned
on, make evaluate must meet the thresholds in docs/evals/README.md against the real model and the
result must be recorded in docs/status.md. See docs/operations.md for the rollout sequence.

Deployment uses one locked image for migrations, web, and workers. PostgreSQL is internal; only
Caddy publishes ports. The web container sees blobs read-only while the worker owns read-write
access. See docs/operations.md for rollout, backup, restore, and release gates.

## Architecture

- FastAPI and Jinja templates for the public read-only site
- SQLAlchemy and Alembic over PostgreSQL
- simple-dictionary full-text search split into metadata and per-page document units
- strict-TLS HTTPX fetching with allowlisted redirects, byte caps, retries, and budgets
- content-addressed storage shared by immutable page snapshots and document versions
- additive parser/extractor backfills from stored bytes without re-crawling
- optional, flag-gated semantic search and cited answers over pgvector, off by default

No GitHub workflow is included by design.
