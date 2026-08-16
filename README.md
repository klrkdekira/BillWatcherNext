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
saved fixtures and SQLite and never contact Parliament. Live tests require
BILLWATCHER_LIVE_TEST=1 make test-live. A live crawl requires the explicit make scrape target.

Before crawling, complete the discovery gates in docs/upstream.md: review robots.txt, archive
request behavior, bilingual labels/statuses, TLS, and the configured contact identity. Live
crawling is disabled by default.

## Operations

make help lists the stable interface. Important targets include make check, make docker-build,
make compose-up, make status, make doctor, make verify-storage, dry-run-first backfills, and guarded
database/blob backup and restore targets.

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

No GitHub workflow is included by design.
