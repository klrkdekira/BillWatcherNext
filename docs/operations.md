# Operations

## Getting a local instance running

```bash
make quickstart
```

That is `setup` → `env` → `db-up` → `migrate` → `seed` → `serve`, and it needs no network access
to Parliament. `make env` writes `.env` from `.env.development` only if `.env` is absent, so it
never overwrites a configured environment. `make db-up` starts `compose.dev.yaml`, which is a
development-only PostgreSQL published on `127.0.0.1:55432` and is not the production stack; it
also creates the `billwatcher_test` database that `make test-pg` uses.

`make seed` runs `billwatcher load-fixtures`: the committed listing fixtures are ingested as a
`fixture`-mode scrape run with real snapshot, blob, and coverage provenance, so browse, search,
bill detail, chamber timelines, `/changes`, and `/status` all have truthful content. It is
idempotent — a second load inserts nothing and records no changes — and it refuses to run against
`ENVIRONMENT=production` without `--confirm-production`.

`CONFIRM_RESET=yes make db-reset` deletes the development database and its volume.

Every operator action is a Make target. `make help` lists them. No default target crawls the live
Parliament site or deletes data, and every mutating backfill is a dry run unless `ARGS=--apply`
is passed.

## Daily and release gates

| Command | What it proves |
| --- | --- |
| `make check` | lint, strict type check, and the whole offline suite |
| `make doctor` | non-zero while any unresolved critical anomaly exists, a current document version is not accepted, or a recorded blob is missing or corrupt |
| `make status` | per-target freshness, queue depth, latest run, pipeline versions |
| `make verify-storage` | every database blob reference exists on disk, and no orphan bytes exist |

`make doctor` is the release and daily-operations gate that stands in for CI. There is no GitHub
workflow in this repository by design.

## PostgreSQL-only tests

The offline suite runs on SQLite. Behaviour that only exists on PostgreSQL — the weighted
`tsvector`, `websearch_to_tsquery` ranking, `ts_headline` snippets, and pgvector cosine retrieval
— runs only when a disposable database is supplied:

```
BILLWATCHER_TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/billwatcher_test \
  uv run pytest tests/integration/test_postgres_search.py tests/integration/test_postgres_semantic.py
```

The fixture drops and recreates the `public` schema and migrates to head, so never point it at a
database you care about. Without the variable the tests skip with a message.

## Migrations

`make migrate` upgrades to head. A fresh, empty database reaching head is proven automatically by
the PostgreSQL fixture above, which drops and recreates the schema before every session.

Downgrade policy: downgrades are for disposable development databases only. Migration 0001's
downgrade drops every table, and no downgrade path is supported against a database holding real
archive data — recovering from a bad migration in production means restoring the database and the
blob store together, not stepping backwards.

## Crawling

Live crawling is off by default and gated behind `SCRAPE_ENABLED` plus an explicit
`--approve-live` flag. Before the first crawl, complete the discovery gates in `docs/upstream.md`:
robots.txt and its hash, the archive request contract, the bilingual label and status sweep, TLS
verification from the deployment host, and the configured contact identity.

- `make scrape` — one approved incremental run
- `make scrape-full` — one approved full archive run, with its own larger budget
- `make reparse` — replay stored snapshots offline at the current parser version; dry run by
  default. At an unchanged parser version this must report zero changes.
- `make reextract` — additive re-extraction of current document versions

## Retention

`make retention` is a dry run. `make retention ARGS=--apply` aggregates expiring `fetch_attempts`
into `daily_fetch_metrics` and deletes them, prunes extractions to the current extractor version
plus the previous one, and releases blob references held by old failed page snapshots. It never
deletes bytes and never touches document versions, record changes, bill events, or presence
observations (ADR-010).

`make prune-blobs` deletes only blobs with no references and orphan files with no database row.
It is a dry run unless `ARGS=--apply`.

## Backups and restore

- `make backup BACKUP_DIR=/srv/backups` — timestamped PostgreSQL custom-format dump
- `make backup-blobs BLOB_BACKUP_DEST=/srv/backups/blobs` — incremental blob-store copy
- `make restore RESTORE_PATH=… CONFIRM_RESTORE=yes`
- `make restore-blobs BLOB_RESTORE_PATH=… CONFIRM_RESTORE=yes`

A database restore without the blob store loses the archive and every future re-extraction. Drill
both together, and record each drill in the manual gate log in `docs/status.md`.

## Release 3 rollout

Semantic search and RAG are off by default and the site is complete without them. Turning either
on is a sequence of recorded decisions, not a configuration flip:

1. Choose an embedding model whose dimension is 1024 and record the decision, licence, cost, and
   multilingual evidence against ADR-008. A different width needs its own migration.
2. Set `EMBEDDING_PROVIDER` and `EMBEDDING_MODEL_ID`, then run `make rechunk ARGS=--apply` and
   `make reembed ARGS=--apply`. Both are dry runs otherwise, and both record a `backfill_jobs`
   row.
3. Run `make evaluate` against the real model. It must meet the thresholds in
   `docs/evals/README.md`. Record the run, the date, and the model ID in the manual gate log.
4. Once representative vectors exist, build the index: `make semantic-index ARGS=--apply`. It
   refuses to build before any vectors exist.
5. Set `SEMANTIC_SEARCH_ENABLED=true`. `/semantic-search` appears; `/search` is unchanged.
6. For answers, record the provider decision against ADR-009, install the optional `rag`
   dependency group, set `RAG_PROVIDER`, `RAG_MODEL_ID`, and credentials, and set
   `RAG_ENABLED=true`.

Switching models later: `make reembed ARGS=--apply` backfills the new model alongside the old
one, and `uv run billwatcher drop-embedding-model <old-id> --apply` removes the superseded vectors
only after the replacement is validated.

`RAG_ENABLED=false` and `SEMANTIC_SEARCH_ENABLED=false` are kill switches. With them off,
`/semantic-search`, `/ask`, and `/api/v1/ask` return 404 and everything else is unaffected.

## Deployment

One locked image runs migrations, the web service, and the worker. PostgreSQL is internal and is
never published to the host. Only Caddy publishes ports 80 and 443. The web container mounts the
blob volume read-only; the worker owns read-write access. Containers run as UID 10001.

`make docker-build`, `make compose-up`, `make compose-down`, `make logs`.

Do not call the service publicly accessible until an external client on another network loads it
over valid HTTPS. A localhost container check is not evidence.
