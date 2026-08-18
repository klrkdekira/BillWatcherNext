# Implementation status

Last reconciled: 2026-08-18 (Asia/Kuala_Lumpur).

## Package ledger

| Package | State | Owner/agent | Branch | Started | Last update | Evidence | Blockers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A scaffold/runtime | done | Codex | worktree | 2026-08-16 | 2026-08-17 | make check; locked image build; fresh Compose health; UID 10001; read-only app blob mount | — |
| B discovery/model | in_review | Claude | main | 2026-08-16 | 2026-08-18 | schema invariants; twelve parser fixtures including dated columns, mixed good/bad rows, and two soft-404 shapes; empty-database migration to head proven on PostgreSQL; live discovery completed for the current listings, with a fixture reduced from stored bytes and A1/A2/A3/A4/A6 settled | Archive contract, Dewan Negara detail labels, and the English listing structure still unobserved |
| C scraper/versioning | in_review | Claude | main | 2026-08-16 | 2026-08-18 | offline `make seed` fixture ingestion satisfying the section 18 walkthrough step 5, idempotent on reload; `make reparse` reports zero changes at the current parser version (step 9); document worker, extraction history, orchestration, robots, replay, queue, versioning; dated columns now produce reading events with ranges and sequences and project onto chamber records; all seventeen HANDOFF 10.5 anomaly kinds raised and provoked by tests; anomalies deduplicate by kind plus entity | Reviewed live full crawl pending |
| D web/search | in_review | Claude | main | 2026-08-17 | 2026-08-18 | routes, schemas, retrieval wiring, and templating split out of app.py per the HANDOFF 7 contract; vendored Datastar adds live search and a streaming /status, with the no-JavaScript baseline asserted by tests (ADR-012); | 12 PostgreSQL search tests (weighted tsvector, ts_rank_cd ordering, escaped ts_headline, exact/prefix identifier paths, filters, keyset pagination, multi-megabyte index guard); `/changes` filters and pagination; bill-page excerpts and supersession notices | Deep-ranked pagination cap documented in ADR-007; awaits acceptance walkthrough |
| E operations/deploy | in_review | Claude | main | 2026-08-17 | 2026-08-18 | image/Compose health, PostgreSQL search, database+blob restore drill, UID/mount checks, `make check`, retention job with rollup and pruning tests | external HTTPS and vulnerability review pending |
| F JSON-LD/discovery | done | Codex | worktree | 2026-08-17 | 2026-08-17 | current, passed, bilingual and malicious JSON-LD tests; canonical, Open Graph, and sitemap | — |
| G semantic search | in_review | Claude | main | 2026-08-18 | 2026-08-18 | chunker, provider interface, migration 0003, `rechunk`/`reembed` backfills, hybrid RRF retrieval, pgvector cosine retrieval and HNSW index proven on PostgreSQL, versioned evaluation set | No production embedding model chosen (ADR-008); evaluation gate not run against a real model |
| H RAG | in_review | Claude | main | 2026-08-18 | 2026-08-18 | bounded answer service, injection isolation, citation verifier, no-answer and outage fallbacks, kill switch, rate limits, `/ask` and `/api/v1/ask` | Depends on Package G gate; provider and retention decision not recorded (ADR-009) |

## Assumption status

