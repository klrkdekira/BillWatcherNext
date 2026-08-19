# Implementation status

Last reconciled: 2026-08-18 (Asia/Kuala_Lumpur), after the archive crawl and the document drain.

This file is the ledger: the assumption register, the decision index, and the dated evidence.
[`TODO.md`](../TODO.md) is the work list derived from it — what is outstanding, who can close it, and
what closing it takes. When the two disagree, this file is right, because it carries dates.

## Package ledger

| Package | State | Owner/agent | Branch | Started | Last update | Evidence | Blockers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A scaffold/runtime | done | Codex | worktree | 2026-08-16 | 2026-08-17 | make check; locked image build; fresh Compose health; UID 10001; read-only app blob mount | — |
| B discovery/model | done | Claude | main | 2026-08-16 | 2026-08-18 | schema invariants; seventeen parser fixtures including the archive tree, its edge cases, dated columns, mixed good/bad rows and two soft-404 shapes; empty-database migration to head proven on PostgreSQL; live discovery completed for the current listings **and the whole archive** — 67 XML documents, both chambers, 1990-2024 — settling A1/A2/A3/A4/A6/A7/A8/A9/A12 and accepting ADR-002 | — |
| C scraper/versioning | in_review | Claude | main | 2026-08-16 | 2026-08-18 | offline `make seed` fixture ingestion satisfying the section 18 walkthrough step 5, idempotent on reload; `make reparse` reports zero changes at the current parser version (step 9); `make fixtures-refresh` now regenerates fixtures from stored snapshots as section 16.3 specifies; document worker, extraction history, orchestration, robots, replay, queue, versioning; **the archive is crawled** (ADR-014) and a second live archive run over 2,130 records wrote zero changes; anomalies key on the upstream document, so a permanent upstream defect stays one row; operators can acknowledge and resolve anomalies; **the whole document corpus is downloaded** — 1,295 fetched, 1,264 stored, 27,575 pages, 0.24 GB — and politeness moved into the fetcher so every request is spaced, not just listing requests | 22 scanned documents need OCR to be searchable by contents |
| D web/search | in_review | Claude | main | 2026-08-17 | 2026-08-18 | routes, schemas, retrieval wiring, and templating split out of app.py per the HANDOFF 7 contract; vendored Datastar adds live search and a streaming /status, with the no-JavaScript baseline asserted by tests (ADR-012); | 12 PostgreSQL search tests (weighted tsvector, ts_rank_cd ordering, escaped ts_headline, exact/prefix identifier paths, filters, keyset pagination, multi-megabyte index guard); `/changes` filters and pagination; bill-page excerpts and supersession notices | Deep-ranked pagination cap documented in ADR-007; walkthrough steps 1-12 evidenced, step 13 needs a host |
| E operations/deploy | in_review | Claude | main | 2026-08-17 | 2026-08-18 | image/Compose health, PostgreSQL search, database+blob restore drill, UID/mount checks, `make check`, retention job with rollup and pruning tests; dependency, container, and CSP review completed and recorded in docs/operations.md; base image pinned by digest, Python 3.12.13, security updates applied; the CSP is now the application's and is asserted by tests | A publicly trusted certificate, public DNS, and one hand-verification of the external nginx (ADR-015) |
| F JSON-LD/discovery | done | Codex | worktree | 2026-08-17 | 2026-08-17 | current, passed, bilingual and malicious JSON-LD tests; canonical, Open Graph, and sitemap | — |
| G semantic search | in_review | Claude | main | 2026-08-18 | 2026-08-18 | chunker, provider interface, migration 0003, `rechunk`/`reembed` backfills, hybrid RRF retrieval, pgvector cosine retrieval and HNSW index proven on PostgreSQL, versioned evaluation set | No production embedding model chosen (ADR-008); evaluation gate not run against a real model |
| H RAG | in_review | Claude | main | 2026-08-18 | 2026-08-19 | bounded answer service, injection isolation, citation verifier, no-answer and outage fallbacks, kill switch, rate limits, `/ask` and `/api/v1/ask`; self-hosted vLLM OpenAI-compatible provider wired by ADR-009 | Depends on Package G gate and production answer-model evaluation |

## Assumption status

