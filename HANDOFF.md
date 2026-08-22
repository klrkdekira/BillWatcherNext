# BillWatcherNext implementation handoff

Document version: 1.13 — 2026-08-22 (Asia/Kuala_Lumpur). See §25 for the changelog and §0 for how to amend this document.  
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

### Release 4: legislation pipeline, Stage L1

Release 4 reads what the stored documents *say*, rather than what Parliament published about
them. It is specified in full in §26 and deliberately scoped to Stage L1 — a layout-aware
structural reading of the existing bills corpus, validated by Gate L1 against each document's own
Arrangement of Sections. Stages L2–L6 (Akoma Ntoso, amendment extraction, consolidation, ELI) are
specified there and blocked on decisions no code can make (§26.7).

- Every current, accepted document version has a structural reading, recorded additively and
  replayable offline from stored bytes at a named extractor and structure version.
- Gate L1's verdict is stored per document together with both trees it compared; a reading that
  fails is preserved for review and is never promoted.
- A parser regression cannot withdraw a reading that passed.
- Scans are recorded as `no_text` and are distinguishable from documents that legitimately have
  no contents page.
- The corpus-wide Gate L1 pass rate is measured against the real stored PDFs and recorded in the
  `docs/status.md` gate log.

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
| A15 | Every Malaysian federal Act and bill opens with an Arrangement of Sections or of Clauses that matches its body, making Gate L1 a valid oracle. | Medium | Measure the `no_arrangement` and pass rates over the real stored corpus (§26.7, §26.8). | Gate L1's validity as a check, §26.3 |
| A16 | `lom.agc.gov.my` can be crawled under a recordable policy, and its reprints state the date to which amendments are incorporated, making Gate L3 possible. | Low | TLS and terms-of-use are read (2026-08-20, `docs/upstream.md`); `robots.txt` returns an unexplained 500 rather than a clean absence; reprint dating convention is still unconfirmed — no listing or document page has been fetched. | Stages L3-L4, Gate L3 |

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
│   ├── version.py          # PARSER_VERSION, NORMALIZER_VERSION, EXTRACTOR_VERSION,
│   │                       # LAYOUT_EXTRACTOR_VERSION, STRUCTURE_VERSION, CHUNKER_VERSION
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   ├── cli.py
│   ├── logging.py
│   ├── domain/
│   ├── storage/
│   │   ├── blobs.py        # content-addressed put/get/verify; no business logic
│   │   └── audit_tree.py   # audit-tree paths, sidecar serialization (§27)
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
│   ├── mineru/              # MinerU vision-language markdown reading (§27.7, ADR-020)
│   │   ├── render.py       # PDF page -> image (pypdfium2)
│   │   ├── client.py       # PageBlockExtractor protocol + vendor client wrapper
│   │   ├── markdown.py     # ContentBlock list -> markdown
│   │   └── service.py      # render + extract + assemble, one document at a time
│   ├── jobs/
│   │   ├── audit_rebuild.py  # verify/rebuild the document tier of the audit tree (§27.4)
│   │   ├── replay.py       # re-parse stored snapshots
│   │   ├── reextract.py
│   │   ├── mineru_extract.py  # the MinerU reading, as a local file artifact only (§27.7)
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
├── var/                    # ignored local snapshots only
└── data/                   # ignored audit tree (§27); default AUDIT_TREE_ROOT in development
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

### `document_structures` — R4 (§26.3)

- `id`, `document_version_id`, `extractor_name`, `extractor_version`, `structure_version`, `unit` (`section` or `clause`), `language`.
- `gate_status` (`passed`, `mismatch`, `no_arrangement`, `empty_body`, `no_text`, `failed`), `arrangement_count`, `body_count`, `difference_count`, `blocking_count`, `detail_json`, `page_count`, `error`.
- `is_current` boolean, `created_at`, `duration_ms`.
- Unique on `(document_version_id, extractor_name, extractor_version, structure_version)`.

A structural reading, additive exactly like `document_extractions`, and deliberately not stored in
that table: two shipped code paths (`persist_current_extraction`'s demotion and retention's
pruning) assume one writer for `document_extractions`, and a second tier would trip both. Only
`is_current = true` may be built on; a reading Gate L1 fails is kept for review and never promoted.

### `provision_nodes` — R4 (§26.3)

- `id`, `structure_id`, `source` (`arrangement` or `body`), `parent_id` (self-referential), `node_type`, `num`, `heading`, `eid`, `ordinal`, `depth`, `page_from`.
- Unique on `(structure_id, source, eid)`.

Both the Arrangement-of-Sections tree and the body tree are stored, because Gate L1's verdict is
reviewable only if what it compared is on the record. `wid` is deliberately absent — nothing in a
single document establishes the identifier a provision carried when first created, which is Stage
L2's job, once a work's expressions can be related to one another.

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

A fifth backfill, `restructure` (§26.3), has the same shape: offline, dry-run by default, and it records a `backfill_jobs` row. It differs in one way — a document that fails Gate L1 is kept and marked not current rather than being reprocessed to a single output, because the point of the backfill is the verdict, not just the derived text.

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
- `make completeness` reports candidate holes in a chamber-year's bill-number sequence, restricted to years whose archive coverage target is closed (`expected_interval_hours == 0`) — the one signal already in this model meaning "this year's listing has been read in full." It is a heuristic for a human to check against the archive, not an enforced gate: no assumption register entry claims Parliament numbers bills with no gaps at all, and a partially-crawled or still-open year is deliberately excluded, since a hole there is just a bill not yet fetched.

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
| `structure_gate_failure_spike` | warn | Gate L1 blocking-failure rate above baseline (§26.3) |
| `audit_tree_divergence` | critical | A tree artifact, its sidecar, and the database disagree (§27.4) |
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
4. Discover pagination/archive requests from the confirmed upstream contract; bound page count and stop on repeated content hashes. For this site's archive the confirmed contract is a year index rather than pagination, so the bound is on year count and each year is a target of its own (ADR-014, §25.6).
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
- A full archive crawl is a separate, explicitly triggered mode with its own, larger budget. "Larger" is not a nicety: the archive introduces its whole back catalogue of documents in one run, and a document budget spent mid-run rolls the run's publication back, so an archive crawl under the incremental budget publishes nothing while appearing to have read everything (§25.6).
- Retrying is part of resumption. A crawl long enough to matter will have a connection closed under it; an unanswered GET is idempotent and must be retried before the target is called unreachable.

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
AUDIT_TREE_ROOT=/var/lib/billwatcher/audit
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
MINERU_ENABLED=false
MINERU_BASE_URL=
PIPELINE_DATA_ROOT=/var/lib/billwatcher/pipeline-data
AKN_LLM_ENABLED=false
AKN_LLM_BASE_URL=
AKN_LLM_MODEL_ID=
AKN_GATE_MIN_TEXT_COVERAGE=0.95
SERVE_LEGISLATION_CORPUS=false
LEGISLATION_PUBLICATION_MODE=metadata
LEGISLATION_CORPUS_RIGHTS_CONFIRMED=false
```

The application should reject placeholder secrets in production mode. It must also **refuse to
boot** rather than warn when a publication flag is set without its recorded rights confirmation:
`SERVE_ARCHIVED_DOCUMENTS` needs `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED` (ADR-013, ADR-004),
`SERVE_LEGISLATION_CORPUS` needs `LEGISLATION_CORPUS_RIGHTS_CONFIRMED`, and
`LEGISLATION_PUBLICATION_MODE=full` needs both (§28.10, ADR-027). Development is ungated, because a
refusal there would only teach an operator to work around it.

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
| `scrape` | One incremental run: the explicit aggregate of `fetch-listings` → `parse-listings` → `fetch-documents` (§27.1) |
| `scrape-full` | Explicit full archive run |
| `fetch-listings` | Step S1: fetch listing/archive pages, snapshot them, write `01-listings/` to the audit tree (§27) |
| `parse-listings` | Step S2: parse stored snapshots into bills/records/events, write `02-bills/`; offline |
| `fetch-documents` | Step S3: drain the document queue, write raw PDFs + sidecars to `03-documents/` |
| `pipeline` | Explicit aggregate S1→S6 in order; live steps keep their approval gate (§27.1) |
| `verify-audit` | Re-hash every tree artifact against its sidecar and the database; non-zero on divergence (§27.4) |
| `audit-rebuild` | Regenerate the whole audit tree from the database and blob store; byte-identical when already correct (§27.4) |
| `pipeline-*` | The file-first pipeline's steps, one target each, specified in §28.2 and nowhere else. A separate pipeline with its own store; its live steps keep the same `SCRAPE_ENABLED`/`--approve-live` gate the targets above use |
| `status` | Print run history, coverage/freshness, queue depth, pipeline versions |
| `completeness` | Report candidate bill-numbering gaps in closed archive years; a heuristic for review, never a gate (§10.4) |
| `doctor` | Evaluate anomalies and invariants; non-zero exit on unresolved critical findings |
| `reparse` | Replay stored snapshots at the current parser version; `--dry-run` default |
| `reextract` | Re-extract document versions below the current extractor version; `--dry-run` default |
| `mineru-extract` | A second, MinerU vision-language markdown reading, written to `04-text/`; `--dry-run` default; live, needs `MINERU_ENABLED`/`MINERU_BASE_URL` (§27.7) |
| `restructure` | Read Gate L1 structure from stored bytes at the current versions; `--dry-run` default (§26.3) |
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
- The audit tree (§27) is a derived projection and is **not** part of the backup contract: `make audit-rebuild` regenerates it from the database and blob store, and deleting it loses nothing they cannot regenerate.
- `PIPELINE_DATA_ROOT` (§28) is the opposite case and must not be confused with it: it is the *record* for the file-first pipeline, not a projection of anything, so nothing can rebuild it. Losing it means re-crawling and re-extracting. Whether it is backed up is a deployment decision; treating it as derived because it looks like a directory tree is a mistake.

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

### Package I — legislation Stage L1

Inputs: §26.1–§26.3, Package C's stored document versions.  
Outputs: `billwatcher.legislation` (layout reading, structural vocabulary, both tree parsers, the
Gate L1 comparator), `document_structures` and `provision_nodes` with their migration, the
`restructure` backfill and Make target, `structure_gate_failure_spike`, ADR-016 and ADR-017.  
Acceptance: a marginal note is never spliced into the provision sharing its baseline; a dropped
section fails Gate L1 and names what is missing; a bill reads as clauses and an Act as sections;
a schedule does not renumber the Act; a failing re-read does not withdraw a reading that passed;
the corpus-wide pass rate is measured against the real stored PDFs and recorded.

### Package J — legislation Stages L2 onward

Inputs: Package I green on the real corpus, **and** the §26.7 decisions concluded.  
Outputs: as specified in §26.4 and §26.5.  
Acceptance: per gate, §26.6. This package must not start before §26.7 concludes; it is listed so
the sequence is visible, not so it can be picked up.

### Package K — auditable step pipeline

Inputs: §27, ADR-019, Package C's ingestion service and stored corpus.  
Outputs: the S1–S3 step decomposition of the scrape CLI with `scrape` kept as their aggregate; the
audit-tree writer and deterministic sidecar serializer (`storage/audit_tree.py`); tree output wired
into S4–S7's existing jobs; per-run manifests; `verify-audit` and `audit-rebuild` with their Make
targets and the `pipeline` aggregate; the `audit_tree_divergence` anomaly kind and its test;
`AUDIT_TREE_ROOT` configuration; `docs/operations.md` and `docs/data-model.md` updated.  
Acceptance: §27.6 in full — each step runs alone by its target and leaves a manifest; a
fixture-mode `make pipeline` populates the tree with hash-matching sidecars and a second run
writes nothing; `audit-rebuild` is byte-identical over a correct tree; `verify-audit` is clean and
catches a single tampered byte; the stored corpus is materialised where the blob store lives, with
counts recorded in the gate log.

### Package L — file-first pipeline

Inputs: §28, ADR-021 through ADR-028. Depends on nothing in Packages A–K: it shares
`billwatcher.scraper`'s pure fetch/parse/normalise modules and `storage.audit_tree`'s deterministic
writers, and imports no database model, session, or job.  
Outputs: `billwatcher.pipeline` — the `PipelineStore` protocol and its `FileStore` implementation;
steps 1–5 plus `import-markdown` and `verify` with their CLI commands and `pipeline-*` Make targets;
`pipeline.frbr` as the single owner of published IRIs; Gate P1 and Akoma Ntoso schema validation
against a vendored XSD; per-artifact provenance and per-run manifests; `pipeline.redact` and the four
publication settings of §28.10; ADR-024 through ADR-028.  
Acceptance: every step runs alone by its command and leaves a manifest; a second run over an
unchanged store writes **nothing**, proven by hash *and* mtime; a rendered document validates against
the vendored schema, and a document that fails Gate P1 leaves a verdict and a rejected render but no
promoted XML; a bill record missing a chamber, year, number or language produces no IRI at all; a
malformed request segment resolves to a 404 rather than a filesystem path; `verify` reports a tampered
byte, a stale artifact and an unexpected file; production refuses to boot with either publication flag
set and its rights confirmation absent. Not in the acceptance list, and deliberately: a corpus-wide
Gate P1 pass rate, which needs the corpus access §26.7 blocks.

### Package M — public static cache, then the step-4 split (current priority)

Inputs: Package L as built, §28.12 (ADR-029), §28.5 as amended (ADR-030), the A14 rights
determination of 2026-08-22.  
Outputs, in this order: **first** the export step — `pipeline.export`, the
`export-static` CLI command and `pipeline-export-static` Make target, `PIPELINE_EXPORT_ROOT` in
§16.2, redaction applied at the export boundary, rights flags enforced at command level, index and
checksums; **only then** the tooling — the ADR-030 split of step 4
(`document.structure.json` + provenance, Gate P1 relocated, the anchored extractor contract,
`render-akn` deterministic), and after that the §28.10 served surface and a database/object-store
`PipelineStore`.  
Acceptance, cache half: an export over a store with one gate-passing and one rejected document
contains exactly the passing one; a re-export over an unchanged store writes nothing, proven by
hash and mtime; the export command refuses without `LEGISLATION_CORPUS_RIGHTS_CONFIRMED` (and
refuses `full` without `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED`); every exported file is named in
`checksums.sha256` and verifies; a metadata-mode export contains no provision text, checked by an
independent reader (`redact.contains_provision_text`), not by the redactor agreeing with itself.
Acceptance, split half: per ADR-030 — a renderer version bump regenerates every `document.akn.xml`
with zero extractor calls; a prompt or model change regenerates every structure; a wrong anchor
fails Gate P1 rather than publishing mis-sliced text.

### Integration sequence

```text
A scaffold ──────┬──────────────> E deployment
                 ├─> D web/search ─> F JSON-LD
