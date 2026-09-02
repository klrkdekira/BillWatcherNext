# ADR-018: The legislation corpus is served, not statically built

Status: accepted
Date: 2026-08-19

## Context

The source specification for the legislation pipeline (HANDOFF 26) prescribes a static `dist/`
tree: one `index.html`, `data.jsonld`, and `akn.xml` per provision-expression, a
`search/corpus.sqlite` queried in-browser over HTTP Range requests, an optional binary-quantised
vector shard, and content negotiation by edge function.

It is a coherent design, and it is not this system's. This service is server-rendered FastAPI over
PostgreSQL behind an nginx deployed separately (ADR-015), with a weighted `tsvector`, `ts_rank_cd`
ranking and `ts_headline` snippets (ADR-007), pgvector retrieval (ADR-008), progressive
enhancement via a vendored Datastar (ADR-012), and an archive served from a content-addressed blob
store through an S3 gateway (ADR-013).

Adopting the static build would contradict four accepted decisions and discard a working search,
templating, provenance, and operations stack, in exchange for one property: mirrorability.

There is also a cardinality argument in the static design's favour that deserves stating rather
than ignoring. Materialising a page per provision per expression per language is large — a
200-section Act with a dozen change points in two languages is several thousand documents — and
generating them is genuinely simpler than querying them. That is a real cost of this decision, not
a reason against the design being rejected.

## Decision

The legislation corpus is served by the application.

- AKN XML, ELI JSON-LD, and provision pages are served on truncatable ELI paths, where each level
  resolves to a listing, and are indexed with the existing search machinery rather than a second
  one built in the browser. Citation lookups continue to be exact, structured queries and never
  touch a vector index — which is what the source specification wanted from SQLite anyway, and
  which PostgreSQL already does.
- **Mirrorability is delivered by a dump, not by the serving architecture.** An N-Quads dump plus
  checksums, produced by a Make target, makes the corpus citable and mirrorable without changing
  how it is served.
- Content negotiation uses extension variants with `Link: rel="alternate"` headers and
  `<link rel="alternate">` in HTML. No edge function, no new infrastructure. The `Accept`-header
  purity the source specification prefers is not worth a platform dependency here.

## Consequences

The point-in-time query the static design resolves client-side against a `versions.json` becomes a
server-side interval lookup. That is a schema requirement on Stage L4, not an architectural one:
expressions are materialised at change points only, and "as at 2023-06-15" selects the interval
containing that date.

**The dump is irreversible and is therefore gated, not merely planned.** Once `corpus.nq.gz` is
mirrored it cannot be withdrawn, so an adverse A14 rights determination or an adverse legal review
of the consolidation methodology (HANDOFF 26.7) could not be given effect afterwards. The dump
target must not ship before both conclude, and it needs the same kind of hard runtime control that
`SERVE_ARCHIVED_DOCUMENTS` already has — a default-off flag plus a configuration validator that
refuses to boot in production without an explicit rights confirmation. Publishing a lower-risk
artifact behind a hard control while a higher-risk one has none would be exactly backwards.

This ADR rejects a *publication architecture*. It does not reject the source specification's
data model: AKN 3.0, ELI, FRBR Work/Expression/Manifestation, `eId`/`wId`, and the SHACL shapes of
Gate L5 are adopted unchanged. Only the question of what serves the bytes is decided here.
