# BillWatcherNext implementation handoff

Document version: 1.3 — 2026-08-18 (Asia/Kuala_Lumpur). See §25 for the changelog and §0 for how to amend this document.  
Status: implementation-ready specification  
Repository state at handoff: no application code and no commits; `HANDOFF.md`, `README.md`, `main.py`, `pyproject.toml`, and `.python-version` exist as an unbuilt `uv init` skeleton.

## 0. How to read and amend this document

This is the contract between the person who commissioned the work and the agents building it. It is normative: "must" means a release gate, "should" means deviation requires a recorded decision (§21), "may" means free choice.

Three separate things in this document are called *tracking*. Do not conflate them:

| Kind | Question it answers | Where specified |
| --- | --- | --- |
| Data change tracking | What did Parliament publish, when did we see it, and what changed since? | §10 |
| Runtime/operational tracking | Is the crawler healthy, fresh, and complete right now? | §10.4, §17 |
| Project tracking | Which work package is done, by whom, proven by what evidence? | §20 |

Amendment procedure:

1. A factual correction to upstream behaviour requires a dated entry in `docs/upstream.md` and an update to the affected assumption in §4.
2. A change to a contract (schema, route, policy, gate) requires an ADR under `docs/decisions/` and a changelog entry in §25, with the document version bumped.
3. Volatile state — who is working on what, which assumptions are verified, which ADRs are accepted — lives in `docs/status.md`, never in this file. This file holds the stable claim and the verification method; `docs/status.md` holds the current status. Never keep the same status in both places.

### What changed in 1.1

Version 1.0 was a sound specification with a mutable-data blind spot: it stored bills, documents, and extracted text as single-valued current state, so any upstream revision destroyed the record it was supposed to preserve. Version 1.1 adds versioned document downloading (§9), data change tracking (§10), and project tracking (§20), and corrects the defects listed in §25.2.

## 1. Mission

Build a public, read-only website that regularly collects Malaysian Parliament bill metadata and official bill documents from <https://www.parlimen.gov.my/>, preserves source provenance, and makes the collection easy to browse and search.

The first public release must be useful without AI: a fast, server-rendered bill index, filters, bill detail pages, exact/full-text search, source links, and freshness information. Semantic search, retrieval-augmented answers, and JSON-LD are planned extensions, with JSON-LD cheap enough to include in the first release if time permits.

Use Python and `uv`. Deployment artifacts must include a `Dockerfile`, `compose.yaml`, and `Makefile`. Do not add GitHub Actions or any other GitHub CI workflow.

### Product principles

1. Parliament is the authority. Never present generated text or our normalized fields as more authoritative than the linked source.
2. Provenance is part of every record, not an afterthought.
3. The ordinary searchable website is the main product. AI features must degrade cleanly and may never be required to browse bills.
4. Scraping must be polite, identifiable, auditable, and idempotent. Do not bypass access controls, TLS verification, or crawl restrictions.
5. The site must remain useful with JavaScript disabled.
6. **Upstream state is mutable; our record of it is append-only.** Every published fact traces to a stored, timestamped observation, every derived artifact records the code version that produced it, and no scrape ever destroys a prior observation.
7. **Absence is an observation, not a deletion.** Not finding something is data to record, never a reason to remove a record.

## 2. Scope and definition of done

### Release 1: public searchable index

Release 1 is done only when all of the following are true:

- Current and archived bill listings for both Dewan Rakyat (`dr`) and Dewan Negara (`dn`) are ingested from the official site.
- Re-running a scrape produces no duplicate bills, chamber records, documents, document versions, or events.
- A bill shared by both chambers remains one bill with two chamber-specific records.
- Every visible bill has its official source URL, `last checked` time, and enough raw provenance to diagnose a parser error.
- **Re-downloading a bill document whose bytes changed creates a new document version, preserves the previous version's bytes, extracted text, and metadata, and shows both on the bill page with their retrieval dates (§9).**
- **Re-downloading unchanged bytes creates no new version and advances only `last_checked_at` (§9.3).**
- **Every field change we record is attributable to a run, a snapshot, and a parser version, and is queryable as history (§10.1).**
- **A `/status` page reports per-target freshness and coverage, not a single global timestamp (§10.4).**
- **Stored snapshots can be re-parsed offline by a newer parser without re-crawling (§9.6).**
- The public site has browse, filter, bill-detail, and keyword-search pages. Search covers identifiers, Malay/English titles where available, sponsor/presenter, status, and extracted document text.
- Search and detail pages render on the server, have stable canonical URLs, usable pagination, accessible labels/focus states, and sensible empty/error states.
- The service exposes liveness and readiness endpoints and can be deployed behind HTTPS with Docker Compose.
- Unit, parser-fixture, database, search, and HTTP smoke tests pass through Make targets.
- Operations can run an initial full scrape, incremental scrapes, migrations, backfills, backup, restore, and logs through documented Make targets.
- `docs/status.md` reflects reality and every row of §22 has evidence.
- No `.github/workflows` directory is introduced.

### Release 2: structured discovery

- Each bill page emits valid Schema.org `Legislation` JSON-LD without claiming a bill passed when it did not.
- `sitemap.xml`, canonical tags, Open Graph metadata, and a crawler policy for this site are present.
- Optional bilingual titles are ingested when the English listing maps unambiguously to the Malay bill code.
- A public `/changes` feed lists recent bill and document-version changes (§14).

### Release 3: semantic retrieval and RAG

- Semantic search runs behind a feature flag and uses versioned embeddings stored in PostgreSQL with pgvector.
- Hybrid results combine lexical and vector retrieval; exact bill-code matches always win.
- The answer page cites the bill and document version/page or chunk supporting each material claim.
- When evidence is absent or retrieval confidence is insufficient, the answer says so and links to search results; it does not improvise.
- RAG can be disabled without affecting indexing, lexical search, bill pages, or deployments.

### Explicit non-goals for the first release

- Scraping unrelated parliamentary material such as Hansard, questions, member profiles, or committee records.
- User accounts, comments, alerts, payments, or write APIs.
- Reproducing Parliament's visual design.
- Treating a bill as enacted law or providing legal advice.
- A general-purpose crawler or crawling off the allowlisted Parliament hosts.
- Publicly serving mirrored PDF bytes before the rights review in §21 concludes. Storing them privately is in scope and required.
- Byte-level or clause-level diffing between document versions. Recording that versions differ is Release 1; explaining how they differ is Release 2 at the earliest.
- GitHub CI.

## 3. Glossary: identity, time, and version words

The v1.0 model used `first_seen_at`, `last_seen_at`, `last_checked_at`, `retrieved_at`, and `observed_at` without defining them, which makes "freshness" unimplementable. These definitions are normative and every column named below must behave exactly this way.

| Term | Definition | Advances when |
| --- | --- | --- |
| `first_seen_at` | First successful observation of this row's subject. | Insert only. Never updated. |
| `last_seen_at` | Most recent successful observation that the subject still exists upstream. | Every successful parse that includes the subject, even if nothing changed. |
| `last_checked_at` | Most recent completed check, including a `304 Not Modified` or a byte-identical `200`. | Every successful HTTP transaction, changed or not. Not advanced by a failed attempt. |
| `last_changed_at` | Most recent time a stored value actually differed from what we held. | Only on a real diff. Drives "what changed" views. |
| `retrieved_at` | When *these exact bytes* were downloaded. Immutable per version. | Insert of a `document_version` or `source_snapshot`. |
| `observed_at` | When a source observation (an event row parsed off a page) was captured. | Insert only. |
| `last_absent_at` / `absent_streak` | Most recent successful *full* run in which the subject was expected but not found, and how many consecutive such runs. | Absence evaluation at end of a full run (§10.3). |
| `tombstoned_at` | Human decision to stop publishing a record. Never set automatically. | Manual, with a recorded reason. |

| Term | Meaning |
| --- | --- |
| Run | One execution of the scraper (`incremental`, `full`, `replay`, or `fixture`), holding an advisory lock. |
| Fetch attempt | One HTTP transaction, successful or not. Append-only. |
| Blob | Immutable stored bytes addressed by SHA-256. Shared by snapshots and document versions. |
| Snapshot | An observation of an upstream *page*: request metadata plus a blob reference. |
| Document | A stable logical document identity (bill + kind + language + canonical URL). Has no bytes of its own. |
| Document version | A distinct byte-content state of a document, numbered monotonically. Bytes live in a blob. |
| Extraction | Text derived from one document version by one named extractor at one version. |
| Chunk set | Chunks derived from one extraction by one chunker version. |
| Embedding set | Vectors derived from one chunk set by one embedding model. |
| Current version | The version most recently retrieved from the canonical URL that passed validation. |
| Superseded version | Any version that is not current. Retained, queryable, never deleted by an automatic job. |

"Last checked" on the website means `last_checked_at`. "As of" for document content means the current version's `retrieved_at`. Never show one where the other is meant.

## 4. Assumption register

Version 1.0 presented indexed-search observations as evidence for the data model. They are plausible and probably right, but nothing here was confirmed against a saved fixture. Each assumption below has an ID; cite the ID in code comments, fixtures, and ADRs. Verification status lives in `docs/status.md`, not here.

| ID | Assumption | Confidence | Verify by | Blocks |
| --- | --- | --- | --- | --- |
| A1 | The four listing URLs in §5 are the correct current/archive entry points for both chambers. | Medium | Fetch and save fixtures; compare against on-page navigation. | Package C |
| A2 | Current listings expose `Kod`, `Tahun`, `Tajuk`, `Status` plus expanded detail rows (readings, presenter, passage, committee referral). **Refuted as stated on 2026-08-18**: the visible table has exactly those four columns; readings, presenter, and passage live in a hidden nested detail table (see §25.4). | Medium | Fixture of one current listing per chamber. | Package B schema |
| A3 | The archive listing requires a form/AJAX request rather than returning all rows in initial HTML. | Low | Inspect forms and network traffic; record the exact request contract. | Package C, ADR |
| A4 | `D.R.15/2026` appears in both chambers with distinct per-chamber reading dates, proving the bill/chamber split. | Medium | Fixture from both chambers showing the same code. | §8 model justification |
| A5 | A bill identifier prefix (`D.R.`) denotes the *originating* chamber, not the chamber whose row is being read. | Medium | Confirm a Dewan Negara-originating bill exists and observe its prefix. | Identifier ADR |
| A6 | Dates are rendered as `DD/MM/YYYY`. | Low | Fixtures across current and archive, both languages. | Date parser (§11.5) |
| A7 | Malay month names (`Januari`, `Februari`, `Mac`, `April`, `Mei`, `Jun`, `Julai`, `Ogos`, `September`, `Oktober`, `November`, `Disember`) and date ranges such as `13–14 Julai 2026` appear in at least some cells. | Medium | Fixtures. | Date parser (§11.5) |
| A8 | Listings are organized by parliamentary term (`Parlimen`), session (`Penggal`), and meeting (`Mesyuarat`), and the archive is navigated by these. | Medium | Archive discovery spike. | §8 `bills` fields, coverage targets |
| A9 | Status vocabulary includes explicit Malay phrases for the three readings, committee referral, passage, and withdrawal. | Medium | Collect the distinct status strings across a full archive crawl before finalizing the mapping. | §8 status enum |
| A10 | Bill documents are PDFs on an allowlisted Parliament host, some native-text and some scanned. | Medium | Download a sample; check text yield and magic bytes. | §9, OCR decision |
| A11 | A revised bill is republished at a *new* URL rather than replacing bytes at the same URL. | Low | Observe over time; check archive for `pindaan`/reprint naming. | §9.5 identity rules |
| A12 | Total corpus is on the order of low thousands of bills and low tens of gigabytes of PDFs. | Low | Measure after the first full crawl; record actuals in `docs/operations.md`. | Storage/backup sizing |
| A13 | `robots.txt` permits crawling these listing paths. **Refuted on 2026-08-18**: the site publishes no robots.txt (HTTP 404); crawl permission is now an explicit recorded decision, not a robot directive (see §25.4). | Unknown | Fetch and record it, with its SHA-256, before any crawl. | All crawling |
| A14 | Republication of PDF bytes is not clearly permitted. | Unknown | Rights review. | Public document serving |