B model/discovery┼─> C scraper ─────> E deployment
                 └─> D web/search
C scraper ────────────────> K audit pipeline (§27)
C extraction + D search ─> G semantic ─> H RAG
C extraction ─────────────> I Stage L1 ─> J Stages L2+ (blocked, §26.7)
(nothing) ────────────────> L file-first pipeline (§28) ─> M public cache, then tooling (current priority, §28.12)
```

Package L hangs off nothing on purpose. It is a parallel pipeline, not a stage of the one above, and
the day it needs a row from the database is the day it has stopped being what §28.1 describes.

The integrator owns migration conflict resolution, lockfile changes, the acceptance walkthrough, `docs/status.md` reconciliation, and updating this handoff when an upstream assumption changes.

## 20. Project status tracking

Implementation progress is tracked in `docs/status.md`, created by Package A and updated in the same change as the work it describes. An agent that lands code without updating the ledger has not finished the task.

### Required sections of `docs/status.md`

**Package ledger.** One row per package A–L:

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
- production hostname and hosting/backup arrangement, including where blob backups live;
- the layout-aware PDF reader for §26.1, measured against the marginal-note case, and the
  dependency cost it carries (ADR-016);
- what Gate L1 blocks on versus merely reports, and why the heading half is not blocking
  (ADR-017);
- whether the legislation corpus is served or statically built, and how mirrorability is
  delivered instead (ADR-018);
- crawl policy and rights for `lom.agc.gov.my`, as a publisher distinct from parlimen.gov.my,
  and separately for `lawnet.com.my`, which is a paid subscription service governed by a
  contract rather than by a public policy (§26.7);
- legal sign-off on the consolidation methodology and on the disclaimers that accompany a
  consolidated statement of law, which is a higher bar than the A14 rights question (§26.7);
- the scheme of every published identifier, since an IRI is permanent and a change to one is a
  change to every citation of it (§28.7, ADR-024);
- what a gate over a *model's* output blocks on, which of its checks are exact, and why the one
  threshold is configuration rather than a constant (§28.8, ADR-025);
- what makes a derived artifact stale, since a wrong answer there leaves a corpus that silently
  disagrees with the code claiming to have produced it (§28.9, ADR-026);
- what is published from a corpus whose rights question is open, which flags gate it, and any
  fragment of source text the metadata-only surface deliberately keeps — **including the bound on
  that fragment**, since "we publish only bounded excerpts" is an empty statement until something
  enforces the bound (§28.10, ADR-027).

Unknown values do not block scaffolding. Use safe defaults and feature flags, but do not fake a deployment domain, contact address, crawl permission, rights determination, or model choice.

## 22. Requirement-to-evidence matrix

Status and evidence links live in `docs/status.md`; this table defines what counts as evidence.

| Requirement | Evidence required at completion |
| --- | --- |
| Scrape Parliament bills | Dated upstream notes, robots result and hash, fixtures, successful reviewed full run, stored source links |
| Both chambers and archive | Run counts plus test/data examples from current/archive for `dr` and `dn`; all coverage targets healthy, including one per archived year |
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
| Legislation Stage L1 | Gate L1 fixtures covering the marginal-note splice, a dropped section, a bill's clauses, a schedule's numbering, and an overlapping letter list; migration to head on PostgreSQL; a measured corpus-wide pass rate in the gate log |
| Layout extractor choice | A dated measurement of each candidate against the same-baseline marginal note, and a re-run dependency audit recording the packages added (ADR-016) |
| Published identifiers | A Work resolving with both language Expressions and every manifestation extension; a malformed request segment answering 404; a bill record missing a chamber, year, number or language producing no IRI at all (§28.7) |
| Gate P1 and schema validity | A rendered document validating against the vendored OASIS XSD; a document with a duplicate eId, a missing number, a broken sequence and low coverage each rejected with its verdict and rejected render kept; a measured corpus-wide pass rate and finding distribution in the gate log (§28.8) |
| Provenance and idempotence | A second run over an unchanged store writing nothing, proven by hash and mtime; a code-version bump regenerating exactly the affected artifact; `pipeline verify` reporting a tampered byte, a stale artifact and an unexpected file (§28.9) |
| Corpus publication | Production refusing to boot with either publication flag set and its rights confirmation absent; every corpus path 404 while serving is off; a metadata-mode response carrying no provision text, checked by a reader independent of the redactor; and a provision whose body text runs in after its number publishing no more of that text than the heading bound allows (§28.10) |
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
| 1.4 | 2026-08-18 | Recorded the archive request contract as observed (§25.6): the archive is a year-indexed XML tree, not the `carian.html` search form. Then downloaded the whole document corpus and read every policy page the site publishes. Closes A3, A7, A8, A9, A10 and A12; A5 and A11 partially; A13's reading is now complete. No contract in §8-§14 changes; §11.3 step 4, §11.4 and §11.7 gain the observed shape. |
| 1.5 | 2026-08-19 | Incorporated the Malaysian legislation pipeline as §26 and Release 4, scoped to Stage L1 over the existing bills corpus. Adds `document_structures` and `provision_nodes` (migration 0004), Gate L1, the `structure_gate_failure_spike` anomaly kind, packages I and J, and ADR-016/017/018. Rejects the source specification's static-build publication architecture while adopting its data model unchanged (§25.7). |
| 1.6 | 2026-08-21 | Added the auditable step pipeline and audit tree as §27 (ADR-019), at the commissioner's direction and prioritised ahead of all other open work: every pipeline step is one Make target, and every step materialises a human-legible local directory holding the raw downloaded PDF beside a JSON sidecar carrying source, URL, language, and full provenance — a mandatory projection of the database, byte-reproducible from it. Adds `fetch-listings`/`parse-listings`/`fetch-documents`/`pipeline`/`verify-audit`/`audit-rebuild` to §16.3, `AUDIT_TREE_ROOT` to §16.2, the `audit_tree_divergence` anomaly kind to §10.5, and Package K to §19 (§25.8). |
| 1.7 | 2026-08-21 | Added `make completeness` (§10.4, §16.3): a heuristic report of candidate bill-numbering gaps within a chamber-year, restricted to closed archive coverage targets so an open or partially-crawled year cannot produce a false gap. Not a gate — no anomaly kind, no `doctor` interaction — and not a claim that Parliament numbers bills with no gaps at all; a reported gap is a pointer for a human to check against the archive. No other contract changes. |
| 1.8 | 2026-08-21 | Added §27.7, a MinerU vision-language markdown reading of stored PDFs via a hosted endpoint (`https://mineru.loqasi.io`), at the commissioner's direction. Written only as a local file artifact under `04-text/` (extending the §27.2 layout already specified, not previously built) — never into `document_extractions`, sidestepping the single-writer landmine TODO 2.4 documents (ADR-020). Adds `mineru-extract` to §16.3, `MINERU_*` settings to §16.2, and the `billwatcher.mineru` package. No schema change. |
| 1.9 | 2026-08-21 | Added §28, a parallel file-first pipeline (`billwatcher.pipeline`) built behind a `PipelineStore` interface, at the commissioner's direction: "database and object store are for later... the pipeline should work with interface of input, such as file and also from db or object store" (ADR-021). `FileStore` is the only implementation. The entire Postgres-backed system (§6-§26, Packages A-K) is left in place, untouched, dormant — nothing in the new package imports it. PDF parsing/extraction is explicitly out of scope: the operator's own vLLM endpoint handles that, separately. No existing contract changes. |
| 1.10 | 2026-08-21 | Added §28.5, a fourth pipeline step converting markdown to Akoma Ntoso (OASIS LegalDocML) XML, at the commissioner's direction ("next up for pipeline after markdown conversion is conversion to the oasis format"). Structure extraction reads with the help of a vLLM endpoint, per a follow-up direction ("should use the help of the vllm server"), behind a `MarkdownStructureExtractor` protocol; eId assignment and XML serialisation stay fully deterministic (ADR-022). Still file-only: `AKN_LLM_*` configuration added, no database or object-store code anywhere in `billwatcher.pipeline`. |
| 1.11 | 2026-08-21 | Added §28.6, a fifth pipeline step generating ELI-style JSON-LD and RDF N-Quads from the stored Akoma Ntoso XML, at the commissioner's direction ("after akn, then it should be to the semantic files such as jsonld and rfg" — read as RDF, flagged as an interpretation). Fully offline: reads `document.akn.xml` back into a tree, builds one JSON-LD graph, and derives the N-Quads from that same graph so the two representations cannot disagree (ADR-023). No database, no object store, no network or LLM call. |
| 1.12 | 2026-08-22 | Made the file-first pipeline publication-ready and recorded the four decisions it rests on: permanent FRBR identifiers built from published facts (§28.7, ADR-024), Gate P1 plus Akoma Ntoso schema validation (§28.8, ADR-025), provenance-gated regeneration with per-run manifests and `pipeline verify` (§28.9, ADR-026), and metadata-only publication redacted at the serving boundary behind two flags (§28.10, ADR-027), with step 5 rebuilt on rdflib and SHACL deferred (ADR-028). Adds `AKN_GATE_MIN_TEXT_COVERAGE`, `SERVE_LEGISLATION_CORPUS`, `LEGISLATION_PUBLICATION_MODE` and `LEGISLATION_CORPUS_RIGHTS_CONFIRMED` to §16.2, `import-markdown` and `verify` to §28.2, and Package L to §19. Withdraws the URL-hash public identifier and the `infer_unit` language default recorded in 1.10 (§25.10). |
| 1.13 | 2026-08-22 | Reordered publication and recorded two directions (§25.11). First: the file-first corpus's first publication surface is a **public static cache of files** — the dataset on its FRBR paths plus the schema/definitions, exported by a new step (§28.12, ADR-029), with backend serving, database integration, and all other tooling explicitly second; the pipeline store stays local-file only and is never committed. Second: step 4 splits into an LLM `extract-structure` step persisting `document.structure.json` (Gate P1 moves to it) and a deterministic `render-akn` step, with the extractor contract changed from re-emitting text to returning anchors (§28.5, ADR-030) — phase-two tooling, specified now so the cache and the split cannot drift apart. Package L loses "current priority" to the new Package M (§19). |

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

- Whether a revised bill appears at the same URL or a new one (A11) is unresolved; §9.2 handles both. The archive sweep could not settle it: it needs the same document observed twice over time, not once thoroughly. No effort has been spent on `document_relations` heuristics.
- ~~Corpus size and storage growth (A12) are unmeasured~~ — measured on 2026-08-18 (§25.6), listings and documents both. The whole document corpus is 1,264 stored PDFs, 27,575 pages, **0.24 GB**, so §16.5's backup sizing is no longer provisional. Growth is bounded by sitting frequency: about 60 bills per chamber per year at ~270 KB each.
- ~~The status vocabulary in §8 is provisional pending the full sweep (A9)~~ — swept on 2026-08-18 across the whole published corpus. It gained `withdrawn` and `third_read` mappings for archive-only phrases; the §8 vocabulary itself needed no new values.
- Document diffing beyond "these versions differ" is out of scope for Release 1 and has no design here.
- Sitting-calendar-aware scheduling is suggested, not specified.
- The `D.N.` half of the identifier rule (A5) has never been exercised: no `D.N.` code exists anywhere in 35 years of archive.

### 25.6 Corrections recorded in 1.4

