# ADR-027: The corpus is published metadata-only, redacted at the serving boundary, behind two flags

Status: accepted
Date: 2026-08-22

## Context

ADR-018 decided *where* this corpus is served from: by the application, on truncatable ELI paths,
rather than as a static `dist/` tree. That decision is not reopened here; this ADR is it being
implemented, now that there is a corpus to serve. ADR-018 also left a warning behind that this
change has to answer: publishing a lower-risk artifact behind a hard control while a higher-risk one
has none "would be exactly backwards".

The rights position has not moved. A14 is still open, and the evidence gathered on 2026-08-18 points
one way: `parlimen.gov.my` publishes no licence, no terms of use and no permission — the only
copyright statement anywhere is a footer reading `© Hakcipta Terpelihara Parlimen Malaysia`, all
rights reserved. ADR-004 therefore stands: official links, version metadata, and bounded text
excerpts only, with stored source bytes kept privately as the preservation record.

The unhelpful reading of that is "no rights answer, therefore publish nothing", and it would waste
the entire pipeline. A structural reading of a bill is genuinely useful with **none** of the
drafter's prose: a citable IRI per provision, the printed numbering, the containment graph, the
shape and size of the document, a machine-readable statement that clause 5 exists and has three
subsections. None of that reproduces a sentence of legislation.

## Decision

1. **The corpus is served by the application on the ADR-024 paths** — `/akn/my/bill/dr/2026/15`,
   `…/msa@`, `…/msa@.xml`, `…/msa@.jsonld`, `…/msa@.nq`, `…/msa@/~cl_5` — with each level truncating
   to a listing and extension variants carrying `Link: rel="alternate"`, exactly as ADR-018
   specified. Nothing about the publication architecture is being decided again here.

2. **The store holds the full text privately; redaction happens at the serving boundary.** This is
   the same posture ADR-004 already established for PDF bytes, applied to their structural reading:
   the record is complete, and what is *published* is a subset chosen by configuration. The
   consequence is the reason for the design — **the rights decision becomes a configuration change
   rather than a corpus regeneration.** A favourable determination publishes text that is already on
   disk; an adverse one stops publishing it. Neither re-invokes the extractor, and neither costs a
   vLLM request.

3. **Two flags, not one.**

   | Setting | Default | Governs |
   | --- | --- | --- |
   | `SERVE_LEGISLATION_CORPUS` | `false` | whether the metadata-only surface exists at all |
   | `LEGISLATION_PUBLICATION_MODE` | `metadata` | whether provision **text** is published |

   With the first off, every corpus path returns 404, the same way `SERVE_ARCHIVED_DOCUMENTS`
   already works. In production the first additionally requires
   `LEGISLATION_CORPUS_RIGHTS_CONFIRMED=true`, and `LEGISLATION_PUBLICATION_MODE=full` requires
   `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true` on top of it — the A14 confirmation, because publishing
   provision text republishes the source document's own words, which *is* the A14 question. A
   configuration validator refuses to boot rather than warning, so turning either on is a recorded
   decision rather than a flag flip.

   One flag would have made the structural surface and the text surface a single decision, which is
   what ADR-018 called exactly backwards: the lower-risk artifact would then be gated by the same
   control as the higher-risk one, and whoever cleared the easier question would have cleared the
   harder one by accident. The mode is an enumeration rather than a boolean so that the safe value
   is a default rather than the negation of a flag.