| ID | Status | Verified on | Evidence |
| --- | --- | --- | --- |
| A1 | verified | 2026-08-18 | The two current entry points return complete listings in the initial HTML. The archive returns rows too, but through the tree XML the `arkib=yes` page loads, not in that page (ADR-014) |
| A2 | refuted | 2026-08-18 | Current listings expose only Kod, Tahun, Tajuk, Status. There is no presenter column and no reading-date columns; those live in a hidden per-bill detail table (docs/upstream.md) |
| A3 | verified | 2026-08-18 | The archive is a year-indexed XML tree fetched with `arkib=yes&ajx=0` then `&ajx=1&id=0_<year>`; 67 documents read, both chambers, 1990-2024. No browser automation needed. This corrects the earlier reading of `carian.html`, which is a document-text search (ADR-014, superseding ADR-011) |
| A4 | verified | 2026-08-18 | D.R.15/2026, D.R.15/2025 and D.R.42/2025 each hold two chamber records with independent reading dates |
| A5 | partially verified | 2026-08-18 | ADR-002 accepted. The prefix is the originating chamber: the Dewan Negara publishes 1,876 `D.R.` codes for bills the Dewan Rakyat introduced. Unexercised half: no `D.N.` identifier exists anywhere in 35 years of archive |
| A6 | verified | 2026-08-18 | Every observed date is DD/MM/YYYY; tests/fixtures/parliament/live_current_dr_bm.html |
| A7 | verified | 2026-08-18 | All 2,245 archived dates and every current-listing date are `DD/MM/YYYY`. No Malay month name and no range has ever been observed; 13 archived readings are `30/11/-0001`, a zero date, rejected as unparseable. The parser still accepts month names and ranges, which costs nothing |
| A8 | verified | 2026-08-18 | The archive is partitioned by calendar year, not by parliamentary term or session: 34 year nodes for the Dewan Rakyat, 33 for the Dewan Negara, 1990-2024, with gaps (neither publishes 2003) |
| A9 | verified | 2026-08-18 | The complete published set: seven Malay phrases and four English, swept across both current listings, both languages, and all 2,130 archived rows. Three appear only in the archive (`Ditarik Balik`, `Tolak`, `Bacaan Kali Kedua dan Ketiga`), so the current-listing sweep could not have closed this. Nothing published normalizes to `unknown` (docs/upstream.md) |
| A10 | verified | 2026-08-18 | The whole corpus downloaded: 1,295 documents, 1,264 stored and validated, 27,575 pages, 0.24 GB. Served as `application/octet-stream`, so magic bytes decide validity — and they had to: 31 links are dead and answered with HTTP 200 and a 23-byte `File does not exist (1)` body. 1,242 extracted, 12 empty, 10 failed; the empties are scans concentrated in 2010, 2013 and 2018, not in the oldest years (docs/upstream.md) |
| A11 | open, and half of it refuted | 2026-08-18 | **A document does not have one canonical URL**: 62 sets of byte-identical documents are published at two or more URLs, usually one per chamber. Content-hash identity (ADR-003) collapses them correctly; URL identity would have double-counted the archive. The question as asked — whether a *revised* document keeps its URL — is still open: after fetching all 1,295 documents, none has a second version, so no revision has been observed |
| A12 | verified | 2026-08-18 | Fully measured. Listings: 2,130 archived rows, 1,202 distinct identifiers, ~4 MB of XML across 67 documents. Published: 1,269 bills, 2,256 chamber records, 4,861 events. Documents: 1,295 fetched, 1,264 stored, **27,575 pages, 0.24 GB** — the whole corpus, so backup sizing is no longer provisional |
| A13 | refuted | 2026-08-18 | `robots.txt` returns 404, **and there are no terms of use either**. Every policy page the site publishes was read — Penafian, Dasar Privasi, Dasar Keselamatan, FAQ — and none mentions crawling, automated access, or reuse; `/hakcipta.html` and `/terma-penggunaan.html` do not exist. So there is nothing to permit and nothing to forbid. Crawling proceeds under the recorded RFC 9309 decision via ROBOTS_MISSING_POLICY, at one request every two seconds, with `robots_absent` raised each run (docs/upstream.md) |
| A14 | open, with the evidence gathered | 2026-08-18 | The site publishes **no licence and no permission**: the only copyright statement anywhere is the footer's `2026 © Hakcipta Terpelihara Parlimen Malaysia` — all rights reserved — and there is no terms-of-use or copyright page. Nothing supports republishing the stored bytes, so ADR-004 stands and SERVE_ARCHIVED_DOCUMENTS stays off. Whether a statutory exception applies, or whether permission should simply be requested, is a legal judgement only the service owner can make |

