# Implementation status

Last reconciled: 2026-08-18 (Asia/Kuala_Lumpur).

## Package ledger

| Package | State | Owner/agent | Branch | Started | Last update | Evidence | Blockers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A scaffold/runtime | done | Codex | worktree | 2026-08-16 | 2026-08-17 | make check; locked image build; fresh Compose health; UID 10001; read-only app blob mount | — |
| B discovery/model | in_progress | Claude | main | 2026-08-16 | 2026-08-18 | schema invariants; twelve parser fixtures including dated columns, mixed good/bad rows, and two soft-404 shapes; empty-database migration to head proven on PostgreSQL | Reviewed live discovery pending |
| C scraper/versioning | in_review | Claude | main | 2026-08-16 | 2026-08-18 | document worker, extraction history, orchestration, robots, replay, queue, versioning; dated columns now produce reading events with ranges and sequences and project onto chamber records; all seventeen HANDOFF 10.5 anomaly kinds raised and provoked by tests; anomalies deduplicate by kind plus entity | Reviewed live full crawl pending |
| D web/search | in_review | Claude | main | 2026-08-17 | 2026-08-18 | routes, schemas, retrieval wiring, and templating split out of app.py per the HANDOFF 7 contract; | 12 PostgreSQL search tests (weighted tsvector, ts_rank_cd ordering, escaped ts_headline, exact/prefix identifier paths, filters, keyset pagination, multi-megabyte index guard); `/changes` filters and pagination; bill-page excerpts and supersession notices | Deep-ranked pagination cap documented in ADR-007; awaits acceptance walkthrough |
| E operations/deploy | in_review | Claude | main | 2026-08-17 | 2026-08-18 | image/Compose health, PostgreSQL search, database+blob restore drill, UID/mount checks, `make check`, retention job with rollup and pruning tests | external HTTPS and vulnerability review pending |
| F JSON-LD/discovery | done | Codex | worktree | 2026-08-17 | 2026-08-17 | current, passed, bilingual and malicious JSON-LD tests; canonical, Open Graph, and sitemap | — |
| G semantic search | in_review | Claude | main | 2026-08-18 | 2026-08-18 | chunker, provider interface, migration 0003, `rechunk`/`reembed` backfills, hybrid RRF retrieval, pgvector cosine retrieval and HNSW index proven on PostgreSQL, versioned evaluation set | No production embedding model chosen (ADR-008); evaluation gate not run against a real model |
| H RAG | in_review | Claude | main | 2026-08-18 | 2026-08-18 | bounded answer service, injection isolation, citation verifier, no-answer and outage fallbacks, kill switch, rate limits, `/ask` and `/api/v1/ask` | Depends on Package G gate; provider and retention decision not recorded (ADR-009) |

## Assumption status

| ID | Status | Verified on | Evidence |
| --- | --- | --- | --- |
| A1 | open | — | Live discovery not yet approved/run |
| A2 | open | — | Fixture required |
| A3 | open | — | Archive discovery ADR proposed |
| A4 | open | — | Cross-chamber fixture required |
| A5 | open | — | ADR-002 proposed; fail-loud parser implemented |
| A6 | open | — | Parser supports claim; upstream fixture required |
| A7 | open | — | Parser/tests cover formats; upstream fixture required |
| A8 | open | — | Archive discovery required |
| A9 | open | — | Status map remains provisional pending full sweep |
| A10 | open | — | Document sample required |
| A11 | open | — | ADR-003 proposed; only the unambiguous same-bytes case is handled (docs/data-model.md) |
| A12 | open | — | First reviewed full crawl required |
| A13 | open | — | robots.txt must be fetched before crawling |
| A14 | open | — | Rights review required |

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

## Open questions

| Question | Raised by | Raised on | Owner | Needed by |
| --- | --- | --- | --- | --- |
| What exact request contract serves archived listings? | HANDOFF A3 | 2026-08-16 | Discovery owner | B/C |
| What is the complete bilingual status vocabulary? | HANDOFF A9 | 2026-08-16 | Discovery owner | B/C |
| Does a revised document normally retain its URL? | HANDOFF A11 | 2026-08-16 | Discovery owner | C |
| May stored official PDF bytes be republished? | HANDOFF A14 | 2026-08-16 | Service owner | E |
| Which embedding model covers Malay and English at an acceptable cost and licence? | ADR-008 | 2026-08-18 | Service owner | G |
| Which answer provider's data-retention terms permit not storing questions or answers? | ADR-009 | 2026-08-18 | Service owner | H |

## Manual gate log

- 2026-08-17 — Codex — Fresh Compose rehearsal passed for database health, one-shot migration, app readiness, non-root UID, and read-only app blob mount; external TLS and restore were not covered.
- 2026-08-17 — Codex — Isolated restore drill passed: PostgreSQL custom dump restored into a new database, seeded bill and blob reference verified, blob bytes restored and SHA-256 verified, and UID-10001 ownership confirmed. In-place destructive restore was not run.
- 2026-08-18 — Claude — PostgreSQL 16 with pgvector 0.8.1: migrations 0001 to 0003 applied to an empty database and the full suite ran green (142 passed). This covers the weighted tsvector, `ts_rank_cd` ranking, escaped `ts_headline` snippets, the multi-megabyte index guard, pgvector cosine retrieval, and HNSW index creation. It does not cover a live crawl, external TLS, or a vulnerability review.
- 2026-08-18 — Claude — Full suite green at 178 tests against PostgreSQL 16 with pgvector after wiring dated listing columns into events, adding the five missing anomaly kinds, and splitting the web layer. No live crawl, external TLS, or vulnerability review is covered.
- 2026-08-18 — Claude — `make evaluate` run against the development `deterministic` embedding provider. It fails the `no_answer_correct` threshold, as documented: the hashed projection has no semantics and is rejected in production. This is a harness check, **not** the Package G release gate. The gate requires a rerun against the chosen production model with the result recorded here.

Still required before release: dependency review, container vulnerability review, external HTTPS
validation, live crawl approval, rights review, and — only if Release 3 is to ship — an embedding
model decision, an answer provider decision, and an evaluation run that meets the thresholds in
`docs/evals/README.md`.

## Requirement evidence

Release 1 and Release 2 requirements have automated evidence in the offline and PostgreSQL
suites. No release requirement is marked complete until the HANDOFF section 18 acceptance
walkthrough and section 22 evidence matrix are satisfied against real upstream data; every
current gate that depends on a live crawl, external TLS, or a rights determination remains open.