These record upstream facts observed on 2026-08-18 from a full sweep of the archive tree — 67 XML documents, both chambers, 1990 to 2024 — with dated evidence in `docs/upstream.md` and the decision in ADR-014. No contract in §8-§14 changes: the model already covered the observed behaviour, which is the second time that has been true and is the strongest evidence yet that §8's bill/chamber/event split is right.

1. **The archive is a year-indexed XML tree, not the `carian.html` search form.** §5 and ADR-011 inferred the mechanism from the `?arkib=yes` page's markup without issuing the request. Issuing it shows that `carian.html` is a full-text search over document *pages* — it returns `Halaman 48` hits with PDF fragment links and no bill code, status, or date anywhere — while the archived listing is a `dhtmlXTree` whose XML the same page loads from `&arkib=yes&ajx=0` (an index of years) and `&arkib=yes&ajx=1&id=0_<year>`. Consequences now normative: the archive is **one target per year** rather than one paginated target, so §11.3 step 4's "bound page count" becomes "bound year count"; a cookieless request to `carian.html` is answered with a `302` and a session cookie, and the fetcher must keep cookies for the run for `lang=en` to work at all; and because the tree declares no header row, §11.6's structure fingerprint has nothing to hash — for the archive it is the set of detail labels the parser does *not* recognise, which is stable while the vocabulary holds and changes the moment a label is renamed.

2. **A8 answered: the archive is partitioned by calendar year**, not by parliamentary term or session. 34 year nodes for the Dewan Rakyat, 33 for the Dewan Negara, both 1990-2024, with gaps.

3. **A9 closed, and three phrases exist only in the archive.** `Ditarik Balik`, `Tolak`, and `Bacaan Kali Kedua dan Ketiga` never appear on a current listing, so 60 archived rows — including every withdrawn bill in 35 years — would have stored `unknown`. This is the second time A9's warning has been vindicated: designing the vocabulary from what is currently visible is not conservative, it is wrong.

4. **A7 closed: every one of 2,245 archived dates is `DD/MM/YYYY`.** No Malay month name and no date range has ever been observed, in either the current listings or 35 years of archive. §11.5's tolerance for both is retained because it costs nothing, but it is not upstream behaviour we have seen. Thirteen readings are dated `30/11/-0001`, a zero date leaking out of the upstream database; §11.5's "an unparseable date raises an anomaly and leaves the date NULL" is what saves those rows from becoming plausible fiction.

5. **A12 measured**: 2,130 archived rows, 1,202 distinct identifiers, 2,067 document links, ~4 MB of XML. Published: 1,269 bills spanning 1990-2026, 2,256 chamber records, 4,861 events, 1,295 documents queued.

6. **§11.7's "own, larger budget" for the archive crawl is load-bearing, not advisory.** The archive introduces ~2,000 documents at once, and §11.7's rule that a spent budget ends the run `partial` combines with §11.6's rollback to mean the run publishes *nothing*. Without a separate archive budget the archive crawl silently accomplishes nothing while reporting that it read everything.

7. **One bill's title is published in several forms, and §10.1 needs an equivalence rule.** `RUU X` and `Rang Undang-Undang X` are one title; the site uses both, and eight archived bills carry one form in one chamber's node and the other in the other's. Treating them as different values rewrites the title on every crawl and appends two changes to the history for ever, which breaks §22's "a second identical run writes zero rows". Sixteen identifiers are affected. Three genuinely differ — including **D.R.11/2013, where the two chambers publish two entirely different bills under one code** — and those raise `duplicate_identifier_conflict` rather than oscillating.

8. **Anomalies must key on the upstream document, not the snapshot of it.** §8's "deduplicate by kind plus entity" is right, but a snapshot is a new entity every run, so a permanent upstream defect added one anomaly per crawl and turned §10.5's work list into a log.

9. **§10.5's minimum set needs two more kinds for this shape**: `unmapped_detail_label` and `malformed_row`. The tree can fail in two ways a column-shaped listing cannot — a detail label we do not understand, and a node whose text does not match the grammar — and reporting either as an identifier problem sends an operator to the wrong place.

10. **A gate nobody can clear is a gate everybody ignores.** §25.2 defect 13 added the anomalies table and `make doctor` as the alert channel, and the schema has had `acknowledged_at` and `resolved_at` from the start, but nothing ever wrote them: the first genuine critical anomaly would have left `make doctor` red permanently. `acknowledge-anomaly` and `resolve-anomaly` close that, and both demand a name and a reason.

11. **Politeness must live in the fetcher, not in each caller.** §5 sets a minimum delay and §11.7 bounds a run, but nothing said *where* the delay is enforced, so it was written into the listing orchestrator and simply absent from the document worker. Draining the 1,292-document queue would have fetched PDFs back to back against a government site. A per-caller delay is a rule that a new caller can forget; a per-request one in the fetcher cannot be.

12. **Validating content instead of trusting a status code is load-bearing, not defensive.** §11.4 step 3 requires magic-byte validation, and the corpus shows why: 31 archived document links do not exist, and the server answers each with **HTTP 200**, `Content-Type: text/html`, and a 23-byte body reading `File does not exist (1)`. A crawler that trusted the status code would have stored 31 HTML error pages as bills.

13. **A document does not have one canonical URL.** 62 sets of byte-identical documents are published at two or more URLs, normally one copy per chamber, and in the archive also under the year each chamber considered the bill. §9.2's content-hash identity collapses them to one blob linked from every bill; URL identity would have double-counted the archive. What remains unobserved is A11 as asked — after fetching all 1,295 documents, none has a second version, so no revision has been seen.

14. **Some bills are scans, and §11.4 step 7's optional OCR worker has a defined subset to serve.** 22 documents (1.7%) yield no text: 12 extract empty and 10 fail outright, concentrated in 2010, 2013 and 2018 at roughly 45 KB per page. Age does not predict it — a 1995 bill extracts cleanly. Distinguishing `empty` from `failed` from `succeeded`, which §11.4 step 5 requires, is what makes the subset addressable instead of invisible.

15. **A13 asked for a reading, and the reading is now complete.** The site publishes no robots.txt *and no terms of use*: Penafian, Dasar Privasi, Dasar Keselamatan and an FAQ are the entire policy set, none mentions crawling or reuse, and `/hakcipta.html` and `/terma-penggunaan.html` do not exist (answered, of course, with HTTP 200). The crawl decision now rests on having looked. For A14 the same absence argues the other way: "Hakcipta Terpelihara" with no licence is not permission to republish, so §6's official-link-only default holds.

16. **A containerised crawler needs outbound access, and §16.2's network split did not give it any.** The `worker` sat alone on the `internal: true` network, so it would have started, reported healthy, and failed every fetch. Live crawling had only ever been run from the host, which is why nothing caught it. Any deployment contract that isolates a database has to say explicitly which services still need egress.

17. **§7 and §16.2 specify Caddy, and this deployment does not use it.** TLS is terminated by an nginx deployed separately, so the `Caddyfile` and the `caddy` service are removed and the stack publishes one loopback origin for an external proxy (ADR-015). Two consequences the contract should carry: the response security headers must live in the **application**, because it is the only component the repository controls, and §17's caution about HSTS becomes a defaulted-off setting rather than proxy configuration. What the contract loses is certificate automation as a property of the stack, and the ability to rehearse the TLS path from the repository at all.

18. **A long crawl loses connections, and §11.7's resumption rules must cover transport failures.** The first live archive attempt died after 59 of 136 requests on a server-closed keep-alive and published nothing. Retrying an unanswered GET is safe and necessary at this length, and an archived year that still cannot be read must degrade that year alone — 66 years of closed history are not withheld because 2007 timed out.


### 25.7 Corrections and decisions recorded in 1.5

These record the incorporation of an externally supplied *Malaysian Legislation Pipeline* handoff
as §26. That document specifies a bilingual BM/EN corpus from source PDF to Akoma Ntoso and ELI
linked data, with seven quality gates. It is adopted, with three departures, each recorded as an
ADR because §0 rule 2 requires it.

1. **The publication architecture is rejected; the data model is adopted unchanged (ADR-018).**
   The source specification prescribes a static `dist/` tree with client-side SQLite/FTS5 over
   HTTP Range and edge-function content negotiation. This service is server-rendered FastAPI over
   PostgreSQL (ADR-007, ADR-012, ADR-013, ADR-015); adopting the static build would contradict
   four accepted decisions to buy mirrorability, which an N-Quads dump provides on its own. AKN
   3.0, ELI, FRBR, `eId`/`wId`, and the Gate L5 SHACL shapes are adopted exactly as specified.

2. **Gate L1 is narrowed to structure, and is per document rather than per language pair
   (ADR-017).** The source specification's "same numbers, same order, same headings, for both BM
   and EN" is two different checks with two different inputs. Heading differences are usually a
   typographic fact — AGC reprints print a section's heading as an abbreviated marginal note —
   so blocking on them would fire on almost every document and train an operator to clear the
   queue without reading it. The bilingual half is Gate L4, and is blocked on document
   classification that does not exist (§26.7).

3. **The layout reader is `pdfminer.six`, chosen by measurement rather than by the source
   specification's suggestion (ADR-016).** `pypdf`, already a dependency, cannot serve: its
   `visitor_text` callback reports the *line's* starting x rather than each run's, which splices
   a marginal note into the middle of the provision sharing its baseline, and its operand-level
   visitor reports accurate matrices but undecoded font bytes. `pdfplumber` wraps the same engine
   while adding an imaging stack this project has no use for; PyMuPDF is AGPL. The locked set
   grows by five packages and the dependency audit was re-run the same day.

Three defects in the existing codebase were confirmed while doing this, all latent rather than
live, and all recorded in `TODO.md` rather than fixed here because each changes behaviour that is
currently correct:

- `scraper/service.py`'s `persist_current_extraction` demotes **every** `is_current` extraction
  for a document version regardless of extractor name, and `jobs/retention.py` keeps two
  extractions per version without partitioning by extractor either. Both are correct while one
  extractor writes that table; both become data loss the moment a second one does — which is what
  the OCR tier will be. §26.1's reading is stored in its own tables precisely to avoid tripping
  them today.
- `documents.document_kind` and `documents.language` are written as `"unknown"` at creation and
  never updated. The corpus therefore cannot be partitioned into BM/EN pairs, which blocks Gate L4.
- `search/chunking.py`'s provision-aware splitting is inert. `_PROVISION` anchors on line starts,
  but `normalize_text` collapses newlines before the extraction is stored, so each page arrives as
  a single line and `_blocks()` returns one block per page. Chunks are page-shaped, not
  provision-shaped, which is not what §12.3 describes.

### 25.8 Changes recorded in 1.6

These record a directed contract change, not an upstream observation. On 2026-08-21 the
commissioner directed that each pipeline step be auditable, that each step be a Make target, and
that each step store its output in a local directory structure — the raw downloaded PDF beside
JSON metadata naming the source, raw file, language, and URL — and that this work be prioritised
ahead of everything else open.

1. **The pipeline's step decomposition and the audit tree are now contract, as §27.** The live
   half of the pipeline, previously fused inside `make scrape`, splits into `fetch-listings`,
   `parse-listings`, and `fetch-documents`; the offline steps keep their existing targets. Every
   step materialises its artifacts into a human-legible tree with deterministic JSON sidecars and
   per-run manifests, checked by `make verify-audit` and rebuildable by `make audit-rebuild`.
2. **The tree is a projection, and that is the recorded design decision (ADR-019).** The
   file-first alternative — tree as source of truth, database as index — was considered and
   rejected: it would discard transactional change history (§10.1), content-hash dedup evidenced
   at scale (ADR-003), and the §8 append-only invariants, and would rewrite Package C, which has
   already ingested the whole corpus. The projection delivers every directed property without
   destroying the record underneath it.
3. **Nothing in §8–§10 changes.** The database and blob store remain the record and the backup
   unit; the tree is derived, gitignored, and deliberately outside the backup contract.
4. **The sidecar's `language` and `document_kind` fields will read `"unknown"` at first**, because
   those columns are the known dead fields (§26.7, TODO 2.4). The sidecar states the record rather
   than guessing; the classification sweep backfills every sidecar via `audit-rebuild` when it
   lands.

### 25.9 Changes recorded in 1.8

Directed on 2026-08-21: parse stored bill PDFs with a hosted MinerU vision-language instance
(`https://mineru.loqasi.io`) and keep the result local-file-based, like the PDF audit tree.

1. **A second, independently versioned markdown reading is added, as §27.7.** MinerU2.5 is a
   vision-language document-parsing model; the hosted instance was confirmed (by querying
   `/v1/models`, `/version`, `/openapi.json` directly) to serve
   `opendatalab/MinerU2.5-Pro-2605-1.2B` behind a standard vLLM OpenAI-compatible API. The vendor's
   own client library, `mineru-vl-utils`, is used rather than reimplemented: its prompt templates
   and per-block-type sampling parameters are intricate enough that the maintainers explicitly
   warn against hand-rolling the API calls.
