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
| `/status` | Per-target freshness — current listings, archive indexes, and one row per archived year — queue depth, open anomalies, pipeline versions |
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

What is left to do, and who can do it, is in [`TODO.md`](TODO.md); the dated evidence behind it is
in [`docs/status.md`](docs/status.md).

`make help` lists everything. The targets that matter:

| Target | What it does |
| --- | --- |
| `check` | Lint, type check, and test — the gate before any change lands |
| `doctor` | Exits non-zero while a critical anomaly is unresolved, a current document version is unaccepted, or a stored blob is missing |
| `status` | Per-target freshness, queue depth, latest run, pipeline versions |
| `seed` | Offline fixture ingestion |
| `scrape` | An approved live crawl of the current listings; requires an explicit opt-in |
| `scrape-archive` / `scrape-full` | The archive, or the archive plus the current listings, with the archive's own larger budget |
| `anomalies` / `resolve-anomaly` / `acknowledge-anomaly` | The `doctor` work list, and the two ways to close an item with a name and a reason attached |
| `fixtures-refresh` | Regenerate the committed fixtures from stored snapshots, offline |
| `reparse` / `reextract` | Replay stored bytes at a newer parser or extractor; dry run by default |
| `restructure` | Read structure from stored bytes and record each document's Gate L1 verdict |
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

**The archive ingests too, and it is much larger.** `?arkib=yes` shows a search form, but the
archived listing is not in that page: it is a `dhtmlXTree` whose XML the page loads separately —
one document per archived year, 1990 to 2024, 67 of them across the two chambers (ADR-014). A
`make scrape-archive` run reads all of them and publishes **1,269 bills spanning 1990 to 2026**,
2,256 chamber records, and 4,861 events, with one coverage target per year so a single unreadable
year is visible on `/status` instead of hiding in an average.

`carian.html`, incidentally, is a full-text search over the *text inside* bill PDFs — page-level
hits with fragment links. It carries no bill code, status, or date, so it is not crawled. Reading
the form and assuming it was the archive is the mistake ADR-011 made and ADR-014 corrects.

A crawl also queues every document it finds, and the queue has been drained: **1,295 documents,
1,264 stored and validated, 27,575 pages, 0.24 GB** — one request every two seconds, each PDF
hashed, magic-byte validated, stored, and text-extracted.

That is where the archive stops being tidy, and the numbers are the point:

- **31 links are dead**, and Parliament answers them with `HTTP 200`, `text/html`, and a 23-byte
  `File does not exist (1)`. Validating content rather than trusting a status code is the only
  reason none of them was stored as a bill document.
- **22 documents have no extractable text** — scans, concentrated in 2010, 2013 and 2018. Age is
  not the predictor: a bill from 1995 extracts cleanly. Those 22 are findable by their listing
  metadata but not by their contents until the optional OCR worker is built.
- **62 documents are published at more than one URL**, usually one copy per chamber. Identity is the
  content hash, so all 62 collapse to one stored blob linked from every bill that points at it. URL
  identity would have counted the archive twice.
- **No document has a second version yet**, so the versioning machinery is exercised only by
  fixtures. That is the archive being young, not the code being untested.

The remaining discovery gate in `docs/upstream.md` is whether a revised document keeps its URL
(A11), which needs the same document observed twice over time. A real contact address is still
needed before a public deployment.

---

## Architecture

```
  your nginx  ──►  FastAPI + Jinja  ──►  PostgreSQL + pgvector
 (TLS, not in                ▲                    ▲
  this repo)                 │                    │
                    scheduled worker  ──►  Parliament pages and PDFs
                             │
                             ▼
             content-addressed blob store (private volume)
                             │
                             ▼
        replay / re-extract / re-chunk / re-embed, all offline
```

TLS is terminated by an nginx deployed separately (ADR-015). This stack publishes exactly one
thing — the app on `127.0.0.1:8000` — for that proxy to sit in front of; PostgreSQL and the blob
gateway are on an internal network and are never reachable from the host. The app sets its own
security headers, so the proxy must not set copies of them, and it needs `proxy_buffering off` for
the status page's event stream. `docs/operations.md` has the configuration.

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

### Serving the legislation corpus

A second pipeline reads each bill's structure and publishes it as Akoma Ntoso XML, ELI JSON-LD and
RDF N-Quads on permanent, truncatable identifiers — a Work, one Expression per language, one
Manifestation per format, and a dereferenceable IRI for every provision:

```text
/akn/my/bill/dr/2026/15                        the bill, in any language
/akn/my/bill/dr/2026/15/msa@                   the Malay reading;  …/eng@ is the English one
/akn/my/bill/dr/2026/15/msa@.xml               .jsonld and .nq are the other formats
/akn/my/bill/dr/2026/15/msa@/~cl_5__subsec_1   one provision of it
```

**It is off by default and every one of those paths returns 404** (`SERVE_LEGISLATION_CORPUS`), and
even when it is on, **what is published is structure only**: the FRBR identifiers, the provision
numbering, the headings, and the graph of what contains what. Every provision's body text is removed
at the serving boundary — the store holds it, the response does not — because republishing the
drafter's words is the same rights question that keeps stored PDFs private (`ADR-004`, assumption
A14). Publishing text is a separate flag with a separate confirmation, deliberately: gating the
lower-risk artifact while leaving the higher-risk one open would be backwards (`ADR-018`, `ADR-027`).