## Decision index

| ID | Title | State | Date |
| --- | --- | --- | --- |
| ADR-001 | Mypy and semantic parser selection | accepted | 2026-08-16 |
| ADR-002 | Bill identifier rules | accepted | 2026-08-16, accepted 2026-08-18 |
| ADR-003 | Document identity and versioning | accepted | 2026-08-16 |
| ADR-004 | Official-link-only publication | proposed | 2026-08-16 |
| ADR-005 | Rollback version uniqueness | accepted | 2026-08-17 |
| ADR-006 | Runtime operations | accepted | 2026-08-17 |
| ADR-007 | Search unit weighting, ranking, and deep pagination | accepted | 2026-08-18 |
| ADR-008 | Embedding model selection deferred; vector width is schema | proposed | 2026-08-18 |
| ADR-009 | Answer provider, prompt isolation, and answer data retention | proposed | 2026-08-18 |
| ADR-010 | Retention sign-off | accepted | 2026-08-18 |
| ADR-011 | Archive is a search endpoint; no browser automation | superseded by ADR-014 | 2026-08-18 |
| ADR-012 | Datastar for progressive enhancement, and its CSP cost | accepted | 2026-08-18 |
| ADR-013 | VersityGW S3 archive gateway; archived-document serving | accepted | 2026-08-18 |
| ADR-014 | Archive is a year-indexed XML tree; per-year targets | accepted | 2026-08-18 |
| ADR-015 | TLS terminated by an external nginx; Caddy removed | accepted | 2026-08-18 |

ADR-013 is accepted for the storage gateway. Its public-serving half remains a proposal: it is inert behind `SERVE_ARCHIVED_DOCUMENTS` and may only be accepted once ADR-004 is superseded by the A14 rights review, with the outcome recorded in the manual gate log.

## Open questions

| Question | Raised by | Raised on | Owner | Needed by |
| --- | --- | --- | --- | --- |
| Does a revised document normally retain its URL? Unobservable so far: all 1,295 documents fetched, none has a second version. Needs time, not effort | HANDOFF A11 | 2026-08-16 | Discovery owner | C |
| May stored official PDF bytes be republished? The site publishes no licence and no terms — only "all rights reserved" — so this is now a legal judgement rather than a discovery task | HANDOFF A14 | 2026-08-16 | Service owner | E |
| Which embedding model covers Malay and English at an acceptable cost and licence? Shortlisted in ADR-008, with BGE-M3 self-hosted recommended; needs the evaluation gate run and the hosting cost accepted | ADR-008 | 2026-08-18 | Service owner | G |
| Should the OCR worker be run for the 22 documents whose text will not extract (scans in 2010, 2013 and 2018)? Until then those bills are findable by metadata but not by contents | Document drain | 2026-08-18 | Service owner | C |
| Zero data retention has to be enabled per organization by arrangement with Anthropic; it cannot be switched on from this repository. Answered otherwise: the terms permit exactly what `/ask` promises, for the surface used (ADR-009) | ADR-009 | 2026-08-18 | Service owner | H |

## Manual gate log

- 2026-08-18 — Claude — **The whole document corpus is downloaded.** 1,295 documents fetched one
  request at a time, two seconds apart: **1,264 stored and validated, 27,575 pages, 0.24 GB** — the
  storage-sizing question A12 was blocking turns out to be a quarter of a gigabyte. Nothing
  dead-lettered. Four findings, all recorded in `docs/upstream.md`:

  1. **31 archive links are dead**, and the server says so with **HTTP 200**, `text/html`, and a
     23-byte `File does not exist (1)` body. Magic-byte validation refused all 31, which is exactly
     why HANDOFF 11.4 step 3 validates content instead of trusting a status code. They raised 31
     critical `document_quarantined` anomalies and `make doctor` went red — the gate working. All 31
     are now acknowledged with the reason recorded, because there is nothing to fix upstream; the
     gate is green and `/status` still shows them.
  2. **22 documents have no extractable text**, concentrated in 2010, 2013 and 2018 — scans, at
     roughly 45 KB per page. Age is not the predictor: a 1995 bill extracts cleanly. This is the
     first real justification for the optional OCR worker, and it is a 1.7% subset rather than the
     archive.
  3. **62 sets of byte-identical documents are published at more than one URL**, usually one copy
     per chamber. Content-hash identity collapsed every one; URL identity would have double-counted
     the archive. That is ADR-003's central decision, evidenced at scale.
  4. **No document has a second version**, so A11 as asked is still unobserved — but "a document has
     one canonical URL" is now definitively false.

  One defect fixed on the way, and it is the one that mattered most: **the document worker had no
  politeness delay at all.** The listing orchestrator slept between targets; the document path did
  not, so draining 1,292 PDFs would have fetched them back to back. The delay now lives in the
  fetcher, enforced per request, so a caller cannot forget it — verified by the drain taking the
  ~43 minutes it should.

