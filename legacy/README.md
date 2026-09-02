# The Postgres-backed stack, frozen

This directory holds the system BillWatcherNext used to be: a FastAPI application over PostgreSQL
and pgvector, with a queue-driven scraper, an object store, lexical and semantic search, a RAG
answer path, and an audit tree projecting the database onto disk.

It is **frozen, not maintained**. Nothing here is imported by `src/`, installed by `make setup`,
or covered by `make check` — `pyproject.toml` excludes it from ruff, mypy and pytest, and the
dependencies it needs (SQLAlchemy, Alembic, FastAPI, uvicorn, psycopg, pgvector, boto3, Jinja2)
are no longer in the project's dependency set. Its imports of `billwatcher.*` refer to modules that
have since moved, so it will not run as it stands.

It was last known working at commit `b0bfb77`. To revive any of it, that commit — not this
directory — is the reliable starting point; what is here is a readable record of the design, kept
in the tree so the decisions behind it stay visible.

## What is in it

| Path | What it was |
| --- | --- |
| `billwatcher/web/` | The FastAPI application, Jinja templates, Datastar progressive enhancement, and the served corpus routes. |
| `billwatcher/search/` | Lexical search over a weighted tsvector, pgvector semantic search, hybrid ranking, the RAG answer path and its evaluation harness. |
| `billwatcher/scraper/` | The queue-driven crawler: orchestrator, ingest, versioning, presence tracking, the document worker. |
| `billwatcher/jobs/` | Backfill and maintenance jobs — reparse, re-extract, rechunk, reembed, retention, audit rebuild. |
| `billwatcher/storage/` | The blob store (filesystem and S3) and the audit tree. |
| `billwatcher/mineru/` | The hosted vision-language PDF reader, and the jobs that drove it. |
| `billwatcher/legislation/` | The Postgres-side structural parse and its Gate L1 persistence. |
| `migrations/` | Alembic revisions for the schema all of the above shared. |
| `compose.yaml`, `Dockerfile` | The production-shaped stack: app, worker, database, S3 gateway. |
| `tests/` | Its suite — 53 files, most of which need a live PostgreSQL. |

## Why it is not in the pipeline any more

The file-first pipeline and this stack were two implementations of overlapping work, and the
pipeline was the one being used. Keeping both meant every change had to be reasoned about twice,
against a database that no step in the live path touched.

Three things did move across rather than being abandoned, because the pipeline genuinely needs
them:

- `storage/audit_tree.py`'s atomic write and deterministic sidecar serialisation became
  `src/billwatcher/files.py`. Resumability and write-if-changed both rest on them.
- `scraper/`'s pure parts — fetching, crawl policy, robots, normalisation, the listing and archive
  parsers — became `src/billwatcher/download/`. None of them ever touched a database.
- `legislation/layout.py` and `legislation/vocabulary.py` became `src/billwatcher/markdown/` and
  `src/billwatcher/graph/` respectively.

## Two capabilities were dropped rather than moved

Both needed a remote model endpoint, against the decision to keep the pipeline on local files:

- **The MinerU cross-check** — a second, independently versioned reading of every stored PDF by a
  hosted vision-language model, reported as divergence from the local reading. It is the one check
  that can judge a reading against the *page* rather than against itself, which the fidelity gate
  cannot do. `billwatcher/mineru/` is here; the pipeline step that drove it
  (`pipeline/crosscheck.py`) is in git history at `b0bfb77`.
- **LLM-assisted structure extraction** — `pipeline/akn_llm.py`, also at `b0bfb77`. Its system
  prompt and its JSON-to-`Node` parsing were not lost: they moved into
  `src/billwatcher/graph/handoff.py`, which is the model-free route that reads the same contract.