Rules: an assumption may be *used* while unverified only if the code fails loudly when it is wrong (for example, a date parser that raises on an unrecognized format rather than silently producing `NULL`). An assumption marked "blocks" may not be assumed away — it gates the listed work.

## 5. Upstream reconnaissance

The following was observed on 2026-08-16 and must be re-verified with saved fixtures before implementation is considered stable. Treat every claim here as pointing at an assumption ID in §4.

### Known listing entry points

| Purpose | Canonical discovery URL |
| --- | --- |
| Dewan Rakyat current, Malay | `https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr` |
| Dewan Negara current, Malay | `https://www.parlimen.gov.my/bills-dewan-negara.html?lang=bm&uweb=dn` |
| Dewan Rakyat archive | `https://www.parlimen.gov.my/bills-dewan-rakyat.html?arkib=yes&lang=bm&uweb=dr` |
| Dewan Negara archive | `https://www.parlimen.gov.my/bills-dewan-negara.html?arkib=yes&lang=bm&uweb=dn` |
| English variants | use `lang=en` on the same two listing paths |

Indexed copies show the current pages exposing `Kod`, `Tahun`, `Tajuk`, and `Status`, plus expanded details such as first reading, second reading, presenter, passage date, and committee referral date (A2). The archive page may require form/AJAX discovery rather than yielding all records in its initial HTML (A3).

The site also exposes presentation variants with prefixes such as `/m/`, `/p/`, `/portal/`, `/actsearch/`, and `/index.php/`. Treat these as alternate views, not distinct sources. Normalize a bill using its identifier and chamber, not the presentation URL.

Important evidence for the data model: the live listings show `D.R.15/2026` in both chambers, with Dewan Rakyat readings on 13–14 July 2026 and Dewan Negara readings on 20–22 July 2026 (A4). A single flat `bill` row would overwrite valid chamber history. Note also that "13–14 July" is a *range inside one cell*: the date parser and event model must accept multiple dates per stage (§11.5).

### Mandatory discovery spike

Before building the production parser, the scraper agent must:

1. Fetch and save `robots.txt`, the four Malay entry points above, and at least one English page using strict TLS verification. Record the `robots.txt` SHA-256 (§11.2).
2. Record redirect chains, content types, response encodings, caching headers (`ETag`, `Last-Modified`, `Cache-Control`), cookies required, and whether archives issue XHR/fetch requests.
3. Inspect forms and browser network traffic to find the archive request contract. Prefer a documented/static endpoint; use browser automation only if a real browser is actually required. Record the decision as an ADR.
4. Locate bill-document links and determine whether they are HTML, native-text PDF, image PDF, or a mix. Record whether document URLs look stable and whether a revision appears at the same URL or a new one (A11) — this decides how much §9.5 identity work is needed.
5. Collect the *complete distinct set* of status strings and column labels seen, in both languages, into `docs/upstream.md`. Do not design the status mapping from a handful of rows (A9).
6. Record the parliamentary term/session/meeting navigation structure of the archive (A8).
7. Commit redacted, minimal HTML fixtures covering: current rows, archived rows, both chambers, a committee referral, a missing date, a date range in one cell, a non-`DD/MM/YYYY` date, an English title, a document link, and one deliberately malformed row.
8. Write `docs/upstream.md` with the observed selectors/request fields, the full label and status vocabulary, and the observation date.

During preparation of this handoff, search indexing could see the pages, while direct probes from the development container encountered an untrusted local CA chain and intermittent gateway responses. That is not permission to set `verify=False`. Fix the host/container trust store or document an upstream certificate incident; the production crawler must fail closed on TLS errors.

### Crawl policy

- Read and obey the current `robots.txt` before any live crawl. If it cannot be fetched, stop the scheduled crawl and retain the last good index.
- Use a descriptive user agent such as `BillWatcherNext/0.1 (+https://PUBLIC_HOST/about; contact: CONTACT_EMAIL)`.
- Default to one concurrent request and at least two seconds between requests per host. Make both settings configurable, but never increase them without an explicit upstream review.
- Use timeouts, bounded retries with exponential backoff and jitter, and `Retry-After` when present. Do not retry ordinary 4xx responses except 408/429.
- Trip a circuit breaker: after a configurable number of consecutive 5xx or transport failures on a host (default 5), abandon the run, mark it `failed`, and back off before the next scheduled run. Do not grind through a full crawl against a failing upstream.
- Enforce a per-run crawl budget (§11.7): maximum requests, bytes, wall-clock duration, and newly queued documents. Exceeding a budget ends the run as `partial` with the queue intact, never as a crash.
- Use `ETag` and `Last-Modified` conditional requests when available.
- Allowlist only `www.parlimen.gov.my`, `parlimen.gov.my`, and a separately reviewed official repository host. Do not follow arbitrary external links.
- Cap response bytes before buffering, validate content type and PDF signature, and never execute downloaded content.
- Preserve official links. Until republication rights are reviewed (A14), publish metadata and short search excerpts while linking to the official full document rather than serving a mirrored PDF publicly. Storing the bytes privately is required regardless — it is what makes versioning and re-extraction possible.
- Never delete a record because one crawl omitted it. Mark absence as an observation (§10.3) and require repeated successful full crawls plus manual review before tombstoning.
- Prefer scheduling that respects the sitting calendar if one can be obtained: bills change during sittings and rarely between them. This is an optimization, not a gate.

## 6. Proposed architecture

```text
Internet
   |
   v
Caddy (HTTPS, compression, security headers, rate limits where appropriate)
   |
   v
FastAPI + Jinja templates ---------------> PostgreSQL + pgvector
   ^                                           ^
   |                                           |
scheduled worker ---> Parliament pages/PDFs ---+
   |   |
   |   +--> content-addressed blob store (private volume)
   |            ^
   |            |
   +--> replay / backfill jobs (offline: reparse, re-extract, re-chunk, re-embed)
                |
optional embedding/RAG provider <--- feature-flagged worker/app adapter
```

The blob store is not a cache. It is the archival record that makes replay, versioning, and post-hoc parser fixes possible, and it is backed up (§16).

Use the same application image for the web, migration, and worker services, with different commands. Keep migrations a one-shot service rather than having every web replica race to migrate. The worker must also take a PostgreSQL advisory lock so only one scheduled scrape can run at a time. Backfill jobs take a *different* advisory lock so a long re-extraction does not block a scheduled scrape, but must not write to rows a scrape is mutating — partition by job kind (§9.6).

### Recommended stack

- Python 3.12 initially; declare the exact supported range in `pyproject.toml`. The skeleton currently pins `>=3.12.5` via `.python-version`; confirm or change deliberately.
- `uv` for dependency management, locking, local commands, and container builds.
- FastAPI/Starlette, Jinja2, and small progressive-enhancement JavaScript only where it materially improves usability.
- SQLAlchemy 2, Psycopg 3, Alembic, PostgreSQL, and pgvector.
- HTTPX plus a small explicit fetch policy; Selectolax or lxml for HTML parsing.
- pypdf for native PDF text. Put OCR behind an optional dependency group and separate job because it is expensive.
- Typer for operational CLI commands.
- Structlog or standard-library structured JSON logging.
- Pytest, Ruff, and mypy/pyright. Pick one type checker and make it a required Make target.
- Caddy for public TLS and reverse proxying.

Do not pin dependency versions by copying numbers from this document. Resolve them when scaffolding, commit `uv.lock`, and make production builds use the lock without mutation.

## 7. Repository contract

The scaffold agent should create this shape unless a short architecture decision record justifies a change. The existing `main.py` is scaffolding noise and should be replaced by the package entry points below.

```text
.
├── .dockerignore
├── .env.example
├── .gitignore
├── Caddyfile
├── Dockerfile
├── HANDOFF.md
├── Makefile
├── README.md
├── compose.yaml
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── migrations/
├── src/billwatcher/
│   ├── __init__.py
│   ├── version.py          # PARSER_VERSION, NORMALIZER_VERSION, EXTRACTOR_VERSION, CHUNKER_VERSION
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   ├── cli.py
│   ├── logging.py
│   ├── domain/
│   ├── storage/
│   │   └── blobs.py        # content-addressed put/get/verify; no business logic
│   ├── scraper/
│   │   ├── fetch.py
│   │   ├── policy.py
│   │   ├── queue.py        # fetch queue, leasing, retry/backoff, dead letter
│   │   ├── parse_listing.py
│   │   ├── parse_document.py
│   │   ├── normalize.py
│   │   ├── versioning.py   # document version promotion/supersession (§9)
│   │   ├── changes.py      # field diffing and record_changes writes (§10)
│   │   └── service.py
│   ├── jobs/
│   │   ├── replay.py       # re-parse stored snapshots
│   │   ├── reextract.py
│   │   ├── rechunk.py
│   │   └── reembed.py
│   ├── search/
│   │   ├── lexical.py
│   │   ├── indexer.py      # maintains search units (§12.1)
│   │   ├── semantic.py
│   │   └── rag.py
│   └── web/
│       ├── app.py
│       ├── routes.py
│       ├── schemas.py
│       ├── templates/
│       └── static/
├── tests/
│   ├── fixtures/parliament/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── docs/
│   ├── upstream.md
│   ├── operations.md
│   ├── data-model.md
│   ├── status.md           # project tracking ledger (§20)
│   ├── decisions/
│   └── evals/
└── var/                    # ignored local snapshots only
```

Application code may not import from `tests`. Parsing functions must accept bytes/text plus source metadata so fixture tests do not need network access. Version constants live in exactly one module (`version.py`) and are written into every derived row.

## 8. Domain and database model

Keep source strings as well as normalized values. Names, titles, and statuses can change spelling; source fidelity matters.

Each table below is tagged with the release that needs it. Do not build R3 tables during R1; do design R1 tables so the R3 ones attach without a destructive migration.

### `bills` — R1

- `id` UUID primary key.
- `identifier_raw` text, for example `D.R.15/2026`.
- `identifier_normalized` text, for example `DR-15-2026`, unique.
- `number` integer nullable and `year` smallint nullable; do not discard an unparseable record.
- `originating_chamber` nullable controlled value, derived from the identifier prefix (A5). Nullable when the prefix is unrecognized. This is *not* the same as the chambers in which the bill has records.
- `parliament_term` and `session` nullable text/smallint (A8), captured when the listing exposes them.
- `slug` text unique and stable, derived from the normalized identifier, not a mutable title.
- `title_bm`, `title_en` nullable text.
- `bill_kind` nullable text.
- `introduced_on` nullable date, derived only when the source semantics are clear.
- `identifier_scheme_version` smallint — which version of the identifier rules produced `identifier_normalized`.
- `created_at`, `updated_at`, `first_seen_at`, `last_seen_at`, `last_checked_at`, `last_changed_at`, `last_absent_at`, `absent_streak`, `tombstoned_at` (§3).

