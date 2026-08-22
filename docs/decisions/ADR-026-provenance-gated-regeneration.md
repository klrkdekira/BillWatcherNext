# ADR-026: Regeneration is gated on input hashes, not on whether an output file exists

Status: accepted
Date: 2026-08-22

## Context

Every step of the file-first pipeline decided whether it had work to do by asking whether its output
file existed: `has_akn`, `has_semantic`, `has_document`. For a download that is correct — the bytes
at a URL are the bytes at that URL. For a *derived* artifact it is wrong in a way that only surfaces
much later.

This change is the proof. It replaces the FRBR identifier scheme (ADR-024), rewrites the AKN
serialiser to be schema-valid (ADR-025), and rebuilds the semantic graph on rdflib (ADR-028). Under
an existence check, **not one already-converted document would have been regenerated.** The corpus
would have kept publishing IRIs the code no longer mints and XML the renderer no longer produces,
and nothing would have reported a problem, because from a file's point of view nothing was wrong.

The Postgres-backed audit tree does not have this exposure: it is a projection, so it can be rebuilt
and diffed against the database that authored it (ADR-019). Here the store *is* the record
(ADR-021). There is nothing to reconcile against, so the record has to carry the evidence itself.

## Decision

1. **Every derived artifact carries a provenance record** — `document.<artifact>.provenance.json`,
   one per artifact per document version, written through the same deterministic sidecar serialiser
   everything else uses. It holds two things and nothing else: `inputs`, naming every source file
   with its SHA-256 plus the code version, gate version, threshold, producer, model id, prompt
   digest and base IRI that were in play; and `output`, the SHA-256 and byte size of each file that
   was written.

2. **`inputs` is the staleness key.** `provenance.needs_rebuild` recomputes `inputs` from the
   current code and store, compares it to the stored record, and rebuilds when they differ. An
   artifact present with **no** provenance record counts as stale — that is what regenerates the
   pre-provenance corpus once, after which it settles.

   **Every input has to be in it, and the first draft of this work missed two.** `render_akn` reads
   the bill record for the FRBR identity, `FRBRdate` and `<longTitle>`, and `build_graph` reads it
   for `eli:number` and the document's `schema:name` — yet `bill.json` was in neither artifact's
   `inputs`, so a later crawl correcting a bill's title or its first-reading date would never have
   reached the published corpus. Worse, `resolve_language` reads the declared language out of the
   markdown provenance and that language is a *permanent component of the Expression IRI*, so a
   corrected language would have left the document published at an IRI asserting the wrong one.
   Both are now recorded, as `bill_sha256` and `markdown_provenance_sha256`.

   They are digests in `inputs` rather than entries in `source_files`, and the distinction is
   load-bearing: `source_files` is the list `pipeline verify` re-hashes *inside the document's own
   directory*, so naming a file that lives elsewhere made a correct store report itself as damaged.
   Staleness compares the whole `inputs` dict either way, so the property is unchanged. The general
   lesson is worth stating: an input-hash gate is only as complete as its enumeration of inputs, and
   an omission is invisible precisely because the artifact keeps looking current.

3. **A provenance record contains no timestamp and no run id.** Both are volatile, and either one
   inside a per-artifact sidecar would make every re-run rewrite the file, destroying the "a repeat
   run writes nothing" guarantee (ADR-019) — which is not a nicety here: byte comparison is how this
   pipeline's idempotence is *checked*, and a sidecar that changes on every run makes the check
   meaningless for everything beside it.

4. **Volatile facts live in the per-run manifest**, `manifests/<step>/<run-id>.json`: when the run
   started and finished, at which code versions, the counts, and the named failures. The path is
   already unique per run, so a volatile field there costs nothing — provided the run id really is
   unique, which at the second granularity it first used it was not: two runs of one step inside the
   same second, which an ordinary sequential shell loop produces, wrote the same path and the first
   run's record was simply gone. A manifest that can be silently overwritten is not an audit record,
   so the id carries microseconds.

5. **A step reports which documents failed, by name.** `StepResult` keeps the flat count histogram
   the CLI echoes and `/status` reads, and carries `StepFailure` records (bill slug, doc key,
   version, reason) beside it, bounded at 50 in any written record. `except Exception: failed += 1`
   told an operator that something failed and nothing about what: over a couple of thousand
   documents a persistently broken document was indistinguishable from a transient endpoint timeout,
   and a bug in our own code was indistinguishable from malformed upstream input.

6. **Every write is atomic** — temp file beside the target, then `os.replace`, via
   `storage.audit_tree.write_atomically`, now shared with the Postgres-backed audit tree. A reader
   is no longer a hypothetical: a later step, a verify pass and the public serving surface all read
   these files, and a half-written `document.akn.xml` served to a consumer is worse than a missing
   one. `_write_if_changed` still compares bytes first, so an unchanged file keeps its mtime as well
   as its contents.

7. **`pipeline verify` is the offline audit this makes possible.** It re-hashes each artifact
   against its provenance `output`, reports every artifact whose `inputs` no longer match what the
   current code would produce, and lists files no step writes at all (`KNOWN_FILENAMES`,
   `iter_unexpected_files`) — a killed process's leftover temp file, a hand-dropped edit, an
   artifact from a future version. It is the file-first equivalent of `verify-audit`, and it needs
   no database.

### Alternatives rejected

**One corpus-wide version stamp: bump a number, invalidate everything.** Seriously considered
because it is a single line of code and would have caught this change. Rejected on two counts. It
cannot distinguish which artifact a change affects, so a prompt fix would re-invoke the vLLM
extractor over the whole corpus and a threshold change would re-render every XML file — expensive in
the first case and pointless in the second, and both discourage exactly the small corrections this
mechanism is meant to make cheap. And it records nothing about what a given file was built from, so
`verify` would have nothing to check and a hand-edited artifact would stay invisible.

**Mtime comparison, the Make model.** Rejected: copying a store, restoring a backup and an atomic
replace all reorder mtimes, so the comparison is a fact about the filesystem rather than about the
artifact. The hash is the fact.

## Consequences

- **This change regenerates every derived artifact once, by design.** That is the mechanism working,
  not a migration to be avoided — and it is the first time a correction to an IRI scheme or a
  renderer has actually reached the corpus.
- **It costs a hash of every input, per document, per run.** Trivial next to a vLLM call, not
  trivial next to a `Path.exists()`. That is the price of noticing, and the alternative was not
  noticing.
- **Provenance records are themselves part of the corpus**, and part of what `verify` protects. A
  hand-edited artifact is now detectable where it previously was not; a hand-edited artifact *and*
  its record are not, because nothing is signed. This mechanism detects accident and drift, not an
  adversary with write access to the store.
- **The `markdown` record is only as truthful as the importer.** PDF-to-markdown extraction happens
  outside this pipeline entirely (ADR-021), so what step 4 knows about a markdown file is what was
  declared when it was imported — including the language, which ADR-024 makes a permanent component
  of an IRI. That is a real limit of the file-first seam, and the reason `resolve_language`
  cross-checks the declaration against the document's own Arrangement heading rather than trusting
  it outright.
- **`document.akn.gate.json` is deliberately not a provenance record.** A gate verdict is a
  judgement about a document rather than a claim about how bytes were produced, and re-judging must
  be allowed to rewrite it. Keeping the two file kinds distinct keeps "a repeat run writes nothing"
  true of provenance while a re-judgement still lands.
