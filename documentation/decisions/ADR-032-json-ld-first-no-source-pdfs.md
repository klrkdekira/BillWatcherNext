# ADR-032: The published dataset is JSON-LD first, and never carries the source PDF

Status: accepted
Date: 2026-08-22

Amends ADR-031, which set *where* and *in what mode* the dataset is published, and ADR-029, whose
decision 5 kept the source documents out of version control. This ADR narrows *which
representations* the first release carries, and turns "no PDFs" from an incidental property of the
exporter into an enforced one.

## Context

Directed by the commissioner on 2026-08-22, immediately after ADR-031: **"don't commit the pdf,
prioritise the jsonld for now."**

Two instructions, one concern — what actually enters the repository.

**On the PDF.** ADR-029 decision 5 already keeps `pipeline-data/` — PDFs included — local and
gitignored, and the exporter has never been able to emit one: its manifestation extensions are
`xml`, `jsonld`, `nq`, and the definitions are text. So the direction described the existing
behaviour. But ADR-031 changed the consequence of getting it wrong: with the tree committed, a
future manifestation type that accidentally carried source bytes would be a *permanent
publication*, not a bug someone notices in a local directory. Republishing the stored bytes is
also a distinct rights question from A14's, which covered readings of bills, and it is the one
ADR-004 and `SERVE_ARCHIVED_DOCUMENTS` still hold closed. An invariant this load-bearing should be
asserted, not inferred.

**On JSON-LD.** The exporter published all three representations of every Expression. JSON-LD is
the one a consumer can use directly: it is self-describing through the context that ships in
`definitions/`, it is the form the semantic web and ordinary HTTP clients read without an XML
toolchain, and it already carries the same graph as the N-Quads by construction (ADR-028 —
both are serialised from one `rdflib.Dataset`, so they cannot disagree). The Akoma Ntoso XML is
the canonical upstream artifact and the N-Quads are the graph interchange form; neither is what a
first consumer reaches for, and both triple the size of the first release.

Measured on the real pilot, in `full` mode:

| Release shape | Files | Dataset size | Per Expression |
| --- | --- | --- | --- |
| All three representations | 276 | 12.15 MB | 132.1 kB |
| **JSON-LD only** | **92** | **3.52 MB** | **38.3 kB** |

At corpus scale that is the difference between ~115–160 MB over ~2,600–3,600 files and
**~33–46 MB over ~870–1,200 files** — which materially changes the history-growth problem ADR-031
recorded, because ADR-026 regenerates every document when `AKN_VERSION` or the renderer moves.

## Decision

1. **The published set of representations is configuration, not a constant.**
   `PIPELINE_EXPORT_REPRESENTATIONS` (`billwatcher.config`) is a `Literal["jsonld", "all"]`
   defaulting to **`jsonld`**. An enumeration rather than three booleans, so widening is one
   recorded value change and the narrow set is the default — the same idiom, and the same reason,
   as `LEGISLATION_PUBLICATION_MODE`.

2. **The first release publishes JSON-LD only.** `akn/…/<lang>@.jsonld` per Expression, plus the
   full `definitions/` set. The JSON-LD context ships with it, so a JSON-LD-only release is
   self-describing. The Akoma Ntoso XSD stays in `definitions/` even though no XML is published:
   it documents the model the JSON-LD is derived from and costs 0.26 MB.

3. **`index.json` states which representations the release carries.** A consumer must be able to
   tell a JSON-LD-only release from a widened one by reading the catalogue, never by probing paths
   for 404s.

4. **Narrowing reconciles, exactly as widening does.** Moving from `all` back to `jsonld` removes
   the `.xml` and `.nq` files it no longer publishes, so the tree and `checksums.sha256` cannot
   disagree. Both directions are covered by tests.

5. **The store is unaffected.** Every representation is still generated and still kept privately
   under `PIPELINE_DATA_ROOT`. This decision governs publication only; nothing about the pipeline's
   own completeness changes, and widening later needs no regeneration.

6. **The exporter refuses to publish source bytes.** `_refuse_source_bytes` rejects any payload
   whose path ends `.pdf` or whose bytes begin `%PDF-`, before checksums are taken or anything is
   written. The dataset carries *readings* of bills, never the official document they were read
   from. This cannot fire today; it exists so that the day a new manifestation type is added, the
   failure is a refused export rather than a permanent publication.

## Consequences

- **The first release gets materially cheaper to carry in git**: ~33–46 MB over ~870–1,200 files
  instead of ~115–160 MB over ~2,600–3,600. ADR-031's history-growth question stands, but at
  roughly a third of the weight per regeneration, which may well be the difference between
  "accept it" and "orphan branch".
- **"For now" is load-bearing.** The direction narrows the first release, it does not retire the
  other two representations. Widening to `all` is one setting, additive over an existing tree, and
  requires no pipeline rerun — the artifacts are already in the store. The path shape in §28.12
  still reserves `.xml` and `.nq` on the same permanent identifier.
- **The `metadata`-mode leak check narrows with the release.** `redact.contains_provision_text` now
  runs over exactly the representations being published. That is correct — nothing unpublished can
  leak — but it means a widening to `all` re-widens the check, and the suite keeps a test that
  exercises all three so the AKN redaction path never goes unexercised.
- **ADR-004 and `SERVE_ARCHIVED_DOCUMENTS` are untouched.** Whether the official PDFs may ever be
  republished remains a separate, still-closed question. Decision 6 makes the static dataset
  incapable of pre-empting it.
