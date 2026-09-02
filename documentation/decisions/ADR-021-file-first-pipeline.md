# ADR-021: A file-first pipeline behind a storage interface; Postgres left dormant

Status: accepted
Date: 2026-08-21

## Context

Directed on 2026-08-21: "we are revisiting from scratch, database and object store are for
later, we want the pipeline to work fully with file first" — followed by "it can work from db,
but it would be an extension, the pipeline should work with interface of input, such as file and
also from db or object store."

Everything built through ADR-020 assumes PostgreSQL is the record and a `document_extractions`
table, `BillDocument` links, and a SQLAlchemy session are how a pipeline step learns what exists
and what to do next. That assumption is now explicitly deferred. Separately, a mid-session
follow-up ("do not attempt to parse the pdf for me too, I have vllm openai compatible endpoint
https://llm.loqasi.io/v1/ for that") removes PDF text/markdown extraction from this pipeline's
scope entirely — that step is the operator's own concern against their own endpoint, not
something this codebase builds.

## Decision

1. **A new package, `billwatcher.pipeline`, implements listings → bills → documents against an
   interface, `PipelineStore`, never against a concrete backend.** Every step function takes a
   `PipelineStore` parameter and calls only its methods (`save_listing`, `load_bill`,
   `save_bill`, `has_document`, `save_document`, the `iter_*` readers). `FileStore` — local
   directories and JSON, using the audit tree's deterministic sidecar writer
   (`storage.audit_tree.sidecar_bytes`) — is the only implementation built so far. A future
   `DatabaseStore` or `ObjectStore` implements the same protocol and every step keeps working
   unchanged; that is the whole point of the interface, not an aspiration deferred to a rewrite.
2. **The existing Postgres-backed system (`models.py`, migrations, `scraper.service`,
   `scraper.ingest`, `scraper.versioning`, `scraper.queue`, `scraper.worker`,
   `scraper.document_worker`, `operations`, and the whole of `billwatcher.mineru`/
   `jobs.mineru_extract` from ADR-020) is left in place, untouched, dormant.** Nothing in
   `billwatcher.pipeline` imports any of it. Reconciling the two — or replacing the file-first
   store's backend with a database one — is future work, not attempted here.
3. **`billwatcher.pipeline` does reuse the parts of `billwatcher.scraper` that were already pure**
   — `fetch.Fetcher`, `policy.CrawlPolicy`, `robots.parse_robots`, `normalize.*`,
   `parse_listing.parse_listing`, `parse_archive.*` — none of which ever imported a database
   model. Re-implementing HTML/XML parsing, HTTP fetch policy, or identifier normalisation from
   scratch would have thrown away tested, correct code for no reason; only the orchestration
   layer (what decides "what's already done" and where output lives) is new.
4. **PDF parsing/extraction is out of scope for this pipeline.** The operator has a vLLM
   OpenAI-compatible endpoint (`https://llm.loqasi.io/v1/`) for that, separately. `fetch_documents`
   stops at a downloaded, magic-byte-validated PDF file; nothing in this package renders a page,
   calls a model, or produces text/markdown from one.
5. **Bill records are deliberately simple.** One JSON file per bill (`bills/<slug>/bill.json`),
   holding the identifier, per-chamber current status/dates/presenter, and accumulated document
   URLs. No field-level change history, no event fingerprints, no `record_changes` equivalent —
   the richer HANDOFF data model is exactly the sophistication being deferred along with the
   database itself. `first_seen_at`/`last_seen_at` are tracked, monotonically (a real bug, found
   while testing this: `FileStore.iter_listings` processes listings in storage-key order, not
   fetch order, so a bill referenced by both chambers — D.R.15/2026, per assumption A4 — could
   settle with `last_seen_at` earlier than its own `first_seen_at` if a blind overwrite were used
   instead of a monotonic max).
6. **A document's identity is its URL**, content-addressed by hashing it
   (`doc-<sha256(url)[:8]>`), because there is no database to assign an id. No version tracking
   yet: a URL already downloaded is skipped, not re-verified. Upstream bytes changing at the same
   URL is a `for later` question, same as the database itself.

## Consequences

- `PIPELINE_DATA_ROOT` (default `pipeline-data/`) is a new, separate setting from
  `AUDIT_TREE_ROOT` (default `data/`) — deliberately: the two systems are conceptually distinct
  (one is a derived projection of a database that may not even be running; the other *is* the
  record for its own pipeline) and should not share a directory by coincidence of a shared
  default.
- `billwatcher pipeline fetch-listings|parse-listings|fetch-documents` is a new sub-app of the
  existing CLI, gated behind `SCRAPE_ENABLED`/`--approve-live` for the two live steps, exactly
  like the Postgres-backed `scrape`/`fetch-documents` commands — politeness and crawl
  authorization are not a database concern and are not relaxed here.
- Extraction (whatever the operator's vLLM endpoint produces) is not this ADR's concern. If it
  is ever wired into this pipeline, it is a fourth step behind the same `PipelineStore`
  interface, added the same way `fetch_documents` was — not a reason to revisit this decision.
- This is the second time in one session a design was chosen by explicit interface abstraction
  (`PageBlockExtractor` in ADR-020, `PipelineStore` here) specifically so a vendor- or
  infrastructure-specific concern never leaks into step logic. The pattern is now established
  enough to reach for by default.