The unique key must not include chamber: the same bill progresses through both chambers.

### `bill_slug_aliases` — R1

- `slug` text primary key, `bill_id`, `created_at`, `reason`.

A slug must never change silently. If identifier rules are corrected and a slug changes, the old slug becomes an alias and `/bills/{old}` issues a permanent redirect. Without this, fixing a parser bug breaks every external link we have already published.

### `chamber_records` — R1

- `id` UUID primary key and `bill_id` foreign key.
- `chamber`: controlled value `dewan_rakyat` or `dewan_negara`.
- `status_raw` and `status_normalized`.
- `first_read_on`, `second_read_on`, `third_read_on`, `passed_on`, `referred_on` nullable dates.
- `presenter_raw` nullable text. If different stages have different presenters, use stage events rather than overwriting this shortcut.
- `source_url`, `source_snapshot_id`, `first_seen_at`, `last_seen_at`, `last_checked_at`, `last_changed_at`, `last_absent_at`, `absent_streak`.
- Unique on `(bill_id, chamber)`.

Normalized status is one of `introduced`, `tabled`, `first_read`, `second_read`, `committee`, `referred`, `third_read`, `passed`, `withdrawn`, `lapsed`, `defeated`, or `unknown`. Preserve the Malay/English source status and map only explicit phrases; never infer passage from the presence of a second-reading date and never infer a reading from an adjacent date column. An unmapped status stores `unknown`, retains `status_raw`, and raises an anomaly (§10.5) — it is never dropped and never guessed.

Do not finalize this enum before the vocabulary sweep in §5 step 5 (A9). Bills lapse on dissolution; if the source expresses that, `lapsed` must map to it rather than leaving stale `second_read`.

### `bill_events` — R1

- `id`, `bill_id`, `chamber`, `event_type`, `event_on` nullable, `event_on_end` nullable (for a range in one cell), `actor_raw` nullable, `sequence` smallint for multiple events of the same type.
- `source_label`, `source_value`, `source_url`, `snapshot_id`, `run_id`, `parser_version`, `observed_at`.
- `fingerprint` text unique.

`event_type` is one of `introduced`, `first_reading`, `second_reading`, `committee_referral`, `committee_report`, `third_reading`, `passed`, `withdrawn`, `lapsed`, `document_published`, `status_observed`, `other`.

The fingerprint recipe must be written down in `docs/data-model.md` and tested. Suggested: `sha256(bill_id | chamber | event_type | event_on | event_on_end | sequence | normalize(source_label) | normalize(source_value))`. It must not include `observed_at`, `run_id`, or the snapshot ID, or every run creates duplicates. It must include enough to distinguish two genuine same-day events.

Use events as the authoritative history and `chamber_records` as a convenient current projection. The projection is rebuildable from events; prove that with a test.

### `blobs` — R1

- `sha256` text primary key, `byte_size` bigint, `media_type` text, `storage_path` text, `compression` text, `first_stored_at`, `ref_count` integer.

One immutable content-addressed store for both page snapshots and document bytes. Identical bytes are stored once, so re-fetching an unchanged page every 12 hours costs a row, not a file. Layout: `<root>/<aa>/<bb>/<sha256>` where `aa`/`bb` are the first two byte pairs of the hash. HTML/JSON bodies are gzipped; PDFs are stored as retrieved. Blobs are never overwritten and never deleted except by an explicit retention job that checks `ref_count = 0` (§16.4).

### `source_snapshots` — R1

- `id`, `run_id`, `url`, `final_url`, `requested_at`, `status_code`, selected response headers (allowlisted: `content-type`, `content-length`, `etag`, `last-modified`, `cache-control`), `blob_sha256` nullable.
- `parser_version`, `parse_status`, `parse_error`, `parsed_at`, `records_parsed`.
- `structure_fingerprint` text — a hash of the page's structural shape (table headers, column labels) used for drift detection (§11.6).
- `retention_class`: `permanent` for snapshots that produced a change, `routine` otherwise.

Link parsed records back to a snapshot. Never store request secrets or unrestricted response headers.

### `fetch_attempts` — R1

- `id`, `run_id`, `target_kind`, `url`, `method`, `attempted_at`, `duration_ms`, `status_code` nullable, `bytes_received`, `conditional` boolean, `not_modified` boolean, `error_class` nullable, `error_detail` nullable (bounded), `blob_sha256` nullable.

Append-only transport log. This is what makes "HTTP status and latency by allowlisted host" (§17) an actual query instead of a hope, and it is the audit trail proving the crawler was polite. Retain 180 days by default, configurable.

### `fetch_queue` — R1

v1.0 said "queue allowlisted documents for conditional download" without defining a queue. This is it.

- `id`, `target_kind` (`listing`, `archive_page`, `document`, `robots`), `url` canonicalized and unique per kind, `bill_id` nullable, `document_id` nullable.
- `priority` smallint, `state` (`pending`, `leased`, `done`, `failed`, `dead`, `skipped`).
- `attempts` smallint, `next_attempt_at`, `last_error`, `lease_owner`, `lease_expires_at`.
- `etag`, `last_modified` — the conditional-request cache for the next fetch.
- `created_at`, `updated_at`.

Rules: leases expire so a crashed worker does not strand items; a target moves to `dead` after a configurable attempt ceiling and raises an anomaly; a `dead` item is re-queueable only by an explicit operator command; the queue survives a `partial` run so budget exhaustion resumes rather than restarts.

### `documents` — R1 (logical identity; holds no bytes)

- `id`, `document_kind`, `language`, `title_raw` nullable.
- `canonical_source_url` unique, plus `source_url_raw` as first encountered.
- `current_version_id` nullable foreign key to `document_versions`.
- `first_seen_at`, `last_seen_at`, `last_checked_at`, `last_changed_at`, `last_absent_at`, `absent_streak`.

`document_kind` is one of `bill_as_introduced`, `bill_as_passed`, `bill_revised`, `explanatory_statement`, `amendment_paper`, `reprint`, `translation`, `other`, `unknown`. `language` is `ms`, `en`, `mixed`, or `unknown` — use BCP 47 `ms`, not `bm`, everywhere except when constructing an upstream query string.

**Correction to v1.0:** `source_url` is unique on `documents` but must not carry the hashes, sizes, or extracted text that v1.0 put here. Those move to `document_versions`. Also, uniqueness on URL previously made it impossible for one PDF to belong to two bills or two chambers; the `bill_documents` link table below fixes that.

### `bill_documents` — R1

- `bill_id`, `document_id`, `chamber` nullable, `role` text, `first_seen_at`, `last_seen_at`, `source_url` (the listing page the link was found on).
- Unique on `(bill_id, chamber, document_id, role)`.

A document linked from both chambers' listings is one document with two links, not two documents.

### `document_versions` — R1 (the versioning core)

- `id`, `document_id`, `version_no` integer starting at 1.
- `content_sha256`, `blob_sha256`, `byte_size`, `media_type_declared`, `media_type_detected`.
- `etag`, `last_modified`, `http_status`, `final_url`.
- `retrieved_at`, `last_verified_at`, `run_id`, `fetch_attempt_id`, `snapshot_id` nullable.
- `supersedes_version_id` nullable, `superseded_at` nullable, `is_current` boolean.
- `change_kind`: `initial`, `content_changed`, or `metadata_only`.
- `validation_status`: `accepted`, `quarantined`, or `rejected`; `validation_error` nullable.
- `page_count` nullable (filled by extraction).

Constraints: unique `(document_id, version_no)`; unique `(document_id, content_sha256)` — the same bytes returning again is a re-verification, not a new version; a partial unique index enforcing at most one `is_current` row per document; `version_no` monotonic and never reused.

A version row is immutable except for `last_verified_at`, `superseded_at`, `is_current`, and `page_count`. Nothing in the system may update `content_sha256` or `blob_sha256` in place.

### `document_relations` — R2

- `from_document_id`, `to_document_id`, `relation` (`reissue_of`, `translation_of`, `part_of`, `superseded_by`), `confidence`, `decided_by` (`heuristic` or `human`), `created_at`, `note`.

When Parliament publishes a revised bill at a *new* URL (A11), that is a new document related to the old one — not a new version of it. Never auto-merge documents with different URLs into one version chain; propose the relation, alert, and let a human confirm.

### `document_extractions` — R1

- `id`, `document_version_id`, `extractor_name` (`pypdf`, `ocr:<engine>`, `html`), `extractor_version`, `pipeline_version`, `mode` (`native` or `ocr`).
- `status` (`succeeded`, `empty`, `failed`, `skipped`), `error` nullable.
- `extracted_text` (or a blob reference for large texts), `text_sha256`, `page_count`, `char_count`.
- `is_current` boolean, `created_at`, `duration_ms`.
- Unique on `(document_version_id, extractor_name, extractor_version, mode)`.

**Correction to v1.0:** extraction state lived on the document row, so a re-extraction with a better tool destroyed the previous result and a new document version destroyed the old text. Separating extraction from version and keying it by extractor version makes re-extraction additive and comparable. Record empty-text failure separately from transport failure and separately from a scanned document awaiting OCR.

### `document_chunks` — R3 (schema may land in R1)

- `id`, `extraction_id`, `chunker_version`, `chunk_index`, `heading`, `page_start`, `page_end`, `content`, `token_count`, `content_sha256`, `created_at`.
- Unique on `(extraction_id, chunker_version, chunk_index)`.

Chunks hang off an extraction, which hangs off a version. A citation therefore always resolves to specific bytes retrieved on a specific date.

### `chunk_embeddings` — R3

- `id`, `chunk_id`, `embedding_model_id`, `model_dimension`, `embedding` vector, `embedding_pipeline_version`, `created_at`.
- Unique on `(chunk_id, embedding_model_id)`.

**Correction to v1.0:** the embedding was a nullable column on the chunk, so switching models meant mutating chunk rows and no two models could coexist during a migration. A separate table lets a new model backfill alongside the old one and lets the old vectors be dropped only after the new set is validated. Embedding dimension belongs in a migration and must match the configured model; a model change is a versioned re-embedding job, never a silent mix.

### `record_changes` — R1

- `id`, `entity_type`, `entity_id`, `field_path`, `value_before` nullable, `value_after` nullable, `changed_at`.
- `change_source` (`scrape`, `replay`, `manual`), `run_id` nullable, `snapshot_id` nullable, `source_url` nullable, `parser_version`, `actor` nullable, `reason` nullable.

Every write that changes a stored value writes a row here, in the same transaction. This is the spine of §10 and the only honest way to show "what changed" and to diagnose a parser regression after the fact.

### `field_overrides` — R1

- `id`, `entity_type`, `entity_id`, `field_path`, `value`, `reason`, `actor`, `created_at`, `expires_at` nullable, `upstream_value_at_creation`.

Without this, an operator correcting a mis-parsed title is silently overwritten by the next scrape and the correction inbox becomes a treadmill. Overrides apply after normalization and before persistence; when the upstream value changes while an override is active, the scrape keeps the override, records the new upstream value, and raises an anomaly for review.

### `presence_observations` — R1

- `id`, `run_id`, `entity_type`, `entity_id`, `listing_url`, `present` boolean, `observed_at`.

Records the §5 rule ("never delete because one crawl omitted it") as data rather than as an intention. Written only for runs that completed a full, validated listing parse; a partial or failed run must not contribute absence evidence.

### `coverage_targets` — R1