- 2026-08-18 — Claude — **Everything the site publishes about crawling and reuse has now been
  read**, which is what A13 was actually asking for. There is no robots.txt *and no terms of use*:
  the complete policy set is Penafian, Dasar Privasi, Dasar Keselamatan and an FAQ, none of which
  mentions crawling, automated access, or reuse, and `/hakcipta.html` and `/terma-penggunaan.html`
  do not exist. The crawl decision therefore rests on a complete reading rather than on an
  unexamined assumption. For A14 the same absence points the other way: the only copyright statement
  anywhere is the footer's "Hakcipta Terpelihara" — all rights reserved, no licence, no permission —
  so ADR-004 stands and `SERVE_ARCHIVED_DOCUMENTS` stays off. What remains is a legal judgement, not
  a discovery task.

- 2026-08-18 — Claude — **Caddy removed; TLS is now terminated by an nginx deployed separately**
  (ADR-015). The `Caddyfile` and the `caddy` service are gone, the app publishes `127.0.0.1:8000` as
  the origin for that proxy, and the security headers stay in the application where the suite can
  assert them. HSTS became an application setting defaulted to **off**, because HANDOFF 17 says to
  enable it only once HTTPS is known good and the app cannot see the transport from behind a proxy.
  `docs/operations.md` carries the nginx configuration, including the `proxy_buffering off` that the
  status page's event stream needs and that a default proxy silently breaks.

  Removing Caddy surfaced a latent defect: the `worker` was alone on the `internal: true` network, so
  **the containerised crawler had no outbound access at all** — it would have started, reported
  healthy, and failed every fetch. Live crawling had only ever been run from the host, so nothing
  caught it. The worker is now on an `egress` network and a test keeps it there.

  Consequence recorded honestly: the TLS rehearsal below is **no longer reproducible from this
  repository**, because the proxy it exercised is gone. The application half of it is still covered
  by tests that need no proxy; the nginx half is now a once-by-hand verification against the real
  deployment, tracked in `TODO.md`.

- 2026-08-18 — Claude — **TLS and the public surface rehearsed through the real stack**, while it
  still shipped Caddy (see `docs/operations.md`). `compose.yaml` and the built image were run with `SITE_HOST=bills.localhost`
  so Caddy used its internal CA and issued no ACME request. Verified: the 308 redirect, TLS over
  HTTP/2, the certificate chain, HSTS, every application security header surviving the proxy
  unchanged, seven routes returning 200, the SSE stream arriving as `text/event-stream`, UID 10001
  with a read-only root filesystem, and `/documents/...` still 404 while serving is off. Two defects
  found: **the image could not run its own documented configuration** — `uv sync` omitted the `s3`
  extra that `.env.example` and `compose.yaml` both select, so the stack never became healthy — and
  **HSTS was not being sent**, because Caddy only adds it for a publicly trusted certificate. Both
  fixed, and a static test now compares the documented configuration against the image's dependency
  set. A publicly trusted certificate and public DNS remain the only untested part.

- 2026-08-19 — Codex — **ADR-009 corrected to the owner's actual deployment:** RAG uses a
  self-hosted vLLM OpenAI-compatible Chat Completions endpoint, not Claude. The Anthropic SDK,
  commercial ZDR assertion, and Claude-specific model blacklist are removed. The application still
  stores only operational metrics and a non-reversible query fingerprint; raw questions and
  answers are not persisted.