| ID | Status | Verified on | Evidence |
| --- | --- | --- | --- |
| A1 | verified | 2026-08-18 | The two current entry points return complete listings; the archive URLs return a search form, not rows (docs/upstream.md, ADR-011) |
| A2 | refuted | 2026-08-18 | Current listings expose only Kod, Tahun, Tajuk, Status. There is no presenter column and no reading-date columns; those live in a hidden per-bill detail table (docs/upstream.md) |
| A3 | resolved | 2026-08-18 | The archive is a GET /carian.html search form with static parameters; no browser automation needed (ADR-011) |
| A4 | verified | 2026-08-18 | D.R.15/2026, D.R.15/2025 and D.R.42/2025 each hold two chamber records with independent reading dates |
| A5 | open | — | ADR-002 proposed; fail-loud parser implemented |
| A6 | verified | 2026-08-18 | Every observed date is DD/MM/YYYY; tests/fixtures/parliament/live_current_dr_bm.html |
| A7 | open | — | No Malay month name or date range was observed in the current listings; the parser still accepts both. Recheck against the archive |
| A8 | open | — | Archive discovery required |
| A9 | open | 2026-08-18 | Four published phrases observed and mapped, one of which the handoff had guessed wrongly (`Lulus`, not `Diluluskan`). Still one chamber, one language, current bills only (docs/upstream.md) |
| A10 | verified | 2026-08-18 | Three documents downloaded: all native-text PDFs (`%PDF-1.4`), 17 to 33 pages, extraction succeeded on each. Served as `application/octet-stream`, so magic bytes decide validity |
| A11 | open | — | ADR-003 proposed; only the unambiguous same-bytes case is handled (docs/data-model.md) |
| A12 | open | — | First reviewed full crawl required |
| A13 | refuted | 2026-08-18 | `https://www.parlimen.gov.my/robots.txt` returns 404: no policy is published. Not "permits crawling" — there is nothing to permit. See docs/upstream.md; crawling now needs a recorded decision via ROBOTS_MISSING_POLICY |
| A14 | open | — | Rights review required. The serving path is built and tested but inert behind SERVE_ARCHIVED_DOCUMENTS (ADR-013); only this review may turn it on |

## Decision index

| ID | Title | State | Date |
| --- | --- | --- | --- |
| ADR-001 | Mypy and semantic parser selection | accepted | 2026-08-16 |
| ADR-002 | Bill identifier rules | proposed | 2026-08-16 |
| ADR-003 | Document identity and versioning | accepted | 2026-08-16 |
| ADR-004 | Official-link-only publication | proposed | 2026-08-16 |
| ADR-005 | Rollback version uniqueness | accepted | 2026-08-17 |
| ADR-006 | Runtime operations | accepted | 2026-08-17 |
| ADR-007 | Search unit weighting, ranking, and deep pagination | accepted | 2026-08-18 |
| ADR-008 | Embedding model selection deferred; vector width is schema | proposed | 2026-08-18 |
| ADR-009 | Answer provider, prompt isolation, and answer data retention | proposed | 2026-08-18 |
| ADR-010 | Retention sign-off | accepted | 2026-08-18 |
| ADR-011 | Archive is a search endpoint; no browser automation | accepted | 2026-08-18 |
| ADR-012 | Datastar for progressive enhancement, and its CSP cost | accepted | 2026-08-18 |
| ADR-013 | VersityGW S3 archive gateway; archived-document serving | accepted / proposed | 2026-08-18 |

## Open questions

| Question | Raised by | Raised on | Owner | Needed by |
| --- | --- | --- | --- | --- |
| The site publishes no robots.txt; do its terms of use permit crawling? | A13 | 2026-08-18 | Service owner | C |
| What response shape, pagination, and date partitioning does `carian.html` use? | ADR-011 | 2026-08-18 | Discovery owner | C |
| What is the complete bilingual status vocabulary? | HANDOFF A9 | 2026-08-16 | Discovery owner | B/C |
| Does a revised document normally retain its URL? | HANDOFF A11 | 2026-08-16 | Discovery owner | C |
| May stored official PDF bytes be republished? | HANDOFF A14 | 2026-08-16 | Service owner | E |
| Which embedding model covers Malay and English at an acceptable cost and licence? | ADR-008 | 2026-08-18 | Service owner | G |
| Which answer provider's data-retention terms permit not storing questions or answers? | ADR-009 | 2026-08-18 | Service owner | H |

## Manual gate log

- 2026-08-18 — Claude — Archive moved behind a VersityGW S3 gateway (ADR-013) and proved end to end against live data: three real bill PDFs downloaded, stored, hash-verified through the gateway, text-extracted (17 to 33 pages), and served over HTTP with the content hash as an ETag. Public serving remains **off**; enabling it is the A14 rights decision, not a configuration change. Two defects fixed on the way: the document worker used a literal `run_id` that violated a foreign key and had only ever run on SQLite, and validation quarantined every genuine PDF because Parliament serves `application/octet-stream`.