4. **Provision headings are published in metadata-only mode.** This is a judgement, made explicitly
   by the project owner, and it is recorded as one because a heading is the drafter's words. The
   reasoning: a provision heading is the same class of short published fragment as a bill's title,
   which this site already publishes on every bill page, in a search index and in JSON-LD, and which
   ADR-004's "bounded text excerpts" already permits. `redact.KEEP_HEADINGS` exists so that the
   boundary is one constant in one module: an adverse or narrower determination is a one-line change
   affecting both published representations at once, not a redesign.

   **The word "bounded" in that reasoning has to be enforced, not assumed, and the first draft of
   this work did not enforce it.** Nothing constrained what reached the `heading` field. Malaysian
   amendment bills typically carry no marginal note at all and run the entire provision in after its
   number — `2. Kanun Keseksaan [Akta 574] dipinda dalam seksyen 375 dengan menggantikan perkataan
   "empat belas tahun" ...` — so the parser stored whole drafted provisions as headings and the
   serving surface published them verbatim, in all four representations, at default settings, with
   the redaction self-check silent. An independent review reproduced it end to end before the change
   landed. It was the single most serious defect in this work: the exact outcome `redact.py` exists
   to prevent, reached through the one field the module deliberately let through.

   The fix is two independent layers, because one was demonstrably not enough.
   `akn.split_marginal_note` classifies the text after a provision number at parse time — a short
   label with no terminal punctuation is a marginal note, anything else is body text and goes to the
   provision's paragraphs. `redact.publishable_heading` then applies the same test again at the
   serving boundary, deliberately duplicated rather than shared, because the parser is not the only
   producer of a tree: an LLM extractor fills `heading` too, and a prompt is a request rather than a
   guarantee. `contains_provision_text` was also extended to fire on a sentence-shaped heading — a
   self-check that only inspected `<content>` stayed quiet through exactly the leak it existed to
   catch, which is worth recording as its own lesson about what a safety net is for.

   Both halves of the test are evidenced rather than guessed. The 80-character bound is the same one
   `legislation.layout` already uses to tell a marginal note from an indented block when it has page
   geometry to look at. The terminal-punctuation test is what separates the two shapes in the
   fixtures captured from real Parliament PDFs, where marginal notes and Arrangement entries are set
   without a final stop and body sentences with one. The residual risk is stated plainly: a run-in
   sentence shorter than 80 characters and printed without a final stop would still be published as
   a heading. That is a genuinely bounded fragment — comparable to the `ts_headline` search snippets
   this site already serves — which is the property ADR-004 asks for and the property the field did
   not have before.

5. **Redaction operates on parsed structures, never on serialised bytes.** `redact_akn` empties
   every `<p>` inside `<content>`, `<intro>` and `<wrapUp>` through ElementTree; `redact_semantic`
   removes every `schema:text` triple from an rdflib graph and re-serialises. A regular expression
   over XML or N-Quads would be one text-processing bug away from leaking the thing it exists to
   withhold. The `<p>` elements are emptied rather than removed, because AKN requires a hierarchy
   element to carry something and an invalid Akoma Ntoso document is not a useful thing to publish
   either. `redact_semantic` rebuilds both published representations from the stored N-Quads, so one
   redaction produces both and they cannot disagree — the same single-graph discipline ADR-023 and
   ADR-028 apply to generation. `contains_provision_text` is the independent second opinion: the
   redactors are the control, and this is the check that they worked.

6. **The N-Quads mirror dump ADR-018 promises is *not* part of this.** A served surface can be
   withdrawn; a mirrored dump cannot. It stays unbuilt and gated on the legal work TODO 1.7 tracks,
   and this ADR does not weaken that.

### Alternatives rejected

**Publish nothing until A14 concludes.** Seriously considered, and it is the conservative reading of
ADR-004. Rejected because ADR-004 itself draws the line at metadata, official links and bounded
excerpts rather than at silence, and a structural graph with no provision prose is on the permitted
side of that line. Waiting would also make the whole pipeline unusable by anybody for a question
whose owner and timeline this project does not control.

**Redact at write time — store only redacted artifacts.** Rejected, and it is the most tempting
alternative, because it would make a leak impossible by construction. It fails on three counts: it
turns the rights decision into a corpus regeneration, so a favourable determination would mean
re-running a vLLM extraction over 1,264 documents to recover text we had already read; it discards
the preservation record this pipeline exists to keep, which is the opposite of ADR-004's own posture
for PDF bytes; and Gate P1's coverage check needs the real text, so the gate would be measuring a
redacted tree against unredacted markdown and failing every document.

**One flag plus one rights confirmation.** Rejected per decision 3.

## Consequences

- **A metadata-only AKN document has empty provisions.** It is honest and it is of limited use to a
  consumer who wants to read the bill — for which the answer is the official link, exactly as it
  already is for the stored PDF. The site's value in this mode is citability and structure, not
  text.
- **We publish headings, which are the drafter's words.** That is a deliberate, bounded, reversible
  judgement, and it should be read as one — not as a finding that headings are outside copyright. A
  narrower determination flips `KEEP_HEADINGS` and re-serves; nothing needs regenerating.
- **Redaction costs a parse per request.** No caching layer is designed here, and for a corpus
  approaching two thousand documents that is a throughput question a future ADR may have to answer.
- **The serving process reads `PIPELINE_DATA_ROOT` directly.** Every path it opens is recomputed
  from a validated identity (`parse_work_path`, then `slug_for`), never joined from a request
  string, so HANDOFF 17's rule holds on the serving side as well.
- **Whether the corpus may be published at all is still not decided.** Both flags are off, and
  production refuses either without a recorded confirmation. What this ADR settles is the *shape* of
  the decision — two questions, two controls, a reversible boundary — not the answer. TODO 1.9
  carries the owner items.