2. **Written only as a local file artifact, never into `document_extractions` (ADR-020).** The
   same single-writer landmine TODO 2.4 documents for a second extraction tier applies here
   exactly as it would to an OCR tier; this reading avoids it the way Stage L1 does, by not
   touching that table at all. `04-text/`, specified but unbuilt in §27.2, is now built.
3. **Two new permissively licensed dependencies**: `mineru-vl-utils` (Apache-2.0; base install
   only, no `vllm` extra, since this project calls a remote hosted endpoint rather than serving
   the model itself) and `pypdfium2` (BSD-3-Clause/Apache-2.0), for the same reason ADR-016 chose
   `pdfminer.six` over PyMuPDF: no AGPL dependency, no unnecessary imaging stack.
4. **The endpoint is configuration, off by default** (`MINERU_ENABLED`, `MINERU_BASE_URL`,
   optional `MINERU_MODEL_NAME`/`MINERU_API_KEY`): sending official document images to a
   third-party inference host is a data-handling decision, the same class of decision ADR-009
   made explicit for the RAG endpoint, not a default.
5. **A live smoke test against the real endpoint, run once by hand, found and fixed one real
   bug**: the vendor `MinerUClient` delegates to an inner backend-specific client at `.client`,
   and the resolved model name lives on *that* object, not on `MinerUClient` itself. No mocked
   test could have caught this, because no mocked test constructs the vendor client at all — the
   fix is now pinned by `tests/unit/test_mineru_client.py`, which fakes the vendor client's
   structural shape rather than the network. The smoke test itself is not part of the automated
   suite, mirroring this project's own `test-live` opt-in pattern for a different third party.

### 25.10 Changes recorded in 1.12

These record a body of correction rather than a new direction: the file-first pipeline of §28 was
built one step at a time and was not publishable as it stood. Nine defects were fixed; five of them
change this document's contract, and those five are here. The full findings, with the direct-run
evidence, are in the `docs/status.md` gate log for 2026-08-22.

1. **The public identifier was withdrawn and replaced (§28.7, ADR-024).** §28.4's URL-hash document
   key remains correct as a *store* key and is wrong as a *published* one: 1.10 recorded FRBR URIs
   of the form `/akn/my/{type}/{year}/doc-<sha256(url)[:8]>`, which are opaque, change when a URL
   changes, and split one bill's two language readings into two unrelated Works. Every published IRI
   is now built from facts the document itself published — country, type, originating chamber (§8,
   ADR-002), year, number, language — and nothing mutable appears in one. **Where §28.4 and §28.7
   appear to disagree, §28.7 is authoritative for anything published and §28.4 for anything stored.**
2. **Language is a recorded fact, not a default.** 1.10's `infer_unit` returned only a unit and the
   renderer hard-coded `msa`, so an English reading was published as Malay under a Work no Malay
   reading shared. `infer_language_and_unit` returns the language separately and as `None` when the
   document declares nothing; `resolve_language` prefers the language declared when the markdown was
   imported and cross-checks it against the Arrangement heading. **A document with no language from
   either source fails**, which is the same refusal §11.5 already applies to an unparseable date.
3. **A model's reading is now gated, and the XML is validated (§28.8, ADR-025).** §26's design
   principle — "deterministic wherever possible, generative only at the edges… no stage may
   best-effort its way past a gate" — was not honoured by §28.5 as built: nothing stood between the
   extractor and the store. Gate P1 is that gate, and the rendered document is additionally
   validated against the vendored OASIS Akoma Ntoso 3.0 schema, which the previous renderer's output
   did not pass.
4. **Regeneration is gated on input hashes, not on a file existing (§28.9, ADR-026).** Every step
   used `has_*` to decide whether it had work, so a corrected identifier scheme or renderer would
   have left the whole corpus untouched with nothing to report it. Each derived artifact now carries
   a provenance record naming what it was built from; volatile facts (run id, timestamps) live in the
   per-run manifest only, because a per-artifact sidecar that changes every run destroys the "a
   second identical run writes zero rows" property §22 requires of this project generally.
5. **Publication has a posture, and it is off (§28.10, ADR-027).** ADR-018 said the corpus is served
   by the application and warned that gating a lower-risk artifact while leaving a higher-risk one
   open would be exactly backwards. The corpus is therefore stored in full and **redacted at the
   serving boundary**, with two flags and two rights confirmations: `SERVE_LEGISLATION_CORPUS` for a
   metadata-only surface and `LEGISLATION_PUBLICATION_MODE=full` for provision text, the latter
   requiring the A14 confirmation §26.7 and ADR-004 already govern. Provision headings are published
   in metadata-only mode, as a recorded judgement (ADR-027 decision 4), reversible in one constant.

Nothing in §6–§27 changes. The Postgres-backed system remains untouched and dormant, and Gate P1 is
**not** Gate L1: they check different things on different inputs, and §26.6's gate table is
unaffected.

### 25.11 Changes recorded in 1.13

Two directions from the commissioner on 2026-08-22, one reprioritisation and one pipeline
restructuring, plus the first-corpus-run corrections already in the working tree.

1. **Publication order is inverted for the file-first corpus (§28.12, ADR-029).** Directed: "my
   priority right now is serving the schema and dataset statically, second part would only be the
   backend serving, db integration and etc. the data pipeline should be solely local file for now,
   not committed, only the static semantic files or definition," then "My prioritise is a public
   cache of files, only then we do the teooling." The first publication surface is a static export
   — gate-passing documents on their §28.7 FRBR paths plus the definitions (XSD, JSON-LD context,
   vocabulary, artifact schemas), an index, and checksums — produced by
   `billwatcher pipeline export-static` behind the same rights flags as serving. §28.10's served
   surface, the database/object-store `PipelineStore`, and the §28.5 step split all become phase
   two. ADR-018 is qualified for this pipeline only, not reversed: it still governs the
   Postgres-backed system (§26.5).
2. **Step 4 is split and the extractor stops re-emitting text (§28.5, ADR-030).** Directed:
   "conversion directly to akoma ntoso is too resource intensive, how about we first produce an
   intermediate format that fits all the bills we got so far then we'll do the conversion probably
   at the end of the pipeline." The provision tree becomes a persisted artifact
   (`document.structure.json`) with its own provenance and JSON Schema; Gate P1 judges it there;
   Akoma Ntoso is rendered from the stored tree deterministically. The extractor returns anchors
   (node type, printed number, heading, start line) and body text is sliced from `document.md`,
   never re-generated by the model. No new format is invented — the intermediate is the `Node`
   tree the pipeline already builds and gates, written down.
3. **First-corpus-run corrections.** Gate P1 has now seen real documents. The corrections it
   forced — among them a preamble text leak past `pipeline.redact`'s wrapper walk, fidelity
   refinements, and version bumps to `AKN_VERSION`/`AKN_FIDELITY_GATE_VERSION` (1.1.0) — are in
   code and belong to the `docs/status.md` gate log, not to this contract; they are noted here
   because 1.12's "the corpus is unmeasured" no longer describes reality.

## 26. Legislation pipeline (Release 4)

Releases 1–3 index what Parliament *published about* a bill: its code, its readings, its status, and the bytes of its PDF. This section specifies reading what those documents *say* — turning a stored PDF into a structured, citable, point-in-time corpus of Malaysian federal legislation.

**Design principle: deterministic wherever possible, generative only at the edges.** Every stage has a validation gate that can fail the build. No stage may "best-effort" its way past a gate. Where a rule cannot decide, the item is queued for a human, never guessed.

**The claim changes weight here, and that is the most important thing in this section.** Releases 1–3 make an accuracy claim about a *record*: we mirror what Parliament published, and we date it. A consolidated provision asserts a proposition about the *world* — that this is what the law says today — which no upstream source published in that form. Section 26.7 governs what may be published as a result, and it is stricter than §14, not looser.

### 26.1 Stage L1 — layout-aware reading

Naive text extraction is forbidden for this pipeline. Malaysian legislative typography carries structure in position: section numbers hang at the left margin, marginal notes sit in the right margin *on the same baseline as the provision they annotate*, running heads and page numbers repeat, and schedules restart numbering.

`billwatcher.scraper.parse_document` continues to produce flat, page-delimited text for search and must not change; nothing in the 27,575 indexed pages is invalidated by this section. Stage L1 is a **second, independently versioned reading** of the same stored bytes, recorded under its own extractor name and its own `LAYOUT_EXTRACTOR_VERSION`.

Requirements:

1. Each text line must carry its page, its baseline, its left edge, its font, and its size.
2. Each line must be classified: `body`, `heading`, `provision`, `marginal`, `header`, `footer`, `page_number`.
3. A marginal note **must not** be joined to the provision sharing its baseline. Joining them splices an annotation into the middle of the legal text.
4. Running heads, running feet, and page numbers are discarded from content **only after** every line has recorded the page it came from, so pinpoint citation back into the stored PDF survives.
5. Every geometric threshold must be a fraction of the page box, never a count of points: Malaysian legislation is published on more than one paper size.
6. A reprint's marginal amendment annotations — `[Am. Act A1234]`, `[Ins. Akta A660]` — are recognisable and must be classified as `marginal` rather than discarded as furniture, so Stage L1 does not destroy evidence Stage L3 will need. `vocabulary.amendment_annotations` parses the annotation's operation and instrument; **it is not yet wired into persistence**, so nothing is stored from it today. Storing it is Stage L3 work, not Stage L1's, since the operation itself is extracted from the amending Act's own words, never from a reprint's margin, and a `provision_nodes` row with nowhere to put an amendment reference would be premature schema.
7. A document the extractor finds no text in at all is a scan. It must be recorded as `no_text`, distinctly from a document that merely has no contents page, and it must not be built on. The 22 known scans are the documents most likely to be wrong; filing them as ordinary is how they become invisible.

The library choice and its dependency cost are ADR-016.

### 26.2 Structural vocabulary and provision identity

| BM | EN | AKN element | eId prefix |
| --- | --- | --- | --- |
| Bahagian | Part | `<part>` | `part_` |
| Bab | Chapter | `<chapter>` | `chp_` |
| Seksyen | Section | `<section>` | `sec_` |
| Fasal *(bills)* | Clause | `<clause>` | `cl_` |
| Subseksyen | Subsection | `<subsection>` | `subsec_` |
| Perenggan | Paragraph | `<paragraph>` | `para_` |
| Subperenggan | Subparagraph | `<subparagraph>` | `subpara_` |
| Jadual | Schedule | `<hcontainer name="schedule">` | `sched_` |
| Mukadimah | Preamble | `<preamble>` | — |

**Bills use Fasal/Clause; Acts use Seksyen/Section.** A clause becomes a section on enactment. That rename is a first-class transition — one function, applied once, idempotent — and never a reparse. Which unit a document uses is read from its own Arrangement heading (`Susunan Fasal` versus `Susunan Seksyen`), so a bill is never asked to match a section tree.

`eId` is the identifier in *this* expression; nesting joins with a double underscore (`sec_5A__subsec_1`). `wId` is the identifier the provision carried when it was first created and never changes: when the Commissioner of Law Revision renumbers on reprint, `eId` changes and `wId` does not.

**Stage L1 must not assign `wId`.** Nothing in a single document establishes what a provision was first called, and a guess makes a renumbering look like a new provision. `wId` is assigned in Stage L2, where a work's expressions are related to one another.

Two ambiguities are normative because getting either wrong silently renumbers everything beneath it:

- **`(i)`, `(v)`, `(x)`, `(l)`, `(c)`, `(d)` and `(m)` are each both a paragraph letter and a roman numeral.** The token alone cannot decide. It must be resolved from the sequence it continues: `(i)` after `(h)` is the ninth paragraph; `(ii)` after `(i)` is the second subparagraph; `(i)` with nothing to continue opens a subparagraph list.
- **A schedule restarts numbering.** Its item `1.` is a paragraph of that schedule, not a second section 1 of the Act.

### 26.3 Gate L1 — the Arrangement of Sections

Every Malaysian Act and bill opens with an Arrangement of Sections (*Susunan Seksyen*) or of Clauses (*Susunan Fasal*). It is a table of contents the drafter published, which makes it **a validation oracle the corpus supplies for free**.

Parse it as a separate artifact, parse the body independently, and assert that the two agree. This is the single highest-value check in Stage L1: it catches dropped pages, failed extractions, and mis-detected hierarchy before any of it can propagate into an amendment operation or a consolidated statement of law.

```
GATE L1 (blocking): the Arrangement-of-Sections tree == the extracted body tree.
                    Mismatch → the reading is stored, is never promoted,
                    and is queued for human review.
```

Both readings must be stored, not just the verdict: a verdict is reviewable only if what it compared is on the record.

Gate L1's outcomes are `passed`, `mismatch`, `no_arrangement`, `empty_body`, `no_text`, and `failed`. Only `passed` and `no_arrangement` may be promoted — an explanatory statement legitimately has no contents page, so the gate has no oracle to apply and says so rather than failing.