- `id`, `chamber`, `listing_kind` (`current`, `archive`), `language`, `term`/`session`/`year` scope key.
- `expected_interval_hours`, `last_attempt_at`, `last_success_at`, `last_success_run_id`, `last_record_count`, `state` (`healthy`, `stale`, `failing`, `never_run`).

A single global "last scraped" timestamp hides a broken archive crawler behind a healthy current crawler. Freshness is per target (§10.4).

### `scrape_runs` — R1

- `id`, `mode` (`incremental`, `full`, `replay`, `fixture`), `trigger` (`schedule`, `manual`, `backfill`), start/end time, `state` (`running`, `succeeded`, `partial`, `failed`, `aborted`).
- Counts for fetched, not-modified, unchanged, parsed, inserted, updated, skipped, failed, new document versions, quarantined versions.
- Policy snapshot: user agent, delay, concurrency, parser version, normalizer version, budget limits and whether each was hit.
- Bounded structured error details with the affected URL.
- `publish_decision` (`published`, `withheld`) and reason (§11.6 guardrails).

### `backfill_jobs` — R1

- `id`, `kind` (`reparse`, `reextract`, `rechunk`, `reembed`), `from_version`, `to_version`, `filter_json`, `dry_run`, `state`, counts, `started_at`, `finished_at`, `error`.

A version bump in any pipeline stage is executed as a recorded job, not as an ad-hoc script someone ran once on a laptop.

### `anomalies` — R1

- `id`, `kind`, `severity` (`info`, `warn`, `critical`), `entity_type` nullable, `entity_id` nullable, `url` nullable, `detail_json` bounded.
- `first_seen_at`, `last_seen_at`, `occurrence_count`, `acknowledged_at`, `acknowledged_by`, `resolved_at`.

Because there is no CI and no paging system, an alert with nowhere to land is a log line nobody reads. Anomalies are rows that accumulate, deduplicate by `kind` + entity, appear on `/status`, and make `make doctor` exit non-zero until acknowledged or resolved.

### Relationship overview

```text
bill ──< bill_documents >── document ──< document_version >── document_extraction ──< document_chunk ──< chunk_embedding
 │                                            │                                                            (R3)
 ├──< chamber_record                          └── blob (immutable, content-addressed)
 ├──< bill_event                                        ^
 └──< record_change                        source_snapshot
```

### Database invariants

- All writes for one parsed source page are transactional, including the `record_changes` rows they generate.
- Upserts update `last_seen_at` and `last_checked_at` even when content is unchanged; they update `last_changed_at` only on a real diff.
- A null/missing newly scraped field does not overwrite a known value unless the source explicitly represents removal.
- Date parsing accepts the formats in §11.5 and stores a `date`; timestamps use UTC, displayed in `Asia/Kuala_Lumpur`.
- Normalize Unicode to NFC and collapse display whitespace, while retaining raw source strings.
- Use URL normalization only for deduplication; always retain the exact official URL encountered.
- Immutability: `blobs`, `fetch_attempts`, `bill_events`, `record_changes`, `presence_observations`, and the content columns of `document_versions` and `document_extractions` are append-only. Migrations may add columns; application code may not update these rows in place.
- Every derived row carries the version of the code that produced it (§9.1).

## 9. Content versioning and reprocessing contract

This section is the answer to "version the bill downloading". It applies to bill documents first and to page snapshots by the same principles.

### 9.1 Version-bearing artifacts

| Artifact | Version identifier | Bump triggers | Backfill job |
| --- | --- | --- | --- |
| Upstream page bytes | `source_snapshots.blob_sha256` | Upstream changed the page | none (append-only) |
| Bill document bytes | `document_versions.version_no` + `content_sha256` | Upstream served different bytes at the same URL | none (append-only) |
| Listing parser | `PARSER_VERSION` (semver) | Selector/label/logic change | `reparse` |
| Normalizer and status map | `NORMALIZER_VERSION` | Identifier rules, status mapping, date parsing change | `reparse` |
| Text extractor | `extractor_name` + `extractor_version` | Tool upgrade, OCR added, settings change | `reextract` |
| Chunker | `CHUNKER_VERSION` | Chunk size, overlap, boundary rules change | `rechunk` |
| Embeddings | `embedding_model_id` + `model_dimension` | Model change | `reembed` |
| Database schema | Alembic revision | Any schema change | migration |
| Public JSON API | URL path `/api/v1` | Breaking field change | new path |
| This handoff | §25 changelog | Any contract change | — |

Two rules govern all of them:

1. **A version bump never mutates existing rows.** It produces new rows alongside the old ones and flips an `is_current` flag when the new output is accepted.
2. **Every derived row records the producing version.** If a row cannot say which parser, extractor, chunker, or model made it, it cannot be selectively rebuilt, and the archive is not trustworthy.

### 9.2 Document identity versus document version

- Same canonical URL, different bytes → **new version** of the same document.
- Different URL → **new document**, optionally linked via `document_relations` (§8), never auto-merged.
- Same bytes at a new URL → new document sharing the same blob; the blob store deduplicates and `ref_count` reflects both.

Canonicalization for identity uses scheme/host lowercasing, default-port removal, percent-encoding normalization, and removal of a documented set of tracking/session parameters only. Never strip a parameter that could select a different file. Retain the raw URL as encountered.

### 9.3 Download state machine

Every document fetch follows exactly this decision table. Implement it as one tested function, not as scattered conditionals.

| Observation | Action |
| --- | --- |
| `304 Not Modified` | Insert `fetch_attempt` with `not_modified = true`. Advance `documents.last_checked_at` and current version `last_verified_at`. No new version. |
| `200`, hash equals current version | Store nothing new (blob already present). Advance `last_checked_at` and `last_verified_at`. If `ETag`/`Last-Modified` changed, record a `metadata_only` note in `record_changes`. No new version. |
| `200`, hash matches an *older*, non-current version | Upstream rolled back. Create a new version row with a new `version_no` pointing at the existing blob, `change_kind = content_changed`, and raise an anomaly — do not resurrect the old row. |
| `200`, new hash, validation passes | Create version `n+1`, `supersedes_version_id = current`, set it current, mark the old one superseded, advance `last_changed_at`, enqueue extraction. |
| `200`, declared type or magic bytes wrong (for example an HTML session-expiry page at a `.pdf` URL) | Store the blob, create the version with `validation_status = quarantined`, do **not** promote it to current, raise a critical anomaly. |
| `200`, size exceeds cap | Abort before buffering the whole body. Record the attempt and an anomaly. Do not store a truncated body as a version. |
| `404`/`410` after a previous `200` | No deletion. Record the attempt, write a presence observation, increment `absent_streak`, keep serving metadata for the last retrieved version with an explicit "no longer available at the official URL" note after the streak threshold. |
| `429`/`5xx`/timeout | Retry per policy, then requeue with backoff; after the attempt ceiling, `dead` plus an anomaly. Never a version, never an absence observation. |

Promotion of a new current version and the supersession of the old one happen in one transaction. Extraction, chunking, and embedding are enqueued, not done inline — a slow or failing PDF must never roll back or delay bill metadata.

### 9.4 What a new version invalidates

When version `n+1` becomes current:

- `document_extractions` for version `n` stay, untouched, and remain queryable.
- Extraction for `n+1` is enqueued at the current extractor version.
- Search units (§12.1) for version `n` are demoted from the default index; units for `n+1` are added when its extraction succeeds. Until then the bill remains searchable on metadata and on version `n` text explicitly labelled as the previous version — never silently.
- Chunks and embeddings for `n` are marked superseded and excluded from default retrieval. They are not deleted, so old citations still resolve.
- The bill page's "as of" date changes; `last_checked_at` and `last_changed_at` diverge and both are shown.

### 9.5 Public presentation of versions

The bill page must show, for each document: kind, language, official link, and a version list ordered newest first, each row carrying `version_no`, `retrieved_at`, byte size, page count, and a short content hash.

Two honesty requirements:

- Label our copy's date explicitly: "Our copy of this document was retrieved on 14 August 2026." Do not imply the official URL still serves those bytes.
- When a superseded version exists, say so plainly: "The official URL served different content when we last checked on 2 May 2026." Linking to the official URL for a superseded version would be misleading, because that URL now serves something else.

Until the rights review (A14) concludes, expose version *metadata* and short excerpts, not the mirrored bytes. If the review permits republication, serving `/documents/{id}/versions/{n}` from the blob store becomes possible without a schema change — that is a reason to build the model this way now.

### 9.6 Reprocessing and replay

Storing snapshots is pointless without a way to reuse them. All four backfills run offline, take the backfill advisory lock, default to `--dry-run`, accept a batch limit and a filter, and record a `backfill_jobs` row.

| Job | Input | Output | Writes to `record_changes` as |
| --- | --- | --- | --- |
| `reparse` | `source_snapshots` blobs | corrected bills/chamber records/events | `change_source = replay` |
| `reextract` | `document_versions` blobs | new `document_extractions` rows | not applicable (additive) |
| `rechunk` | current extractions | new chunk sets at the new chunker version | not applicable (additive) |
| `reembed` | current chunk sets | new `chunk_embeddings` rows | not applicable (additive) |

Rules:

- Replay must produce byte-identical results to the original run when the parser version is unchanged. Prove this with a test: replaying a snapshot at the same parser version writes zero `record_changes` rows.
- A replay never issues a network request. It is the safe way to fix a parser after a bad crawl without re-crawling Parliament.
- Replay respects `field_overrides` exactly as a live scrape does.
- A backfill that would change more than a configurable fraction of affected rows (default 30%) stops and asks for confirmation, the same guardrail as §11.6.
- After a successful non-dry-run backfill, the affected search units are rebuilt in the same job.

## 10. Change tracking, freshness, and coverage

### 10.1 Field-level change history

Every persisted change writes a `record_changes` row in the same transaction as the change. The diffing layer, not each call site, decides what counts as a change:

- Compare normalized values, not raw strings, for change detection; store both old and new raw values in the row.
- Whitespace-only and Unicode-normalization-only differences are not changes.
- A transition from a known value to `NULL` is a change only when the source explicitly represents removal; otherwise it is skipped per the §8 invariant and recorded as an anomaly if the field was previously reliable.
- Manual corrections and overrides write rows with `change_source = manual`, an actor, and a reason.

This gives, for free: a per-bill history section, a site-wide `/changes` feed, "which run introduced this wrong value" debugging, and evidence for the requirement matrix.

### 10.2 What the public sees

- Bill page: a history list combining `bill_events` (what Parliament did), `record_changes` (what our record changed and when), and `document_versions` (when documents changed). Label the three sources distinctly; they are not the same kind of fact.
- `/changes`: reverse-chronological, filterable by chamber and change type, paginated.
- Never present a change in our record as a change in Parliament's position. A parser fix that corrects a title is our error being corrected, and the feed must say so.

### 10.3 Absence and tombstoning

- Absence is evaluated only at the end of a run whose listing parse passed validation and was published.
- Each expected entity gets a `presence_observations` row per such run.
- `absent_streak` increments on absence and resets to zero on presence.
- At a configurable threshold (default 3 consecutive successful full runs), raise a `warn` anomaly and mark the record as "not seen recently" in the UI. Never hide or delete it.
- Tombstoning is manual only, requires a reason, is recorded in `record_changes`, and still leaves the page reachable with an explanatory note.

### 10.4 Freshness and coverage

Per-target rather than global:

- Each `coverage_targets` row has an expected interval and derives `state` from `last_success_at`.
- `/status` shows every target, its state, last success, record count, and last change; plus queue depth, dead-letter count, open anomalies by severity, oldest pending document extraction, and current pipeline versions.
- The homepage freshness line reports the *oldest* healthy-target success time, not the newest. Reporting the newest lets a working current-listing crawl mask a six-week-stale archive.
- Staleness thresholds are configuration, and a stale target is an anomaly.

### 10.5 Anomaly taxonomy

Minimum set, each with a defined severity, an owner action, and a test that provokes it:

| Kind | Severity | Trigger |
| --- | --- | --- |
| `unmapped_status` | warn | Status string not in the mapping |
| `unparseable_identifier` | warn | Identifier normalization failed |
| `unparseable_date` | warn | Date string matched no accepted format |
| `structure_drift` | critical | Page structure fingerprint changed |
| `zero_records` | critical | A current listing parsed to zero rows |
| `count_drop` | critical | Record count fell beyond the threshold |
| `duplicate_identifier_conflict` | critical | Same normalized identifier, conflicting titles |
| `pagination_loop` | warn | Repeated content hash while paginating |
| `document_quarantined` | critical | Content-type or magic-byte validation failed |
| `document_rollback` | warn | Bytes matched an older non-current version |
| `document_gone` | warn | Absence streak threshold reached |
| `extraction_failure_spike` | warn | Extraction failure rate above baseline |
| `override_conflict` | warn | Upstream changed a field under an active override |
| `robots_changed` | critical | `robots.txt` hash changed |
| `target_stale` | warn | Coverage target past its expected interval |
| `queue_dead_letter` | warn | Items in `dead` state |
| `budget_exhausted` | info | A run ended `partial` |

`make doctor` exits non-zero when any unresolved `critical` anomaly exists, and is the release and daily-operations gate that substitutes for CI.

## 11. Scraper implementation contract

### 11.1 Fetch/parse separation

The fetcher returns an immutable result containing request URL, final URL, timestamp, status, safe headers, and bytes. Parsers never perform network I/O. This makes failures reproducible from fixtures and snapshots, and it is what makes §9.6 replay possible.

### 11.2 Preflight

1. Acquire the scrape advisory lock; refuse to start if held.
2. Fetch `robots.txt`, store it as a snapshot, compare its SHA-256 to the last stored value, and raise `robots_changed` on a difference. A changed policy stops the run pending review.
3. Load the crawl budget and policy into the run's policy snapshot.

### 11.3 Listing workflow

1. Start a `scrape_run` with mode and trigger.
2. Validate crawl permission and policy.
3. Fetch the current and archive entry points for both chambers. Fetch English only when enabled.
4. Discover pagination/archive requests from the confirmed upstream contract; bound page count and stop on repeated content hashes.
5. Snapshot every fetched page before parsing it.
6. Parse table labels and expanded-detail labels semantically. Do not depend only on `nth-child`, generated IDs, or visual CSS classes.
7. Normalize identifiers with a tested parser tolerant of whitespace and punctuation differences. Keep `identifier_raw` if normalization fails and raise `unparseable_identifier` instead of dropping the row.
8. Apply `field_overrides`, diff against stored state, upsert bill, chamber record, and events, and write `record_changes`. Reconcile English titles by normalized identifier only.
9. Write presence observations for the entities the listing was expected to contain.
10. Queue allowlisted documents into `fetch_queue`.
11. Commit only after page-level validation. Update coverage targets, finish the run with metrics, release the lock.

### 11.4 Document workflow

1. Lease a queue item and issue a conditional GET using the stored `ETag`/`Last-Modified`.
2. Enforce response and content limits before buffering.
3. Validate declared media type and magic bytes.
4. Hash bytes, store the blob if new, and apply the §9.3 state machine.
5. On a new current version, enqueue extraction. Extract page-aware text, recording empty text, native-text failure, and transport failure as distinct outcomes.
6. Normalize text conservatively; preserve headings, section numbers, page boundaries, and the raw extracted text.
7. OCR only through an explicit optional worker queue, recorded as a separate extractor with `mode = ocr`.
8. Chunk only after extraction succeeds. A document failure must never roll back bill metadata.

### 11.5 Date and text parsing

The v1.0 contract accepted only `DD/MM/YYYY`, which will silently produce nulls the first time a Malay month name appears. Required behaviour:

- Accept `DD/MM/YYYY`, `D/M/YYYY`, `DD-MM-YYYY`, `YYYY-MM-DD`, and `D <MonthName> YYYY` for Malay and English month names and common abbreviations (A7).
- Accept ranges in a single cell (`13–14 Julai 2026`, `13/07/2026 - 14/07/2026`, en dash and hyphen) and store `event_on` plus `event_on_end`.
- Accept multiple dates in one cell and produce multiple events with an incrementing `sequence`.
- Reject ambiguous two-digit years rather than guessing a century.
- Never guess between `DD/MM` and `MM/DD`; the source is Malaysian, so `DD/MM` is assumed, and a value above 12 in the second position raises `unparseable_date` rather than swapping.
- An unparseable date raises an anomaly, retains the raw string, and leaves the date `NULL`. It never silently disappears.

### 11.6 Guardrails against silent corruption

- A current page yielding zero bills is a failed parse, not an empty Parliament.
- Abort publication of a run when record count drops by more than a configurable threshold (default 30%) from the last successful comparable run. "Abort publication" means the run is recorded with `publish_decision = withheld` and prior data remains live.
- Compare each page's `structure_fingerprint` to the last accepted one and raise `structure_drift` on change, because a redesigned page that still parses to plausible-looking rows is the most dangerous failure mode.
- Treat a `200` response containing an error/soft-404 body as a parse failure, detected by fingerprint and record count, not by status code alone.
- Raise the anomalies in §10.5 rather than logging and continuing.
- Save the failing snapshot and parser version.
- Golden fixture tests must assert exact structured output. A live smoke test is opt-in and may not be the only parser test.

### 11.7 Crawl budget, resumption, and scheduling

- Per-run limits: `max_requests`, `max_bytes`, `max_duration_seconds`, `max_new_documents`. All configurable; all recorded in the run's policy snapshot.
- Hitting a limit ends the run as `partial` with the queue intact and raises `budget_exhausted`. The next run resumes from the queue.
- The scheduler adds jitter, never overlaps runs (enforced by the advisory lock, not by timing), and does not attempt to catch up on missed runs by bursting.
- A full archive crawl is a separate, explicitly triggered mode with its own, larger budget.

## 12. Search contract

### 12.1 Lexical search is mandatory

Use PostgreSQL full-text search with the `simple` dictionary so Malay words and legal identifiers are not damaged by an English stemmer.

**Correction to v1.0:** v1.0 put identifiers, titles, presenters, and full extracted body text into a single weighted vector per bill. A `tsvector` is limited to about 1 MB (and each lexeme to 2 KB), so a long bill PDF will fail to index or will be silently truncated, and every new document version would rewrite one enormous row. Split the index instead:

