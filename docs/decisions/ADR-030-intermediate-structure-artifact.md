# ADR-030: The structural reading is a persisted intermediate artifact; Akoma Ntoso is rendered from it, and the extractor returns anchors, not text

Status: accepted
Date: 2026-08-22

## Context

Step 4 as built (ADR-022, ADR-025) is one fused step: an LLM extractor reads `document.md`, the
tree is gate-checked, rendered to Akoma Ntoso, schema-validated, and only the XML is kept. The
tree — the actual product of the expensive call — is thrown away after one use.

Two costs follow, both observed once the first real corpus went through:

- **The LLM re-emits the entire document.** The ADR-022 prompt asks for the hierarchy *with body
  text* (`"paragraphs": [...]`), so output tokens scale with document length. Output generation is
  the slow, GPU-bound half of an LLM call; a long bill burns minutes re-typing text that already
  sits on disk in `document.md`, risks truncation and timeout, and can paraphrase — which Gate P1
  then correctly rejects, wasting the whole call.
- **Every regeneration re-pays the read.** `needs_rebuild` keys the AKN artifact on the renderer
  version, gate version, and `bill.json` hash, so a renderer fix, a threshold bump, or a crawl
  correcting one title re-runs the full LLM extraction of every affected document even though
  nothing about its structure changed.

The commissioner directed the shape of the fix on 2026-08-22: "conversion directly to akoma ntoso
is too resource intensive, how about we first produce an intermediate format that fits all the
bills we got so far then we'll do the conversion probably at the end of the pipeline."

## Decision

1. **The provision tree becomes a persisted artifact**: `document.structure.json`, a versioned
   JSON serialisation of the existing `Node` tree (node type from the §26.2 vocabulary, printed
   `num`, `heading`, paragraphs, children) plus the resolved `language` and `unit`, written beside
   `document.md` with its own provenance record and validated against its own JSON Schema
   (published with the definitions, ADR-029). No new format is invented: this is the tree the
   pipeline already builds, trusts, and gates — now written down.
2. **Step 4 splits into two steps with two provenance keys.**
   - *4a `extract-structure`* (LLM, expensive): markdown → `document.structure.json`. Staleness
     keys: the markdown hash, extractor `name`/`model_id`/`prompt_sha256`, gate version. **Gate P1
     moves here** — `fidelity.evaluate` judges a tree against markdown and never needed the XML.
     Its verdict is written as `document.structure.gate.json`; a blocked reading is kept as
     `document.structure.rejected.json`; `has_structure` becomes the promotion flag.
   - *4b `render-akn`* (deterministic, cheap): promoted structure + `bill.json` →
     `document.akn.xml`, schema-validated as today. Staleness keys: the structure hash,
     `bill_sha256`, `AKN_VERSION`. A renderer or FRBR fix now regenerates the whole corpus in
     seconds with **zero** LLM calls; only a prompt/model change or new markdown re-invokes the
     extractor.
3. **The extractor contract changes from text to anchors.** The markdown is sent with numbered
   lines; the model returns each node's type, printed number, heading, and start line — never body
   text. Paragraphs are sliced out of `document.md` deterministically between anchors. Output
   tokens drop from O(document) to O(provisions); paraphrase becomes structurally impossible,
   because body text never passes through the model. `MarkdownStructureExtractor` keeps its
   protocol shape; both implementations (vLLM, regex) satisfy the anchored contract — the regex
   extractor anchors trivially, since it already walks lines.
4. **Gate P1 keeps all seven findings.** Coverage is near-by-construction under slicing, but the
   gate stays: a wrong anchor mis-slices text exactly the way `low_text_coverage`,
   `sequence_order` and `unanchored_run` detect, and eId discipline (`duplicate_eid`,
   `missing_num`) is unchanged. eId assignment stays with `assign_eids`, never the extractor.
5. **"Conversion at the end" means decoupled, not deferred.** Rendering and XSD validation stay in
   the routine corpus pass — they are the cheap steps and they surface renderer defects while they
   are one document old. The win is that the expensive read and the cheap render stop being one
   atomic step.

## Consequences

- **This is phase-two tooling** (ADR-029): the public cache ships first from the fused step as
  built. When the split lands, the fused step's artifacts regenerate once under ADR-026's
  provenance rule (their stored `inputs` no longer match) and then settle.
- `KNOWN_FILENAMES`, `PipelineStore` (structure save/load/has/withdraw, gate verdict, rejected
  reading), the CLI, and Make targets all grow; `document.akn.gate.json` and
  `document.akn.rejected.xml` are retired in favour of the structure-level names, since the gate
  no longer judges the XML.
- **The redaction posture improves for free**: the stored intermediate keeps full text privately
  in `pipeline-data/` (never committed, ADR-029), and redaction remains purely a
  publication-boundary policy (`pipeline.redact`), applied at export and at serving — never baked
  into the stored reading.
- **Precedent, for the record**: mature legislative systems treat AKN as a publication format
  rendered at the edge of an internal working representation — Laws.Africa's Indigo (Bluebell
  plain-text grammar → AKN), legislation.gov.uk (CLML → transforms), the US (USLM). The
  intermediate-first shape is the standard pattern, not a compromise.
- A tiered extractor (regex first, LLM only for the Arrangement/body split or on gate rejection)
  becomes cheap to add later, but is deliberately not decided here.