A **repeated `eId` within one tree is blocking** (`duplicate_eid`), and must be caught by the gate rather than by a database constraint. An eId is an identifier: a body containing two section 1s gives every later citation, amendment anchor, and consolidation target two possible referents. It also cannot be caught by comparing the two trees as sets, because a set collapses the duplicate and reports the document as passing — which is exactly the well-formed-looking wrong answer this stage exists to prevent.

**The gate is otherwise blocking on structure — which provisions exist, and in what order — and reports heading differences without blocking on them.** A section's heading is printed as a marginal note in some reprints and inline in others, so a heading difference is usually a typographic fact about the source rather than a defect in the parse. That narrowing is deliberate and is ADR-017; widening it is a one-constant change.

**Gate L1 as specified here is per document, in whichever language that document is written.** The bilingual comparison the pipeline also needs is Gate L4 (§26.4) and is a different check on a different input: it needs a *pair* of documents, which requires document classification that does not yet exist (§26.7).

A single failing document is a work item, not an incident. A *rate* of failures above baseline means the parser or the upstream typography changed, and raises `structure_gate_failure_spike` (§10.5) — exactly as `extraction_failure_spike` already does for extraction.

### 26.4 Stages L2–L6 — specified, not built

These are recorded so the shape is agreed before anyone codes them. None is implemented, and each is blocked (§26.7).

**Stage L2 — Akoma Ntoso 3.0.** Target OASIS LegalDocML, namespace `http://docs.oasis-open.org/legaldocml/ns/akn/3.0`. `<act>` for an Act, `<bill>` for a bill, `<act>` with `<analysis><activeModifications>` for an amending Act. Naming follows the AKN Work/Expression/Manifestation pattern (`/akn/my/act/2010-06-02/710/msa@2014-01-15`), ISO 639-3 (`msa`, `eng`). `<analysis>` is the native home for amendment operations; do not invent a parallel structure. Stage L2 assigns `wId`.

**Stage L3 — amendment extraction.** Malaysian amending language is highly formulaic in both languages (`...dipinda dengan menggantikan perkataan "X" dengan perkataan "Y"` / `...is amended by substituting for the words "X" the words "Y"`). Rules first, model second; an LLM may propose an operation but emits into the same schema and passes the same gate. Log the rules-versus-model ratio as a health metric.

```
GATE L2 (blocking): for every operation with an anchor, that string occurs
                    exactly once in the target provision at the version in
                    force immediately before the operation's commencement.
                    0 matches → extraction or consolidation wrong → review.
                    >1        → anchor ambiguous → review.
```

**Stage L4 — consolidation.** Materialise expressions **at change points only**, never per calendar date; a query for "as at 2023-06-15" resolves to the interval containing it. Same-day operations must be ordered deterministically and the order documented. `wId` is preserved across every operation, including renumbering. **Commencement lives on provisions, not instruments** — an Act can come into force section by section via P.U.(B) notification, and modelling it on the instrument publishes text that is not yet law.

```
GATE L3 (blocking): consolidate to a published AGC reprint's stated date and
                    diff against the reprint. Normalised whitespace, exact
                    otherwise. Get this green on a representative sample
                    before scaling the corpus.
```

Gate L3 is the correctness oracle for consolidation, and it only exists for Acts with a published reprint. **Every consolidated expression without one is published with no oracle at all**, which is a limit on what may be claimed, not merely a coverage gap. Subsidiary legislation (P.U.(A)/P.U.(B)) is out of scope, yet Malaysian Acts are routinely amended by ministerial order; an expression consolidated only from Acts is therefore not guaranteed complete, and must say so.

**Stage L5 — ELI/JSON-LD.** AKN carries structure and text; ELI carries the metadata graph. Publish both. Every provision needs a dereferenceable IRI — no blank nodes — in a flat `@graph` with `hasPart`/`isPartOf`, on truncatable paths where each level resolves to a listing.

```
GATE L5 (blocking): SHACL shapes pass; no dangling `amends` target; no
                    blank-node provision; every expression has `validFrom`;
                    no two expression intervals overlap for one wId+language.
```

**Stage L6 — bilingual cross-check.** BM and EN share identical structure, so alignment is on the structural path and needs no embeddings.

```
GATE L4 (warning): every wId present in one language and absent in the other
                   is flagged, as is any aligned pair whose child counts or
                   numbering diverge.
```

Malay is the authoritative language for federal law, so unexplained divergence is a finding worth publishing, not just an internal bug.

`GATE L6` (ELI validator clean) and `GATE L7` (golden-set recall and abstention accuracy on out-of-corpus questions) are non-blocking; Gate L7 is substantially what `make evaluate` already does.

### 26.5 Publication is served, not static

The source specification for this pipeline proposed a static `dist/` tree with client-side SQLite/FTS5 over HTTP Range and edge-function content negotiation. **That is rejected for this project** (ADR-018). This service is a server-rendered FastAPI application over PostgreSQL with an external nginx (ADR-015), a weighted `tsvector` with `ts_rank_cd` ranking (ADR-007), and pgvector retrieval; adopting a static build would discard all of it and contradict four accepted decisions to buy a property — mirrorability — that a dump artifact provides on its own.

Consequently:

- AKN XML, ELI JSON-LD, and provision pages are served by the application on truncatable ELI paths, and indexed with the existing search machinery rather than a second one.
- Mirrorability is delivered by an N-Quads dump plus checksums, produced by a Make target. **The dump is gated on the same rights determination as everything else (§26.7): once mirrored, it cannot be withdrawn.**
- Content negotiation uses extension variants with `Link: rel="alternate"` headers, which needs no infrastructure.

### 26.6 Gate summary

Gates are named `L1`–`L7` to keep them distinct from the three kinds of tracking §0 warns against conflating, and from the gates in §18.

| Gate | Stage | Blocking | Checks |
| --- | --- | --- | --- |
| L1 | L1 extraction | Yes | Arrangement of Sections == extracted body tree, per document |
| L2 | L3 amendment | Yes | Anchor text occurs exactly once in the target at the prior version |
| L3 | L4 consolidation | Yes | Output == AGC reprint at the reprint's stated date |
| L4 | L6 bilingual | No | Structural parity between BM and EN |
| L5 | L5 graph | Yes | SHACL shapes; no dangling `amends`; no blank-node provision |
| L6 | L5 metadata | No | ELI validator report clean |
| L7 | retrieval | No | Golden-set recall@k; abstention on out-of-corpus questions |

### 26.7 What is blocked, and on whom

Nothing below is resolvable in code. Each is tracked in `docs/status.md` with an owner.

- **Acts are not yet obtainable, though a discovery spike has now run.** Acts and AGC reprints live on `lom.agc.gov.my`, which is not on the allowlist. A read-only discovery pass on 2026-08-20 (`docs/upstream.md`, A16) found a complete TLS chain, read the Terms & Conditions and FAQ in full, and confirmed the s.61 disclaimer and the pre-2011 coverage boundary from AGC's own text — but `robots.txt` returns an unexplained HTTP 500 rather than a clean absence, which is its own condition and its own decision, not A13's reused by analogy; no listing or document page was fetched, so the reprint-dating convention Gate L3 needs is still unconfirmed; and the FAQ's "for purposes of reference" download language is a fact on the record, not a permission this project has granted itself. Adding the host to the allowlist and beginning to crawl still needs its own recorded policy decision and, per the finding below, legal sign-off — the same discipline parlimen.gov.my got, and for the same reason. Stages L3, L4 and Gate L3 cannot start until both conclude. **Without Acts there is no consolidation and no correctness oracle**, so Stage L1 over the existing bills corpus remains the only part of this pipeline that can proceed today.
- **`lawnet.com.my` is a different risk class** from AGC and must not be bundled with it: it is a paid PNMB subscription service, so access is governed by a contract, raising terms-of-use and unauthorised-access exposure on top of copyright.
- **Publishing consolidated law needs legal sign-off**, not merely a rights answer. A Malaysian-qualified lawyer must review the consolidation methodology and the disclaimers before anything consolidated is public-facing. This is a *higher* bar than A14, which concerns mirroring bytes.
- **The AGC disclaimer must be carried through.** The AGC portal states that copies printed from it do not constitute Gazette copies for the purposes of section 61 of the Interpretation Acts 1948 and 1967. That is a true statement about the authority of the data and must appear on every document derived from it. Note that today's disclaimers are bill-shaped — "Parliament is the authority" is *false* for a consolidated Act, whose authority is the Gazette — so the existing disclaimer regime must be extended, not reused.
- **Document classification does not exist, and cannot yet be added reliably.** `documents.document_kind` and `documents.language` are written as `"unknown"` at creation and never updated, so the corpus cannot yet be partitioned into BM/EN pairs. This was checked, not merely left undone: `docs/upstream.md` already records that document URLs must be treated as opaque — only the search endpoint's own deep link (`/files/bm/billindex/pdf/...`), which this project does not crawl, carries a language segment in the path; the crawled URLs' filenames carry an inconsistent, partial marker (`DR 17 BM.pdf`, `DR 17 BI.pdf`, `D.R.45_2017 (bm).pdf`, or nothing at all) rather than a regular one. Writing a classifier from the handful of examples on record would repeat the exact mistake A9's status-vocabulary sweep already corrected twice — designing a rule from what happens to be visible rather than a real sweep. It needs the same corpus access Gate L1's pass-rate measurement is blocked on, not just developer time. Gate L1 sidesteps the whole question by reading the language from the document's own Arrangement heading; **Gate L4 cannot**, and is blocked on it.
- **The stored corpus is not reachable from a clean checkout.** The 1,264 PDFs live on the deployment host or in the S3 gateway. Measuring Gate L1's pass rate over real Malaysian typography requires access to that blob store, and until then the gate is proven only against constructed fixtures.

### 26.8 Release 4 definition of done — Stage L1 only

Release 4 is deliberately scoped to Stage L1 over the existing bills corpus. It is done when:

- Every current, accepted document version has a structural reading at the current extractor and structure versions, recorded additively and replayable offline from stored bytes.
- Gate L1's verdict is stored per document, with both compared trees, and a reading that fails is preserved for review and never promoted.
- A parser regression cannot withdraw a reading that passed.
- Scans are recorded as `no_text`, counted, and distinguishable from documents that legitimately have no contents page.
- `structure_gate_failure_spike` is raised on a failure-rate spike and is clearable by an operator with a name and a reason.
- The corpus-wide pass rate is measured against the real stored PDFs and recorded in the `docs/status.md` gate log.
- `make check` and `make test-pg` are green and `make doctor` is clean.

Of these, only the corpus-wide pass rate is not yet met — the stored PDFs are not reachable from a clean checkout (§26.7) — and it is unmet for that reason alone: `make check` and `make test-pg` are green and `make doctor` is clean today. See `TODO.md`.

## 27. Auditable step pipeline and the audit tree

**Superseded as the current priority by §28**, later the same day and by the same commissioner
("we are revisiting from scratch, database and object store are for later"). It still takes
precedence over every other open work item — the embedding model, the OCR worker, and the Gate L1
corpus measurement included — until its definition of done (§27.6) is met, and what is built of it
stays in place and supported. The design decision it rests on is ADR-019.

The requirement it answers: every step of the pipeline must be auditable by a person with a file
browser and no database access; every step must be one Make target; and every step must store its
output in a local directory structure — for a document, the raw downloaded PDF beside a JSON
sidecar detailing the source, the raw file, the language, the URL, and the rest of its provenance.

The design principle: **the database remains the authoritative, append-only record (§8–§10 are
unchanged); the audit tree is a mandatory, byte-reproducible projection of it, written by every
step as part of that step's own run.** The tree can fall behind the database — that is detectable
and is an anomaly — but it can never silently disagree with it, because every sidecar is generated
deterministically from the same rows the step writes, and regenerating the whole tree from the
database and blob store must be byte-identical (§27.4). Why the projection direction and not
file-first, and the alternatives rejected, are recorded in ADR-019.

### 27.1 Steps and Make targets

The pipeline decomposes into these steps. Each step is exactly one Make target; no step runs as an
implicit side effect of another; aggregates are explicit targets that name their members.

| Step | Make target | Reads | Writes to the tree | Network |
| --- | --- | --- | --- | --- |
| S1 fetch listings | `fetch-listings` | Parliament listing/archive endpoints | `01-listings/` raw HTML/XML + sidecars | live, approval-gated |
| S2 parse listings | `parse-listings` | stored snapshots | `02-bills/` one `bill.json` per bill | none |
| S3 fetch documents | `fetch-documents` | `fetch_queue` | `03-documents/` raw PDFs + sidecars | live, approval-gated |
| S4 extract text | `reextract` | stored document bytes | `04-text/` extracted text + sidecars | none |
| S5 structure (Gate L1) | `restructure` | stored document bytes | `05-structures/` both trees + verdict + sidecars | none |
| S6 chunk | `rechunk` | current extractions | `06-chunks/` chunk sets + sidecars | none |
| S7 embed | `reembed` | current chunk sets | `07-embeddings/` sidecars only (§27.3) | provider-dependent |

Rules:

