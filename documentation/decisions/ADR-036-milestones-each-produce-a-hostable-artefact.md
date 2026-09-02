# ADR-036: Every pipeline milestone produces a hostable artefact of its own

Status: accepted
Date: 2026-08-23

## Context

Directed on 2026-08-23: "each is part of the milestone while able to produce hostable artefact…
Parliament bills download. Then conversion and markdown formatting, this should produce a hostable
static public data. Next parsing then formatting to jsonld and rdf, then this is another hostable
static resource… Current intermediate goal should be the markdown then the semantic knowledge
graph."

The pipeline did not work that way. `build_projection` admitted a document only if it had a passing
Gate P1 verdict **and** the complete Akoma Ntoso + JSON-LD + N-Quads trio, and it derived the
Expression identity by parsing the AKN XML. Two consequences followed, and both were the misalignment
the direction above corrects:

- **The markdown tier could not be published at all.** There was no representation for it, no
  identity for it without an AKN, and no admission rule. A reading of the corpus existed on disk and
  had no route to `dist/`.
- **The corpus was publishable only at the speed of its slowest stage.** Measured on the real store
  the day this was written: 1,265 documents read into markdown, and **92 Expressions (7%)**
  publishable, because the other 93% had not yet been through an LLM conversion and a fidelity gate.
  ADR-031 refuses to publish a 7% sample under a name implying the corpus — correctly — so the
  practical effect was that nothing could be published for months.

Publishing the reading is not a lowering of the bar. It is a different artefact: a reading of a bill
is a resource in its own right, and it does not become one only once a graph has been built from it.

## Decision

1. **Milestones are publication points, and each one ships.** In order, with what each publishes:

   | # | Stage | Hostable artefact | State |
   | --- | --- | --- | --- |
   | 1 | Download | none, deliberately — never a source PDF (ADR-032) | done: 1,265 PDFs |
   | 2 | **Markdown reading** | **`.md` per Expression + `index.json` + checksums** | **current** |
   | 3 | **Semantic graph** | **`.jsonld` + `.nq` per Expression, gate-passing only** | in progress |
   | 4 | Cross-reference | divergence report over the readings (ADR-035) | built, unrun |

   Stage 1 has no artefact by prior decision, not by omission. Stages 2 and 3 are both live surfaces
   and widen the *same* site.

2. **One layered site, not one site per milestone.** A document's text and its graph sit at one
   Expression identity, differing only in extension — `…/msa@.md`, `…/msa@.jsonld`, `…/msa@.nq`.
   This is the mechanism ADR-032 already described for widening ("reserved extensions on the same
   §28.7 identifier"), used as intended. `md` is registered in `MANIFESTATION_TYPES` as
   `text/markdown`, so a Manifestation URI can be minted for it like any other.

3. **Eligibility is per representation, not per document.** The semantic trio still publishes only
   behind a passing Gate P1 verdict — that is unchanged, and the gate still judges what it always
   judged. What changed is that failing it no longer withholds the *reading* as well. A document
   contributes whatever representations it actually has; `index.json` lists the release's configured
   `representations`, and each Expression's own `files` says what it holds.

4. **Identity without an AKN comes from the bill record plus the declared language.** The Work from
   `identity_from_bill`, the language from the markdown provenance record's `inputs.language`.
   Declared rather than detected, deliberately: that value is already a permanent component of the
   Expression IRI, so reading it from the text could mint a second IRI for one document. A reading
   with no declared language has no Expression and is refused by name.

5. **Every reading publishes, with its measured quality attached.** Roughly a fifth of the corpus
   carries a quality signal (ADR-035); withholding those would ship a release that is silently ~78%
   of the corpus while looking complete, which is exactly the failure ADR-031 exists to prevent. Each
   Expression carrying a reading gets a `reading` object in the catalogue — extractor,
   `heading_ratio`, `lone_letter_rate`, `suspect` — so a consumer can filter without re-deriving
   anything, and a consumer who ignores it gets the whole corpus rather than a trimmed one.

6. **Metadata mode refuses to publish prose representations.** There is no redacted markdown: strip
   the provision text and only headings remain. Asking for `markdown` under
   `LEGISLATION_PUBLICATION_MODE=metadata` is refused rather than silently satisfied with an empty
   text dataset. Publishing the reading is publishing the text, and rests on the same A14
   determination and the same `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED` flag as `full` mode.

`PIPELINE_EXPORT_REPRESENTATIONS` and `PIPELINE_SITE_REPRESENTATIONS` gain `markdown` and
`markdown-semantic`; `all` now includes `md`.

## Consequences

**Measured immediately, on the real store**: `markdown-semantic` publishes **1,192 Expressions of
1,265 documents (94%)**, of which 1,110 are text-only and 82 carry both tiers, with 252 readings
labelled suspect, 61 duplicate Expressions collapsed, 12 documents skipped for having neither a
reading nor a passing gate, and 0 failures. The comparable figure before this ADR was 92.

The 12 skipped are the no-text-layer scans from ADR-035: nothing to publish at either tier until the
cross-reference reads them.

**What this does not change.** Gate P1's threshold, what it judges, and the rule that no
gate-failing graph is published. The no-PDF refusal. The rights flags. Milestone 3 is still gated on
conversion quality, and the honest reading of the numbers above is that the semantic milestone is 82
Expressions in, not that it is done.

**The new hazard, recorded.** A reader who takes `.md` as authoritative gets a machine reading with
no fidelity gate behind it — Gate P1 scores a tree against the markdown, never the markdown against
the page (ADR-035). The `reading` object is the only warning the dataset carries, so it is not
optional decoration, and the cross-reference milestone is what eventually puts evidence behind it.
