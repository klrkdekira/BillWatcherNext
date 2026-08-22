# ADR-029: The first publication surface is a public static cache of files; tooling comes after

Status: accepted
Date: 2026-08-22

## Context

Directed by the commissioner on 2026-08-22: "my priority right now is serving the schema and
dataset statically, second part would only be the backend serving, db integration and etc. the
data pipeline should be solely local file for now, not committed, only the static semantic files
or definition," then, sharpening the ordering: "My prioritise is a public cache of files, only
then we do the teooling" — read as: *publish a public cache of the corpus files first; backend
serving, database integration, and pipeline tooling improvements are all second.*

ADR-018 decided the opposite ordering for the Postgres-backed system: the corpus is served by the
application, and mirrorability is delivered by a dump. That decision was made against a working
FastAPI/PostgreSQL stack with search, templating, and operations already in place. The file-first
pipeline (§28, ADR-021) is in the opposite position: its store is plain files, its outputs
(`document.akn.xml`, `document.jsonld`, `document.nq`) are already static artifacts, and the
serving surface §28.10 describes is application code sitting *in front of* files that need no
application to be useful. For this pipeline, a static export is the shortest path to a public,
citable corpus — and it is what was directed.

The rights position changed since ADR-018 was written: the A14 determination (2026-08-22, gate
log) is that bills are public information and the corpus may be published in full-text mode. The
measurement position also changed: the first real corpus run has happened and Gate P1 has now seen
real documents (the fixes it forced are in the working tree and the gate log).

## Decision

1. **The file-first pipeline's first publication surface is a public static cache**: a directory
   tree exported from the store, publishable by any static file host (or committed, if the
   operator so chooses — see 5), containing:
   - the **dataset**: for every document whose reading passed Gate P1, its Akoma Ntoso XML,
     JSON-LD, and N-Quads, laid out on the §28.7 FRBR paths
     (`akn/my/bill/dr/2026/15/msa@.xml|.jsonld|.nq`) so a cached file's path *is* its citable
     identifier;
   - the **definitions**: the vendored OASIS Akoma Ntoso XSD, the JSON-LD context, the structural
     vocabulary, and the JSON Schema of any intermediate artifact the pipeline publishes — the
     schema half of "serving the schema and dataset";
   - an **index and checksums**: a machine-readable listing of Works/Expressions present, and a
     SHA-256 manifest over every exported file, so a mirror can verify itself.
2. **Export is a pipeline step, not a serving feature**: `billwatcher pipeline export-static`
   (Make: `pipeline-export-static`), offline, reading only the store, writing only
   `PIPELINE_EXPORT_ROOT`. It exports **only gate-passing documents** and applies
   `pipeline.redact` at the export boundary under the same `LEGISLATION_PUBLICATION_MODE`
   settings that govern serving — the export boundary is a serving boundary.
3. **Publication controls carry over, not loosen.** ADR-018's warning is *more* true of a static
   cache than of a served surface: once mirrored, it cannot be withdrawn. The export command
   refuses to run without `LEGISLATION_CORPUS_RIGHTS_CONFIRMED=true` (and
   `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true` for `full` mode) — the same flags, enforced at the
   same hard level as production boot. Both confirmations are now legitimate to set (A14,
   2026-08-22), which is what makes this ADR actionable at all.
4. **The application serving surface (§28.10) and all backend tooling are phase two.** Backend
   serving, a database or object-store `PipelineStore`, and the step-4 split of ADR-030 are all
   "the tooling" in the commissioner's words, and none of them blocks the cache: the pipeline as
   built already produces every file the cache needs.
5. **The pipeline's working store is never committed.** `PIPELINE_DATA_ROOT` (`pipeline-data/`)
   stays local and gitignored — PDFs, markdown, provenance, rejected renders, manifests, all of
   it. The only pipeline output that may enter version control or a public host is the export
   tree and the definitions: "only the static semantic files or definition."

## Consequences

- **ADR-018 is qualified, not reversed.** It governed the Postgres-backed system and still does
  (§26.5). For the file-first corpus, the static cache is the first surface and the served surface
  is second — which inverts ADR-018's ordering for this pipeline only. ADR-018's mirrorability
  mechanism (a dump plus checksums) is essentially what this ADR builds, generalised from one
  N-Quads file to the whole corpus tree.
- **Withdrawal is no longer an available remedy** once the cache is public and copied. The rights
  determination that makes this acceptable is A14's; anything *consolidated* (Stages L3–L4) stays
  under TODO 1.7's stricter bar and must never enter the cache without that sign-off.
- **The cache is only as fresh as its last export.** There is no invalidation, no redirects, no
  content negotiation — a re-export overwrites in place and the checksums manifest is how a
  consumer detects change. Anything needing liveness (search, listings, point-in-time queries)
  belongs to phase two.
- **The XSD's redistribution terms need one check** before the definitions ship: the vendored
  OASIS schema files carry OASIS copyright notices, which must be preserved in the export.