Provision **headings** are published in structure-only mode. That is a recorded judgement, not an
oversight: a heading is the same kind of short fragment as a bill's title, which this site already
publishes everywhere. One constant (`redact.KEEP_HEADINGS`) reverses it if a rights review says so.

"Short" is enforced rather than assumed, and it took a review to notice that it wasn't. Amendment
bills often print no heading at all and run the whole provision in after its number, so without a
bound the "heading" was the provision — published in full, in every format, at default settings.
Two independent layers now apply the same test, one where the tree is parsed and one where the
response is built, and a provision printed without its own heading is shown without one rather than
with the first eighty characters of its text.

Turning it on, in order:

1. Build the corpus: `make pipeline-fetch-listings`, `pipeline-parse-listings`,
   `pipeline-fetch-documents`, then `billwatcher pipeline import-markdown` per document,
   `make pipeline-convert-to-akn` and `make pipeline-generate-semantic`.
2. Check it: `billwatcher pipeline verify` — every artifact re-hashed against the record of what it
   was built from, with nothing unexplained in the store.
3. Record the rights decision in the `docs/status.md` gate log, then set
   `SERVE_LEGISLATION_CORPUS=true` **and** `LEGISLATION_CORPUS_RIGHTS_CONFIRMED=true`. Production
   refuses to start with the first without the second.
4. Only for full text, and only after the A14 review: `LEGISLATION_PUBLICATION_MODE=full`, which
   additionally requires `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true`.

Nothing has been built from real data yet. No listing or document has been fetched into the
pipeline's store, so the corpus is proven against constructed fixtures and one end-to-end run, and
the fidelity gate's pass rate over Parliament's real typesetting is unmeasured.

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

Neither can start without an explicitly configured model. **No embedding or answer model is
chosen or defaulted here.** ADR-009 selects a self-hosted vLLM OpenAI-compatible endpoint for
answers; ADR-008 leaves the embedding model decision open. The `deterministic` and `echo`
providers exist for development and are rejected in production configuration.

Before either flag goes on, `make evaluate` must meet the thresholds in `docs/evals/README.md`
against the real model, and the result must be recorded in `docs/status.md`.
`docs/operations.md` has the rollout sequence.

---

## Reading the documents themselves

Everything above indexes what Parliament *published about* a bill. A separate pipeline reads what
those documents *say*: a layout-aware structural reading of each stored PDF, validated against the
Arrangement of Sections the document carries on its own contents page.

That check — Gate L1 — is the point. Malaysian legislative typography puts structure in position:
section numbers hang at the left margin and **a marginal note sits in the right margin on the same
baseline as the provision it annotates**, so a reader that joins a baseline into one line splices
an annotation into the middle of the legal text and produces something that still looks
well-formed. Reading geometry rather than characters is what avoids that, and comparing the parsed
body against the drafter's own table of contents is what proves it worked. A dropped page, a failed
extraction, or a mis-detected hierarchy shows up as a difference between two independent readings
of one document.

```bash
make restructure            # dry run over stored bytes; ARGS=--apply to write
```

A reading that fails the gate is **stored and never promoted** — it is a review item, not a
discard — and a newer parser that fails cannot withdraw a reading that passed. Scans are recorded
as `no_text` rather than quietly filed as "no contents page", because the 22 documents with no
extractable text are the ones most likely to be wrong.

**This is Stage 1 of a larger specification.** HANDOFF §26 specifies the rest — Akoma Ntoso 3.0,
amendment extraction, point-in-time consolidation, and an ELI linked-data graph. The Akoma Ntoso and
ELI half of it now exists for **bills**, in a second, file-only pipeline that keeps its whole record
in a directory tree rather than the database (HANDOFF §28) and whose output is what "Serving the
legislation corpus" above describes. Amendment extraction and consolidation remain unstarted, and
§26.7 records why: Acts and the AGC reprints that would validate a consolidation live on a host this
project has never contacted, and publishing consolidated law asserts what the law *is*, which needs
legal sign-off rather than only a rights answer. Nothing consolidated is served, and the gate for it
is deliberately higher than the one for mirroring bytes.

```bash
make pipeline-convert-to-akn      # markdown -> Akoma Ntoso, behind a fidelity gate
make pipeline-generate-semantic   # Akoma Ntoso -> ELI JSON-LD + RDF N-Quads, offline
```

Structure here is read with a language model, because an Arrangement of Clauses entry is textually
identical to the provision it lists and markdown carries no page geometry to separate them. That is
also why nothing it produces is published unchecked: a deterministic gate asks whether the tree
accounts for the words that were on the page — every provision numbered, numbered once, in sequence
— and a reading that cannot is kept for review rather than promoted or discarded.

## Project state

`HANDOFF.md` is the normative specification; every "must" in it is a release gate.
`docs/status.md` is the live ledger of what is done, what is blocked, and what evidence exists.

Releases 1 and 2 are implemented and covered by automated tests. Release 3 is implemented and
feature-flagged off pending model decisions. Release 4 (§26) is implemented as far as Stage L1 and
is proven against constructed fixtures only — the corpus-wide pass rate is not yet measured. The
file-first pipeline (§28) is implemented end to end and has never been run against real data: its
store is empty, so its gate's pass rate is unmeasured too, and its publication surface is off.
Still open, and not resolvable in code: approval for a live crawl, external HTTPS verification from
another network, the document and corpus republication rights reviews, and the dependency and
container vulnerability reviews.

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
