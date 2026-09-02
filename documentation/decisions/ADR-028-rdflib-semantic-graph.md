# ADR-028: The semantic graph is an rdflib dataset, serialised in sorted order; SHACL is deferred

Status: accepted
Date: 2026-08-22

## Context

ADR-023 built step 5 by hand: a JSON-LD dictionary assembled from the AKN tree, and an N-Quads
serialiser that flattened *that same dictionary* rather than walking the tree a second time. The
guarantee it bought — one graph construction, so the two files cannot disagree — is right and is
kept. The implementation carried three defects that only a real corpus would have exposed:

- **`_escape_literal` was incomplete.** It escaped `"`, `\` and `\n`, and not `\r` or `\t`. A
  carriage return or a tab anywhere in a bill's text — plausible in markdown produced by a
  vision-language model — produced a malformed quad, which is a corrupt file rather than a wrong
  one.
- **Literals carried no language tag.** For a corpus whose whole point is a bilingual Malay/English
  record, an untagged literal cannot tell a consumer which language it is reading. HANDOFF 15
  already mandates BCP 47 for this project's structured output.
- **The graph existed only as our own dict shape**, so no RDF tooling could validate, query or
  canonicalise it, and Gate L5's SHACL shapes (HANDOFF 26.6) had nothing to run against.

## Decision

1. **Step 5 builds one `rdflib.Dataset` and serialises it twice.** ADR-023's single-graph guarantee
   is preserved by a different mechanism: one graph construction, two serialisations of the same
   in-memory triples, rather than one construction and one derivation. A triple missing from the
   JSON-LD is missing from the N-Quads because there is one set of triples, not two renderers.

2. **Both outputs are explicitly sorted before they are written** — the JSON-LD `@graph` by `@id`
   and then re-dumped with `sort_keys=True`, the N-Quads line-sorted. rdflib makes no promise about
   serialisation order, and byte comparison is this pipeline's idempotence mechanism (ADR-026): an
   unsorted serialiser would rewrite both files on every run, make `_write_if_changed` a no-op in
   name only, and destroy the one cheap check that a repeat run changed nothing.

3. **N-Quads is serialised from the `Dataset`, JSON-LD from the named `Graph` inside it.** This
   looks like a stylistic detail and is not: rdflib's N-Quads serialiser requires a context-aware
   store, which a plain `Graph` is not, and serialising the whole `Dataset` as JSON-LD wraps
   everything in a named-graph object, silently changing the flat top-level `@graph` shape ADR-023
   committed to and ADR-018 needs for truncatable ELI paths.

4. **Literals carry BCP 47 language tags** (`@ms`, `@en`), the same spelling split ADR-024 records:
   ISO 639-3 in the AKN IRI, BCP 47 in RDF and HTML, mapped in one place.

5. **Reading stored XML back refuses a doctype or entity declaration** before parsing, the same
   refusal `scraper.parse_archive` already makes for the archive tree. These bytes are normally ours, but markdown and
   AKN can now be imported by an operator and the result is served publicly, so an entity-expanding
   parser is not something to hand untrusted input to.

6. **Gate L5's SHACL validation is deferred, with a reason rather than an omission.** Its shapes
   check for dangling `amends` targets, missing `validFrom` on an expression, and overlapping
   expression intervals for one `wId`+language (HANDOFF 26.4). Every one of those facts is produced
   by Stage L3 (amendment extraction) or Stage L4 (consolidation), neither of which exists — so
   pySHACL today would validate an empty half of the shape set and report success, which is worse
   than not running it. Building the graph in rdflib is precisely what lets the shapes drop in later
   without a rewrite. No dependency is added until there is something for it to check.

## Consequences

- **`rdflib` and `xmlschema` become core dependencies** (with `pyparsing` and `elementpath`
  transitively). Both are pure Python, permissively licensed, and add no native code — the same test
  ADR-016 applied to `pdfminer.six` and ADR-020 applied to `pypdfium2`. HANDOFF 20's dependency
  review is the only control on that set in a project with no CI, and it is now stale: it records 67
  locked requirements, and the lock stands at 79 today. The four packages here are not the whole
  difference — the MinerU dependencies (ADR-020) landed without the audit being re-run — which is
  exactly the bookkeeping failure the 2026-08-19 review already had to reconstruct once. Re-running
  it is an operator action and is recorded as one (`docs/operations.md`, TODO).
- **The ELI predicates are still not validated against the published ontology.** They are asserted
  by our own tests agreeing with our own builder, which is the weaker kind of evidence, and
  `eli:has_part`/`eli:is_part_of`/`eli:number`/`eli:language`/`eli:jurisdiction` should be read as
  our reading of ELI rather than a certified one until Gate L5 runs.
- **rdflib is slower than string concatenation**, and step 5 now parses the AKN file, builds a graph
  and serialises twice per document. It is offline, replayable and not in a request path, so
  throughput is not a constraint here — the same argument ADR-016 made for `pdfminer.six`.
- ADR-023 is **not** superseded: its decisions — derive the semantic files from the stored XML
  rather than step 4's in-memory tree, one flat graph, a malformed file counted `failed` rather than
  raised, no new configuration — all still hold. Only the construction mechanism changed.