- 2026-08-18 — Claude — **The two deferred provider decisions are researched rather than merely
  deferred.** ADR-009 is now answered against Anthropic's published terms, read on 2026-08-18: zero
  data retention covers the Messages API, Citations, token counting and prompt caching, which is
  exactly the surface `/ask` uses, so the promise that questions are not stored can be kept. It
  excludes Batches (29-day retention) and code execution, and **Claude Fable 5 and Mythos 5 require
  30-day retention and cannot be used at all** — the one case where the most capable model is the
  wrong choice. Those constraints are now enforced in configuration, not just written down:
  `RAG_ZERO_RETENTION_CONFIRMED` must be set before RAG starts in production, and a
  retention-requiring model is refused outright. ADR-008 gains a shortlist restricted to models
  already matching the 1024-wide schema, with **BGE-M3 self-hosted recommended** — MIT licensed, no
  per-query cost, and no third-party egress, which is the only option consistent with a site that
  makes no third-party requests. Anthropic publishes no embeddings endpoint, so these are
  necessarily two different vendors. Both still need the owner: a hosting cost, and a ZDR
  arrangement.

- 2026-08-18 — Claude — **The archive is crawled. Release 1's archive criterion is met.** ADR-011
  had the mechanism wrong: `carian.html` is a full-text search over document *pages* and carries no
  bill metadata at all, while the archived listing is a `dhtmlXTree` whose XML the same page loads
  (ADR-014). Discovery swept all 67 year documents in both chambers, 1990-2024, and the crawl then
  ran live twice. First run: 70 requests, 2,130 records, published; **1,269 bills spanning
  1990-2026**, 2,256 chamber records, 4,861 events, 1,295 documents queued, all 71 coverage targets
  healthy, `make doctor` clean. Second run: 70 requests, 2,130 records, **0 inserted, 0 updated, 0
  recorded changes** — the HANDOFF 22 idempotence evidence, now over the whole corpus rather than
  three fixtures.

  The sweep closed A3, A7, A8, A9 and A12, settled the Dewan Negara and English structures, and
  let ADR-002 be accepted. It also found six defects, all fixed and covered by tests:

  1. **The English listing silently kept no dates.** Its detail labels are `The second reading` and
     `Passed At`, not the phrases a translator would guess. All 67 rows parsed and every reading
     vanished.
  2. **Three status phrases exist only in the archive** (`Ditarik Balik`, `Tolak`, `Bacaan Kali
     Kedua dan Ketiga`), so 60 archived rows would have stored `unknown` — including every
     withdrawn bill in 35 years.
  3. **One bill's title is published in several forms**, so change tracking rewrote titles on every
     crawl. Sixteen identifiers are affected; thirteen are the same title spelled differently and
     are now treated as one, and the three that genuinely differ raise a conflict instead of
     flip-flopping for ever. One of them, D.R.11/2013, is two different bills sharing a code.
  4. **A dropped connection lost the entire run.** The first live archive attempt died after 59 of
     136 requests on `RemoteProtocolError` and published nothing. Transport failures are now
     retried, and a year that still fails degrades only that year.
  5. **The archive would have published nothing even when it worked**, because 2,000 new documents
     exceed the incremental document budget and a spent budget rolls publication back. The archive
     mode now has its own budget, as HANDOFF 11.7 requires.
  6. **Anomalies for permanent upstream defects accumulated one row per run**, because they were
     keyed on the snapshot rather than the document.

  Thirteen archived readings are dated `30/11/-0001` — a zero date leaking out of the upstream
  database — and one bill code carries a stray `ARKIB` suffix. Both are retained raw and reported,
  never guessed at. `docs/upstream.md` lists every upstream defect the corpus contains.

- 2026-08-18 — Claude — **Dependency, container, and CSP review** (HANDOFF 17), recorded in full in
  `docs/operations.md`. 67 locked packages audited against PyPI advisories and OSV: no known
  vulnerabilities. Three container findings fixed: the base image was pinned by a mutable tag only
  and is now pinned by digest; Python was 3.12.5, nine patch releases behind, and is now 3.12.13
  with the full suite green on it; the image carried an outstanding `ca-certificates` security
  update and the runtime stage now applies security upgrades — which matters here because the
  crawler verifies upstream TLS against that store. Nine OS packages still carry 26 advisories for
  which Debian 12 offers no fix. The CSP review found that the policy existed **only in the
  `Caddyfile`**, so `make serve` and any other deployment sent none and nothing tested it; it is now
  set by the application and asserted on every page, along with the vendored bundle's digest. Not
  covered: external HTTPS validation, which needs a deployed host.