- **One step, one target.** `make scrape` remains, redefined as the explicit aggregate S1→S2→S3
  in one run; `make pipeline` is the aggregate S1→S6 (S7 joins once ADR-008 concludes). Both
  aggregates are conveniences over the step targets, never a different code path.
- S4–S7 keep their existing target names and semantics: they process everything pending or below
  the current code version, which covers both the step role (process new items) and the backfill
  role (reprocess at a bumped version). They keep their dry-run default when run standalone; the
  `pipeline` aggregate runs them applied.
- S1 and S3 are live and stay behind the existing `--approve-live` gate and crawl policy (§5,
  §11.7). S2 and S4–S6 are fully offline — auditable and re-runnable from stored bytes alone,
  exactly like §9.6 replay.
- **Every step is idempotent against the tree**: re-running a step with unchanged inputs writes
  no new artifact and rewrites no existing one, the same invariant §8 already imposes on rows.
- **Every step run writes a manifest** to `manifests/<step>/<run-id>.json`: step name, run ID,
  invoking target, started/finished times, the code versions involved, counts of inputs
  considered, outputs written, items unchanged, and bounded failure details. The manifest is what
  makes a step *run* auditable, as the sidecars make its *artifacts* auditable.

### 27.2 The audit tree layout

The tree lives under `AUDIT_TREE_ROOT` (default `./data` in development, a dedicated volume in
containers). It is local, gitignored state, like `var/`.

```text
${AUDIT_TREE_ROOT}/
├── manifests/<step>/<run-id>.json
├── 01-listings/<chamber>-<kind>[-<year>]-<lang>/<requested-at>/raw.html|raw.xml + metadata.json
├── 02-bills/<bill-slug>/bill.json
├── 03-documents/<bill-slug>/<doc-key>/v<NNN>/document.pdf + metadata.json
├── 04-text/<bill-slug>/<doc-key>/v<NNN>/<extractor>@<version>/text.txt + metadata.json
├── 05-structures/<bill-slug>/<doc-key>/v<NNN>/structure@<version>/structure.json + metadata.json
├── 06-chunks/<bill-slug>/<doc-key>/v<NNN>/chunker@<version>/chunks.json + metadata.json
└── 07-embeddings/<bill-slug>/<doc-key>/v<NNN>/<model-id>/metadata.json
```

Rules:

- **Paths are built only from our own identifiers** — bill slugs, a `doc-<first 8 hex of the
  document UUID>` key (full UUID on collision), version numbers, and code-version strings. Never
  from upstream filenames or URL fragments (§17); those live inside the sidecar.
- **Paths never encode mutable fields.** Language and document kind are sidecar fields, not
  directory names, so a later classification never moves a file.
- **The append-only rule extends to the tree.** A new document version is a new `v<NNN>/`
  directory; a superseded version's directory stays. Nothing in the tree is overwritten except
  `02-bills/<slug>/bill.json`, which is explicitly a *current-state* projection — its history is
  `record_changes`, in the database, where history lives.
- **Legibility beats deduplication here.** A document linked from two bills appears under both;
  the sidecars carry the same SHA-256, which is how an auditor (or `verify-audit`) sees they are
  one document. The blob store keeps physical storage deduplicated; at 0.24 GB for the whole
  corpus (A12), tree duplication costs nothing that matters.

### 27.3 The sidecar contract

Every artifact in the tree carries a `metadata.json` sidecar (for `02-bills`, the `bill.json` is
itself the artifact and embeds the same envelope). Sidecars are versioned by
`metadata_schema_version`, and serialise deterministically: UTF-8, LF line endings, two-space
indentation, keys sorted, trailing newline — because §27.4's byte-identical rebuild is the test
that proves the tree carries no state of its own.

A document sidecar must carry at least:

```json
{
  "metadata_schema_version": 1,
  "artifact": "document",
  "raw_file": "document.pdf",
  "sha256": "…",
  "byte_size": 273181,
  "media_type_declared": "application/octet-stream",
  "media_type_detected": "application/pdf",
  "source": {
    "publisher": "Parlimen Malaysia",
    "host": "www.parlimen.gov.my",
    "url": "https://www.parlimen.gov.my/…/DR152026.pdf",
    "final_url": "https://www.parlimen.gov.my/…/DR152026.pdf",
    "upstream_filename": "DR 15 2026.pdf",
    "listing_url": "https://www.parlimen.gov.my/bills-dewan-rakyat.html?…"
  },
  "http": { "status": 200, "etag": null, "last_modified": null },
  "retrieved_at": "2026-08-21T02:15:04Z",
  "language": "unknown",
  "document_kind": "unknown",
  "bill": {
    "identifier_raw": "D.R.15/2026",
    "identifier_normalized": "DR-15-2026",
    "slug": "dr-15-2026"
  },
  "chambers": ["dewan_rakyat", "dewan_negara"],
  "version_no": 1,
  "is_current": true,
  "produced_by": { "step": "fetch-documents", "run_id": "…", "parser_version": "…" },
  "database": { "document_id": "…", "document_version_id": "…", "blob_sha256": "…" }
}
```

Derived-step sidecars (text, structure, chunks, embeddings) additionally name the tree path of the
input artifact they were derived from and the producing tool and version (`extractor`,
`structure_version`, `chunker_version`, `embedding_model_id`), so the derivation chain is walkable
on disk exactly as it is in the schema. Embedding sidecars record the model, dimension, chunk-set
reference, and a checksum of the vectors, not the vectors themselves — a vector is not
human-auditable and the database is its home.

Honesty rule: `language` and `document_kind` are `"unknown"` today because the classification
sweep has not run (§26.7, TODO 2.4). The sidecar states what the record states — it never guesses.
When classification lands, `make audit-rebuild` backfills every sidecar from the corrected rows.

### 27.4 Verification and rebuild

Two targets keep the projection honest:

- `make verify-audit` — offline. Re-hashes every file in the tree against its sidecar,
  regenerates every sidecar from the database and compares byte-for-byte, and checks that every
  current row that should have a tree artifact has one. Any disagreement raises
  `audit_tree_divergence` (critical, §10.5) and exits non-zero. This is `make doctor`'s
  file-level counterpart and joins it as an operations gate.
- `make audit-rebuild` — offline. Regenerates the entire tree from the database and blob store.
  Running it against an already-correct tree must be byte-identical and write nothing, proven by
  a test. It is the recovery path (a lost tree costs nothing), the backfill path (a sidecar
  schema bump or a classification sweep re-emits every sidecar), and the materialisation path for
  the already-ingested corpus, which predates this section.

### 27.5 What this changes, and what it does not

- §8, §9, and §10 are unchanged: the database is still the record, the blob store is still the
  archival byte store, and every invariant on them stands.
- The backup contract (§16.4, §16.5) is unchanged. The tree is **not** backed up: it is
  rebuildable from what is backed up, and backing up a projection would imply it carries state,
  which it must never do.
- §9.6 replay and the backfill jobs are unchanged in semantics; they gain tree output.
- The `/status` page gains the tree's last `verify-audit` time and result alongside the existing
  pipeline versions (§10.4).

### 27.6 Definition of done

- Every step in §27.1 is invokable alone by its Make target, and every run leaves a manifest.
- After a fixture-mode `make pipeline` run, every artifact appears in the tree with a sidecar
  whose hash matches its file, and re-running the pipeline writes nothing new.
- `make audit-rebuild` over an existing tree is byte-identical, proven by a test.
- `make verify-audit` is clean on a correct tree and exits non-zero on a single tampered byte,
  proven by a test.
- The already-stored corpus (1,264 PDFs) is materialised into the tree by `make audit-rebuild`
  wherever the blob store lives, with the counts recorded in the `docs/status.md` gate log.
- `make check` and `make test-pg` are green and `make doctor` is clean.

### 27.7 The MinerU markdown reading

A second, independently versioned reading of the same stored PDFs, this time via a hosted
vision-language model rather than the native-text `pypdf` path (ADR-020). Directed on 2026-08-21,
using a hosted MinerU2.5 instance.

**What it is.** MinerU2.5 reads a *page image* and returns a list of content blocks — type
(`text`, `table`, `equation`, `title`, `header`, …), a normalised bounding box, and recognised
content (text, an HTML table, or LaTeX) — via a standard vLLM OpenAI-compatible Chat Completions
API. `billwatcher.mineru` renders each stored PDF's pages to images (`pypdfium2`), sends them to
the configured endpoint through the vendor's own `mineru-vl-utils` client — never reimplemented by
hand, because its prompt templates and per-block sampling parameters are exactly the kind of
detail worth trusting to the maintainers — and assembles the returned blocks into markdown,
trusting the model's own reading order rather than re-deriving one from bounding boxes.

**Where it lives.** Written only as a local file artifact, under the `04-text/` tier §27.2 already
specifies:

```
data/04-text/<bill-slug>/<doc-key>/v<NNN>/mineru@<version>/document.md + metadata.json
```

Never into `document_extractions`: that table demotes every `is_current` row for a version
regardless of extractor name (TODO 2.4), and a second writer would silently destroy the native
`pypdf` extraction the moment it ran. This reading avoids that landmine the same way Stage L1's
structural reading does — by not touching the table at all — except here there is no database row
whatsoever, not even in a dedicated table: the whole point of this reading is to live as a file,
and eligibility (has this version already been read?) is decided by whether that file already
exists, not by a query.

**What a quarantined document gets.** A download that failed PDF validation is still a
bytes-on-the-wire fact; if it was attempted, its status (`succeeded`/`empty`/`failed`) is recorded
honestly in the sidecar rather than the document being silently skipped.

**Configuration**, off by default because sending official document images to a third-party
inference host is a data-handling decision, not a default (ADR-020, matching ADR-009's treatment
of the RAG endpoint):

```dotenv
MINERU_ENABLED=false
MINERU_BASE_URL=
MINERU_MODEL_NAME=
MINERU_API_KEY=
MINERU_RENDER_DPI=150
MINERU_TIMEOUT_SECONDS=120
```

`make mineru-extract` (dry-run default, `--apply` to write) processes current, accepted document
versions that have a bill link and no existing markdown file, oldest first, up to `--limit`. It
never contacts Parliament, but it does call the configured MinerU endpoint over the network for
each eligible document — a live, real-cost call, which is why this is a manual step and not part
of the scheduled worker or `make pipeline`.

## 28. The file-first pipeline (`billwatcher.pipeline`)

Directed on 2026-08-21, in parallel with everything in §6-§27: "database and object store are for
later... the pipeline should work with interface of input, such as file and also from db or
object store" (ADR-021). This section describes a second, independent pipeline living entirely
under `billwatcher.pipeline`. It does not replace §6-§27 — the Postgres-backed system stays in
place, untouched, dormant — and it is not described by any other section of this document.

### 28.1 The interface, not the backend

Every step depends only on `billwatcher.pipeline.store.PipelineStore`, a protocol:
`save_listing`/`iter_listings`, `load_bill`/`save_bill`/`iter_bill_slugs`,
`has_document`/`save_document`/`iter_documents`. `FileStore` — local directories and JSON — is the
only implementation. A database or object-store backend is a later, additive extension: implement
the same protocol and every step works unchanged, because no step imports `FileStore` by name.

### 28.2 Steps

This table is the only place this pipeline's targets are specified; where it and the code disagree,
the code is the defect. Every path below is relative to `PIPELINE_DATA_ROOT`, and every version
directory is `documents/<bill-slug>/<doc-key>/v<NNN>/`.

| Step | Function | Network | Reads | Writes |
| --- | --- | --- | --- | --- |
| 1 fetch listings | `pipeline.listings.fetch_listings` | live | Parliament | `listings/<key>/body.<ext>` + `metadata.json` |
| 2 parse listings | `pipeline.listings.parse_listings` | none | stored listings | `bills/<slug>/bill.json` |
| 3 fetch documents | `pipeline.documents.fetch_documents` | live | `bills/*/bill.json` | `document.pdf` + `metadata.json` |
| 3b import markdown | CLI only | none | a markdown file the operator produced elsewhere | `document.md` + `document.markdown.provenance.json` |
| 4a extract structure | `pipeline.akn.extract_structures` | live (vLLM) | `document.md` | `document.structure.json` + `document.structure.provenance.json`, always `document.structure.gate.json` (Gate P1 judges the tree here, §28.8), and `document.structure.rejected.json` instead of the structure when it blocks |
| 4b render Akoma Ntoso | `pipeline.akn.render_documents` | none | `document.structure.json`, `bill.json` | `document.akn.xml` + `document.akn.provenance.json` |
| 5 generate semantic files | `pipeline.semantic.generate_semantic_files` | none | `document.akn.xml`, `bill.json` | `document.jsonld` + `document.nq` + `document.semantic.provenance.json` |
| 6 export static cache | `pipeline.export.export_static` | none | every promoted artifact above, `bill.json` | the `PIPELINE_EXPORT_ROOT` tree (§28.12) — the one step that writes outside the store |
| verify | — | none | everything above | nothing; it reports (§28.9) |