- 2026-08-18 — Claude — **First reviewed live crawl.** Crawl permission decided: the site publishes no robots.txt, so RFC 9309 treats crawling as unrestricted; `ROBOTS_MISSING_POLICY=allow` set and each run records a `robots_absent` warning so the decision stays visible. TLS verified through a bundle carrying the intermediate the site omits. Result: 126 records parsed from the two current listings, 67 bills and 126 chamber records published, 505 events, 127 documents queued, `make doctor` clean. Both archive targets report `failing` because the archive is a search endpoint (ADR-011) and is not implemented; the run ended `partial`. No document was downloaded. This crawl found four parser defects, all fixed and covered by tests against a fixture reduced from the stored bytes.

- 2026-08-18 — Claude — First live probe of `www.parlimen.gov.my`, limited to `robots.txt`. Two upstream facts recorded in `docs/upstream.md`: the site serves an incomplete TLS chain (leaf only, missing the Sectigo intermediate), and it publishes no robots.txt (404). Verification succeeds once the intermediate is supplied through `UPSTREAM_CA_BUNDLE`; TLS verification was never disabled. No listing page was fetched, and crawl approval remains outstanding.

- 2026-08-17 — Codex — Fresh Compose rehearsal passed for database health, one-shot migration, app readiness, non-root UID, and read-only app blob mount; external TLS and restore were not covered.
- 2026-08-17 — Codex — Isolated restore drill passed: PostgreSQL custom dump restored into a new database, seeded bill and blob reference verified, blob bytes restored and SHA-256 verified, and UID-10001 ownership confirmed. In-place destructive restore was not run.
- 2026-08-18 — Claude — PostgreSQL 16 with pgvector 0.8.1: migrations 0001 to 0003 applied to an empty database and the full suite ran green (142 passed). This covers the weighted tsvector, `ts_rank_cd` ranking, escaped `ts_headline` snippets, the multi-megabyte index guard, pgvector cosine retrieval, and HNSW index creation. It does not cover a live crawl, external TLS, or a vulnerability review.
- 2026-08-18 — Claude — Offline acceptance path rehearsed end to end on PostgreSQL 16: `make quickstart` from an empty database, then `make seed` (3 bills, 4 chamber records, 12 events, 1 recorded change), a second `seed` producing zero inserts and zero changes, `make doctor` clean, `make verify-storage` clean, and `make reparse` reporting zero changes over 10 stored snapshots. Steps 6, 13, and the external checks of the section 18 walkthrough remain untested because they need a live crawl and a real host.
- 2026-08-18 — Claude — Full suite green at 183 tests against PostgreSQL 16 with pgvector after wiring dated listing columns into events, adding the five missing anomaly kinds, and splitting the web layer. No live crawl, external TLS, or vulnerability review is covered.
- 2026-08-18 — Claude — `make evaluate` run against the development `deterministic` embedding provider. It fails the `no_answer_correct` threshold, as documented: the hashed projection has no semantics and is rejected in production. This is a harness check, **not** the Package G release gate. The gate requires a rerun against the chosen production model with the result recorded here.

Still required before release: a Content-Security-Policy review covering the `'unsafe-eval'`
grant that Datastar requires (ADR-012), dependency review, container vulnerability review, external HTTPS
validation, a crawl-permission decision now that no robots.txt exists (A13), live crawl approval, rights review, and — only if Release 3 is to ship — an embedding
model decision, an answer provider decision, and an evaluation run that meets the thresholds in
`docs/evals/README.md`.

## Requirement evidence

Release 1's "current **and archived** listings for both chambers" criterion is **not** met: the
archive is a search endpoint that is not yet crawled (ADR-011). The current listings are ingested
from live data. Everything else in Release 1 and Release 2 has automated evidence in the offline
and PostgreSQL suites. No release requirement is marked complete until the HANDOFF section 18 acceptance
walkthrough and section 22 evidence matrix are satisfied against real upstream data; every
current gate that depends on a live crawl, external TLS, or a rights determination remains open.
