# ADR-019: Every pipeline step is a Make target that materialises an auditable file tree

Status: accepted
Date: 2026-08-21

## Context

On 2026-08-21 the commissioner directed three requirements, to be prioritised ahead of all other
open work: each pipeline step must be auditable; each pipeline step must be a Make target; and
each step must use a local directory structure storing the raw downloaded PDF together with JSON
metadata detailing the source, raw file, language, URL, and provenance.

Today none of the three holds in the form asked for:

- **Steps are fused.** `make scrape` performs listing fetch, listing parse, document fetch, and
  extraction enqueue as one run. The offline steps (`reextract`, `restructure`, `rechunk`,
  `reembed`) are already discrete targets, but the live half of the pipeline is not.
- **The bytes are stored opaquely, by design.** Raw PDFs live in a content-addressed blob store
  laid out as `<root>/<aa>/<bb>/<sha256>` (HANDOFF §8), which is exactly right for dedup,
  immutability, and backup, and exactly wrong for a person with a file browser: nothing about
  `3f/9a/3f9a…` says which bill, which URL, or when.
- **Provenance requires SQL.** Everything the commissioner asks for in the JSON sidecar — source,
  URL, language, retrieval date, hashes — is already recorded, but only as rows in
  `source_snapshots`, `document_versions`, `fetch_attempts`, and `documents`. The record is
  right; it is not inspectable without the database.

Constraints worth preserving, all load-bearing and all evidenced at scale:

- The append-only record: no scrape destroys a prior observation (§1 principle 6), and every
  change is transactional with its `record_changes` row (§8 invariants).
- Content-hash identity: 62 sets of byte-identical documents are published at two or more URLs,
  and hash identity is what stopped the archive being double-counted (ADR-003, §25.6 item 13).
- The backup contract: PostgreSQL dump plus blob store is the whole archive (§16.4, §16.5).
- §17's rule that storage paths are never built from upstream-controlled strings — the crawled
  filenames (`DR 17 BM.pdf`, `D.R.45_2017 (bm).pdf`) are inconsistent and attacker-shaped.

## Decision

1. **The pipeline is decomposed into named steps, one Make target per step** (HANDOFF §27.1).
   The live half splits into `fetch-listings`, `parse-listings`, and `fetch-documents`; the
   offline half keeps its existing targets (`reextract`, `restructure`, `rechunk`, `reembed`).
   `make scrape` remains as the explicit aggregate of the three live steps, and `make pipeline`
   as the explicit aggregate of the whole sequence. No step runs implicitly as a side effect of
   another.

2. **Every step materialises its output into the audit tree** — a human-legible directory
   structure under `AUDIT_TREE_ROOT` (HANDOFF §27.2). For every document version that means the
   raw PDF beside a `metadata.json` sidecar carrying source host, exact URL as encountered and
   final URL, upstream filename, retrieval time, SHA-256, byte size, declared and detected media
   types, language, document kind, bill identifiers, chamber links, version number, and the run
   and code versions that produced it (§27.3). Every step run writes a manifest recording what it
   read, what it wrote, and at which code versions.

3. **The audit tree is a mandatory projection, not the authority.** PostgreSQL plus the blob
   store remain the record; the tree is rebuildable from them, byte-identically, by
   `make audit-rebuild`, and is checked against them by `make verify-audit`. Divergence between a
   file, its sidecar, and the database is a critical anomaly (`audit_tree_divergence`), not a
   merge problem. Because sidecars are generated from the same rows the step writes, the tree can
   fall behind (detectable) but cannot silently disagree (regeneration is deterministic).

4. **The tree trades deduplication for legibility.** A document linked from two bills appears
   under both; byte-identical copies are detectable by the SHA-256 in their sidecars. The whole
   corpus is 0.24 GB (A12, measured), so the duplication cost is irrelevant and the audit value —
   everything about a bill is under that bill's directory — is not.

5. **Tree paths are built only from our own identifiers** — bill slugs, document UUIDs, version
   numbers, code-version strings. The upstream filename appears in the sidecar, never in a path
   (§17).

### Alternatives rejected

- **Make the tree the source of truth and the database a derived index.** This is the classic
  file-first ETL shape and it was seriously considered, because it is the simplest reading of the
  direction. Rejected because it discards properties the project has already paid for and
  evidenced: transactional field-level change history (§10.1) has no filesystem equivalent short
  of reinventing a database; content-hash dedup and `ref_count`-guarded pruning stop working when
  the same bytes live at many meaningful paths; and the append-only invariants of §8 are enforced
  today by one writer per table, not one convention per directory. It would also rewrite Package
  C, which is in review with the whole corpus already ingested. The projection design delivers
  every property the direction names — step-wise Make targets, raw PDF beside JSON metadata,
  filesystem auditability — without destroying the record underneath it.
- **Make the blob store itself legible** (name blobs by bill/URL). Identity and meaning conflict:
  the same bytes belong to several bills, and meaningful names come from upstream strings §17
  forbids in paths.
- **Export-on-demand only** (a target that dumps the tree when asked). An audit surface that only
  exists when someone asks for it is not an audit surface; steps must leave their evidence behind
  as they run. `audit-rebuild` exists, but as the recovery and backfill path, not the norm.

## Consequences

- The Makefile gains `fetch-listings`, `parse-listings`, `fetch-documents`, `pipeline`,
  `verify-audit`, and `audit-rebuild`; `scrape` becomes an explicitly documented aggregate.
- The audit tree joins `var/` as local, gitignored state. It is **not** part of the backup
  contract (§16.4): it is rebuildable from what is backed up, and backing up a projection would
  imply it carries state, which it must never do.
- Sidecar JSON must serialise deterministically (sorted keys, fixed indentation, UTF-8, LF,
  trailing newline), because "rebuild is byte-identical" is the test that proves the tree carries
  no state of its own.
- The `language` and `document_kind` sidecar fields surface the known dead-field problem
  (TODO 2.4, HANDOFF 26.7) at file level: both read `"unknown"` today, honestly. When the
  classification sweep lands, a rebuild backfills every sidecar — which is the projection design
  working as intended, not a migration.
- A tampered or bit-rotted file in the tree is caught by `verify-audit` re-hashing against
  sidecars, giving the archive a second integrity check independent of `verify-storage`.
