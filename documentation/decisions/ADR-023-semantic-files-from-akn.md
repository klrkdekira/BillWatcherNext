# ADR-023: Semantic files (JSON-LD + RDF N-Quads) are derived from the stored Akoma Ntoso XML, not re-extracted

Status: accepted
Date: 2026-08-21

## Context

ADR-021 established the file-first pipeline; ADR-022 added step 4, converting each document's
markdown into Akoma Ntoso (OASIS LegalDocML) XML. Mid-session direction for the next step:
"after akn, then it should be to the semantic files such as jsonld and rfg" — "jsonld" is
unambiguous; "rfg" does not match any known standard or file format. Read in context (HANDOFF
26.5 already specifies "AKN carries structure and text; ELI carries the metadata graph... N-Quads
dump" for the equivalent Postgres-backed stage) as RDF, specifically N-Quads — flagged to the
commissioner as an interpretation, to be corrected if wrong.

AKN XML encodes a document's structure and text. A semantic/metadata graph — what a provision
*is*, how it relates to its parent and siblings, machine-readable identifiers a legal-data
consumer can query without an XML parser — is a distinct, additive representation, per the same
ELI (European Legislation Identifier) pattern HANDOFF 26.5 already committed to.

## Decision

1. **Step 5 reads the AKN XML back from the store, not the in-memory tree step 4 built.**
   `pipeline.semantic.parse_akn` reverse-parses `document.akn.xml` into the same `Node` shape
   `pipeline.akn.render_akn` produced it from, plus the FRBR URI and root element name
   (`bill`/`act`). This keeps step 5 depending only on step 4's file output — the same seam every
   step in this pipeline uses (`PipelineStore`, ADR-021) — so the two steps can run independently,
   any time apart, and a step 5 re-run never has to re-invoke the vLLM extractor step 4 needed.
2. **JSON-LD is a flat `@graph`**: one entry per document and per provision, each keyed by an
   `@id` IRI (the document's FRBR URI under `base_iri`, or a provision's URI suffixed
   `/~<eid>`), carrying `@type` (`akn:bill`/`akn:act`/`akn:<node_type>`), `eli:number`, and
   `schema:name`/`schema:text` where the source markdown had them. Parent/child structure becomes
   `hasPart`/`isPartOf` edges between entries, not nesting — a flat graph is what N-Quads (step
   3 below) requires, and keeping JSON-LD's own shape flat avoids two different graph shapes for
   one set of facts.
3. **N-Quads are derived from the JSON-LD dict `build_jsonld` returned, not by walking the AKN
   tree a second time.** `render_nquads` flattens that same dict into one quad per literal or
   edge, all in one named graph (the document's own IRI). This makes disagreement between the two
   files structurally impossible: an entry, edge, or literal missing from N-Quads is missing from
   the JSON-LD graph it was derived from, and vice versa — there is exactly one graph
   construction, not two independent ones that could drift apart from a future edit to either
   renderer.
4. **A malformed or unreadable `document.akn.xml` is counted `failed`, not raised.**
   `generate_semantic_files` iterates every eligible document in the store in one call; one
   corrupt file must not abort every other document's conversion. `has_semantic` gates
   reprocessing the same way `has_akn`/`has_document` already do for their own steps.
5. **No new configuration.** Step 5 needs no LLM, no network, and no new settings — `base_iri`
   reuses the existing `public_base_url` setting rather than introducing a semantic-files-specific
   one, since it is the same "where do our public IRIs live" fact `public_base_url` already
   answers elsewhere in this codebase.

## Consequences

- Steps 4 and 5 are independently replayable and independently re-runnable from stored files —
  the same replay property HANDOFF's Postgres-backed system requires of its own pipeline (§11.1),
  now true of this file-first one across every step so far (ADR-021, ADR-022, this ADR).
- If "rfg" meant something other than RDF N-Quads, this ADR and `pipeline.semantic` are the
  concrete artifact to correct; nothing about the file-first architecture, `PipelineStore`
  interface, or prior steps changes either way.
- Nothing here touches a database or object store; `billwatcher.pipeline` remains file-only, per
  standing direction, and this is now true of five sequential steps (listings, bills, documents,
  Akoma Ntoso, semantic files).