- `search_units` — one row per unit, where a unit is either a **bill metadata unit** (weights A and B: normalized identifier, raw identifier, titles, presenter, status, chamber, year) or a **document text unit** (weight C: one page or one chunk of one document version's current extraction).
- Columns: `id`, `unit_kind`, `bill_id`, `document_version_id` nullable, `page_from`/`page_to` nullable, `content`, `tsv` generated/stored, `is_current` boolean, `updated_at`.
- GIN index on `tsv`; supporting indexes on `bill_id` and `is_current`.

Query behaviour:

- Search both unit kinds, roll document hits up to their bill, and return one row per bill with the best matching passage.
- Default to `is_current = true` units only; expose `include_superseded=1` as an explicit option.
- Index maintenance is an explicit service call in the same transaction as the write that caused it (bill upsert, extraction completion, version promotion, backfill). Document the ownership in `docs/data-model.md`; do not split it between triggers and application code.

Use parameterized `websearch_to_tsquery('simple', :query)` for ordinary terms and an explicit normalized-identifier path for inputs such as `D.R. 15/2026`. Consider `pg_trgm` for spelling tolerance only after measuring it.

Ranking order:

1. exact normalized identifier;
2. identifier prefix;
3. weighted full-text rank across the bill's units;
4. newest relevant event date;
5. normalized identifier as deterministic tie-breaker.

Limits and safety:

- Trim and cap queries (suggested maximum 200 Unicode characters).
- Cap page size (suggested default 20, maximum 100). Use keyset pagination beyond a configurable offset so deep pages do not degrade.
- Parameterize every query.
- Generate snippets only for the results on the page being rendered, from the matching unit rather than the whole document, with bounded fragments.
- Escape snippets before inserting highlight markup; never render database `ts_headline` output as trusted HTML without sanitization.
- Log latency, result count, and a privacy-preserving query fingerprint. Do not retain raw user queries by default.

### 12.2 Filters

The `/bills` and `/search` pages share GET parameters:

- `q`
- `chamber=dewan_rakyat|dewan_negara`
- `status=<normalized-status>`
- `year=YYYY`
- `lang=bm|en`
- `page=N`

Invalid filters return a helpful 400 response rather than silently changing meaning. Preserve filters in pagination links. The no-query state is a browsable bill index ordered by newest activity.

### 12.3 Semantic extension

Use pgvector and a provider interface, not provider calls embedded in route handlers. The default embedding model must cover Malay and English and be recorded on every vector.

- Start with section/page-aware chunks around 500–800 model tokens and roughly 10–15% overlap.
- Do not split a numbered provision when it fits within the maximum chunk size.
- Retrieve lexical and vector candidates separately, then fuse with reciprocal-rank fusion. Exact identifier matches remain first.
- Filter by chamber/year/status and by current-version-only before or during vector retrieval, not only after limiting results.
- Return source, document version, page range, and a deterministic chunk anchor with each result.
- Build an HNSW cosine index after representative data exists and validate recall/latency before tuning.
- Cache query embeddings by model and normalized query with a bounded TTL.
- A model change follows the `reembed` job in §9.6: backfill alongside, validate, switch, then drop the old vectors by explicit job.

## 13. RAG contract

RAG is an evidence-viewing feature, not a chatbot with general legal knowledge.

### Request flow

1. Validate and rate-limit the question.
2. Run hybrid retrieval with metadata filters, restricted to current document versions by default.
3. Reject or qualify retrieval below an evaluated threshold.
4. Construct a prompt containing only bounded, labeled source chunks and instructions to treat retrieved text as untrusted data.
5. Generate an answer in the requested language when supported.
6. Verify that every citation points to a retrieved chunk and render the official bill/document link, the document version and its retrieval date, and the page range.
7. Store operational metadata (model, latency, token counts, cited chunk IDs), but not the raw question/answer by default.

### Required behavior

- The UI says answers are generated from indexed parliamentary documents and are not legal advice.
- Claims about status or dates should prefer structured bill fields over generated interpretation.
- Every citation is version-pinned: it names the document version it came from and when we retrieved it. An answer generated from a now-superseded version must say so.
- Prompt injection inside a document must not change system behavior, request new tools, or reveal configuration.
- No answer may cite a chunk that was not supplied to the model.
- If the model provider is unavailable, return the retrieved passages and normal search links.
- Set per-request time/token/cost ceilings and a global kill switch: `RAG_ENABLED=false`.
- Do not ship until a small, versioned Malay/English evaluation set covers identifier lookup, status questions, cross-chamber timelines, amendments, superseded-document cases, no-answer cases, and citation correctness.

Suggested extension endpoints:

- `GET /semantic-search?q=...`
- `GET /ask` for the form
- `POST /api/v1/ask` for answers, with stricter rate limits

Never expose an unrestricted model proxy.

## 14. Web and API contract

### Public routes

| Route | Purpose | Release |
| --- | --- | --- |
| `GET /` | Product explanation, search box, newest bills, data freshness | R1 |
| `GET /bills` | Filterable, paginated index | R1 |
| `GET /bills/{stable-slug}` | Bill metadata, chamber timelines, documents and their versions, text/search excerpts, provenance, history | R1 |
| `GET /search` | Keyword results using the same filters | R1 |
| `GET /status` | Per-target freshness/coverage, run history, open anomaly counts, pipeline versions | R1 |
| `GET /about` | Methodology, limitations, crawl identity, contact, source attribution | R1 |
| `GET /health/live` | Process liveness only | R1 |
| `GET /health/ready` | Database/migration readiness; no upstream request | R1 |
| `GET /changes` | Recent record and document-version changes | R2 |
| `GET /sitemap.xml` | Canonical public bill URLs | R2 |
| `GET /robots.txt` | Policy for BillWatcherNext, unrelated to upstream policy | R1 |

`/status` is public and must contain no credentials, hostnames of internal services, stack traces, or raw error bodies — counts, states, and timestamps only.

Provide read-only JSON under `/api/v1/bills` and `/api/v1/bills/{identifier}` only after the HTML routes work. Return stable field names, pagination metadata, source URLs, document version metadata, `updated_at`, and a versioned schema. Add cache validators to public read responses.

Old slugs redirect permanently to the current slug via `bill_slug_aliases`.

### Bill page requirements

- Identifier and Malay title as the primary heading; English title when known.
- Clearly separated Dewan Rakyat and Dewan Negara timelines.
- Raw source status beside a carefully labeled normalized status.
- Presenter/sponsor exactly as published, without attempting risky person-entity resolution.
- Official listing and document links.
- Documents section listing every document with its version history per §9.5.
- `Last checked` and `Last changed` timestamps, plus the current document version's `retrieved_at`, each labelled with the §3 meaning.
- A history section per §10.2, distinguishing parliamentary events from corrections to our own record.
- Searchable extracted-text excerpts or sections, with a notice when extraction/OCR is incomplete or pending.
- A visible note when the bill has not been seen in recent runs (§10.3).
- A correction/contact path; corrections land as `field_overrides` with a reason, not as silent database edits.
- No implication that `passed` is equivalent to royal assent, gazettal, commencement, or current law.

### Accessibility and resilience

- Semantic HTML, one `h1`, associated form labels, keyboard-visible focus, skip link, adequate contrast, and status text that does not depend on color.
- Correct `lang` attributes: the document language for UI chrome and per-element `lang` for Malay titles inside English pages and vice versa.
- Search/filter submit works without JavaScript.
- Responsive layout from narrow mobile widths upward.
- Page title and heading communicate the active query/filter.
- Error pages include a request ID but no stack trace.
- Avoid third-party fonts, trackers, and client-side analytics in the first release.

## 15. JSON-LD contract

Use Schema.org [`Legislation`](https://schema.org/Legislation) on a bill detail page. Generate JSON through the application serializer and Jinja's safe JSON mechanism; never concatenate source strings into a `<script>` block.

Illustrative shape (values must come from the record):

```json
{
  "@context": "https://schema.org",
  "@type": "Legislation",
  "@id": "https://PUBLIC_HOST/bills/dr-15-2026#bill",
  "url": "https://PUBLIC_HOST/bills/dr-15-2026",
  "name": "RUU Perlindungan Saksi (Pindaan) 2026",
  "alternateName": "Witness Protection (Amendment) Bill 2026",
  "legislationIdentifier": "D.R.15/2026",
  "legislationJurisdiction": "Malaysia",
  "legislationType": "Bill",
  "inLanguage": ["ms", "en"],
  "sameAs": "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr",
  "isPartOf": {
    "@type": "WebSite",
    "name": "BillWatcherNext",
    "url": "https://PUBLIC_HOST/"
  }
}
```

Rules:

- Use BCP 47 `ms` for Malay in structured output even though the upstream query parameter is `bm`.
- Emit only fields supported by source data.
- Add `legislationDate` only for an explicitly passed bill and use the correctly scoped passage date; chamber-specific dates can instead be represented in page content to avoid ambiguity.
- Add `legislationPassedBy` only when the source supports the claim and the modeled body is correct.
- Do not use `legislationLegalForce` for a bill merely marked passed by a chamber.
- `sameAs` must point to the relevant official record or document, not a generic home page when a better source exists.
- Do not emit our stored copy as though it were the canonical document; any `associatedMedia`-style reference must point at the official URL.
- Validate representative pages with a JSON parser and Schema.org-aware test. Escaping tests must include `</script>`, quotes, ampersands, and Unicode names.

## 16. Docker and operations contract

### 16.1 `Dockerfile`

- Multi-stage build based on an official slim Python image.
- Copy `uv` from its official image pinned to an immutable version or digest.
- Install from committed `pyproject.toml` and `uv.lock` with `uv sync --locked`; production must not resolve dependencies at container startup.
- Build/install the project non-editably for production.
- Run as a numeric, unprivileged user and group that owns the blob volume mount.
- Set deterministic Python environment variables, use an exec-form command, and stop cleanly on `SIGTERM` — a worker must release its lease and advisory lock on shutdown rather than stranding queue items.
- Include only runtime libraries in the final image. Put OCR system packages in a separate target/profile if needed.
- `.dockerignore` must exclude `.git`, `.venv`, caches, test artifacts, local snapshots, backups, and secrets.

### 16.2 `compose.yaml`

Required services:

- `db`: PostgreSQL image with pgvector, internal only, persistent named volume, health check.
- `migrate`: one-shot application command, dependent on healthy database.
- `app`: web command, dependent on successful migration, health check, no source bind mount in production; read-only access to the blob volume.
- `worker`: scheduled scraper command from the same image, dependent on migration; read-write access to the blob volume.
- `caddy`: only service publishing ports 80/443, persistent certificate volumes, dependent on healthy app.

Use `restart: unless-stopped` for long-running services, explicit networks, log rotation, and service-level resource guidance. Do not publish PostgreSQL to the host. Do not put passwords or API keys in the Compose file. `.env.example` contains safe names/placeholders only; the real `.env` is ignored and mode-restricted.

At minimum, configuration includes:

```dotenv
SITE_HOST=bills.example.org
DATABASE_URL=postgresql+psycopg://billwatcher:CHANGE_ME@db:5432/billwatcher
POSTGRES_DB=billwatcher
POSTGRES_USER=billwatcher
POSTGRES_PASSWORD=CHANGE_ME
PUBLIC_BASE_URL=https://bills.example.org
CONTACT_EMAIL=operator@example.org
BLOB_STORAGE_ROOT=/var/lib/billwatcher/blobs
SCRAPE_ENABLED=false
SCRAPE_INTERVAL_HOURS=12
SCRAPE_DELAY_SECONDS=2
SCRAPE_CONCURRENCY=1
SCRAPE_MAX_REQUESTS_PER_RUN=2000
SCRAPE_MAX_BYTES_PER_RUN=1073741824
SCRAPE_MAX_DURATION_SECONDS=3600
DOCUMENT_MAX_BYTES=104857600
ABSENCE_STREAK_ALERT=3
COUNT_DROP_ABORT_FRACTION=0.30
FETCH_ATTEMPT_RETENTION_DAYS=180
SEMANTIC_SEARCH_ENABLED=false
RAG_ENABLED=false
```

The application should reject placeholder secrets in production mode.

### 16.3 `Makefile`

Targets are the human and agent interface. Use tabs correctly, declare phony targets, and make failures visible.

| Target | Contract |
| --- | --- |
| `help` | Document targets and defaults |
| `setup` | `uv sync --locked --all-groups` after a lock exists |
| `lock` | Explicitly update/validate `uv.lock`; never part of production start |
| `format` | Apply formatter |
| `lint` | Ruff/static lint checks |
| `typecheck` | Required type check |
| `test` | Offline unit + fixture + integration tests |
| `test-live` | Explicit opt-in, low-rate upstream smoke test |
| `check` | lint + typecheck + test |
| `serve` | Local development web server |
| `migrate` | Upgrade database to head |
| `scrape` | One incremental run |
| `scrape-full` | Explicit full archive run |
| `status` | Print run history, coverage/freshness, queue depth, pipeline versions |
| `doctor` | Evaluate anomalies and invariants; non-zero exit on unresolved critical findings |
| `reparse` | Replay stored snapshots at the current parser version; `--dry-run` default |
| `reextract` | Re-extract document versions below the current extractor version; `--dry-run` default |
| `rechunk` | Rebuild chunk sets at the current chunker version; `--dry-run` default |
| `reembed` | Backfill embeddings for a named model; `--dry-run` default |
| `verify-storage` | Verify blob hashes against the database; report orphans and missing blobs |
| `prune-blobs` | Delete only unreferenced, non-`permanent` blobs; `--dry-run` default |
| `fixtures-refresh` | Regenerate test fixtures from stored snapshots, offline |
| `docker-build` | Reproducible image build |
| `compose-up` | Start the production-shaped stack |
| `compose-down` | Stop services without deleting volumes |
| `logs` | Follow bounded service logs |
| `backup` | Timestamped PostgreSQL dump to an explicit backup directory |
| `backup-blobs` | Incremental blob-store backup to an explicit destination |
| `restore` | Guarded restore requiring an explicit backup path |

No default target may crawl the live Parliament site or delete data. Every destructive or mutating backfill defaults to a dry run and prints what it would change. A destructive `clean` target, if added, must not remove volumes, snapshots, blobs, or backups.

### 16.4 Retention

- `document_versions` and their blobs: retained indefinitely. They are the archive. No automatic pruning, ever.
- `source_snapshots`: all rows retained. Blobs deduplicate by hash, so unchanged pages cost one row per observation and no extra bytes. Blobs for `quarantined` or failed responses may be pruned after 90 days.
- `fetch_attempts`: retained per `FETCH_ATTEMPT_RETENTION_DAYS`, then aggregated into daily counters before deletion.
- `document_extractions`: keep the current extractor version and the immediately previous one; older ones prunable by explicit job.
- `chunk_embeddings`: keep the current model; a superseded model's vectors are dropped only by explicit job after the replacement is validated.
- `record_changes`, `bill_events`, `presence_observations`: retained indefinitely.
- Blob deletion is only ever performed by `prune-blobs` with a reference check, never inline by application code.

### 16.5 Public deployment runbook

1. Provision a host with Docker Engine and current Compose, persistent disk sized against A12, backups, and outbound HTTPS.
2. Point the chosen DNS A/AAAA records at it and allow inbound 80/443 only (plus tightly restricted SSH administration).
3. Copy the repository and create the private production environment file with a generated database password, real public URL, and contact email.
4. Build with the lockfile, start the database, run migrations, and execute a fixture-mode scrape.
5. Verify the live upstream policy manually, then enable and run one low-rate full scrape. Review counts, anomalies, and `make doctor` before publication.
6. Start app, worker, and Caddy. Verify external HTTPS from a different network, canonical redirects, readiness, search, a detail page, source links, `/status`, and certificate renewal storage.
7. Configure daily database backups **and blob-store backups**, plus periodic restore drills covering both. A database restore without the blob store loses the archive and every future re-extraction.
8. Monitor readiness, per-target scrape freshness, last successful run, run duration, parse errors, zero-result anomaly, queue depth, dead-letter count, new document versions per day, extraction backlog, disk usage, database size, blob-store size, response error rate, and p95 search latency.

Do not call the service publicly accessible until an external client can load it over valid HTTPS; a localhost container check is insufficient evidence.

## 17. Security, privacy, and observability

- Use strict TLS for inbound and upstream traffic.
- Parameterized SQL, autoescaped templates, safe JSON serialization, trusted-host validation, and conservative proxy-header configuration are required.
- Caddy should add HSTS only after HTTPS/domain correctness is established, plus `X-Content-Type-Options`, a restrictive `Referrer-Policy`, and a tested Content Security Policy.
- Outbound requests resolve and connect only to allowlisted hosts; revalidate redirects to prevent SSRF. A redirect off the allowlist ends the fetch, is recorded, and raises an anomaly.
- Blob paths are derived from content hashes only; never build a storage path from an upstream-controlled string, and never serve a blob by a path supplied in a request.
- Admin/scrape/backfill commands are CLI-only in Release 1. Do not expose a public `POST /scrape` route.
- Rate-limit search and especially RAG without blocking ordinary browsing.
- Logs are structured and include request/run IDs, but exclude database URLs, cookies, API keys, full response bodies, raw RAG prompts, and raw user queries by default.
- `/health/live` does not reveal dependencies. `/health/ready` returns minimal status and no credentials/version dump. `/status` reveals operational counters only.
- Dependency and container vulnerability review is a documented manual release gate because GitHub CI is out of scope; record each review date in `docs/status.md`.

Key metrics:

- last successful incremental/full run time, per coverage target;
- records inserted/updated/unchanged/failed;
- new document versions created, quarantined versions, rollbacks detected;
- HTTP status and latency by allowlisted host, and conditional-request hit rate;
- queue depth, lease expiries, dead-letter count;
- parser failures and unknown status values;
- document extraction/OCR outcomes and extraction backlog age;
- index freshness and oldest pending document;
- open anomalies by severity and age of the oldest unacknowledged critical;
- blob-store size and growth rate;
- semantic/RAG latency and cost when enabled.

## 18. Testing and release gates

### Offline required tests

- Identifier, date, whitespace, Unicode, status, and URL normalization, including Malay month names, date ranges, multi-date cells, and rejection of ambiguous dates.
- Listing fixtures for both chambers/current/archive and Malay/English variants.
- Changed markup, missing fields, empty page, duplicate rows, conflicting cross-chamber dates, unexpected statuses, and a soft-404 body served with `200`.
- Fetch policy: robots denial, robots hash change, disallowed redirects, retry/`Retry-After`, timeout, size limit, content type, conditional GET, circuit breaker, budget exhaustion, and TLS failure.
- Idempotent upserts, `last_seen_at` versus `last_changed_at` behavior, and a second identical run writing zero `record_changes` rows.
- Versioning, as its own suite:
  - refetch with `304` → no new version, `last_checked_at` advances, `last_changed_at` does not;
  - refetch with identical bytes → no new version, no duplicate blob;
  - refetch with changed bytes → `version_no` increments, old version and its extraction remain readable, `is_current` moves, `last_changed_at` advances;
  - bytes matching an older version → new version plus rollback anomaly;
  - wrong magic bytes → quarantined version, current version unchanged, critical anomaly;
  - `404` after `200` → nothing deleted, presence observation written, absence streak increments;
  - one blob shared by two documents → `ref_count` correct, `prune-blobs` deletes neither.
- Replay: re-parsing a snapshot at the same parser version produces zero changes; at a bumped version, changes are attributed to `replay` and overrides survive.
- Overrides: a scrape does not clobber an active override, and a conflicting upstream change raises an anomaly.
- Presence/coverage: freshness reports the oldest healthy target; a stale target flips state.
- Migration upgrade from an empty database; migration downgrade policy documented.
- Lexical ranking: exact code, Malay phrase, English title, presenter, body text, filters, pagination, and escaping.
- Index scale guard: a synthetic multi-megabyte extracted text indexes and searches without error, proving the §12.1 split.
- Search excludes superseded versions by default and includes them on request.
- Slug alias redirects permanently to the current slug.
- HTML response accessibility smoke tests and no-JavaScript form behavior.
- JSON API contract and cache validators.
- JSON-LD field omission and script-breaking input escaping.
- Docker image starts as non-root, both health endpoints behave correctly, and `make doctor` exits non-zero with a seeded critical anomaly.

### Optional live tests

`make test-live` must require an explicit environment opt-in, obey crawl delay, fetch only a tiny known set, never run as part of `make test`, and skip with a clear message when policy/TLS/upstream availability prevents it.

### Release acceptance walkthrough

1. Start from a fresh clone plus environment file.
2. `make setup` and `make check` pass.
3. `make docker-build` and the Compose stack start from empty named volumes.
4. Migrations reach head exactly once.
5. Fixture ingestion proves the entire site without network access.
6. Approved live full scrape ingests both chambers and archives with reviewed totals and `make doctor` clean.
7. Running it again produces zero duplicates and zero recorded changes.
8. A simulated upstream document change (fixture mode) produces a second version, and the bill page shows both versions with correct dates.
9. `make reparse --dry-run` over stored snapshots reports zero changes at the current parser version.
10. Search manually proves an exact `D.R.` code, Malay title terms, a presenter, a status/year/chamber filter, and a phrase from a document.
11. A shared bill shows distinct chamber timelines.
12. `/status` shows every coverage target healthy with plausible timestamps.
13. External HTTPS, canonical URL, source link, readiness, sitemap, database backup, blob backup, and restore are verified.

## 19. Agent work packages and integration order

Agents should work in small branches/worktrees and hand back code, tests, migrations, observed assumptions, an updated `docs/status.md`, and exact verification commands. Do not let multiple agents independently redesign shared models; `docs/data-model.md` and migrations are the contract after Package B lands.

### Package A — scaffold and runtime

Inputs: §6, §7, §16.  
Outputs: `pyproject.toml`, lockfile, package skeleton, `version.py`, config, logging, CLI shell, blob storage module, Dockerfile, Compose, Caddy, Makefile, README, `docs/status.md` seeded, basic health routes.  
Acceptance: locked local setup, non-root image, fresh Compose health, blob volume writable by the worker and read-only to the app, no GitHub workflows.

### Package B — upstream discovery and data model

Inputs: §4, §5, §8, §9.  
Outputs: `docs/upstream.md` with the full label/status vocabulary, minimal fixtures, domain types, SQLAlchemy models, first Alembic migration, normalization and date unit tests, §4 register updated in `docs/status.md`.  
Acceptance: discovery evidence is dated and every §4 assumption it touches is marked verified or explicitly still open; the same bill can hold two chamber records; one document can hold multiple versions; empty-db migration passes.

Package B must precede parser and web integration. Package A and the non-network portions of B can start independently.

### Package C — scraper, versioning, and extraction

Inputs: approved Package B contracts and fixtures.  
Outputs: policy/fetch layer, fetch queue, listing parsers, idempotent ingestion service, change tracking, the §9.3 version state machine, PDF extraction, replay/backfill jobs, scrape CLI/worker, run metrics, anomalies, fixture tests.  
Acceptance: two identical fixture runs produce no duplicates and no recorded changes; a changed-bytes fixture produces a second version with the first preserved; corruption guardrails fire; replay at the same parser version is a no-op; live smoke remains opt-in.

### Package D — public web and lexical search

Inputs: Package B schema plus seeded fixtures; it need not wait for live scraping.  
Outputs: server-rendered routes/templates/styles, search units and index migration, filters/pagination, `/status`, document version display, slug redirects, API v1, accessibility and HTTP tests.  
Acceptance: Release 1 search/detail walkthrough passes with JavaScript disabled; the multi-megabyte index guard passes; version history renders with correct §3 labels.

### Package E — operations and public deployment

Inputs: Packages A, C, and D.  
Outputs: production Compose hardening, operations runbook, backup/restore for database and blobs behind Make targets, retention jobs, `make doctor`, observability, external deployment checklist.  
Acceptance: fresh-volume rehearsal, restore drill including blobs, `verify-storage` clean, external HTTPS verification, database not published.

### Package F — JSON-LD and discovery

Inputs: Package D stable bill pages.  
Outputs: Legislation serializer, canonical/metadata tags, sitemap, `/changes` feed, escaping/validation tests.  
Acceptance: representative current, passed, bilingual, and malicious-string fixtures emit truthful parseable JSON-LD.

### Package G — semantic search

Inputs: stable extraction and search metrics.  
Outputs: chunker, provider adapter, vector migration/index, `reembed` backfill, hybrid retrieval, evaluation set, feature-flagged UI/API.  
Acceptance: versioned embeddings, measured hybrid relevance, exact-code priority, superseded chunks excluded by default, clean disabled mode.

### Package H — RAG

Inputs: Package G retrieval evaluation is acceptable.  
Outputs: bounded answer service, prompt-injection controls, version-pinned citation verifier, rate/cost controls, no-answer behavior, RAG evaluations.  
Acceptance: all cited chunks were retrieved and name their document version; provider outage falls back to passages; kill switch leaves core site healthy.

### Integration sequence

```text
A scaffold ──────┬──────────────> E deployment
                 ├─> D web/search ─> F JSON-LD
B model/discovery┼─> C scraper ─────> E deployment
                 └─> D web/search
C extraction + D search ─> G semantic ─> H RAG
```

The integrator owns migration conflict resolution, lockfile changes, the acceptance walkthrough, `docs/status.md` reconciliation, and updating this handoff when an upstream assumption changes.

## 20. Project status tracking

Implementation progress is tracked in `docs/status.md`, created by Package A and updated in the same change as the work it describes. An agent that lands code without updating the ledger has not finished the task.

### Required sections of `docs/status.md`

**Package ledger.** One row per package A–H:

| Package | State | Owner/agent | Branch | Started | Last update | Evidence | Blockers |
| --- | --- | --- | --- | --- | --- | --- | --- |

State is one of `not_started`, `in_progress`, `blocked`, `in_review`, `done`. `done` requires the acceptance line from §19 to be satisfied and the evidence column to name a command, test, or artifact — not a claim.

**Assumption status.** One row per §4 ID: status (`open`, `verified`, `refuted`, `superseded`), verified-on date, evidence link (fixture path or `docs/upstream.md` section). A refuted assumption requires a §25 changelog entry, because it means this handoff is now wrong somewhere.

**Decision index.** One row per ADR: ID, title, state (`proposed`, `accepted`, `superseded`), date. Mirrors §21.

**Open questions.** Question, raised-by, raised-on, owner, needed-by (which package it blocks). A question with no owner is not tracked, it is forgotten.

**Manual gate log.** Dated entries for the checks CI would otherwise do: dependency review, container vulnerability review, restore drill, live crawl approval, rights review. Each with a date, who, and outcome.

### Rules

- The handoff holds stable contracts; `docs/status.md` holds volatile state. Never duplicate a status into this file.
- Do not track task-level minutiae here — package-level state plus blockers is the resolution. Sub-tasks belong in the branch.
- Cadence: update on every package handback, and review open questions and assumption status at least weekly while any package is `in_progress`.
- `make status` reports *runtime data* freshness (§10.4). It does not read this ledger, and the ledger does not claim to know runtime state. Keep the two separate.

## 21. Decisions that must be recorded, not left implicit

Create short ADRs under `docs/decisions/` for:

- exact archive request mechanism and why browser automation is or is not needed (A3);
- canonical bill identifier rules, originating-chamber prefix semantics, and handling of malformed identifiers (A5);
- the normalized status vocabulary, finalized only after the full vocabulary sweep (A9);
- document identity and canonicalization rules, and what constitutes a new version versus a new document (A11, §9.2);
- public document republication versus official-link-only policy, and what happens to already-stored bytes if republication is refused (A14);
- retention policy sign-off, including the decision never to auto-prune document versions;
- selected type checker and parser library;
- scheduler implementation, advisory-lock keys for scrape versus backfill, and queue leasing parameters;
- search index ownership: application-managed versus trigger-managed `search_units`;
- embedding model, dimension, license, multilingual evaluation, and operating cost;
- RAG provider/data-retention policy;
- alert delivery mechanism given there is no CI (anomaly table plus `make doctor` plus `/status`, and whether any push channel is added);
- production hostname and hosting/backup arrangement, including where blob backups live.

Unknown values do not block scaffolding. Use safe defaults and feature flags, but do not fake a deployment domain, contact address, crawl permission, rights determination, or model choice.

## 22. Requirement-to-evidence matrix

Status and evidence links live in `docs/status.md`; this table defines what counts as evidence.

| Requirement | Evidence required at completion |
| --- | --- |
| Scrape Parliament bills | Dated upstream notes, robots result and hash, fixtures, successful reviewed full run, stored source links |
| Both chambers and archive | Run counts plus test/data examples from current/archive for `dr` and `dn`; all coverage targets healthy |
| Versioned bill downloads | A document with two or more versions, both blobs present, both extractions readable, bill page showing both with distinct retrieval dates; the §18 versioning suite passing |
| Change tracking | `record_changes` history for a real bill, a `/changes` or per-bill history view, and a second identical run writing zero rows |
| Reprocessing | `make reparse --dry-run` output showing zero changes at the current parser version, and a recorded `backfill_jobs` row from a real bump |
| Freshness and coverage | `/status` output plus a demonstrated stale-target alert |
| Public searchable webpage | External HTTPS URL and manual/API checks for browse, search, filters, detail, mobile/no-JS |
| Python | `pyproject.toml`, code under `src/`, supported-version tests |
| `uv` | committed `uv.lock`; locked setup/test/container build |
| Semantic search | feature-flagged hybrid retrieval, vector migration/index, model metadata, evaluation evidence |
| RAG | cited-answer/no-answer/provider-outage tests, version-pinned citations, retrieval evaluation, kill switch |
| JSON-LD | page output, parser/escaping tests, representative validation |
| Docker deployment | non-root `Dockerfile`, healthy fresh `compose.yaml` rehearsal, persistent data |
| Makefile | documented targets execute the development and operations gates |
| No GitHub CI | repository audit confirms no `.github/workflows`; manual gate log in `docs/status.md` |
| Operable public service | database and blob backup/restore drill, `verify-storage` clean, external TLS check, health/freshness monitoring, `make doctor` clean |

## 23. First implementer checklist

- [ ] Commit this handoff as the baseline specification.
- [ ] Create `docs/status.md` with the §20 sections before writing application code.
- [ ] Complete the upstream discovery spike without disabling TLS verification, and resolve or explicitly defer every §4 assumption it touches.
- [ ] Record crawl permission, `robots.txt` hash, and document republication policy.
- [ ] Scaffold Python/uv, replace the `main.py` skeleton, and commit the generated lockfile.
- [ ] Land the database contract, including `document_versions`, and fixtures before parallel parser/web work.
- [ ] Build fixture-mode ingestion, including a changed-bytes fixture that exercises versioning, before any full live crawl.
- [ ] Prove replay works on stored snapshots before trusting the parser in production.
- [ ] Deliver lexical search and public bill pages before enabling semantic/RAG features.
- [ ] Rehearse deployment from empty volumes, including a blob restore, and verify externally.
- [ ] Update `docs/status.md` and the §22 evidence at release time.

## 24. Reference snapshot

These links informed the handoff and should be rechecked because upstream pages and tool documentation evolve:

- [Parliament of Malaysia — Dewan Rakyat bills](https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr)
- [Parliament of Malaysia — Dewan Negara bills](https://www.parlimen.gov.my/bills-dewan-negara.html?lang=bm&uweb=dn)
- [Parliament of Malaysia — Dewan Rakyat archive](https://www.parlimen.gov.my/bills-dewan-rakyat.html?arkib=yes&lang=bm&uweb=dr)
- [Parliament of Malaysia — Dewan Negara archive](https://www.parlimen.gov.my/bills-dewan-negara.html?arkib=yes&lang=bm&uweb=dn)
- [Schema.org — Legislation](https://schema.org/Legislation)
- [uv — using uv in Docker](https://docs.astral.sh/uv/guides/integration/docker/)
- [uv — locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
- [pgvector-python — SQLAlchemy integration](https://github.com/pgvector/pgvector-python#sqlalchemy)
- [PostgreSQL — text search limitations](https://www.postgresql.org/docs/current/textsearch-limitations.html) (the `tsvector` size limit behind §12.1)

## 25. Document changelog

### 25.1 Versions

| Version | Date | Summary |
| --- | --- | --- |
| 1.0 | 2026-08-16 | Initial handoff (staged, uncommitted). |
| 1.1 | 2026-08-16 | Added versioned document downloading (§9), data change tracking (§10), project tracking (§20), a glossary (§3) and assumption register (§4); corrected the defects in §25.2. |
| 1.2 | 2026-08-17 | Resolved document-version hash uniqueness conflict: rollback observations create monotonic rows sharing an existing blob (ADR-005). |
| 1.3 | 2026-08-18 | Recorded refuted assumptions A2 (as stated) and A13, and the A9 passage-phrase correction, against dated evidence in `docs/upstream.md` (§25.4). No contract changes. |

### 25.2 Defects corrected in 1.1

These were not omissions of detail; each one would have caused data loss or an unimplementable requirement.

1. **Documents were single-versioned.** `sha256`, `etag`, `extracted_text`, and `retrieved_at` lived on the document row, so a republished PDF overwrote the previous record — in a project whose stated purpose is preservation. Split into `documents` + `document_versions` + `document_extractions` (§8, §9).
2. **`documents.source_url` was globally unique**, making it impossible for one PDF to be linked from two bills or two chambers. Replaced by document identity plus a `bill_documents` link table.
3. **Chunks referenced mutable document text**, so a document update would silently invalidate every citation pointing at it. Chunks now hang off an immutable extraction of an immutable version.
4. **Embeddings were a nullable column on chunks**, making a model migration a destructive in-place mutation. Moved to `chunk_embeddings` keyed by model.
5. **No third reading in the status vocabulary**, despite a three-reading legislature; also no `lapsed`, `defeated`, `tabled`, or `committee`.
6. **Full document text in one weighted `tsvector` per bill** would exceed PostgreSQL's ~1 MB `tsvector` limit on long bills and rewrite a huge row on every change. Replaced by per-unit search rows (§12.1).
7. **"Queue allowlisted documents" with no queue defined** — no states, retries, backoff, leasing, or dead letter. Added `fetch_queue` (§8).
8. **"Mark absence as an observation" with nowhere to record it.** Added `presence_observations` and absence-streak fields (§8, §10.3).
9. **Date parsing accepted only `DD/MM/YYYY`**, while the document's own reconnaissance quotes a date *range* in a single cell and Malay month names are likely. Expanded in §11.5 with explicit failure behaviour.
10. **Snapshots were stored with no way to reuse them.** Added replay and the four backfill jobs (§9.6), which is the entire justification for storing them.
11. **No crawl budget, resumption, or circuit breaker**, so a large archive crawl had no defined bound and a failing upstream would be ground against.
12. **No manual-correction mechanism**, so any operator fix would be silently reverted by the next scrape. Added `field_overrides`.
13. **Alerts with no destination**, in a project that forbids CI. Added the `anomalies` table, `/status`, and `make doctor` as the gate.
14. **Freshness defined as a single site-wide timestamp**, which would let a healthy current-listing crawl mask a broken archive crawl. Replaced by per-target coverage.
15. **Slugs promised to be stable but had no alias mechanism**, so correcting an identifier bug would break published URLs.
16. **Time-field vocabulary was undefined** (`last_seen_at` versus `last_checked_at` versus `retrieved_at`), making "last checked" unimplementable and untestable. Defined in §3.
17. **Blob storage layout was unspecified**, and the backup runbook covered PostgreSQL only — losing the archive on any host failure. Added §8 `blobs`, §16.4 retention, and blob backup/restore.
18. **Reconnaissance claims were presented as evidence** without confidence or verification status. Moved into the §4 register.


### 25.2.1 Defect corrected in 1.2

1. **Rollback versions contradicted content-hash uniqueness.** Section 9.3 requires an A-B-A rollback to create version 3 pointing at the existing A blob, while section 8 prohibited two rows with the same document and hash. ADR-005 removes that uniqueness constraint while preserving no-op behavior for bytes identical to the current version.

### 25.4 Corrections recorded in 1.3

These record upstream facts observed on 2026-08-18 (dated evidence in `docs/upstream.md`) that contradict this document's reconnaissance. They correct the §4 register and §5 observations; no contract in §8–§14 changes, because the model already covered the observed behaviour.

1. **A13 refuted: no robots.txt is published.** `https://www.parlimen.gov.my/robots.txt` returns HTTP 404. Section 4's assumption that a policy *permits* crawling is not merely unverified — there is no policy to read. Consequences: preflight's `robots_changed` comparison has no baseline hash; a missing policy is itself an observation, so each run records a `robots_absent` warning and crawling proceeds only under an explicit recorded decision (2026-08-18: RFC 9309 treats an absent robots.txt as unrestricted, recorded in the manual gate log). If a robots.txt appears later, the first hash stored becomes the baseline for §11.2 step 2 and any restriction in it must be obeyed immediately.
2. **A2 refuted as stated: the visible listing has exactly four columns.** The current listings expose only `Kod`, `Tahun`, `Tajuk`, and `Status`; there is no presenter column and no reading-date columns. Readings, presenter, passage, and referral data live in a hidden `<div>` containing a nested `<table>` inside the status cell. Two parser consequences are now normative for any implementation: table nesting must be tracked (a flattening parser marks every row malformed), and the hidden box must not contribute to the cell's visible text. This is a reconnaissance correction, not a contract change — §8's event and chamber-record model is exactly what this shape requires.
3. **A9 correction: the published passage phrase is `Lulus`, not `Diluluskan`.** Only one of the four observed status phrases matched this document's pre-live mapping, which is precisely why A9 forbids designing the status vocabulary from a handful of assumed rows. The observed set and its mapping are recorded in `docs/upstream.md`; the full vocabulary remains open pending the complete sweep (archive, Dewan Negara, English).

### 25.5 Known gaps deliberately left open

- Whether a revised bill appears at the same URL or a new one (A11) is unresolved; §9.2 handles both, but the archive discovery spike must settle which is common before effort is spent on `document_relations` heuristics.
- Corpus size and storage growth (A12) are unmeasured; backup sizing in §16.5 is provisional until the first full crawl.
- The status vocabulary in §8 is provisional pending the full sweep (A9) and will change.
- Document diffing beyond "these versions differ" is out of scope for Release 1 and has no design here.
- Sitting-calendar-aware scheduling is suggested, not specified.