- 2026-08-18 — Claude — **Walkthrough step 10 satisfied against real data, including the hard
  part.** With 27,262 document-text search units built from the extracted corpus, searching
  `IMPLIKASI KEWANGAN` — a phrase that appears only inside bill PDFs, never in listing metadata —
  returns 913 ranked hits spanning 2001 to 2020, each with a highlighted snippet and page-level
  provenance ("From our stored document text, page 11"). Exact `D.R.` codes, Malay title terms,
  presenter, and the status/year/chamber filters were already covered by the PostgreSQL suite; this
  was the item that needed a real corpus rather than fixtures.

- 2026-08-18 — Claude — **Acceptance walkthrough steps 6 and 7, literally.** One approved
  `make scrape-full` run read both current listings and all 67 archived years in a single pass: 72
  requests, 2,256 records parsed, **0 inserted, 0 updated, 0 recorded changes**, all 71 coverage
  targets healthy, `make doctor` clean. `make reparse` then replayed 96 stored snapshots — the
  archive's XML among them — with zero changes and zero failures, which is step 9. Steps 1 to 5 and
  8 to 12 have automated evidence; step 13 needs a deployed host.

- 2026-08-18 — Claude — A defect this session's own work introduced, and how it was caught:
  keying parse-issue anomalies on the listing URL put a URL into `anomalies.entity_id`, a
  `varchar(36)` column meant for our own primary keys. Every SQLite test passed; **PostgreSQL
  rejected it on the live archive run** with `value too long for type character varying(36)`, and
  the run withheld publication as designed, so nothing was corrupted. Such conditions belong to an
  upstream document rather than to a row we store, so they now carry no entity and deduplicate on
  the URL. The gap that let it through is closed too: `tests/integration/test_postgres_archive.py`
  exercises the archive's ingestion, its bad rows, and its title conflicts against real
  PostgreSQL, because SQLite does not enforce column widths and the archive is where the
  wide real-world values are.

- 2026-08-18 — Claude — Full suite green at **281 tests with nothing skipped**, on Python 3.12.13
  against PostgreSQL 16 with pgvector 0.8.1 and a live VersityGW gateway. This is the first run
  covering the PostgreSQL, pgvector, and S3 paths in the same pass as everything else.

- 2026-08-18 — Claude — Archive moved behind a VersityGW S3 gateway (ADR-013) and proved end to end against live data: three real bill PDFs downloaded, stored, hash-verified through the gateway, text-extracted (17 to 33 pages), and served over HTTP with the content hash as an ETag. Public serving remains **off**; enabling it is the A14 rights decision, not a configuration change. Two defects fixed on the way: the document worker used a literal `run_id` that violated a foreign key and had only ever run on SQLite, and validation quarantined every genuine PDF because Parliament serves `application/octet-stream`.

- 2026-08-18 — Claude — **First reviewed live crawl.** Crawl permission decided: the site publishes no robots.txt, so RFC 9309 treats crawling as unrestricted; `ROBOTS_MISSING_POLICY=allow` set and each run records a `robots_absent` warning so the decision stays visible. TLS verified through a bundle carrying the intermediate the site omits. Result: 126 records parsed from the two current listings, 67 bills and 126 chamber records published, 505 events, 127 documents queued, `make doctor` clean. Both archive targets report `failing` because the archive is a search endpoint (ADR-011) and is not implemented; the run ended `partial`. No document was downloaded. This crawl found four parser defects, all fixed and covered by tests against a fixture reduced from the stored bytes.

- 2026-08-18 — Claude — First live probe of `www.parlimen.gov.my`, limited to `robots.txt`. Two upstream facts recorded in `docs/upstream.md`: the site serves an incomplete TLS chain (leaf only, missing the Sectigo intermediate), and it publishes no robots.txt (404). Verification succeeds once the intermediate is supplied through `UPSTREAM_CA_BUNDLE`; TLS verification was never disabled. No listing page was fetched, and crawl approval remains outstanding.

