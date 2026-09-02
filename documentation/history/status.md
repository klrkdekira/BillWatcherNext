# Implementation status

Last reconciled: 2026-08-22 (Asia/Kuala_Lumpur), after the commissioner directed "prioritise
static published dataset" and the three decisions ADR-029 had left open were closed (ADR-031,
HANDOFF 28.12 as amended, Package M, TODO §0): the file-first corpus's published dataset is
a **GitHub Pages site in a separate repository** on `bills.engineers.my`, built by `make build`
into `dist/` (ADR-033, which reversed ADR-031's "committed to this repository" the same day),
publishing in **`full` mode**, **only once the corpus run widens past the pilot**, carrying the
semantic files (JSON-LD + RDF N-Quads) and never a source PDF (ADR-032). Reconciled earlier the same day after the same commissioner reordered
publication so that the file-first corpus's first public surface is a static cache of files
(ADR-029, HANDOFF 28.12), with backend serving, database integration and the step-4 split into a
persisted structure artifact with an anchored extractor (ADR-030, HANDOFF 28.5) all second.
Reconciled earlier the same day after making the file-first pipeline
publication-ready: permanent FRBR identifiers (ADR-024), Gate P1 and schema validation (ADR-025),
provenance-gated regeneration (ADR-026), metadata-only corpus publication (ADR-027), and the rdflib
semantic graph (ADR-028), recorded as HANDOFF 28.7–28.10 and Package L. Reconciled before that on
2026-08-21, after incorporating the auditable step pipeline as HANDOFF 27 (ADR-019, Package K), the
MinerU markdown reading as HANDOFF 27.7 (ADR-020), the file-first pipeline as HANDOFF 28 (ADR-021),
its Akoma Ntoso conversion step as HANDOFF 28.5 (ADR-022), and its semantic files step as
HANDOFF 28.6 (ADR-023) — all at the commissioner's direction.

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
| I legislation Stage L1 | in_review | Claude | main | 2026-08-19 | 2026-08-19 | `billwatcher.legislation` (layout reading, structural vocabulary, arrangement and body parsers, the Gate L1 comparator), `document_structures` + `provision_nodes` in migration 0004 proven to head on PostgreSQL, the `restructure` backfill and Make target, `structure_gate_failure_spike` registered in the HANDOFF 10.5 taxonomy and its test; Gate L1's outcome histogram and the two new pipeline versions on `/status`; ADR-016/017/018; `make check` green at 320 and `make test-pg` 348 passed with nothing skipped, including proof migrations 0003 and 0004 both upgrade a pre-existing database on PostgreSQL | The corpus-wide Gate L1 pass rate is unmeasured: the 1,264 stored PDFs are not reachable from a clean checkout, so the gate is proven only against constructed fixtures |
| J legislation Stages L2+ | blocked | — | — | — | 2026-08-19 | Specified in HANDOFF 26.4-26.5; no code | Every item in HANDOFF 26.7, none resolvable in code: AGC crawl policy and rights, legal sign-off on consolidation, document classification |
| K auditable step pipeline | in_progress | Claude | main | 2026-08-21 | 2026-08-21 | Step S3 built and tested: `storage/audit_tree.py` (deterministic sidecar writer, write-if-changed idempotence), `document_worker.py` (per-download tree write for accepted *and* quarantined versions, `run_fetch_documents_step`), `jobs/audit_rebuild.py` (`rebuild_documents`/`verify_documents`/`check_audit_tree`, rebuild-then-diff design), CLI + Make targets `fetch-documents` (gated behind `SCRAPE_ENABLED`/`--approve-live` like `scrape`), `verify-audit`, `audit-rebuild`; `AUDIT_TREE_ROOT` wired through config/env/compose. One S4 slice also landed: the MinerU vision-language markdown reading (`billwatcher.mineru`, `jobs/mineru_extract.py`, `make mineru-extract`, ADR-020), verified against the real hosted endpoint, not just mocks. `make check` 366 passed offline, `make test-pg` 394 passed against real PostgreSQL+pgvector+VersityGW, nothing skipped | S1/S2 (listing fetch/parse split) and the `pypdf`-based S4 tree output deliberately deferred (TODO.md §0); corpus materialisation needs the deployment host or S3 gateway |
| L file-first pipeline | in_review | Claude | main | 2026-08-21 | 2026-08-22 | `billwatcher.pipeline` behind `PipelineStore`/`FileStore` (ADR-021): steps 1–5, permanent FRBR identity, Gate P1 + schema validation, provenance and manifests, semantic files, redaction controls, CLI and Make targets. The first real slice is now measured: 123 bills, 122 document-bearing bills / 181 URL-addressed records, with Gate P1 outcomes and findings in the gate log below | Gate P1's rejected readings still need human review; 32 duplicate Expression claims remain in the store. No `DatabaseStore`/`ObjectStore` |
| M published static dataset (Pages site), then tooling | in_progress | Claude | main | 2026-08-22 | 2026-08-22 | **Cache half complete:** `pipeline.export`, `export-static`, `pipeline-export-static`, `PIPELINE_EXPORT_ROOT`; rights-gated metadata/full export, definitions, Works/Expressions index, checksums, stale-file reconciliation and write-if-changed atomicity. Real metadata export: 92 Expressions / 276 manifestations, independently checksum- and leak-verified; `make check` 647 passed offline | **Publication half not started:** the corpus run is still the 7% pilot (123 bills of ~1,269), 53 Gate P1 rejections are unreviewed (A15), **the dataset licence is unstated** (the landing page says so), and the Pages repository's history-growth policy is undecided. The site builder itself is built and tested but has never been run outside tests — `dist/` does not exist. ADR-030 split, backend serving and alternate stores remain phase two |

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
| A14 | **resolved by owner determination, 2026-08-22** (see the gate log) | 2026-08-22 | The site publishes **no licence and no permission**: the only copyright statement anywhere is the footer's `2026 © Hakcipta Terpelihara Parlimen Malaysia` — all rights reserved — and there is no terms-of-use or copyright page. Nothing supports republishing the stored bytes, so ADR-004 stands and SERVE_ARCHIVED_DOCUMENTS stays off. Whether a statutory exception applies, or whether permission should simply be requested, is a legal judgement only the service owner can make |
| A15 | partially verified | 2026-08-22 | Gate P1 ran over the pilot's 181 URL-addressed records: 124 passed, 53 rejected, 4 failed at 0.95. This measures the distribution; whether the rejected readings are false rejections remains open until a human reviews them |
| A16 | partially verified | 2026-08-20 | A read-only discovery spike (`docs/upstream.md`) found: TLS chain complete (unlike parlimen.gov.my, no CA bundle needed); `robots.txt` returns HTTP 500, not a clean 404 — a different condition from A13's, needing its own recorded decision; Terms & Conditions and FAQ read in full, confirming the s.61 disclaimer and the pre-2011 coverage boundary from AGC's own text, plus a "downloaded... for purposes of reference" clause more permissive than anything on parlimen.gov.my, and a Gazette-status nuance (s.18(4)) neither settled nor resolvable here. Unresolved: whether reprints state an "incorporating amendments up to" date — no listing or document page was fetched, and no decision to crawl has been made |

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
| ADR-016 | Layout-aware extraction uses pdfminer.six, as a second reading | accepted | 2026-08-19 |
| ADR-017 | Gate L1 blocks on structure and reports heading differences | accepted | 2026-08-19 |
| ADR-018 | The legislation corpus is served, not statically built | accepted | 2026-08-19 |
| ADR-019 | Every pipeline step is a Make target that materialises an auditable file tree | accepted | 2026-08-21 |
| ADR-020 | A MinerU vision-language markdown reading, as a local file artifact only | accepted | 2026-08-21 |
| ADR-021 | A file-first pipeline behind a storage interface; Postgres left dormant | accepted | 2026-08-21 |
| ADR-022 | The Akoma Ntoso conversion step reads structure with an LLM, not regex alone | accepted | 2026-08-21 |
| ADR-023 | Semantic files (JSON-LD + RDF N-Quads) are derived from the stored Akoma Ntoso XML | accepted | 2026-08-21 |
| ADR-024 | Permanent FRBR identifiers, built from published facts; the URL-hash scheme is withdrawn | accepted | 2026-08-22 |
| ADR-025 | Gate P1 blocks on accountability, and the rendered XML is validated against the schema | accepted | 2026-08-22 |
| ADR-026 | Regeneration is gated on input hashes, not on whether an output file exists | accepted | 2026-08-22 |
| ADR-027 | The corpus is published metadata-only, redacted at the serving boundary, behind two flags | accepted | 2026-08-22 |
| ADR-028 | The semantic graph is an rdflib dataset, serialised in sorted order; SHACL is deferred | accepted | 2026-08-22 |
| ADR-029 | The first publication surface is a public static cache of files; tooling comes after | accepted | 2026-08-22 |
| ADR-030 | The structural reading is a persisted intermediate artifact; the extractor returns anchors, not text | accepted | 2026-08-22 |
| ADR-031 | The published dataset lives in this repository, in full text, after the corpus run widens | accepted | 2026-08-22 |
| ADR-032 | The published dataset is JSON-LD first, and never carries the source PDF | accepted | 2026-08-22 |
| ADR-033 | The published dataset is a GitHub Pages site in a separate repository, built into `dist/` | accepted | 2026-08-22 |
| ADR-034 | The corpus download is resumable; only closed archive years may be skipped | accepted | 2026-08-22 |

**ADR-018 is qualified by ADR-029** for the file-first pipeline only: the static cache ships first
there and the served surface (HANDOFF 28.10) is phase two, while ADR-018 continues to govern the
Postgres-backed system unchanged (HANDOFF 26.5). **ADR-022 is amended by ADR-030**: the extractor
keeps its protocol and its LLM, but its contract becomes anchors over line-numbered markdown
rather than re-emitted body text, and the tree it returns becomes a persisted, gate-judged
artifact rather than an in-memory intermediate.

Two earlier decisions are amended rather than superseded, and both are worth reading with their
amendment beside them. **ADR-021 decision 6** — a document's identity is a hash of its URL — remains
correct for the *store* key and is corrected by **ADR-024** for anything published. **ADR-023
decision 3** — N-Quads derived from the JSON-LD dict, so the two files cannot disagree — keeps its
guarantee, but the mechanism is now one rdflib dataset serialised twice (**ADR-028**), so its
description of the implementation is history rather than contract.

ADR-027 is accepted for the *shape* of the publication decision — two questions, two controls, a
reversible heading boundary — and not for publishing anything. Both `SERVE_LEGISLATION_CORPUS` and
`LEGISLATION_PUBLICATION_MODE=full` are off, and production refuses either without its recorded
rights confirmation; the decision itself is a service-owner judgement (TODO 1.9), the same standing
as ADR-013's public-serving half below.

ADR-013 is accepted in full as of 2026-08-22: the A14 determination is recorded in the manual gate log, so its public-serving half may be enabled by setting `SERVE_ARCHIVED_DOCUMENTS=true` with `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true` — the recorded decision the validator asks the operator to assert.

## Open questions

| Question | Raised by | Raised on | Owner | Needed by |
| --- | --- | --- | --- | --- |
| Does a revised document normally retain its URL? Unobservable so far: all 1,295 documents fetched, none has a second version. Needs time, not effort | HANDOFF A11 | 2026-08-16 | Discovery owner | C |
| ~~May stored official PDF bytes be republished?~~ **Answered 2026-08-22: yes — the owner determined bills are public information** (gate log). Enabling the serving flags is the remaining operator action | HANDOFF A14 | 2026-08-16 | Service owner | E |
| Which embedding model covers Malay and English at an acceptable cost and licence? Shortlisted in ADR-008, with BGE-M3 self-hosted recommended; needs the evaluation gate run and the hosting cost accepted | ADR-008 | 2026-08-18 | Service owner | G |
| Should the OCR worker be run for the 22 documents whose text will not extract (scans in 2010, 2013 and 2018)? Until then those bills are findable by metadata but not by contents | Document drain | 2026-08-18 | Service owner | C |
| Zero data retention has to be enabled per organization by arrangement with Anthropic; it cannot be switched on from this repository. Answered otherwise: the terms permit exactly what `/ask` promises, for the surface used (ADR-009) | ADR-009 | 2026-08-18 | Service owner | H |
| May `lom.agc.gov.my` be crawled, and under what licence may its Acts and reprints be used? A second publisher, so A13 and A14 are reopened for it rather than inherited. Blocks every stage after L1 | HANDOFF 26.7 | 2026-08-19 | Discovery owner, then Service owner | J |
| Is a Malaysian-qualified lawyer available to review the consolidation methodology and the disclaimers? Publishing consolidated law asserts what the law *is*, which is a stronger claim than mirroring a record, and a higher bar than the A14 rights question | HANDOFF 26.7 | 2026-08-19 | Service owner | J |
| Who staffs the Gate L1 review queue, and to what SLA? An unstaffed review queue silently becomes a coverage gap. This is the same question the OCR decision raises and should be answered once | HANDOFF 26.3 | 2026-08-19 | Service owner | I |
| Where can Stage L1 reach the stored corpus? The 1,264 PDFs are on the deployment host or in the S3 gateway, not in a clean checkout, so the Gate L1 pass rate over real Malaysian typography cannot be measured from here | HANDOFF 26.7 | 2026-08-19 | Service owner | I |
| ~~Where should the completed static cache live?~~ **Answered 2026-08-22, twice.** First: committed to this repository (ADR-031). Then, the same day and superseding it: **a GitHub Pages site in a separate repository** on `bills.engineers.my`, built by `make build` into `dist/` (ADR-033). What remains is execution, not decision — plus two choices it creates: the dataset licence, still unstated and admitted as such on the landing page, and whether the Pages repository's rebuild history is accepted, squashed, or orphaned (TODO §0) | ADR-029, ADR-031, ADR-033 | 2026-08-22 | Service owner | M |
| Is Gate P1's coverage threshold (0.95) acceptable? The pilot is now measured (124 pass / 53 reject / 4 fail over 181 stored records), but the false-rejection rate is unknown until a human reads the rejected artifacts. **Now publication-affecting (ADR-031):** once the dataset is committed, a false rejection is a bill silently missing from the published corpus, so this review is a release prerequisite rather than a measurement | ADR-025, ADR-031 | 2026-08-22 | Service owner, then a developer | L |

## Manual gate log

- 2026-08-22 — Claude — **A JSON-LD viewer is added to the published page (HANDOFF 1.19), and a
  publication defect was found while building it.** Directed: "I want viewer for the jsonld too" —
  which is the detail pane deliberately not built in the entry below, now asked for.

  **How it works.** A hash route (`#/akn/my/bill/dr/2025/34/msa@`) fetches that Expression's own
  published `.jsonld` and renders it: the provision tree built from `hasPart`/`isPartOf`, with
  `eli:number`, `schema:name` headings and — where the mode publishes them — `schema:text` bodies,
  beside a facts panel (number, language, type, provision count, Work) and the raw JSON in a
  `<details>`. It reads the **dataset itself**, never a parallel index, so what a reader sees cannot
  drift from what they download. Each table row carries `data-route`/`data-title`/`data-files`, so
  opening a record costs exactly one request. Routes are deep-linkable, honour the back button, and
  a failed fetch degrades to a link to the raw file rather than a blank pane.

  **Verified by actually running the shipped script, not by reading it.** Node was used to
  `--check` both the in-page script and the boot script, and then to execute the real IIFE against a
  minimal DOM shim and a genuine 34-node full-text record from the store. It rendered the facts, the
  nested clause → subsection tree with numbers, headings and Malay provision text, and the raw-JSON
  section, with no `[object Object]` and no `undefined` anywhere. That harness is a one-off
  verification and is **not** wired into `make check`: doing so would make the offline suite depend
  on Node, which is a new dependency this change does not need. The Python tests pin the markup
  contract instead — including the viewer's one real assumption, that a record route plus `.jsonld`
  is always a file the release published, checked across all three representation sets so a future
  set that dropped JSON-LD fails the suite rather than 404-ing on every record.

  **Defect found, and it is a release blocker rather than a nuisance.** Every `@id` in the pilot's
  stored JSON-LD and N-Quads reads `http://127.0.0.1:8000/…`, because step 5 derives its base IRI
  from `PUBLIC_BASE_URL` and the pilot ran with the development default. §28.7's whole claim is that
  the path *is* the identifier, so a published graph asserting localhost identifiers contradicts the
  corpus's own contract, and no consumer could dereference them. The fix is offline and cheap — set
  `PUBLIC_BASE_URL` to the published domain and re-run `make pipeline-generate-semantic`, which
  ADR-026 regenerates rather than skips because `base_iri` is part of the recorded provenance — but
  it must happen before the first release, and it is now an item in `TODO.md §0`. **It was not run
  here:** it rewrites 92 stored artifacts while the operator's corpus download is in progress, and
  the correct base URL is theirs to confirm. The viewer limits the blast radius by displaying the
  *path* and discarding the authority, but that is presentation, not a fix to the data.

  Three new tests (row carries the viewer's data, every route resolves to a published file under all
  three representation sets, and the identifier plus raw links survive with scripting off), for
  **689 passed, 28 skipped, 2 deselected**; Ruff clean, strict mypy clean across 93 source files.
  The page is 86.9 kB for 92 bills, well-formed, still carrying no build timestamp. Rendered to a
  scratch path and sent to the operator: **no `dist/` was created by this session**, and the store
  was only read.

- 2026-08-22 — Claude — **§28.13's landing page rebuilt in the design language of the operator's
  `cheeleong.dev/graph20` reference corpus (HANDOFF 1.18).** Directed: "I want to improve the
  index.html, this is my another site, use it as reference https://cheeleong.dev/graph20/". The
  reference is the same genre — a source-faithful JSON-LD reference corpus — so its vocabulary
  transfers directly rather than by analogy.

  **Adopted from the reference:** the token palette verbatim (warm paper light `#f7f5f1`/`#fffefa`
  with rust `#a53e2a`; slate dark `#15191b`/`#1d2326` with `#ee9975`), Inter at 15px/1.65 for UI
  against `ui-serif`/Iowan Old Style for display type, the dark brand mark with its amber glyph,
  pill badges, stat cards with big serif numerals, two-column resource groups, `h3.sect` rules,
  `.tablewrap` + `table.data`, the `data-theme` toggle with a `localStorage` key and a
  before-paint boot script so a saved dark choice never flashes light, the skip link,
  `:focus-visible` outlines, `prefers-reduced-motion`, and the 920px/560px breakpoints.

  **Deliberately not adopted:** the three-pane nav/list/detail app shell. That shape exists to route
  between records, and this tree has no per-record HTML pages — a record's detail *is* its
  `.jsonld` file. A single landing page with a filterable index is the honest analogue; inventing
  detail pages would have been scope the direction did not ask for.

  **Added beyond the reference, for this corpus:** a client-side filter over the corpus table with a
  live "N of M bills" count and an empty state, a Year column derived from the §28.7 identifier
  rather than guessed, and the identifier-guarantee and provenance sections that ADR-031 requires of
  a published dataset.

  **Two properties held as invariants, both tested.** The page is **self-contained** — no external
  stylesheet, font, script or image; a published dataset must not break because a third-party host
  went away, and a corpus page that phones home leaks its readers. And it is **progressively
  enhanced**: every row is in the HTML, so the corpus is readable and crawlable with scripting off,
  while the filter and the theme toggle are hidden by CSS until the script adds a `js` class, so the
  page never renders a control that does nothing.

  **The licence became configuration, empty by default, and is still not guessed.**
  `PIPELINE_SITE_LICENCE`/`PIPELINE_SITE_LICENCE_URL` fill the licence slot, the header badge and
  `<link rel="license">`. While unset the page says plainly that terms are pending and that the
  dataset is unlicensed for redistribution. The reference site publishes as CC BY 4.0, which makes it
  the obvious candidate here — but a grant is the owner's to make, so it is offered rather than
  assumed, and `TODO.md §0` now records that setting two variables is all it takes.

  Six new tests: the pending-licence wording appears and nothing implies `CC BY`; a configured
  licence produces the `rel="license"` link and the badge and drops the pending note; the rows
  survive with scripting off and both controls are CSS-hidden until `js`; the page contains no
  `http://` and no off-domain `https://` reference, no external stylesheet and no `<script src=`; a
  title carrying quotes and markup cannot break out of the `data-search` attribute; and the Year
  column comes from the identifier. `make check` green: Ruff clean, strict mypy clean across 93
  source files, **686 passed, 28 skipped, 2 deselected**.

  Rendered against the live pilot catalogue for review — 50.1 kB for 92 works, 92 rows, well-formed
  with no unclosed or mismatched tags, and still no build timestamp, so a rebuild over an unchanged
  corpus writes nothing. Written to a scratch path and sent to the operator: **no `dist/` was
  created**, and the corpus download they started in parallel was only read from, never written to.

- 2026-08-22 — Claude — **The corpus download is made resumable and given one command
  (`make pipeline-download`), with a deliberately narrow skip rule (HANDOFF 28.2 as amended,
  ADR-034).** Directed: "the pipeline should download all the bills, skip if exists locally" — the
  gating item of §0, since the published dataset cannot represent the corpus while the pipeline has
  read only the pilot's 123 bills of ~1,269.

  **Half of it was already true, and is now evidenced rather than assumed.** Step 3
  (`fetch_documents`) already iterated every bill in the store and skipped anything
  `store.has_document` held, which is where the cost is (1,264 PDFs at one request every two
  seconds); step 1 already fetched every archive year when given no `--archive-years` limit, so the
  pilot's narrowness came from that flag, not from a missing capability. What "download all the
  bills" needed was one command: `make pipeline-download` runs `fetch-listings` (no limit) →
  `parse-listings` → `fetch-documents`.

  **Step 1 had no skip at all, and now has one — for closed archive years only.** A year before the
  current calendar year cannot gain rows, so a stored successful snapshot is the whole answer.
  `PipelineStore` gains `has_listing`, and step 1's counts gain `skipped`.

  **The narrowness is the decision, not an implementation detail.** `robots.txt`, both current
  listings, both archive indices and the **current** calendar year are always re-fetched. Listings
  are mutable and are the only route by which a new bill or a newly closed year is discovered, so a
  naive "skip if it exists locally" over a current listing would not save a request — it would make
  the crawl silently stop tracking Parliament while still reporting success. A stored non-200 also
  does not count as present, so a re-run retries a failure rather than cementing it.
  `--refetch-archive` forces the closed years for the case where re-reading the archive is the point
  of the run.

  **Five new tests**, each pinning one of those choices: a second crawl skips both closed years and
  requests neither (`skipped: 2, fetched: 5`) while still re-requesting robots and all four targets;
  with `current_year=2024` the 2024 archive **is** re-read and only 2011 is skipped; a bill added to
  the current listing between two runs is found by the second, which is the coverage hole a naive
  skip would open; a stored HTTP 500 is retried and then stores successfully; and
  `skip_existing=False` re-fetches all seven. The pre-existing exact-dict assertion on step 1's
  counts was updated for the new `skipped` key. `make check` is green: Ruff clean, strict mypy clean
  across 93 source files, **680 passed, 28 skipped, 2 deselected**.

  **No crawl was run.** This is live, outward-facing work against Parliament's servers — hours of
  requests at the mandated two-second spacing — so it is the operator's to start. Politeness is
  unchanged: skipping reduces how many requests are made and never shortens the delay between them.
  One accepted limitation recorded rather than fixed: ~31 document URLs answer HTTP 200 with a
  23-byte `File does not exist (1)` body (A10), so they never store, never count as present, and are
  retried every run at about a minute in total. Recording a negative result would raise a question
  ADR-034 does not need to answer — when a dead link should be retried — so it is left deliberate.

  **A test-suite defect found and fixed while checking this, and it had already fired.** The
  autouse settings-isolation fixture *unset* the configuration variables, which left
  `PIPELINE_DATA_ROOT`, `PIPELINE_EXPORT_ROOT`, `PIPELINE_SITE_ROOT` and `AUDIT_TREE_ROOT` at their
  defaults — paths **relative to the working directory**, which during a test run is the repository.
  Any test reaching a step that writes would therefore write into the developer's real
  `pipeline-data/`, `public-cache/` or `dist/`. One did: a full 194-file `dist/` (92 JSON-LD + 92
  N-Quads + definitions + `index.html`, `CNAME`, `.nojekyll`) appeared in the working tree, built
  from the real pilot store, on a day the operator had explicitly asked that `dist/` not be created.
  It was gitignored throughout, so nothing entered git, and it has been removed. The
  `export-static` command tests avoided this by redirecting both roots to `tmp_path`; the
  `build-site` command test added earlier did not, which is the door that was left open. Both halves
  are now fixed: that test pins its roots and asserts no tree was written, and the fixture pins all
  four writable roots inside `tmp_path` for **every** test, so the accident is structurally
  impossible rather than avoided by each test remembering. `test_the_legislation_corpus_ships_off_
  and_metadata_only` now asserts the *field* default for `pipeline_export_root` rather than an
  instance's, which is strictly stronger: environment can no longer mask it. A full `make check`
  was then confirmed to leave no `dist/` behind.

- 2026-08-22 — Claude — **A GitHub Pages site tree is built (step 7, HANDOFF 28.13, ADR-033), and
  the hosting answer is reversed: the dataset goes to a *separate* repository, not this one.**
  Directed: "create a directory called dist that I can commit to another repo as github page. This
  contains the index.html and the semantic files such as jsonld and rdf, the build script should
  allow me to set prefix such as 'bills.engineers.my' (this should be the default)," then "dist
  should be part of the make target build, do not create youself."

  **The reversal, recorded rather than overwritten.** ADR-031 decision 1 (this morning) put the
  published tree in this repository. ADR-033 withdraws that: the dataset is a Pages site in a
  separate repository on `bills.engineers.my`. `dist/` is gitignored here and `public-cache/` stays
  gitignored, so nothing in this repository carries the dataset. ADR-031's other decisions stand
  (`full` mode; publish only after the corpus widens), as does ADR-032 (no source PDFs), whose
  published set widens to `semantic` — JSON-LD **and** RDF N-Quads, this project's own phrase for
  "the semantic files" (28.6) — for the site surface only. The Akoma Ntoso XML is still unpublished.

  **Built:** `billwatcher pipeline build-site` + `make build` (with `PREFIX=`) →
  `PIPELINE_SITE_ROOT` (default `dist/`), plus `PIPELINE_SITE_PREFIX` (default
  `bills.engineers.my`) and `PIPELINE_SITE_REPRESENTATIONS` (default `semantic`). The tree is the
  28.12 dataset plus `index.html`, `CNAME` (the bare host, which is how Pages learns the domain)
  and `.nojekyll`. The landing page carries the counts, how to fetch and verify, what the
  identifiers guarantee, the provenance and disclaimer, and a table of every published Work.

  **The substantive engineering is that the two surfaces became shared code, not parallel code.**
  `build-site` and `export-static` both call the new `export.build_projection`, so gate selection,
  FRBR identity, same-Expression deduplication, `pipeline.redact` at the publication boundary, and
  the source-bytes refusal have exactly one implementation. A site able to publish what the dataset
  export withholds is now impossible by construction rather than by review. `write_tree` is shared
  too, so the site gets the same atomic, write-if-changed, scoped-reconciliation discipline — and
  the scoping is no longer defensive: the site root may be a checkout of the publishing repository,
  so sparing `.git/`, its `README.md`, its `LICENSE` and its workflows is the normal case.

  **Verified, 22 new tests.** The tree carries the three site files beside the semantic files and no
  `.xml`; the page lists every Work, escapes upstream titles (a title carrying `<script>` is
  rendered inert), and links only files that exist; a rebuild over an unchanged store reports
  `written: 0, removed: 0` with identical mtimes, which is what proves the page carries **no build
  timestamp** — otherwise every rebuild would be a commit; changing the prefix rewrites exactly
  three files (`index.html`, `CNAME`, `checksums.sha256`) and leaves the dataset bytes alone,
  because the data does not depend on where it is served; a pasted `https://` or trailing slash is
  normalised, while a path, a port, `localhost` or an empty string is **refused** rather than
  written verbatim into `CNAME`; building into a seeded checkout leaves `.git/`, `README.md`,
  `LICENSE` and `.github/workflows/` byte-identical with `removed: 0`; and the site refuses on
  missing rights, redacts in `metadata` mode, and withholds a gate-rejected reading exactly as
  `export-static` does. `index.html`, `CNAME` and `.nojekyll` are all named in
  `checksums.sha256`, so a mirror can verify the whole tree. `make check` is green: Ruff clean,
  strict mypy clean across 93 source files, **675 passed, 28 skipped, 2 deselected**.

  Rendered against the real pilot catalogue for a sanity check (to a scratch path, not to `dist/`):
  27.6 kB for 92 Works, 92 table rows, 184 file links, well-formed with no unclosed or mismatched
  tags, canonical set to `https://bills.engineers.my/`, and no timestamp anywhere.

  **`dist/` was not created, as directed** — `make build` is the operator's to run, which also keeps
  the irreversible act (building, then committing to a public repository) in their hands. The
  standing "no GitHub CI, ever" constraint is untouched: Pages serves committed files and nothing
  runs in Actions.

  **One release blocker surfaced by having a page at all.** ADR-031 listed a licence for the
  project's own output as a prerequisite and it has not been chosen, so `index.html` publishes an
  explicit *"Licence: not yet stated … treat it as unlicensed for redistribution"* note. That is
  honest but not releasable: it must be settled before the first commit to the public repository,
  and it is now an item in `TODO.md §0`. Content types are a known limitation — Pages decides what
  `.jsonld` and `.nq` are served as and it cannot be configured, so `index.json` names the formats
  and the extension is the contract.

- 2026-08-22 — Service owner (recorded by Claude) — **"Don't commit the pdf, prioritise the jsonld
  for now": the first release narrows to JSON-LD, and "no source PDFs" becomes enforced rather than
  incidental (ADR-032).** Two instructions with one concern — what actually enters the repository
  now that the entry below commits the dataset to it.

  **JSON-LD first.** `PIPELINE_EXPORT_REPRESENTATIONS` is added to `billwatcher.config` as
  `Literal["jsonld", "all"]` defaulting to `jsonld` — the same idiom and the same reasoning as
  `LEGISLATION_PUBLICATION_MODE`, so the narrow set is the default and widening is one recorded
  value change. JSON-LD is the representation usable without an XML toolchain, self-describing
  through the context that ships in `definitions/`, and the same graph as the N-Quads by
  construction (ADR-028). `index.json` now carries a `representations` field so a consumer can tell
  a narrow release from a wide one without probing paths for 404s. **"For now" was read as narrowing
  the release, not retiring the formats:** the XML and N-Quads are still generated, still in the
  store, still reserved on the same §28.7 identifier, and widening is additive with no pipeline
  rerun. Narrowing back reconciles too, so the tree and `checksums.sha256` cannot disagree.

  **No source PDFs, now enforced.** ADR-029 decision 5 already kept `pipeline-data/` out of git and
  the exporter never could emit a PDF — the direction described existing behaviour. What changed is
  the consequence of a future mistake: with the tree committed, a manifestation type that carried
  source bytes would be a permanent publication, not a local bug. `export._refuse_source_bytes`
  now rejects any payload whose path ends `.pdf` or whose bytes begin `%PDF-`, before checksums are
  taken or anything is written. Republishing the official bytes stays a separate and still-closed
  question (A14 covered readings of bills; ADR-004 and `SERVE_ARCHIVED_DOCUMENTS` hold the rest
  shut), and this guard keeps the static dataset from pre-empting it.

  **Remeasured on the real pilot, in `full` mode.** A JSON-LD-only release is **3.52 MB over 92
  files, 38.3 kB per Expression**, against 12.15 MB over 276 files (132.1 kB) for all three — 29%
  of the bytes and a third of the files. At corpus scale that is ~33–46 MB over ~870–1,200 files
  rather than ~115–160 MB over ~2,600–3,600, which materially reduces the history-growth problem
  the entry below records without resolving it. The export reported the same corpus counts as every
  run before it (181 documents → 92 exported / 57 skipped-rejected / 0 no-identity / 32 duplicates
  / 21 conflicting / 0 failed) and `index.json` recorded `representations: ["jsonld"]`; an
  independent sweep of all 99 files found no `.pdf` path and no `%PDF-` payload.

  Six new tests cover it: a default release publishes only `.jsonld` and says so in `index.json`;
  widening to `all` is additive and leaves the JSON-LD bytes untouched; narrowing back removes the
  other two and cleans the manifest; no export carries a PDF, asserted end to end **and** against
  the guard directly with both a smuggled `%PDF-` payload and a `.pdf` path. Four existing tests
  were pinned to `representations="all"` so the Akoma Ntoso redaction path stays exercised rather
  than silently dropping out of coverage with the narrowed default. The new setting was registered
  in `tests/conftest.py`'s `_LEAKY_SETTINGS` — the hand-maintained isolation list caught its own
  omission, which is what it is for. `make check` is green: Ruff clean, strict mypy clean across 92
  source files, **653 passed, 28 skipped, 2 deselected**.

  Nothing was published: `public-cache/` is still gitignored, the rights flags are still `false`,
  no export was committed, and the measurement exports were written to a scratch directory outside
  the repository. HANDOFF is at 1.15 (§25.13, §28.12 further amended, Package M acceptance grown),
  with ADR-032, `TODO.md §0` and this ledger updated to match.

- 2026-08-22 — Service owner (recorded by Claude) — **"Prioritise static published dataset": the
  goal moves from a locally produced cache to a published dataset, and the three decisions ADR-029
  left open are closed (ADR-031).** ADR-029's task boundary was explicitly a cache *produced
  locally and not published*; the word **published** moves publication into scope, which forces the
  three questions ADR-029 had assigned to the owner. Answered:

  1. **Where it lives — committed to this repository.** `public-cache/` stops being gitignored and
     becomes tracked content, so the corpus, the code that produced it, and its `checksums.sha256`
     share one commit and one review path. A separate repository and a sync to a static host behind
     ADR-015's nginx were both offered and not taken. This closes the open question recorded
     earlier today.
  2. **Which mode — `full`.** Real legislative text, requiring
     `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true` alongside the corpus confirmation, both resting on
     the A14 determination. The reason recorded: a `metadata` tree carries **no** provision text at
     all — independently verified as 0 provisions across all 276 pilot representations — which
     makes it a catalogue rather than a dataset.
  3. **What counts as the dataset — not the pilot.** The pilot's 92 Expressions are ~7% of ~1,269
     bills. The pipeline runs over the stored corpus first; the first release is dated and states
     its scope.

  **Deliberately unchanged, and recorded so a later session does not "tidy" them away.** The rights
  confirmations stay `false` by default in `billwatcher.config`, `.env.example` and
  `.env.development` — ADR-031 records which posture is *authorised*, not a new default, and a
  fresh clone must not be able to publish by accident. `pipeline.redact` is not removed or
  weakened and its tests still run: `full` is a reversible posture, not the deletion of the
  publication-boundary control. `pipeline-data/` is still never committed (ADR-029 decision 5).
  ADR-018 and ADR-027 still govern the Postgres-backed system untouched. Stages L3–L4 output still
  may not enter the dataset (§1.7's legal sign-off, which A14 does not satisfy).

  **Sizing, measured rather than estimated,** by exporting the real pilot in both modes: `metadata`
  is 6.84 MB of dataset over 276 files (74.4 kB per Expression); `full` is 12.15 MB over the same
  276 files (132.1 kB per Expression); definitions are 0.26 MB either way. Extrapolated to the
  corpus at the pilot's 68.5% Gate P1 pass rate that is ~870 Expressions, ~115 MB and ~2,610
  manifestation files, rising to ~160 MB and ~3,600 files if the pass rate improves. The one-time
  size is acceptable; **the compounding cost is re-export churn**, because ADR-026 regenerates
  every document when `AKN_VERSION` or the renderer moves, so each such bump commits a fresh copy
  of the whole tree into history permanently. Whether that is accepted, squashed, or moved to an
  orphan branch is now an explicit item in `TODO.md §0`, to be decided **before** the tree is first
  committed — git history is the one publication channel where withdrawal requires a history
  rewrite.

  **Nothing was published by this entry.** No export was committed, `public-cache/` is still
  gitignored, and the flags remain `false`; the full-mode export used for sizing was written to a
  scratch directory outside the repository and not to the tracked tree. This entry records a
  direction and its decisions, and the goal documents were updated to match: HANDOFF 1.14
  (§25.12, §28.12 amended, Package M restructured with a publication half and its acceptance
  criteria), ADR-031, `TODO.md §0` rewritten as an ordered publication work list, and this ledger.
  The remaining work is execution: widen the corpus run, review the 53 Gate P1 rejections, write
  the publication contract (scope, licence, attribution, identifier guarantee), decide the
  history-growth policy, then release.

- 2026-08-22 — Claude — **Package M's cache half independently re-verified against the real
  pilot, and one latent defect in the export root fixed.** Every acceptance criterion was re-checked
  from the tree and the store rather than from the entry below, and all of them hold. Reproduced
  from `pipeline-data/` in `metadata` mode with the corpus rights confirmation asserted:
  **181 document records → 92 exported, 57 skipped-rejected, 0 skipped-no-identity, 0 incomplete,
  32 same-Expression duplicates, 21 conflicting readings, 0 failed**, writing 283 files
  (276 manifestations = 92 Expressions x 3, five definition files, `index.json`,
  `checksums.sha256`) — identical to the counts recorded below.

  Independent verification, not the exporter checking itself. The exported set equals the store's
  gate-passing set **exactly** (92 distinct passing Expressions; 0 exported records that are not
  `status == "passed"`, 0 non-passing-only Expressions present, 0 passing Expressions absent);
  store verdicts recount to 124 passed / 50 mismatch / 3 empty_tree / 4 failed = 181, so
  124 passes collapse to 92 Expressions + 32 duplicates and 50+3+4 = the 57 skipped. All 282
  checksum entries verify, `checksums.sha256` is correctly not self-named, and no payload on disk
  is unnamed. `redact.contains_provision_text` — the reader, not the redactor — found
  **0 leaks across all 276 public representations**. Every manifestation path matches
  `akn/my/bill/<chamber>/<year>/<number>/<lang>@.<ext>` and equals its own §28.7 Expression
  identifier plus extension (all 276 are chamber `dr`, language `msa`, years 2024-2026); the 276
  paths listed in `index.json` are exactly the 276 on disk, and no Expression lacks a title. Both
  exported XSDs are byte-identical to the vendored copies, with the OASIS copyright and the CC BY
  4.0 notice intact. All three refusals were exercised through the real CLI and each exits 2
  **with `ENVIRONMENT=development`**, confirming the gate is unconditional on environment. A second
  real export reported `written: 0, removed: 0`, and all 283 files were confirmed byte- and
  `st_mtime_ns`-identical.

  **Defect found and fixed: the export step reconciled the whole export root.**
  `export._remove_unexpected` unlinked every file it had not itself written. Probed on a scratch
  root, a re-export destroyed `.git/` (leaving the repository unusable), `CNAME`, `.nojekyll`,
  `robots.txt` and a hand-written `README.md` — 22 files. This was latent only because
  `public-cache/` currently holds nothing but the export, and it directly contradicts the one open
  §0 decision: two of ADR-029's three hosting options (commit the cache to a repository, or sync it
  into a static host's document root) put exactly those files beside the export. Reconciliation is
  now scoped to the namespaces this step owns — `_MANAGED_ENTRIES` = `akn/`, `definitions/`,
  `index.json`, `checksums.sha256` — so stale exported files are still expunged while foreign files
  are left alone. Two tests pin both halves: a re-export over a root seeded with `.git/`, `CNAME`,
  `.nojekyll`, `README.md` and `assets/` reports `removed: 0` and leaves every byte intact; a
  stale `akn/.../msa@.xml` and a leftover `definitions/*.json` are still removed, with the emptied
  directory pruned. The fix is behaviour-preserving on the real cache: the export re-ran to the
  same counts and the same 283 files, unchanged in hash and mtime.

  `make check` is green — Ruff clean, strict mypy clean across 92 source files,
  **649 passed, 28 skipped, 2 deselected** (the 647 below plus these two). `pipeline-data/` and
  `public-cache/` remain gitignored and untracked (`git ls-files` returns nothing for either); the
  cache was produced locally and was **not** published, uploaded, pushed, or added to git. The
  `document.structure.json` JSON Schema that §28.12 lists under `definitions/` is still absent
  because ADR-030's artifact does not exist yet; no phase-two work was started. The remaining §0
  item is still the owner's hosting decision.

- 2026-08-22 — Codex — **Package M's public-static-cache half is complete and exercised over the
  real pilot** (HANDOFF 28.12, ADR-029). `pipeline/export.py`, CLI `billwatcher pipeline
  export-static`, Make target `pipeline-export-static`, and `PIPELINE_EXPORT_ROOT` (default
  `public-cache/`) now project only explicit Gate P1 passes onto their FRBR Manifestation paths.
  The command refuses in every environment without `LEGISLATION_CORPUS_RIGHTS_CONFIRMED=true`, and
  refuses `full` without `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true`. In `metadata` mode the AKN is
  redacted and both semantic forms are rebuilt from the redacted N-Quads graph at the export
  boundary; the store remains full text.

  The exported definitions are the unmodified vendored `akomantoso30.xsd` and its required
  `xml.xsd` dependency, the exact JSON-LD context used by `semantic.render_jsonld`, and a generated
  JSON rendering of the §26.2 structural vocabulary. The main XSD's embedded notice says OASIS
  provides it under CC BY 4.0. The authoritative licence grants reproduction and sharing subject
  to attribution and retention of supplied creator/copyright/licence/source notices
  (`https://creativecommons.org/licenses/by/4.0/legalcode.en`, sections 2(a) and 3(a)); the export
  copies both schemas byte-for-byte and adds `definitions/OASIS-AKN-NOTICE.md` with OASIS, licence,
  and upstream-source attribution. **Redistribution-terms check: satisfied on that basis, with all
  embedded notices preserved.** The JSON Schema for `document.structure.json` is not present
  because ADR-030's artifact is phase two and does not exist yet.

  **Pilot topology and Gate P1 measurement.** `pipeline-data/` contains 123 bill records and 122
  document-bearing bills, represented as 181 URL-addressed document records because 59 bills were
  linked and fetched through both chambers. Current verdicts at the 0.95 threshold are **124
  passed / 53 rejected / 4 failed** (the 53 are 50 `mismatch` plus 3 `empty_tree`); 177 verdicts
  carry coverage, with min `0.0`, p25 `0.991`, median `1.0` (passing: min `0.95`, p25 `0.998875`,
  median `1.0`; rejected: min `0.0`, p25 `0.258`, median `0.9231`). Documents carrying each
  blocking finding: `low_text_coverage` 27, `duplicate_eid` 18, `missing_num` 16,
  `sequence_order` 9, `unanchored_run` 8, `sequence_gap` 5; language disagreements: 0. The four
  failures are endpoint/request failures recorded as `StructureExtractorUnavailable`. These are
  measurements, not a threshold verdict: the rejected artifacts still need human review.

  Replaying step 5 filled three missing semantic trios (`eligible: 3, converted: 3, failed: 0`).
  The real `metadata` export, with both rights confirmations asserted, then reported **92 exported
  Works/Expressions, 57 skipped non-passing records, 0 skipped-no-identity, 0 incomplete, 32
  same-Expression candidates deterministically deduplicated, 21 conflicting promoted readings,
  and 0 failed**. It wrote 283 files: 276 manifestations, five definition files, `index.json`, and
  `checksums.sha256`. An independent audit verified all 282 non-self checksum entries, found no
  unnamed payload, and `redact.contains_provision_text` found **0 leaks across all 276 public
  representations**. A second real export reported `written: 0, removed: 0`; fixture coverage
  separately pins identical hashes and mtimes.

  **Store/spec discrepancy, retained rather than concealed.** Fifty-eight of the 59 cross-chamber
  pairs carry byte-identical source PDFs; D.R.33/2025 differs between chamber URLs. Of 32 pairs
  where both readings passed, 21 produced different promoted artifacts despite identical source
  hashes. The exporter ranks the originating-chamber record first (then newest version and stable
  document key), so filesystem traversal never decides a permanent path, and exports a sole
  later-chamber pass when that is the only pass. `pipeline verify` still reports the 32
  same-Expression claims, correctly: the cache projection is deterministic, but the store's URL
  identity and the public FRBR identity are many-to-one and its independently generated readings
  disagree. Resolving that belongs to the phase-two identity/version tooling; no store evidence was
  deleted or rewritten for this export.

  Acceptance evidence: eight exporter tests (passing-only, both command refusals, independent
  metadata leak check, checksum verification, hash+mtime no-op, no-identity absence, deterministic
  duplicate ranking) plus the existing redaction/semantic/config suites. `make check` is green:
  Ruff clean, strict mypy clean across 92 source files, **647 passed, 28 skipped, 2 deselected**.
  `pipeline-data/` and `public-cache/` are both gitignored; the cache was produced locally and was
  not published, uploaded, pushed, or added to git. The remaining §0 decision is where it lives.

- 2026-08-22 — Service owner (recorded by Claude) — **The A14 rights determination: Parliament
  bills are public information, and no copyright restriction applies to republishing them.**
  Stated by the owner in their own words — "there's no copyright because this is public
  information" — and recorded here because the A14 row has said since 2026-08-18 that this is a
  legal judgement only the service owner can make. The record keeps its honesty either way: the
  site's only copyright statement remains the footer's `© Hakcipta Terpelihara Parlimen Malaysia`
  with no licence and no terms of use (`docs/upstream.md`), so this entry is the owner's judgement
  that legislative texts are public information notwithstanding that footer — the position many
  jurisdictions take for official texts of a legislative nature — not a discovery that the footer
  changed.

  What this unlocks, each still a deliberate flag flip rather than a default:
  `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true` (stored PDF bytes may be served,
  `SERVE_ARCHIVED_DOCUMENTS`, ADR-004/ADR-013), `LEGISLATION_CORPUS_RIGHTS_CONFIRMED=true` and
  `LEGISLATION_PUBLICATION_MODE=full` (the corpus may be served with provision text, ADR-027), and
  the N-Quads dump is no longer rights-blocked (ADR-018) — though it remains unbuilt, and shipping
  it is still gated on its own hard runtime control per TODO §1.7. The `KEEP_HEADINGS` residual
  recorded in TODO §1.9 is moot in full-text mode.

  What this deliberately does **not** cover, in the record's own words: consolidated law remains a
  higher bar than A14 and must not be folded into it (TODO §1.7 — stating what the law *is* needs a
  Malaysian-qualified lawyer's sign-off), and `lom.agc.gov.my` is a different publisher whose
  crawl-and-reuse questions are reopened, not inherited (HANDOFF 26.7). This determination covers
  Parliament's bills: the stored bytes, and readings derived from them.

  Closes TODO §1.2 and §1.9.

- 2026-08-22 — Claude — **The file-first pipeline is made publication-ready: permanent FRBR
  identifiers, a fidelity gate, provenance-gated regeneration, schema validation, and a
  metadata-only publication posture** (HANDOFF 28.7–28.10, ADR-024 through ADR-028, Package L).
  Nine defects were fixed. Three of them would have put wrong facts on the permanent public record,
  which is why this is one entry rather than five.

  1. **The published identifier was a hash of a URL.** Step 4 minted
     `/akn/my/{type}/{year}/doc-<sha256(url)[:8]>` — opaque (nothing in it names a bill), unstable
     across a URL change (and 62 sets of byte-identical documents are already published at two or
     more URLs, §25.6 item 13), and it split one bill's Malay and English readings into two
     unrelated Works, which is the exact relationship FRBR exists to express. The same renderer
     hard-coded `msa` on every document, so an English reading was published as Malay.
     `pipeline/frbr.py` now owns every published IRI: Work `/akn/my/bill/dr/2026/15`, `…/msa@`,
     Manifestation `…/msa@.xml`, provision `…/msa@/~cl_5__subsec_1`, with the originating chamber
     in the AKN subtype slot per ADR-002 and nothing mutable anywhere in the string (ADR-024).
     Language now comes from a declared fact at import cross-checked against the document's own
     Arrangement heading, and a document with no language on the record **fails** rather than
     defaulting. The bill slug as a single path segment was considered and rejected — it is not
     truncatable, which is the ELI property ADR-018 adopted.
  2. **A model's reading of the law was published unchecked.** ADR-022 makes the canonical Akoma
     Ntoso a model's output, and a model that drops clause 7 produces a well-formed document that
     is wrong. `pipeline/fidelity.py` adds Gate P1 (ADR-025): `duplicate_eid`, `missing_num`,
     `sequence_gap`/`sequence_order` exactly, and one threshold — text coverage over *distinct*
     tokens of the extractor's own view of the markdown, because an Arrangement entry contributes
     no new distinct word while a dropped page or schedule does. The threshold is
     `AKN_GATE_MIN_TEXT_COVERAGE` (default 0.95) precisely because the real corpus is unmeasured
     (A15). A rejected document keeps `document.akn.gate.json` (written on every path) and
     `document.akn.rejected.xml`, and no `document.akn.xml` — a review item, not a discard, the
     same discipline ADR-017 set for Gate L1.
  3. **The renderer's output was not valid Akoma Ntoso.** Validated against the published OASIS XSD
     for the first time, it failed: `<content>` beside child elements, three near-identical FRBR
     blocks missing `FRBRcountry`/`FRBRsubtype`/`FRBRnumber`/`FRBRlanguage`/`FRBRformat`, and
     `FRBRauthor` pointing at organisations that were never declared. Every one of those documents
     would have been rejected by a consumer's AKN tooling, which is the only reason to use the
     standard. The schema is vendored with recorded digests (`pipeline/schemas/`), validated by
     `xmlschema` — pure Python, `py.typed`, no native code, the same reasoning ADR-016 used against
     `pdfplumber`.
  4. **Every step decided its work by asking whether a file existed**, so this very change — a new
     IRI scheme, a rewritten renderer, a rebuilt graph — would have regenerated **nothing**, and
     the corpus would have kept publishing IRIs the code no longer mints with nothing to detect it.
     `pipeline/provenance.py` makes the *inputs* the gate: source hashes plus code, gate, model and
     prompt versions, compared against the stored record. A provenance record deliberately carries
     no timestamp and no run id — either would make every re-run rewrite it and destroy the "a
     repeat run writes nothing" guarantee that is how idempotence is checked here (ADR-026).
     Volatile facts live in the per-run manifest only.
  5. **A failing step said `failed: 1` and nothing else.** `pipeline/reporting.py` adds
     `StepResult`/`StepFailure`: the histogram the CLI echoes, plus every failure named by bill,
     document and version with its reason, bounded at 50 in any written record.
  6. **Writes were not atomic**, so a reader — a later step, a verify pass, the serving surface —
     could observe a half-written artifact. `storage/audit_tree.write_atomically` is now shared by
     both pipelines; `_write_if_changed` still short-circuits identical bytes, so an unchanged file
     keeps its mtime.
  7. **The semantic serialiser was hand-rolled and lossy.** `_escape_literal` handled `"`, `\` and
     `\n` but not `\r` or `\t`, so a carriage return in bill text produced a malformed quad, and no
     literal carried a language tag — in a bilingual corpus, a consumer could not tell Malay from
     English. Step 5 is now one `rdflib.Dataset` serialised twice, which keeps ADR-023's
     cannot-disagree guarantee by a different mechanism, with both outputs **explicitly sorted**
     because rdflib promises no stable order and byte comparison is this pipeline's idempotence
     mechanism (ADR-028). pySHACL is deliberately not added: Gate L5's shapes check `amends` and
     `validFrom`, which Stages L3/L4 would have to produce first.
  8. **There was no publication posture at all.** ADR-027 implements ADR-018: the store keeps full
     text privately and `pipeline/redact.py` redacts at the *serving boundary*, so the rights
     decision is a configuration change rather than a corpus regeneration — the same posture
     ADR-004 already takes for PDF bytes. Two flags, not one: `SERVE_LEGISLATION_CORPUS` for the
     metadata-only surface (in production requiring `LEGISLATION_CORPUS_RIGHTS_CONFIRMED`) and
     `LEGISLATION_PUBLICATION_MODE=full` for text (additionally requiring the A14 confirmation,
     `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED`), because gating the lower-risk artifact while leaving
     the higher-risk one open would be, in ADR-018's words, exactly backwards. **Provision headings
     are published in metadata-only mode** — the project owner's explicit judgement, on the reading
     that a heading is the same class of bounded fragment as a bill title, which this site already
     publishes and which ADR-004 permits; `redact.KEEP_HEADINGS` isolates it so an adverse review
     narrows it in one line.
  9. **A cycle and a stray default.** `Node`/`strip_markdown_line` moved to `pipeline/tree.py` to
     break an `akn` ↔ `fidelity` import cycle, and `PUBLIC_BASE_URL` with a trailing slash was
     minting IRIs with a doubled separator (`https://host//akn/…`), now stripped by a validator.

  **Checked directly, in a throwaway store, and quotable as evidence.** One constructed Malay bill
  (`D.R.15/2026`) through steps 4 and 5 with the deterministic regex extractor, no network and no
  model call: identity `/akn/my/bill/dr/2026/15` with `msa@`/`eng@` as two Expressions of it and
  `slug_for` round-tripping to `dr-15-2026`; step 4 `{"eligible": 1, "converted": 1, "rejected": 0,
  "failed": 0}` and the rendered XML **valid against the vendored OASIS XSD**; step 5 `{"eligible":
  1, "converted": 1, "failed": 0}` with `@ms`-tagged literals; the version directory holding exactly
  the eleven expected filenames and `iter_unexpected_files` returning nothing; **a second run of
  both steps wrote nothing at all** — every file identical by hash *and* mtime, which is the
  ADR-026 claim tested rather than asserted; `redact_akn` output carrying no provision text and
  still schema-valid, and both redacted semantic representations carrying no `schema:text`. Refusals
  checked the same way: a bill record with no originating chamber, year or number raises
  `FrbrIdentityError` rather than minting a placeholder IRI, and `parse_work_path` /
  `parse_expression_segment` return `None` for a two-digit year, a zero-padded number, an unknown
  document type, an unknown language and an unknown extension — every one of which a caller turns
  into a 404 rather than a filesystem path.

  **Gate P1 caught the real thing it was built for, on the first document put through it.** With
  the same fixture at the default 0.95 threshold and the regex extractor — which ADR-022 records as
  unable to separate an Arrangement of Clauses from the body — the gate rejected the document with
  `low_text_coverage, sequence_order`, wrote the verdict and `document.akn.rejected.xml`, and left
  no `document.akn.xml` behind. `sequence_order` is exactly the table-of-contents bleed signature
  (1, 2, then 1 again). One calibration observation worth recording before anyone reads the default
  as tuned: structural furniture words (`Susunan`, `Fasal`, `Bahagian`) never appear in a node's
  number, heading or text, so on a five-node constructed document those three words alone cost 8%
  of the distinct-token coverage (33 of 36 tokens covered). On a real 200-clause bill that is
  noise; on a short document it is most of the budget, which is one more reason the threshold is
  configuration rather than a constant.

  **Deliberately not claimed.** No pass rate over the real corpus: nothing has been fetched into
  `pipeline-data/`, and the 1,264 stored PDFs are not reachable from a clean checkout — the same
  blocker §1.8 of `TODO.md` already carries for Gate L1, and 0.95 is a starting point rather than a
  finding. The ELI predicates are **not** SHACL-validated (Gate L5, deferred with its reason in
  ADR-028), so they are our reading of ELI rather than a certified one. There is **no version chain**:
  a bill revised at a new URL resolves to the same Expression IRI, which A11 says has never been
  observed and ADR-024 says is a change to that ADR when it is. The `dn` branch of the identifier
  scheme has never seen real data, because no `D.N.` code exists anywhere in 35 years of archive
  (A5).

  **Closing run, 2026-08-22.** `make check` green: `ruff check` clean over `src tests migrations`,
  strict `mypy src` clean across 91 source files, and **626 passed, 28 skipped, 2 deselected** (the
  skips are the PostgreSQL and S3 suites, the deselections the live tests) — up from 446 before this
  work. `make test-pg` is green too — **654 passed, nothing skipped** — which is the run that matters
  for the dormant Postgres-backed system, because this change did reach two of its dependencies: the
  new atomic-write helper in `storage/audit_tree.py` and the `SCHEDULE_ORDINALS` rename in
  `legislation/vocabulary.py`. `uv lock --check` resolves 80 packages; by the counting command in
  `docs/operations.md` that
  is **79 locked requirements**, four more than the previous review recorded (`rdflib`, `xmlschema`
  and their two transitive dependencies, all pure Python). Ten files still fail
  `ruff format --check`; all ten predate this work and none was touched by it.

  **This work was adversarially reviewed before it landed, and the review is the most useful thing
  in this entry.** Thirty-one independent passes over the change — five reviewers writing findings,
  each finding then handed to a separate agent instructed to refute it — produced 26 reported
  findings, of which 23 survived refutation and 3 were correctly dismissed as recorded trade-offs.
  All 23 are fixed. Recording the notable ones, because every single one of them would have been
  invisible in production and several were invisible to a passing test suite:

  - **A rights leak, the most serious defect in the change.** `KEEP_HEADINGS = True` published
    provision headings, justified in ADR-027 as "the same class of *bounded* fragment as a bill
    title" — but nothing bounded what reached the field. Malaysian amendment bills carry no marginal
    note and run the whole provision in after its number, so entire drafted provisions became
    headings and were served verbatim in all four representations, at default settings, while the
    A14 rights review is open. The redaction self-check stayed silent because it only inspected
    `<content>`. Fixed in two independent layers (`akn.split_marginal_note` at parse time,
    `redact.publishable_heading` at the serving boundary) with the self-check extended to fire on it.
  - **A gate that would have rejected the corpus it was written to protect.** Coverage counted a
    bill's front matter — cover page, long title, enacting formula — which no provision tree can
    hold, so a *faithful* reading of a real bill PDF scored 0.71-0.81 against a 0.95 threshold. The
    structural-keyword exclusion (`BAHAGIAN`, `SUSUNAN FASAL`) was a second, smaller instance of the
    same error, costing 5.2% on a short document. Both were invisible against the provision-only
    markdown the tests used: **a threshold can only be calibrated against the shape of the real
    input.**
  - **Gate P1 read a Part's roman number as a paragraph letter**, so `BAHAGIAN I` followed by
    `BAHAGIAN II` expected `j` and reported a gap — rejecting essentially every multi-Part bill, the
    exact ADR-017 failure the gate is written to avoid. Found independently by three reviewers.
  - **Two real inputs were missing from the staleness key**: the bill record (which supplies
    `FRBRdate` and `<longTitle>`) and the declared language (which is a *permanent component of the
    Expression IRI*). A correction to either would never have reached the published corpus.
  - **Continuity was blind to a constant offset**: a tree numbered 3, 4, 5 for a document printed
    1, 2, 3 passed at coverage 1.0 with every eId and provision IRI off by two.
  - **A failing re-read left the previous reading promoted** beside a `mismatch` verdict, so the
    served document and the confidence statement printed next to it described different renders.
  - **Unauthenticated 500s and identifier aliasing** from validating the number segment with
    `str.isdigit()`, which accepts every Unicode digit: `٢` aliased the same Work at 200 and `²`
    raised out of `int()`. A `$`-anchored guard also let a URL with a trailing newline into a `Link`
    header, and one corrupt sidecar 500'd every listing page in a chamber.
  - **`validate_akn` could be induced to read a local file**, because `xmlschema` resolves a short
    string argument as a path.
  - Smaller but real: chapters restarting inside each Part were rejected; a document-wide run was
    assembled level-order rather than in document order; an invented tree passed against markdown
    with no recoverable text; an AKN `preamble` made the render schema-invalid; an unnumbered
    `JADUAL` read faithfully by the LLM path was rejected; manifests at second granularity
    overwrote each other; and a bilingual Work page attributed one language's provenance to both.

  A second, smaller review pass over the *fixes* then found five more, of which one mattered:
  withdrawing a gate-rejected reading removed its Akoma Ntoso but left the semantic pair derived
  from it, whose provenance names that XML as its source — so a run in which every step behaved
  correctly ended with `pipeline verify` reporting the store as damaged, and the corpus holding a
  graph describing an unpublished reading. The withdrawal now cascades. The other four were an
  unwired safety net on the HTML path (the control was applied but the independent second opinion
  was not — the same shape as the defect above it), two docstrings that had become false about their
  own code, and an empty `<heading/>` element that asserted a provision had a blank heading where
  the disclaimer promises none is shown.

  The pattern across all of them is worth naming, because it is the reason to review rather than to
  trust a green suite: almost every one passed every test, because the tests and the code were
  written from the same understanding. What caught them was fixtures shaped like real documents, and
  reviewers told to try to break the thing rather than to confirm it. Note also that the review of
  the fixes found a defect *in a fix* — which is the argument for reviewing corrections at least as
  carefully as the code they correct.

  Evidence beyond the direct run above: `pipeline/frbr.py`, `fidelity.py`, `provenance.py`,
  `reporting.py`, `redact.py`, `akn_schema.py`, `tree.py`, `schemas/` (vendored XSD, digests
  re-checked with `sha256sum` and matching `schemas/README.md`), the rewritten `akn.py`,
  `semantic.py` and `store.py`, `config.py`'s four new settings and their production validator, and
  `version.py`'s `AKN_VERSION`/`AKN_FIDELITY_GATE_VERSION`/`SEMANTIC_VERSION`. Tests: the changed
  modules' own suites (`tests/unit/test_pipeline_akn.py`, `test_pipeline_semantic.py`,
  `test_pipeline_store.py`, `test_config_gates.py`, `tests/integration/test_pipeline_akn_step.py`,
  `test_pipeline_semantic_step.py`) plus new per-module suites for `frbr`, `fidelity`, `provenance`,
  `redact` and `akn_schema`, landing with the code in this same change.

- 2026-08-21 — Claude — **Step 5 of the file-first pipeline, ELI-style semantic files (JSON-LD +
  RDF N-Quads), is built from the stored Akoma Ntoso XML** (HANDOFF 28.6, ADR-023), directed as
  "after akn, then it should be to the semantic files such as jsonld and rfg" — read as RDF
  N-Quads, flagged as an interpretation of "rfg" for the commissioner to correct if wrong. Fully
  offline: no LLM, no network, no new configuration (`base_iri` reuses the existing
  `public_base_url`).

  `pipeline/semantic.py`: `parse_akn` reverse-parses `document.akn.xml` back into the same `Node`
  shape `render_akn` produced it from, plus the FRBR URI and root element name — step 5 depends
  only on step 4's file output, never on step 4's in-memory tree, so the two steps stay
  independently replayable. `build_jsonld` builds one flat ELI-style `@graph` (one entry per
  document and per provision, `hasPart`/`isPartOf` edges, `eli:number`/`schema:name`/`schema:text`
  literals); `render_nquads` flattens that *same* dict into one named-graph N-Quads line per edge
  or literal, rather than walking the AKN tree a second time, so the two files cannot disagree —
  an entry missing from one is structurally missing from the other. `pipeline/store.py` gained
  `has_semantic`/`save_jsonld`/`save_rdf`. A malformed or unreadable `document.akn.xml` is counted
  `failed`, not raised, since one bad file must not stop the rest of a batch.

  Evidence: 10 new tests, all offline (`tests/unit/test_pipeline_semantic.py`,
  `tests/integration/test_pipeline_semantic_step.py`), including one pinning that a malformed AKN
  file fails without raising and one pinning that JSON-LD and N-Quads agree on the same document.
  `uv run pytest` 418 passed offline (28 PostgreSQL-only skipped, 2 deselected); `make test-pg` 446
  passed against real PostgreSQL — the dormant Postgres-backed system remains unaffected; `uv run
  billwatcher doctor` clean; `uv run billwatcher pipeline generate-semantic` on an empty store
  returns `{"eligible": 0, "converted": 0, "failed": 0}`, checked directly.

- 2026-08-21 — Claude — **Step 4 of the file-first pipeline, markdown-to-Akoma Ntoso conversion,
  is built with vLLM-assisted structure extraction** (HANDOFF 28.5, ADR-022), directed as "next up
  for pipeline after markdown conversion is conversion to the oasis format," then "Akoma Ntoso XML
  parsing should use the help of the vllm server." Still entirely file-only, per standing
  direction: no database or object-store code anywhere in `billwatcher.pipeline`.

  `pipeline/store.py` gained four methods (`has_markdown`/`load_markdown`/`save_markdown`,
  `has_akn`/`save_akn`), writing `document.md`/`document.akn.xml` beside the existing
  `document.pdf` in the same version directory — markdown itself stays out of scope (the
  operator's own vLLM endpoint at `https://llm.loqasi.io/v1/` produces it, separately).
  `pipeline/akn.py`: `Node`, the deterministic `assign_eids` (never delegated to a model, the
  same discipline HANDOFF 26.2 already applies to `wId`), `render_akn` (`<bill>` for Fasal/Clause,
  `<act>` for Seksyen/Section, FRBR identification from the bill's own year and the document's
  content-addressed key), and a `MarkdownStructureExtractor` protocol with two implementations:
  `RegexMarkdownStructureExtractor` (deterministic, reuses `billwatcher.legislation.vocabulary`
  as-is — pure text classification, no database or PDF-layout dependency) for tests and explicit
  offline use, and `pipeline/akn_llm.py`'s `VllmMarkdownStructureExtractor` (production path) for
  everything else. `build_structure_extractor` refuses outright when unconfigured — no silent
  regex fallback in production.

  **A live smoke test against the real endpoint** (`https://llm.loqasi.io/v1`, model
  `qwen-3.8-27b`) — not part of the automated suite, mirroring this project's `test-live` pattern
  — found the model correctly solving the exact problem this design exists for (telling a
  document's Arrangement of Sections apart from its body, which the regex extractor's own module
  docstring documents as unsolved) and correctly reading a Part's title into its `heading` field
  from context. It also found **one real bug**: every parenthesised token came back wrapped in its
  own punctuation (`"(1)"`, `"(a)"`, `"(i)"` instead of `"1"`, `"a"`, `"i"`), which would have
  poisoned every eId beneath those nodes with literal parentheses. Fixed two ways — the prompt now
  states the rule with worked examples, and `_normalize_num` strips it defensively regardless of
  what the model returns, since a prompt instruction is a request, not a guarantee. Re-ran the
  same smoke test after the fix and confirmed clean eIds
  (`part_II__cl_3__subsec_1__para_a__subpara_i`) end to end, including a full, well-formed
  Akoma Ntoso document.

  Evidence: 23 new tests, all offline/mocked (`tests/unit/test_pipeline_akn.py`,
  `tests/unit/test_pipeline_akn_llm.py`, `tests/integration/test_pipeline_akn_step.py`, plus one
  config-gate test), including the pinned regression for the parenthesis-stripping bug. `make
  check` 408 passed offline (28 PostgreSQL-only skipped); `make test-pg` 436 passed against real
  PostgreSQL, nothing skipped — the dormant Postgres-backed system remains unaffected; `make
  doctor` clean; `uv run billwatcher pipeline convert-to-akn` (unconfigured) refuses with exit 2,
  checked directly.

- 2026-08-21 — Claude — **A parallel file-first pipeline is built, behind an explicit storage
  interface, at the commissioner's direction** (HANDOFF 28, ADR-021): "revisiting from scratch,
  database and object store are for later... the pipeline should work with interface of input,
  such as file and also from db or object store," then "do not attempt to parse the pdf for me
  too, I have vllm openai compatible endpoint https://llm.loqasi.io/v1/ for that."

  New package `billwatcher.pipeline`, importing nothing from `billwatcher.models`/`billwatcher.db`
  or any Postgres-backed scraper/jobs module — the entire existing system (§6-§27, Packages A-K,
  including the MinerU work recorded just below) is left in place, untouched, dormant. `store.py`
  defines `PipelineStore` (a protocol: listings/bills/documents, save+iterate) and `FileStore`, its
  only implementation; every step function is written against the protocol, not `FileStore` by
  name, so a database or object-store backend is a later, additive extension rather than a
  rewrite. `targets.py`, `listings.py` (`fetch_listings`/`parse_listings`), `bills.py`
  (`merge_listing_into_bill`, pure), and `documents.py` (`fetch_documents`, content-addressing a
  document by its URL since there is no database to assign an id) implement the three steps,
  reusing `billwatcher.scraper`'s already-pure `fetch`/`policy`/`robots`/`normalize`/
  `parse_listing`/`parse_archive` unchanged — none of them ever imported a database model, so
  nothing about HTML/XML parsing, HTTP fetch policy, or identifier normalisation needed
  rewriting. New CLI sub-app (`billwatcher pipeline fetch-listings|parse-listings|fetch-documents`)
  and Make targets, the two live steps gated behind `SCRAPE_ENABLED`/`--approve-live` exactly like
  the Postgres-backed commands. PDF parsing/extraction is explicitly out of scope: nothing in this
  package renders a page or calls a model.

  **One real bug found and fixed while testing against real fixtures**, not merely against
  hand-picked unit cases: `FileStore.iter_listings` processes stored listings in storage-key
  order, not fetch order, so when a bill is referenced by both chambers — D.R.15/2026, the exact
  fixture case behind assumption A4 — a blind `last_seen_at = observed_at` overwrite could settle
  with `last_seen_at` earlier than the bill's own `first_seen_at`, purely as an artifact of
  processing order rather than real chronology. Fixed with a monotonic max and pinned by a unit
  test that reproduces the ordering directly, plus the integration test that first surfaced it.

  Evidence: 19 new tests, all offline (`tests/unit/test_pipeline_store.py`,
  `tests/unit/test_pipeline_bills.py`, `tests/integration/test_pipeline_listings.py` using real
  `current_dr_bm.html`/`current_dn_bm.html`/`archive_index_dr.xml`/`archive_year_dr_2024.xml`/
  `archive_year_dn_2011.xml` fixtures, `tests/integration/test_pipeline_documents.py`). `make check`
  385 passed offline (28 PostgreSQL-only skipped, as always); `make test-pg` 413 passed against
  real PostgreSQL, nothing skipped — confirming the existing Postgres-backed system is genuinely
  unaffected, not just untouched in source; `make doctor` clean; the CLI's live-fetch gate refuses
  without `--approve-live`, checked directly. **Not run**: the new pipeline against the real
  Parliament site — no listing or document has been fetched into `pipeline-data/` yet, since doing
  so needs the same explicit live-crawl approval every other live step in this project requires.

- 2026-08-21 — Claude — **A second, independently versioned markdown reading via a hosted MinerU
  vision-language model is built and verified against the real endpoint** (HANDOFF 27.7, ADR-020),
  directed as a follow-up: "use MinerU instant [`https://mineru.loqasi.io`] ... still local file
  based, but this time as the markdown artefacts."

  New package `billwatcher.mineru`: `render.py` rasterises stored PDF pages with `pypdfium2`
  (BSD-3-Clause/Apache-2.0, the same reasoning ADR-016 used to reject PyMuPDF's AGPL licence);
  `client.py` wraps the vendor `mineru-vl-utils` client behind a project-owned
  `PageBlockExtractor` protocol — the same shape `EmbeddingProvider`/`AnswerProvider` already use
  — because the vendor client builds its own internal `httpx.Client` with no test-transport
  injection point and checks the served model at construction time; `markdown.py` assembles the
  model's `ContentBlock` list into markdown, trusting the model's own reading order rather than
  re-deriving one from bounding boxes (multi-column legislative typesetting is exactly where that
  guess goes wrong); `service.py` ties render → extract → assemble into one status
  (`succeeded`/`empty`/`failed`), mirroring `parse_document.extract_pdf`'s vocabulary.
  `jobs/mineru_extract.py` is additive and file-based only: it never writes to
  `document_extractions` — which would trip the exact single-writer landmine TODO 2.4 already
  documents (`persist_current_extraction` demotes every row for a version regardless of extractor
  name) — and decides eligibility from whether `04-text/.../mineru@<version>/document.md` already
  exists, not from a database row, since nothing about this reading needs the database at all. A
  quarantined download still gets a directory, tagged by its own `validation_status`, rather than
  being silently skipped.

  New dependencies, both permissively licensed and audited the same day: `mineru-vl-utils`
  (Apache-2.0, base install only — no `vllm` extra, since this project calls a remote hosted
  endpoint) and `pypdfium2` (BSD-3-Clause/Apache-2.0). New configuration, off by default because
  sending official document images to a third-party host is a data-handling decision (ADR-020,
  matching ADR-009's treatment of the RAG endpoint): `MINERU_ENABLED`, `MINERU_BASE_URL`,
  `MINERU_MODEL_NAME`, `MINERU_API_KEY`, `MINERU_RENDER_DPI`, `MINERU_TIMEOUT_SECONDS`. New Make
  target `mineru-extract` (dry-run default).

  **A live smoke test against the real hosted endpoint found and fixed one real bug that no
  mocked test could have caught**, precisely because no mocked test constructs the vendor client
  at all: `MineruHttpExtractor.model_name` read `self._client.model_name`, but the vendor
  `MinerUClient` delegates to an inner backend-specific client at `.client`, and the resolved
  model name lives on *that* object. First discovered when the live smoke script raised
  `AttributeError`; fixed, and pinned by `tests/unit/test_mineru_client.py`, which fakes the
  vendor client's structural shape (a `.client.model_name` attribute) rather than the network, so
  the regression cannot reappear silently. The same live run also confirmed `http://` 301-redirects
  to `https://` on this endpoint and that the vendor's own model-name auto-detection is the right
  default (the server reports a full snapshot path as its model id, not a clean name, so hardcoding
  one in configuration would have been wrong). The full pipeline was proven end to end against real
  inference: a three-page synthetic Act rendered at 150 DPI, sent through `two_step_extract`, and
  reassembled into markdown that correctly recovered the Arrangement headings, body text, and a
  marginal amendment annotation — using a throwaway in-memory database and a throwaway audit-tree
  directory, never the shared dev Postgres instance.

  Evidence: `make check` 366 passed offline (28 PostgreSQL-only skipped, as always); `make test-pg`
  394 passed against real PostgreSQL 16 + pgvector + VersityGW, nothing skipped; `make doctor`
  clean; `uv run billwatcher mineru-extract` (unconfigured) refuses with exit 2, checked directly.
  **Not run**: `make mineru-extract` against the shared dev database's fixture-seeded queue — doing
  so would mean real, uncontrolled calls to a live third-party endpoint outside what this session's
  direction authorized for that shared state; the live verification instead used an isolated
  throwaway database, exactly as documented above.

- 2026-08-21 — Claude — **`make completeness` added: a heuristic check for holes in a
  chamber-year's bill numbering** (HANDOFF 10.4, 16.3; v1.7), in response to "test the
  completeness of bills," scoped after clarification to corpus coverage rather than record-level
  or per-document completeness.

  `operations.find_bill_number_gaps` restricts itself to years whose archive coverage target is
  closed (`expected_interval_hours == 0`) — the existing signal for "this year's listing has been
  read in full and cannot change" — and reports missing integers in each chamber-year's number
  range. An open or partially-crawled year is deliberately excluded, since a hole there is just a
  bill not yet fetched, not evidence of anything missing; nothing in the assumption register
  claims Parliament's numbering has no legitimate gaps either, so this is a pointer for a human to
  check against the archive, not a gate — it raises no anomaly and does not affect `make doctor`.

  Checked directly against the dev database (fixture-seeded, not a real crawl): every archive
  coverage row there carries `expected_interval_hours = 720` (sampled as "newest year," per
  fixture selection), so no year qualifies as closed and the command correctly reports `[]` rather
  than flagging fixture sparsity as missing bills. **Not yet run against the real corpus** — same
  reachability limit as the Gate L1 pass-rate measurement (`TODO.md` §1.8): the 1,264 stored
  documents and the coverage rows a real archive crawl produces are not available from a clean
  checkout.

  Evidence: six new tests (`tests/integration/test_completeness.py`) covering a detected gap, a
  clean sequential year, an open year's gap correctly ignored, a year with no coverage row at all
  correctly ignored, chamber isolation, and a bill with an unparsed number/chamber correctly
  excluded rather than miscounted. `make check` 337 passed offline, `make test-pg` 365 passed
  against real PostgreSQL, nothing skipped.

- 2026-08-21 — Claude — **Step S3 of the auditable pipeline (the PDF download step) is built,
  scoped exactly to the commissioner's follow-up: "work on the PDF download pipeline… do not
  begin the processing yet."** S1/S2 (the listing fetch/parse split) and S4–S7's tree output
  remain deliberately unbuilt; `TODO.md` §0 records why and what unblocks them.

  What landed: `storage/audit_tree.py` (path layout, the deterministic sidecar serializer, and
  the write-if-changed rule that makes both the live step and `audit-rebuild` idempotent);
  `document_worker.py` gained `build_document_sidecar`/`write_version_to_audit_tree` (written for
  every bill a document is linked from, for an **accepted or quarantined** download alike — a bad
  download is still a raw-bytes fact worth an auditable record, tagged by its own
  `validation_status`) and `run_fetch_documents_step` (drains the whole queue as one Make target
  with one manifest); `jobs/audit_rebuild.py` gained `rebuild_documents` and `verify_documents`,
  the latter designed to rebuild into a scratch directory and diff file-by-file against the real
  tree rather than re-deriving an expected sidecar inline a second time — one code path for both
  operations to agree with. `check_audit_tree` raises the `audit_tree_divergence` anomaly HANDOFF
  10.5 names, which `make doctor` already reads generically with no changes needed there.

  New CLI commands and Make targets: `fetch-documents` (gated behind
  `SCRAPE_ENABLED`/`--approve-live`, exactly like `scrape`, since it is a second command that
  hits the same live host — checked directly against the CLI, not assumed), `verify-audit`,
  `audit-rebuild`. `AUDIT_TREE_ROOT` is wired through `config.py`, both `.env` files,
  `compose.yaml` (a new `audit` volume, read-write on `worker` only, explicitly outside the
  backup contract), and `.gitignore`.

  A design point worth flagging for review: the live write path only ever touches the version it
  just downloaded, so when a second version supersedes the first, the first version's on-disk
  sidecar keeps saying `is_current: true` until something re-derives it. This is deliberate, not
  a bug — `verify_documents` is supposed to catch exactly that drift, and `audit-rebuild` is the
  fix — and it is pinned by a test
  (`test_second_version_gets_its_own_directory_and_the_first_survives`) that creates a second
  version, asserts the stale flag, runs `verify_documents` and sees the divergence, then runs
  `rebuild_documents` and sees it resolved.

  Evidence: `make check` 331 passed offline (28 PostgreSQL-only tests skip without a live
  database, as always); `make test-pg` 359 passed against real PostgreSQL 16 + pgvector 0.8.1 +
  VersityGW, nothing skipped — up from the prior 359 baseline is not a typo, the new tests replace
  what would otherwise have been skipped-elsewhere counts; `make migrate`, `make seed`,
  `make audit-rebuild`, and `make verify-audit` all run clean against the real dev database
  (`{"issues": 0}`); `uv run billwatcher fetch-documents` (no approval flag) refuses with exit 2,
  checked directly rather than assumed. **Not run**: `make fetch-documents` itself against real
  data — the dev database's fixture-seeded queue holds live `parlimen.gov.my` document URLs, and
  draining it would issue real, unapproved requests to that host, which is outside what this
  session's direction authorized. The step is proven by mocked-transport integration tests
  instead (`tests/integration/test_fetch_documents_step.py`,
  `tests/integration/test_document_worker_audit_tree.py`).

- 2026-08-21 — Claude — **The auditable step pipeline is incorporated as HANDOFF 27 (v1.6),
  ADR-019, and Package K, at the commissioner's direction, and is prioritised ahead of all other
  open work.** The direction: every pipeline step auditable, every step a Make target, every step
  storing its output in a local directory structure — the raw downloaded PDF beside a JSON sidecar
  detailing source, raw file, language, URL, and provenance. Specification only; no code yet.

  The one design judgement made here rather than directed, recorded in ADR-019 for review: the
  audit tree is a **mandatory, byte-reproducible projection** of the database and blob store, not
  a replacement for them. The file-first alternative was considered and rejected because it would
  discard transactional change history (§10.1), content-hash dedup evidenced across 62
  byte-identical document sets (ADR-003), and §8's append-only invariants, and would rewrite
  Package C after it has already ingested the whole corpus. Consequences carried into the
  contract: `verify-audit`/`audit-rebuild` keep the projection honest, divergence is a critical
  anomaly, the tree is outside the backup contract, and sidecars serialise deterministically so
  a rebuild is provably byte-identical. The sidecar `language`/`document_kind` fields will read
  `"unknown"` until the classification sweep lands (TODO 2.4), stated rather than guessed.

- 2026-08-20 — Claude — **A read-only AGC discovery spike ran, with the user's explicit
  confirmation for this specific action.** Eight honestly-identified GET requests
  (`BillWatcherNext-discovery-spike/0.1`, contact given, several seconds apart) against
  `lom.agc.gov.my`: the portal root, `robots.txt` twice, `tnc.php`, `faq.php`, and one contextual
  check of `www.agc.gov.my/robots.txt`. Full findings in `docs/upstream.md`; A16 moves from "no
  request ever issued" to "partially observed" (§4).

  Headline facts: TLS chain is complete (unlike parlimen.gov.my, no CA bundle equivalent needed).
  `robots.txt` returns **HTTP 500**, consistently, not a clean 404 — a different condition from
  A13's, deliberately **not** treated as resolved by `ROBOTS_MISSING_POLICY`'s reasoning, since a
  500 does not read as RFC 9309 "no restrictions" the way a 4xx does; it needs its own decision.
  The Terms of Use and FAQ were read in full: both confirm the s.61 Interpretation Acts disclaimer
  verbatim and the pre-2011 coverage boundary from AGC's own text (matching HANDOFF's Stage 0
  sources table, now with a primary citation), and the FAQ adds language more permissive than
  anything on parlimen.gov.my — "downloaded and printed... for purposes of reference" — which is
  recorded as a fact, **not treated as a licence this project has granted itself** to build a
  mirrored, structured corpus. The FAQ also raises a Gazette-status nuance under section 18(4) of
  the Interpretation Acts that is flagged for the eventual lawyer, not resolved here.

  **No document, listing, or reprint page was fetched** — deliberately, to keep this reconnaissance
  rather than the start of a crawl — so whether AGC reprints state an "incorporating amendments up
  to" date remains unconfirmed. **No decision to crawl AGC has been made.** TODO.md 1.6 carries the
  remaining decisions: what the `robots.txt` 500 means for policy, and the crawl/rights ADR itself.

- 2026-08-19 — Claude — **A combinatorial stress sweep of Stage L1's layout classifier found
  and fixed a more severe instance of the running-head bug already found by adversarial review.**
  The earlier fix (ADR-016 addendum) protected Part/Chapter/Schedule headings from being erased
  as furniture when they land in the header or footer band; the sweep — varying part counts,
  section counts, subsections, schedules, and page geometry together, 108 + 72 combinations —
  found the same failure for two further signals Gate L1 depends on: a **numbered provision's own
  opening line** (`Seksyen 1.` on one page, `Seksyen 2.` on the next, masking to one key at a
  shared baseline) and a **marginal note** in the same position. Both are now checked before the
  furniture test, exactly like the heading fix. A residual, lower-severity limit — a plain body
  sentence in the same position is still unprotected — is documented in `layout.py` rather than
  fixed, since Gate L1 never compares body text, only structure, so it cannot turn a mismatch into
  a false pass; widening the fix further risks no longer recognising a genuine running head at all.

  Re-ran both stress sweeps after the fix: 0 issues across 108 geometry combinations, and the 72
  structural-shape combinations reduced to exactly the ones where the test script's own
  constructed arrangement genuinely omits the schedule it lists in the body — expected, not a
  defect. Two regression tests pin the fixes. Evidence: `make check` **320 passed**.

- 2026-08-19 — Claude — **Migration 0003 carried the same untyped-foreign-key defect as 0004,
  and is fixed.** Recorded as a `TODO.md` item during the Stage L1 review rather than fixed
  immediately, then closed the same day: `document_chunks.extraction_id` and
  `chunk_embeddings.chunk_id` were declared `sa.ForeignKey(...)` with no explicit type, which
  compiles to `NullType` inside a migration and would have failed any database that reached
  revision 0002 before Release 3 shipped. Fixed the same way as 0004, and proven the same way —
  by dropping the Release 3 tables from a database at revision 0002 and upgrading to head, on
  SQLite and on the real dev **PostgreSQL** — plus `tests/integration/test_migration_bodies.py`'s
  `MIGRATION_TABLES` now covers both migrations, so a database-that-predates-the-migration
  scenario is exercised for each. Evidence: `make check` **318 passed**.

- 2026-08-19 — Claude — **An adversarial review of the Stage L1 change found six further
  defects, all fixed, one of them the most serious of the day.**

  1. **Migration 0004 could not run against any real deployment.** Its foreign-key columns were
     declared `sa.ForeignKey(...)` with no type, which compiles to `NullType` — a migration
     builds each table in its own metadata, so there is nothing to infer the type from — and
     raises `CompileError` at upgrade time. It only ever appeared to work because migration 0001
     runs `Base.metadata.create_all()`, so a fresh database already has the tables and every
     later migration's guard skips its own DDL. **Every database that had already reached
     revision 0003 would have failed to upgrade.** The same defect exists in migration 0003 and
     is recorded as a separate item rather than fixed here (`TODO.md`). Fixed by typing every
     foreign key explicitly, and proven by dropping the tables from a database at 0003 and
     re-running `alembic upgrade head` to completion — on SQLite and, separately, against the
     real dev **PostgreSQL** — plus two new tests that construct exactly that "database that
     predates the migration" scenario, which an empty-database run can never exercise.
  2. **A body with two identical section numbers was reported as `passed`.** Comparing the
     arrangement and body as sets silently collapses a repeated eId, which is precisely the
     well-formed-looking wrong answer Stage L1 exists to prevent — every later citation or
     amendment anchor would have had two referents. `duplicate_eid` is now checked before the
     comparison and is blocking.
  3. **One bad document in a batch would have failed the whole run.** `run_restructure` caught
     exceptions per document, but a `duplicate_eid` write would leave the session in
     pending-rollback state on PostgreSQL, failing every remaining document and the backfill-job
     row with it. Each document now runs inside its own savepoint; a test seeds one unreadable
     document among two good ones and asserts the good ones survive.
  4. **A duplicate provision's own children were silently dropped**, subtree and all, by the code
     written to fix finding 2 — an early return meant to skip re-storing a repeated eId also
     skipped recursing into its descendants. Parentage is now passed down as the parent's row id
     rather than looked up by eId string, and the stored key is disambiguated (`sec_1~2`) only
     for storage; nothing is lost.
  5. **A genuine Part heading positioned near the top of most pages could be erased as a running
     head.** `_furniture_key` masks digits so `Akta 710   12`/`13` collapse to one running head;
     `BAHAGIAN 1`…`BAHAGIAN 5`, one per page, collapse the same way and would have been silently
     deleted along with it — deleting real structure, not furniture. A line recognisable as a
     Part, Chapter, or Schedule heading is now checked before the furniture test, regardless of
     position.
  6. **A provision typeset in capitals was read as a heading, emptying the whole body tree.**
     `_looks_like_heading` cannot distinguish `1. TAJUK RINGKAS` in capitals from a genuine
     all-capitals heading by shape alone, and it was checked before the numbered-provision test.
     Reordered so a line matching a provision or subsection number is classified as a provision
     regardless of case.

  One further limitation was found, assessed, and left as a documented, tested boundary rather
  than fixed: `resolve_letter` decides a paragraph-versus-subparagraph letter from sequence alone,
  never from indentation, so a subparagraph list that happens to open `(i)` immediately beneath
  paragraph `(h)` reads as the ninth paragraph. Gate L1 does not compare below section level — no
  Arrangement enumerates paragraphs — so this cannot turn a mismatch into a false `passed`; real
  corpus data is needed before deciding whether indentation would help or would itself be
  unreliable.

  A parallel documentation pass found and fixed: `make test-pg`'s package-ledger and gate-log
  counts, quoted from an earlier point in the same session and stale by the time of writing;
  HANDOFF §26.8's closing sentence, which was wrong in both directions (only the corpus-wide pass
  rate is unmet; `make check`/`test-pg`/`doctor` already are); §26.6 miscounting §0's three kinds
  of tracking as four; §26.1's amendment-annotation requirement, which overclaimed that captured
  annotations are stored, when `amendment_annotations` is parsed but not yet wired into
  persistence; assumptions A15 and A16, added to the `docs/status.md` ledger without the §4
  register rows they are supposed to track (added, with Confidence/Verify-by/Blocks); §8's domain
  model, missing entries for `document_structures`/`provision_nodes`; §16.3's Makefile contract
  and `docs/operations.md`'s runbook, missing `restructure`; §7's repository-contract comment,
  stale for `version.py`; and `docs/operations.md`'s dependency-review entry, which read "67
  locked packages" before and after a stated five-package addition — arithmetically impossible
  until the intervening drop to 62 (an unrecorded RAG-provider migration, confirmed from the git
  history: `anthropic`, `distro`, `docstring-parser`, `jiter`, `sniffio` removed by commit
  `f04550a`) is recorded.

  Evidence: `make check` green at **317 passed** (was 314); `make test-pg` **345 passed, nothing
  skipped** (was 339); migration 0004 proven against a pre-existing PostgreSQL database, not only
  an empty one. Every fix above is pinned by a test that reproduces the original failure.

- 2026-08-19 — Claude — **`make quickstart` was broken from a fresh clone, and is fixed.**
  Found while running the operator path end to end for Stage L1. `.env.development` ships
  `UPSTREAM_CA_BUNDLE=` empty — deliberately, because it names a decision rather than a default —
  and `make env` copies it verbatim to `.env`. Pydantic read the empty string as `Path("")`, which
  normalises to `.`, and the `reject_unreadable_ca_bundle` validator then refused to construct
  `Settings` at all. Every command after `make env` failed, `migrate`, `seed`, `serve` and `doctor`
  included. Reproduced at HEAD on a pristine `git worktree` to confirm it was not introduced by the
  Stage L1 work. An empty variable now means unset; a variable that names a missing file is still
  refused, and both are asserted by tests. Verified: `make migrate`, `make seed`,
  `make restructure` (dry and `--apply`), and `make doctor` all run clean from a copied `.env`.

- 2026-08-19 — Claude — **The legislation pipeline is incorporated as HANDOFF 26, and Stage L1 is
  built.** An externally supplied *Malaysian Legislation Pipeline* handoff — source PDF to Akoma
  Ntoso and ELI, seven gates — is adopted as §26 and Release 4, with three departures recorded as
  ADR-016, ADR-017 and ADR-018 (§25.7). Scope is deliberately Stage L1 over the bills corpus
  already on disk: Acts are unobtainable until AGC crawl policy and rights conclude, and without
  Acts there is no consolidation and no Gate L3 oracle.

  Four findings, three of them defects in existing code that are latent rather than live:

  1. **`pypdf` cannot do layout extraction, and this was measured rather than assumed.** Its
     `visitor_text` callback reports the *line's* starting x, not each run's, so a marginal note —
     which is typeset on the same baseline as the provision it annotates — is spliced into the
     middle of the legal text. Its operand-level visitor reports accurate matrices but undecoded
     font bytes. `pdfminer.six` gives both, paired, and is what ADR-016 selects; `pdfplumber` was
     rejected for pulling an imaging stack, PyMuPDF for AGPL. The locked set grew by five
     packages and the dependency audit was re-run the same day: **67 locked requirements, no known
     vulnerabilities** from PyPI advisories or OSV.
  2. **Two shipped code paths would destroy a second extraction tier the moment one exists.**
     `scraper/service.py`'s `persist_current_extraction` demotes every `is_current` extraction for
     a version regardless of extractor name, and `jobs/retention.py`'s `_prune_extractions` keeps
     two rows per version without partitioning by extractor. Both are correct today, with one
     extractor, and both become data loss when the OCR tier lands. Stage L1 writes to its own
     tables so it does not trip them; the hazard is in `TODO.md` for whoever adds OCR.
  3. **`documents.document_kind` and `documents.language` are dead fields.** Both are written as
     `"unknown"` at creation and never updated, so the corpus cannot be partitioned into BM/EN
     pairs. Gate L1 sidesteps this by reading the language from the document's own Arrangement
     heading, which is better evidence than a listing column; Gate L4 cannot, and is blocked.
  4. **Provision-aware chunking is inert.** `search/chunking.py`'s `_PROVISION` anchors on line
     starts, but `normalize_text` collapses newlines before an extraction is stored, so every page
     arrives as one line and `_blocks()` returns one block per page. Chunks are page-shaped, not
     provision-shaped. Verified directly: `normalize_text("1. Tajuk\n2. Tafsiran")` returns
     `"1. Tajuk 2. Tafsiran"`.

  Evidence: `make check` green at **317 passed**; `make test-pg` **345 passed, nothing skipped**,
  which includes an empty-database migration to head on PostgreSQL with migration 0004; and the
  whole operator path run end to end — `make migrate`, `make seed`, `make restructure` dry and
  `--apply`, `make doctor` clean. Stage L1 was also driven against **PostgreSQL** rather than only
  SQLite, on two seeded document versions built from the fixtures: `{"eligible": 2, "processed": 2,
  "gate_passed": 1, "gate_mismatch": 1, "gate_blocked": 1}`. The passing reading stored 6
  arrangement nodes and 8 body nodes and is current; the failing one stored both its trees, named
  `sec_3` as `missing_in_body`, and is not current. `/status` reported the histogram and a 50%
  pass rate. The synthetic rows were then removed and `make doctor` re-run clean. New tests cover the marginal-note splice, a running head that
  carries its own page number, a dropped section, a bill's clauses, a schedule's numbering, an
  overlapping letter list, a `5, 5A, 6` insertion, and a failing re-read that must not withdraw a
  passing one.

  **Two defects were found in this work by attacking it, and both are fixed.** A body that repeats
  a provision number — two section 1s — was reported by Gate L1 as **passing**, because the
  comparison collapses the two trees to sets and a set has no duplicates. That is precisely the
  well-formed-looking wrong answer Stage L1 exists to prevent: an eId is an identifier, so every
  later citation and amendment anchor would have had two referents. `duplicate_eid` is now a
  blocking difference checked before the comparison. Separately, such a document would then have
  violated `uq_provision_nodes_eid` mid-write, and because the backfill wrote every document in
  one transaction, that would have aborted the transaction on PostgreSQL and failed **every
  remaining document in the batch**. Each document is now read inside its own savepoint, with a
  test that seeds one unreadable document among good ones and asserts the good ones survive.

  Two behaviours are pinned as tests rather than left as assumptions. A section printed *after* a
  schedule is absorbed by that schedule — schedules are terminal in Malaysian drafting and the
  parser assumes it — but the section then goes missing from the body tree, so Gate L1 reports it
  and the reading is never promoted; the limit is a reported mismatch, not a silent corruption. A
  contents page with no body is `empty_body` rather than a pass.

  **Not evidence, and stated as such:** the Gate L1 pass rate over the real corpus is unmeasured.
  Every fixture is constructed typography built in `tests/support/pdfs.py`, not captured upstream
  bytes, because the 1,264 stored PDFs are not reachable from a clean checkout. Until that is run,
  Gate L1 is proven correct in its logic and unproven against Parliament's actual typesetting.

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