**Steps 4a/4b are the ADR-030 split and are phase-two tooling; until they land, the fused step 4
as built (`pipeline.akn.convert_to_akn`, reading `document.md` + `bill.json`, writing
`document.akn.xml`/`document.akn.gate.json`/`document.akn.rejected.xml`) remains the working
contract**, and step 6 exports from it. When the split lands, the fused step's artifacts
regenerate once under §28.9's provenance rule and the `document.akn.gate.json`/
`document.akn.rejected.xml` names retire in favour of the structure-level ones.

Every run of every step also writes `manifests/<step>/<run-id>.json` (§28.9). `KNOWN_FILENAMES` in
`pipeline/store.py` is the closed set of filenames above; anything else in a version directory is
reported by `verify` rather than ignored.

`billwatcher pipeline fetch-listings|parse-listings|fetch-documents|import-markdown|convert-to-akn|generate-semantic|export-static|verify`
runs them (`convert-to-akn` becomes `extract-structure` + `render-akn` when the ADR-030 split
lands), with `make pipeline-fetch-listings`/`pipeline-parse-listings`/`pipeline-fetch-documents`/
`pipeline-convert-to-akn`/`pipeline-generate-semantic`/`pipeline-export-static` for the corpus-wide
steps.
`import-markdown` is per document and takes the language as an argument, so it stays a CLI command
rather than a target that would hide it.

Steps 1 and 3 require `SCRAPE_ENABLED=true` or `--approve-live`, the same politeness and
authorization discipline as the Postgres-backed `scrape`/`fetch-documents` commands — that
discipline is not a database concern. Step 4 (4a once split) requires `AKN_LLM_ENABLED=true`,
`AKN_LLM_BASE_URL`, and `AKN_LLM_MODEL_ID`. Steps 2, 3b, 4b, 5, 6 and `verify` need neither network
nor model: they read stored files only. Step 6 additionally requires the rights confirmations of
§28.12, because its output is the publishable unit.

**Step 3b is the seam, not a gap.** PDF-to-markdown extraction is out of scope for this pipeline
(§28.11) because the operator's own vLLM endpoint does it. What `import-markdown`
adds is the *record* of that: the markdown lands in the store together with a provenance sidecar
naming what it was extracted from and, critically, which language it is in — the fact §28.7 makes a
permanent component of every published identifier.

Fetch and parse are separated for the same reason §11.1 separates them in the Postgres-backed
scraper: a parser fix must be replayable from stored bytes without re-crawling Parliament.
`billwatcher.scraper.fetch`, `.policy`, `.robots`, `.normalize`, `.parse_listing`, and
`.parse_archive` are reused as-is — none of them ever imported a database model, so nothing about
this pipeline required rewriting HTML/XML parsing, HTTP fetch policy, or identifier
normalisation.

### 28.3 Bill records

One JSON file per bill, `bills/<slug>/bill.json`: identifier (raw, normalized, number, year,
originating chamber, slug — all already produced by `normalize.normalize_identifier`), a title per
observed language, one current record per chamber (status raw/normalized, presenter, dates,
source URL, `last_seen_at`), and an accumulated, deduplicated list of document URLs. `first_seen_at`
is set once; `last_seen_at` is a monotonic max across every merge, not a blind overwrite — a real
bug, found while testing this pipeline: `FileStore.iter_listings` processes listings in storage-key
order, not fetch order, so a bill referenced by both chambers (D.R.15/2026, per A4) could otherwise
settle with `last_seen_at` earlier than its own `first_seen_at`.

Deliberately simple: no field-level change history, no event fingerprints, no `record_changes`
equivalent. That sophistication belongs to the database this pipeline is not using yet.

### 28.4 Document identity, in the store

A document's identity **in the store** is its URL, content-addressed as `doc-<sha256(url)[:8]>` —
there is no database to assign an id. A URL already downloaded is skipped, not re-verified or
re-hashed; there is no version tracking yet. A document shared by two bills gets its own directory
under each bill slug (legibility over deduplication, the same choice §27.2 made for the audit tree).

This key is deliberately **not** a published identifier. It names a location we fetched from, which
is exactly the property a permanent identifier must not have, and 1.10 published it as one. What is
published is built in §28.7 instead.

### 28.5 Converting markdown to Akoma Ntoso

Markdown itself is produced elsewhere (§28.11) and lands at
`documents/<bill-slug>/<doc-key>/v<NNN>/document.md` through `import-markdown` (§28.2).
`convert_to_akn` reads it and writes `document.akn.xml` beside it: `<bill>` for a Fasal/Clause
document, `<act>` for a Seksyen/Section one (§26.2, `infer_language_and_unit` reads the markdown's
own Arrangement heading to decide), with a full FRBR Work/Expression/Manifestation triple built by
§28.7 — never from the document's store key, which is what 1.10 did.

The rendered document must be **valid Akoma Ntoso 3.0** and is checked against the vendored OASIS
schema before it is written; an invalid render is our renderer's defect, so it fails the document
loudly (`AknSchemaError`) rather than being filed as a bad reading (§28.8). Whether the tree itself
is publishable is Gate P1's question, also §28.8.

Reading the provision hierarchy out of markdown is behind `pipeline.akn.MarkdownStructureExtractor`
— one method, `extract(markdown_text, *, unit) -> Node`, plus the `name`/`model_id`/`prompt_sha256`
an extractor must report so its identity lands in the artifact's provenance (§28.9) — so the
decision of *how* is independent of everything else in this step (ADR-022):

- **`VllmMarkdownStructureExtractor`** (`pipeline.akn_llm`), the production path, sends the
  markdown to a configured OpenAI-compatible vLLM endpoint and asks for the tree as JSON, at the
  operator's direction. This is the only mechanism able to tell a document's Arrangement of
  Sections (table of contents) apart from its body — a table-of-contents entry is textually
  identical to the real provision it lists, which a regex cannot resolve without a page/geometry
  signal markdown does not carry.
- **`RegexMarkdownStructureExtractor`** wraps a deterministic line classifier
  (`parse_markdown_structure`) built on `billwatcher.legislation.vocabulary` — reused as-is,
  since it is pure text classification with no database or PDF-layout dependency. Available for
  tests and explicit offline use; does not solve the Arrangement/body problem above, and is never
  a silent production fallback.

**eId assignment is never delegated to either extractor.** `pipeline.akn.assign_eids` computes
every eId deterministically from a node's own `node_type`/`num` and its parent's, after whichever
extractor ran — the same discipline HANDOFF 26.2 requires of `wId`: an identifier comes from what
was printed, never from a guess, model-generated or otherwise. A live smoke test against the real
endpoint found the model wrapping every parenthesised token in its own punctuation (`"(1)"`
instead of `"1"`), which would have poisoned every eId beneath it; fixed defensively
(`_normalize_num` strips it regardless of what the model returns) as well as in the prompt.

**The tree becomes a persisted intermediate, and the extractor stops re-emitting text (ADR-030,
phase two).** As built, the tree lives only in memory and the prompt asks the model for the
hierarchy *with body text*, so output tokens scale with document length, a long bill risks timeout,
truncation and paraphrase, and every renderer or `bill.json` correction re-pays the full LLM read
(§28.9 keys the AKN artifact on both). The amended contract:

- `document.structure.json` is the reading of record — a versioned JSON serialisation of the
  `Node` tree plus resolved `language` and `unit`, with its own provenance and its own JSON Schema
  (published with the definitions, §28.12). Gate P1 judges it there (§28.8); `has_structure` is
  the promotion flag; step 4b renders `document.akn.xml` from the *stored* tree, so a renderer or
  FRBR fix regenerates the corpus with zero LLM calls.
- **The extractor returns anchors, not prose**: node type, printed number, heading, and the start
  line in a line-numbered copy of the markdown. Body text is sliced from `document.md` between
  anchors, deterministically — it never passes through the model, so paraphrase is structurally
  impossible and output cost drops from O(document) to O(provisions). The
  `MarkdownStructureExtractor` protocol keeps its shape; the regex extractor anchors trivially.
- "Conversion at the end" means *decoupled*, not deferred: rendering and XSD validation stay in
  every corpus pass, because they are the cheap steps and they surface renderer defects one
  document at a time rather than corpus-wide.

### 28.6 From Akoma Ntoso to the semantic graph

Directed on 2026-08-21: "after akn, then it should be to the semantic files such as jsonld and
rfg" — read as JSON-LD plus RDF (N-Quads); flagged to the commissioner as an interpretation of
"rfg", to be corrected if wrong. `generate_semantic_files` (`pipeline.semantic`) is step 5: for
every document whose semantic files are missing or no longer match their inputs (§28.9), it reads
the XML back (`parse_akn`, a reverse-parser producing the same `Node` tree, Expression URI, root
element name and language `render_akn` produced), builds one graph, and writes `document.jsonld` and
`document.nq` beside the XML.

Reading the AKN file back rather than reusing step 4's in-memory tree keeps the two steps able to
run independently, hours or files apart — step 5 depends only on step 4's file output, the same
seam every other step in this pipeline uses.

The JSON-LD graph is a flat `@graph` of one node per document and per provision, each with an
`@id` (the document's Expression IRI, or a provision's IRI suffixed `/~<eid>`, both from §28.7), an
`@type` (`akn:bill`/`akn:act`/`akn:<node_type>`), `eli:number`, and `schema:name`/`schema:text` where
the markdown carried them; parent/child edges are `eli:has_part`/`eli:is_part_of`. **JSON-LD and
N-Quads cannot disagree**, because there is one graph construction and two serialisations of it —
originally a hand-rolled JSON-LD dict that the N-Quads writer flattened, and since 1.12 a single
`rdflib.Dataset` serialised twice (ADR-028). The guarantee is unchanged; the mechanism is stronger,
and it is what buys correct N-Quads escaping and BCP 47 language tags on every literal, without
which a bilingual corpus cannot tell a consumer whether it is reading Malay or English.

Both outputs are **explicitly sorted** before they are written, because rdflib promises no stable
serialisation order and byte comparison is how this pipeline's idempotence is checked (§28.9).

A malformed or truncated `document.akn.xml` is counted `failed`, not raised — this step runs over
every eligible document in the store in one pass, and one bad file must not stop the rest. XML
declaring a doctype or an entity is refused outright, the same refusal `scraper.parse_archive`
already makes for the archive tree: these bytes are normally ours, but markdown and Akoma Ntoso can
be imported by an operator and the result is served publicly.

**Gate L5 is not run.** Its SHACL shapes (§26.4, §26.6) check for dangling `amends` targets and
missing or overlapping `validFrom` intervals, all of which Stages L3 and L4 would have to produce
first, so pySHACL today would validate an empty half of the shape set and report success. Building
the graph in rdflib is what lets those shapes drop in later without a rewrite; until then the ELI
predicates are this project's reading of ELI rather than a validated one, and should be cited as
such (ADR-028).

### 28.7 Published identifiers: FRBR Work, Expression, Manifestation, provision

`pipeline.frbr` owns every published IRI, because these strings are permanent: once a citation or a
mirror points at one, it has to keep meaning the same document. The scheme follows the Akoma Ntoso
naming convention, with the **originating** chamber (§8, ADR-002) in the subtype slot:

| Level | Path | What it is |
| --- | --- | --- |
| Work | `/akn/my/bill/dr/2026/15` | the bill itself, in any language |
| Expression | `/akn/my/bill/dr/2026/15/msa@` | that bill in one language |
| Manifestation | `/akn/my/bill/dr/2026/15/msa@.xml` | one file of it (`.xml`, `.jsonld`, `.nq`, `.html`) |
| Provision | `/akn/my/bill/dr/2026/15/msa@/~cl_5__subsec_1` | one provision of that Expression |

Normative rules, all of them consequences of "permanent":

- **Every component is a fact the document published.** Country, document type (from its own
  Arrangement heading, §26.2), originating chamber, year, number, language. **Nothing derived from a
  URL, a byte hash, or a retrieval time may appear in an IRI**, because all three change when we
  re-fetch the same document.
- **The Expression's version date is empty** — `msa@`, which in the AKN convention reads as "the
  only version we have". `@YYYY-MM-DD` is reserved for a real document date on the record.
- **Malay and English are two Expressions of one Work.** The language comes from what was declared
  when the markdown was imported, cross-checked against the Arrangement heading; a disagreement is
  recorded in the gate verdict rather than silently resolved, and **a document with no language from
  either source fails**.
- **Two spellings, one mapping.** ISO 639-3 (`msa`/`eng`) in the AKN name; BCP 47 (`ms`/`en`) on RDF
  literals and HTML `lang`, per §15. `frbr.AKN_LANGUAGES` is the only place they meet.
- **A missing fact is a refusal, not a default.** `FrbrIdentityError` fails the document by name in
  the step's failure list. A placeholder inside a citable identifier is worse than no output.
- **A request segment is validated and then discarded.** `parse_work_path` and
  `parse_expression_segment` return `None` for anything malformed (a caller answers 404), and the
  store key is recomputed from the validated identity (`slug_for`) — never joined from the request
  string, which is §17's rule applied to serving.