- 2026-08-17 — Codex — Fresh Compose rehearsal passed for database health, one-shot migration, app readiness, non-root UID, and read-only app blob mount; external TLS and restore were not covered.
- 2026-08-17 — Codex — Isolated restore drill passed: PostgreSQL custom dump restored into a new database, seeded bill and blob reference verified, blob bytes restored and SHA-256 verified, and UID-10001 ownership confirmed. In-place destructive restore was not run.
- 2026-08-18 — Claude — PostgreSQL 16 with pgvector 0.8.1: migrations 0001 to 0003 applied to an empty database and the full suite ran green (142 passed). This covers the weighted tsvector, `ts_rank_cd` ranking, escaped `ts_headline` snippets, the multi-megabyte index guard, pgvector cosine retrieval, and HNSW index creation. It does not cover a live crawl, external TLS, or a vulnerability review.
- 2026-08-18 — Claude — Offline acceptance path rehearsed end to end on PostgreSQL 16: `make quickstart` from an empty database, then `make seed` (3 bills, 4 chamber records, 12 events, 1 recorded change), a second `seed` producing zero inserts and zero changes, `make doctor` clean, `make verify-storage` clean, and `make reparse` reporting zero changes over 10 stored snapshots. Steps 6, 13, and the external checks of the section 18 walkthrough remain untested because they need a live crawl and a real host.
- 2026-08-18 — Claude — Full suite green at 183 tests against PostgreSQL 16 with pgvector after wiring dated listing columns into events, adding the five missing anomaly kinds, and splitting the web layer. No live crawl, external TLS, or vulnerability review is covered.
- 2026-08-18 — Claude — `make evaluate` run against the development `deterministic` embedding provider. It fails the `no_answer_correct` threshold, as documented: the hashed projection has no semantics and is rejected in production. This is a harness check, **not** the Package G release gate. The gate requires a rerun against the chosen production model with the result recorded here.

Still required before release. Every item is now a decision, a purchase, or a deployment — none of
it is engineering work, and each names exactly who can close it and what evidence they already have:

- **A publicly trusted certificate, public DNS, and the external nginx verified once.** TLS is now
  terminated outside this repository (ADR-015), so the proxy half of the path — the redirect, the
  chain, HSTS not being set twice, and `proxy_buffering off` for the event stream — can only be
  checked against the real deployment. *Needs: a host.*
- **The A14 rights judgement.** The evidence is gathered: the site publishes no licence and no terms,
  only "all rights reserved". The serving path is built, tested, and inert behind
  `SERVE_ARCHIVED_DOCUMENTS`. *Needs: the service owner to decide, or to ask Parliament for
  permission.*
- **A zero-data-retention arrangement** with the answer provider, if Release 3 ships. The terms are
  verified as compatible (ADR-009) and the constraints are enforced in configuration; enabling ZDR
  is a per-organization arrangement with Anthropic. *Needs: a commercial conversation.*
- **An embedding model.** Shortlisted to models that already match the schema width, with BGE-M3
  self-hosted recommended (ADR-008). *Needs: the hosting cost accepted and `make evaluate` run
  against it, with the printed gate-log line recorded here.*
- **The OCR worker**, if the 22 scanned bills should be searchable by contents rather than only by
  metadata. *Needs: a decision that it is worth building; the subset is identified.*

Done and recorded above, so no longer blocking: the crawl-permission reading (A13), the
Content-Security-Policy review, the dependency review, the container vulnerability review, the
storage-sizing question (0.24 GB), and the live archive crawl.

## Requirement evidence

Release 1's "current **and archived** listings for both chambers" criterion is **met**: both
current listings and all 67 archived years in both chambers are ingested from live data, 1,269
bills spanning 1990 to 2026, with all 71 coverage targets healthy (ADR-014). Everything else in
Release 1 and Release 2 has automated evidence in the offline, PostgreSQL, and S3 suites, which now
run in one pass with nothing skipped.

Release 1's documents are downloaded too: 1,295 fetched, 1,264 stored and validated, 27,575 pages,
0.24 GB. Two Release 1 items remain, and both are honest gaps rather than untested code:

- **The 22 unextractable documents need OCR** if their contents are to be searchable. They are
  scans, identified, and a 1.7% subset; the optional OCR worker exists in the contract and has not
  been built, because until the corpus was downloaded there was no evidence anything needed it.
- **A publicly trusted certificate has not been obtained**, because there is no deployed host.
  Everything else about the TLS path was rehearsed through the real proxy.

No release requirement is marked complete until the HANDOFF section 18 acceptance walkthrough and
section 22 evidence matrix are satisfied against real upstream data; the gates that depend on
external TLS or a rights determination remain open.
