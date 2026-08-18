# BillWatcherNext

A provenance-first, read-only index of Malaysian Parliament bills.

It preserves timestamped snapshots of every page it reads and every document it downloads,
records each new content state instead of overwriting the last one, and serves the result as a
fast, server-rendered site that works without JavaScript.

**Parliament of Malaysia is the authority.** A normalized status here is this index's
classification, not a legal conclusion, and a bill passed by a chamber is not law.

---

## Quickstart

Requirements: Python 3.12.5+, [uv](https://docs.astral.sh/uv/), Docker, and GNU Make.

```bash
make quickstart
```

That runs, in order: `setup` (locked dependencies) → `env` (writes `.env` from
`.env.development`) → `db-up` (PostgreSQL 16 with pgvector on `127.0.0.1:55432`) → `migrate` →
`seed` (loads the committed fixtures) → `serve`.

Open <http://127.0.0.1:8000>. Stop the server with Ctrl-C and the database with `make db-down`.

Nothing in that path touches the internet. `seed` ingests fixtures committed to this repository
as a `fixture`-mode scrape run, with real snapshot and blob provenance, so every page has
something truthful to show.

### What you should see

| Page | Seeded content |
| --- | --- |
| `/` | Three bills and a freshness line reporting the **oldest** healthy coverage target |
| `/bills` | Browsable index with chamber, status, year, and title-language filters |
| `/search?q=Perlindungan` | A ranked hit with a highlighted passage; `?q=D.R.15/2026` matches the code exactly |
| `/bills/dr-15-2026` | One bill with two chamber timelines, reading dates, provenance, and document versions |
| `/changes` | Recent changes, labelled Parliament's versus this index's own corrections |
| `/status` | Five coverage targets, queue depth, open anomalies, pipeline versions |
| `/api/v1/bills` | The read-only JSON API |

`D.R.15/2026` appears in both chambers deliberately: it is one bill with two independent
timelines, which is the case a single flat table would get wrong.

### Running it again

```bash
make seed     # idempotent: a second load inserts nothing and records no changes
make db-down  # stop the database, keep the data
CONFIRM_RESET=yes make db-reset   # delete the dev database and its volume
```

---

## Tests

```bash
make check     # lint, strict mypy, and the offline suite (SQLite, no network)
make test-pg   # the above plus the PostgreSQL-only tests, against the dev database
```

The offline suite runs entirely on SQLite. Behaviour that only exists on PostgreSQL — the
weighted `tsvector`, `ts_rank_cd` ranking, `ts_headline` snippets, and pgvector cosine retrieval
— runs only when `BILLWATCHER_TEST_DATABASE_URL` points at a disposable database, and skips with
a clear message otherwise. `make test-pg` sets it to the `billwatcher_test` database that
`make db-up` creates. That fixture drops and recreates the `public` schema, so never aim it at a
database you care about.

`make test-live` performs a tiny opt-in check against the real Parliament site. It requires
`BILLWATCHER_LIVE_TEST=1`, obeys the crawl delay, fetches at most two documents, and skips
cleanly when robots policy, TLS, or upstream availability prevents it. It never runs as part of
`make test`.

---

## Operator interface

`make help` lists everything. The targets that matter:

| Target | What it does |
| --- | --- |
| `check` | Lint, type check, and test — the gate before any change lands |
| `doctor` | Exits non-zero while a critical anomaly is unresolved, a current document version is unaccepted, or a stored blob is missing |
| `status` | Per-target freshness, queue depth, latest run, pipeline versions |
| `seed` | Offline fixture ingestion |
| `scrape` / `scrape-full` | An approved live crawl; both require an explicit opt-in |
| `reparse` / `reextract` | Replay stored bytes at a newer parser or extractor; dry run by default |
| `retention` | Roll transport logs into daily counters and prune old extractions; never deletes archive data |
| `verify-storage` / `prune-blobs` | Check every blob reference; delete only unreferenced bytes |
| `backup` / `backup-blobs` / `restore` / `restore-blobs` | Guarded database and blob-store operations |
| `docker-build` / `compose-up` / `compose-down` / `logs` | The production-shaped stack |

Every mutating backfill is a dry run unless you pass `ARGS=--apply`. No default target crawls
Parliament or deletes data. There is no GitHub Actions workflow, by design: `make doctor` and the
manual gate log in `docs/status.md` take its place.

---

## Crawling

Live crawling is off by default and needs two separate opt-ins: `SCRAPE_ENABLED=true` and the
explicit `--approve-live` flag that `make scrape` passes.

The crawler defaults to one request at a time with a two-second delay, refuses to be less
polite, verifies TLS strictly, allowlists only Parliament hosts, and revalidates every redirect.

Two upstream conditions must be settled before a crawl runs, both recorded in
`docs/upstream.md`:

1. **The site serves an incomplete TLS certificate chain.** It sends its leaf certificate without
   the intermediate that signs it, so verification fails. Browsers hide this by fetching the
   intermediate themselves; Python does not. Supply the intermediate in a bundle and set
   `UPSTREAM_CA_BUNDLE`. There is no setting that disables verification, and adding one is
   forbidden by the specification.
2. **The site publishes no `robots.txt`** — it returns 404. RFC 9309 would read that as
   unrestricted, but this project requires the decision to be reviewed and recorded first. Once
   you have checked the site's terms and logged the outcome in `docs/status.md`, set
   `ROBOTS_MISSING_POLICY=allow`; every run then records an anomaly noting it crawled without a
   published policy, so the decision stays visible.

A failed run explains itself and prints a command for the full record:

```
$ make scrape
FAIL: robots.txt returned 404; no crawl policy is published. ...
Inspect the run with: uv run billwatcher run-report <run-id>
```

### What a crawl currently collects

The two current listings ingest fully: 126 bills across both chambers, with reading dates,
presenters, and document links read out of the hidden per-bill detail table each row carries.

**The archive does not.** `?arkib=yes` returns a search form, not archived rows — it is a
`GET /carian.html` endpoint whose response shape has not been observed yet (ADR-011). Both archive
coverage targets therefore report `failing` on `/status`, each raises a warning, and a run ends
`partial` while the current listings publish normally. Release 1's archived-listings criterion is
not met until that endpoint is implemented.

The remaining discovery gates in `docs/upstream.md` are the `carian.html` contract, the Dewan
Negara detail labels, the English listing structure, and a real contact address.

---

## Architecture

```
Caddy (TLS)  →  FastAPI + Jinja  →  PostgreSQL + pgvector
                      ↑                    ↑
              scheduled worker  →  Parliament pages and PDFs
                      ↓
        content-addressed blob store (private volume)
                      ↓
        replay / re-extract / re-chunk / re-embed, all offline
```

The blob store is not a cache. It is the archival record that makes replay, versioning, and
post-hoc parser fixes possible, and it is backed up alongside the database.

Design rules the code holds to:

- **Upstream state is mutable; our record is append-only.** Re-downloading changed bytes creates
  a new document version and preserves the old one, its extracted text, and its metadata.
- **Absence is an observation, not a deletion.** A bill missing from one crawl is recorded as
  absent, never removed.
- **Every derived row names the code that produced it**, so a parser or extractor fix can rebuild
  exactly the affected rows from stored bytes without re-crawling.
- **Anomalies are rows, not log lines.** They deduplicate by kind and entity, surface on
  `/status`, and make `make doctor` fail until resolved.

---

## The archive

Every page snapshot and every document byte is stored content-addressed by SHA-256. That store
is not a cache: it is what makes versioning, replay, and re-extraction possible, and it is backed
up alongside the database.

Two backends implement one contract. `filesystem` (the default) writes files directly.
`s3` talks to any S3-compatible service; the deployment runs
[VersityGW](https://github.com/versity/versitygw) with its POSIX backend pointed at the same
volume, so the bytes stay on an ordinary filesystem in the same layout while standard S3 tooling
and off-host backup get a supported interface. The gateway is internal to the Compose network and
is never published. Switching backends migrates nothing.

### Serving archived documents

The site can serve its stored copy of a bill PDF at
`/documents/{document_id}/versions/{version_no}`, always beside a link to Parliament's official
URL. **It is off by default and returns 404**, because publishing mirrored bytes is gated on the
rights review in assumption A14 (see `docs/decisions/ADR-004` and `ADR-013`). The official link
never depends on it.

When enabled, only validated versions are served — a quarantined one is kept for the record and
withheld — and each response carries the content hash as an `ETag`, an immutable `Cache-Control`,
a canonical `Link` to the official URL, and `X-Robots-Tag: noindex`, because our copy is a
preservation artifact rather than the authoritative record.

## Frontend

Server-rendered HTML with a small amount of progressive enhancement. **Every page is complete
and usable with JavaScript disabled** — that is a tested property, not an aspiration: the suite
asserts the content is server-rendered, the filter form is a plain `GET`, and no script appears
outside `<head>`.

[Datastar](https://data-star.dev) v1.0.2 adds exactly two things, both additive:

- **Search as you type** on `/bills`, debounced, patching only the results region.
- **A live `/status`** that subscribes to a bounded server-sent event stream, so an operator
  watching a crawl sees it change.

Each fragment endpoint renders the same Jinja partial the full page includes, so the enhanced
and unenhanced views cannot drift. Anything HTML can already do — disclosure, navigation, form
submission — uses HTML, not script.

Datastar is **vendored** into `static/vendor/` with its version and SHA-256 recorded beside it;
nothing is fetched from a CDN and the site makes no third-party requests. It does require
`script-src 'unsafe-eval'`, because it compiles `data-*` expressions with the `Function`
constructor. That trade-off, and why the CSP-safe fork was rejected, is recorded in
`docs/decisions/ADR-012`. `unsafe-inline` is **not** granted.

The stylesheet has no web fonts, supports light and dark via `prefers-color-scheme`, honours
`prefers-reduced-motion`, and never signals state by colour alone — every badge carries a text
label and a shape cue.

## Optional Release 3 features

Semantic search and generated answers sit behind `SEMANTIC_SEARCH_ENABLED` and `RAG_ENABLED`,
both off. With them off, `/semantic-search`, `/ask`, and `/api/v1/ask` return 404 and nothing
else changes.

Neither can start without an explicitly configured model. **No embedding model or answer provider
is chosen or defaulted here**, because that decision has not been made — see
`docs/decisions/ADR-008` and `ADR-009`. The `deterministic` and `echo` providers exist for
development and are rejected in production configuration.

Before either flag goes on, `make evaluate` must meet the thresholds in `docs/evals/README.md`
against the real model, and the result must be recorded in `docs/status.md`.
`docs/operations.md` has the rollout sequence.

---

## Project state

`HANDOFF.md` is the normative specification; every "must" in it is a release gate.
`docs/status.md` is the live ledger of what is done, what is blocked, and what evidence exists.

Releases 1 and 2 are implemented and covered by automated tests. Release 3 is implemented and
feature-flagged off pending model decisions. Still open, and not resolvable in code: approval for
a live crawl, external HTTPS verification from another network, the document republication rights
review, and the dependency and container vulnerability reviews.

## Documentation

| File | Contents |
| --- | --- |
| `HANDOFF.md` | The specification and its acceptance criteria |
| `docs/status.md` | Package ledger, assumption register, decision index, manual gate log |
| `docs/operations.md` | Running, migrating, retention, backup and restore, rollout |
| `docs/data-model.md` | Conventions the schema alone does not show |
| `docs/upstream.md` | What has and has not been confirmed about the source site |
| `docs/decisions/` | Architecture decision records |
| `docs/evals/` | The versioned retrieval and answer evaluation set |