Two limits are contract, not oversight. There is **no version chain**: a bill revised and
republished at a new URL resolves to the same Expression IRI, which A11 records as never yet
observed, and which needs an Expression date or a version component when it is. And the `dn` branch
has never seen real data, because no `D.N.` identifier exists anywhere in 35 years of archive (A5).

### 28.8 Gate P1 — does the tree account for the markdown, and is the XML valid?

§26's design principle applies to this pipeline too: no stage may best-effort its way past a gate.
Step 4's canonical output is a **model's** reading (ADR-022), and a model that drops a clause or
renumbers a subsection produces a document that parses, validates, builds a graph, and is wrong.

Gate P1 (`pipeline.fidelity`) is the deterministic check between the extractor and the store. It
asks whether a reading is *accountable*, not whether it is good:

| Finding | Blocking | Check |
| --- | --- | --- |
| `duplicate_eid` | Yes | two provisions resolving to one identifier |
| `missing_num` | Yes | a provision with no printed number (it would inherit its parent's eId) |
| `sequence_gap` | Yes | a skipped number, with an inserted `5A` modelled rather than tolerated |
| `sequence_order` | Yes | a number running backwards — the table-of-contents bleed signature |
| `low_text_coverage` | Yes | distinct source tokens absent from the tree, against a threshold |
| `unanchored_run` | Yes | the document's provision run does not start at 1 or 2 |
| `no_source_text` | Yes | a tree judged against a source with nothing scoreable in it |

- **Only coverage has a threshold**, `AKN_GATE_MIN_TEXT_COVERAGE` (default 0.95), because the real
  corpus is unmeasured (A15). Exact where exactness is defensible; configuration where it is a
  judgement, for the reason ADR-017 gives: a gate that fires on everything trains an operator to
  clear a queue without reading it.
- **Coverage is measured from the document's first structural heading onward**, over *distinct*
  tokens, excluding the words that name a structure (`BAHAGIAN`, `JADUAL`, `SUSUNAN FASAL`). All
  three exclusions are the same rule: a provision tree can only be held to the text a provision tree
  can contain. Counting a bill's front matter — cover page, long title, enacting formula — scored a
  *faithful* reading of a real bill 0.71-0.81 against the 0.95 default; the structural keywords cost
  a further 5.2% on a short document. With both excluded a faithful reading scores exactly 1.0. The
  cost, stated: front matter is unchecked, which it effectively always was.
- **Continuity alone is not enough**, because comparing adjacent pairs is blind to a constant
  offset: a tree numbered 3, 4, 5 for a document printed 1, 2, 3 is continuous and scores 1.0 while
  every eId and provision IRI is off by two. `unanchored_run` checks where the run starts.
- An Arrangement entry contributes no new distinct word — the provision it lists prints the same words —
  so the measure is insensitive to how long a contents page is, while a dropped page, clause or
  schedule removes whole distinct words. The multiset ratio is reported beside the verdict and never
  blocks.
- **Provisions are one document-wide sequence**; only subsections, paragraphs and subparagraphs
  restart inside their parent. Checking every sibling list would demand that Part II's first clause
  be numbered 1 and would fail nearly every multi-Part bill.
- **A rejected document is a review item, not a discard.** `document.akn.gate.json` is written on
  every path, including a failure that happened before a tree existed; a blocked render is kept as
  `document.akn.rejected.xml` and `document.akn.xml` is not written, because `has_akn` is the
  promotion flag every later step reads.
- **The gate is replayable offline** from the stored markdown with no model call, which is why
  `AKN_FIDELITY_GATE_VERSION` is separate from `AKN_VERSION`: a threshold change re-judges every
  document without re-rendering any of them.

Separately, the rendered XML is validated against the **vendored OASIS Akoma Ntoso 3.0 XSD**
(`pipeline/schemas/`, byte-identical to upstream with recorded digests, loaded from disk so
validation never touches the network). A schema violation is a defect in our renderer, not a
statement about the document, so it counts `failed` rather than `rejected` and names the errors.

Gate P1 is **not** Gate L1, and §26.6's table is unaffected: Gate L1 compares two independent
readings of one PDF using page geometry (ADR-016), which is a stronger oracle this step does not
have — the LLM extractor is instructed to drop the Arrangement, since separating it from the body is
the problem it was introduced to solve. What Gate P1 cannot detect is stated rather than implied: it
measures source words reaching the tree, so a model that **invents** a subsection while preserving
every real word passes.

### 28.9 Provenance, manifests, and `verify`

Every derived artifact carries `document.<artifact>.provenance.json` naming what it was built from
(`inputs`: every source file with its SHA-256, plus code version, gate version, threshold, producer,
model id, prompt digest, base IRI) and what was written (`output`: SHA-256 and byte size per file).
**Eligibility is decided by comparing a freshly computed `inputs` against the stored one**, never by
asking whether the output file exists — which is what makes a corrected identifier scheme, prompt or
renderer actually regenerate the corpus instead of leaving stale bytes behind a check that cannot
notice. An artifact with no provenance record counts as stale, so a pre-provenance corpus regenerates
once and then settles.

**A provenance record carries no timestamp and no run id.** Either would make every re-run rewrite
it and destroy the "a repeat run writes nothing" property this store's determinism rests on (§27.3,
ADR-019). Volatile facts belong to `manifests/<step>/<run-id>.json`: start and finish, code
versions, counts, and every failure named by bill, document and version. A step's counts stay a flat
histogram — that is what the CLI echoes — with failures beside them rather than mixed into it.

Every write is atomic (temp file, then `os.replace`), because a later step, a `verify` pass and the
public serving surface all read these files and none of them may observe a half-written artifact.
Identical bytes are still short-circuited, so an unchanged file keeps its mtime.

`billwatcher pipeline verify` is the offline audit this makes possible, and the file-first analogue
of `verify-audit` (§27.4): it re-hashes each artifact against its provenance `output`, reports
artifacts whose `inputs` no longer match what the current code would produce, and lists files no
step writes at all — a killed process's temp file, a hand-dropped edit, an artifact from a future
version. Nothing is signed, so this detects drift and accident, not an adversary with write access.

### 28.10 Publication: what is served, and under which flags

**Since 1.13 this surface is phase two** (§28.12, ADR-029): the first publication surface is the
public static cache, and the served surface below — with the database/object-store `PipelineStore`
and every other piece of "the tooling" — comes after it. The contract here is unchanged; only its
place in the queue moved.

This is ADR-018 being implemented, not re-decided: the corpus is served by the application on the
truncatable §28.7 paths, with extension variants and `Link: rel="alternate"` for content
negotiation, and each level resolving to a listing.

**The store keeps the full text; redaction happens at the serving boundary** (`pipeline.redact`) —
the same posture ADR-004 already takes for stored PDF bytes. The consequence is the point: the
rights decision is a configuration change rather than a corpus regeneration.

| Setting | Default | Governs |
| --- | --- | --- |
| `SERVE_LEGISLATION_CORPUS` | `false` | whether the corpus surface exists at all; every path 404s while it is off |
| `LEGISLATION_PUBLICATION_MODE` | `metadata` | `metadata` publishes structure only; `full` publishes provision text |
| `LEGISLATION_CORPUS_RIGHTS_CONFIRMED` | `false` | required in production for the first |
| `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED` | `false` | required in production for `full`, on top of the above |

Two flags rather than one, because they are two questions with different risk: a structural reading
republishes none of the drafter's prose, while provision text is the A14 question §26.7 and ADR-004
already govern. Gating the lower-risk artifact behind a hard control while leaving the higher-risk
one open would be, in ADR-018's words, exactly backwards. Production **refuses to boot** rather than
warning, so turning either on is a recorded decision.

In `metadata` mode: every `<p>` inside `<content>`/`<intro>`/`<wrapUp>` is emptied and every
`schema:text` triple dropped, on parsed structures rather than by regular expression over serialised
bytes, and the redacted Akoma Ntoso stays schema-valid because an invalid document is not a useful
thing to publish either. **Provision headings are published**, as a recorded judgement (ADR-027):
they are the same class of bounded fragment as a bill title, which this site already publishes and
which ADR-004 permits, and `redact.KEEP_HEADINGS` is the one constant that reverses it.

**The bound on that fragment is enforced, in two independent layers, and must stay that way.** It
was not, in the first implementation, and the consequence was the most serious defect in this work:
a Malaysian amendment bill carries no marginal note and runs the whole provision in after its
number, so entire drafted provisions became `heading` values and were served verbatim in every
representation while the A14 review is open. `akn.split_marginal_note` classifies the text at parse
time and `redact.publishable_heading` re-applies the same test at the serving boundary — 80
characters, no terminal punctuation, matching `legislation.layout`'s existing marginal-note bound and
the shapes in the real captured fixtures. The duplication is deliberate: the parser is not the only
producer of a tree, since an LLM extractor fills the same field, and a prompt is a request rather
than a guarantee. `redact.contains_provision_text` checks headings as well as body wrappers, because
a self-check that inspected only `<content>` stayed silent through exactly the leak it existed to
catch.

The N-Quads **mirror dump** §26.5 promises is not part of this and stays unbuilt: a served surface
can be withdrawn, a mirror cannot, and TODO 1.7 carries the legal work that gates it.

### 28.11 What this pipeline does not do

- **No PDF parsing or extraction.** The operator has a vLLM OpenAI-compatible endpoint
  (`https://llm.loqasi.io/v1/`) for that, separately. `fetch_documents` stops at a downloaded,
  magic-byte-validated PDF; markdown arrives at `document.md` from that external process through
  `import-markdown` (§28.2), which records its language and source but does not produce it.
- **No database, no object store, no blob deduplication.** `PIPELINE_DATA_ROOT` (default
  `pipeline-data/`, a deliberately separate setting from `AUDIT_TREE_ROOT`) is the whole record.
- **No reconciliation with the Postgres-backed system.** The two pipelines coexist without
  awareness of each other; bringing them together is future work, not attempted here.
- **No measurement.** Nothing has been fetched into `pipeline-data/`, and the 1,264 stored PDFs of
  the Postgres-backed corpus are not reachable from a clean checkout (§26.7), so Gate P1's pass rate
  over real Malaysian typography is unknown and its default threshold is uncalibrated. Every claim
  about this pipeline is a claim about constructed fixtures and one direct run, and nothing here
  should be read as a measured pass rate.
- **No amendment, consolidation, or point-in-time query.** Those are Stages L3–L4 of §26.4, and they
  are blocked on §26.7, not on this pipeline. Which is also why Gate L5 cannot run (§28.6).


### 28.12 The public static cache — the first publication surface

Directed 2026-08-22 (ADR-029): "My prioritise is a public cache of files, only then we do the
teooling." The corpus's first public form is a directory tree any static file host can serve — no
application, no database, no content negotiation. `billwatcher pipeline export-static` (Make:
`pipeline-export-static`) produces it from the store into `PIPELINE_EXPORT_ROOT`
(default `public-cache/`), and it is the only step that writes outside `PIPELINE_DATA_ROOT`.

What the tree holds:

| Path | Content |
| --- | --- |
| `akn/my/bill/<chamber>/<year>/<number>/<lang>@.xml\|.jsonld\|.nq` | every **gate-passing** document's Akoma Ntoso, JSON-LD and N-Quads, laid out so a cached file's path *is* its §28.7 identifier |
| `definitions/` | the vendored OASIS AKN XSD (copyright notices preserved), the JSON-LD context, the §26.2 structural vocabulary, and the JSON Schema for `document.structure.json` |
| `index.json` | the Works and Expressions present, with titles and file listings — the machine-readable catalogue |
| `checksums.sha256` | a digest per exported file, so a mirror can verify itself |

Normative rules:

- **Only promoted artifacts are exported.** A document whose reading Gate P1 rejected, or whose
  bill record cannot mint a §28.7 identity, is absent — never exported "for completeness".
- **The export boundary is a serving boundary.** `pipeline.redact` applies at export under
  `LEGISLATION_PUBLICATION_MODE`, exactly as §28.10 applies it when serving; the store keeps full
  text either way.
- **The same rights flags gate it, at the same hardness.** The command refuses to run without
  `LEGISLATION_CORPUS_RIGHTS_CONFIRMED=true`, and `full` mode additionally requires
  `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true`. ADR-018's irreversibility warning binds *harder*
  here: a cache, once mirrored, cannot be withdrawn. Both confirmations became legitimate to set
  with the A14 determination of 2026-08-22.
- **The store is never committed; the export may be published.** `pipeline-data/` — PDFs,
  markdown, structures, provenance, rejected renders, manifests — stays local and gitignored.
  The export tree and the definitions are the only pipeline output that may enter version control
  or a public host: "only the static semantic files or definition."
- **Freshness is a re-export.** No invalidation and no redirects; a re-export overwrites in place,
  idempotently (unchanged bytes are not rewritten, §28.9's discipline), and `checksums.sha256` is
  how a consumer detects change. Anything needing liveness belongs to §28.10.
- **Nothing consolidated may enter the cache.** Stages L3–L4 output stays under TODO 1.7's legal
  sign-off, which is a higher bar than A14 and is not satisfied by it.
