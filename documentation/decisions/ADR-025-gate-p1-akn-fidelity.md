# ADR-025: Gate P1 blocks on accountability, and the rendered XML is validated against the schema

Status: accepted
Date: 2026-08-22

## Context

ADR-022 made a language model the reader of legislative structure, for a good reason: an Arrangement
of Clauses entry is textually identical to the body provision it lists, and markdown carries no page
or geometry signal to tell them apart. The consequence is that **the canonical Akoma Ntoso for a
piece of legislation is a model's output**, and a model that quietly drops clause 7 or renumbers a
subsection produces a document that is well-formed, plausible, and wrong. Nothing downstream can
notice: the XML parses, the eIds look ordinary, the graph builds, the provision IRIs resolve.

Until this change there was no check at all between the extractor and the store. `convert_to_akn`
wrote `document.akn.xml` if serialisation did not raise. Two different questions therefore had no
answer:

- Does the tree account for the markdown it was read from?
- Is the XML we are calling Akoma Ntoso actually Akoma Ntoso?

The second turned out not to be rhetorical. Validating the existing renderer's output against the
published OASIS schema for the first time failed it: `<content>` was emitted alongside child
elements (AKN's hierarchy model lets a container introduce its children *or* carry content, not
both), the FRBR blocks were three near-identical copies missing `FRBRcountry`, `FRBRsubtype`,
`FRBRnumber`, `FRBRlanguage` and `FRBRformat`, and `FRBRauthor` referenced organisations that were
never declared. Every one of those documents would have been rejected by a consumer's AKN tooling,
which is the only reason to use the standard.

ADR-017's warning is the binding design constraint on the first question: **a gate that fires on
almost every document is not a gate — it trains an operator to clear a queue without reading it.**

## Decision

1. **Gate P1 asks whether a reading is *accountable*, not whether it is *good*.** Four checks, in
   `pipeline.fidelity`:

   | Finding | Question | Kind |
   | --- | --- | --- |
   | `duplicate_eid` | do two provisions resolve to one identifier? | exact |
   | `missing_num` | is a provision missing its printed number? | exact |
   | `sequence_gap` / `sequence_order` | is a number skipped, or does it run backwards? | exact |
   | `low_text_coverage` | do the source's words appear in the tree? | threshold |

   All five kinds are blocking. `duplicate_eid` is the one nothing else catches — `assign_eids` will
   mint the same eId twice without complaint, and every citation, `hasPart` edge and provision IRI
   beneath it is then ambiguous, the same reasoning that made it blocking in Gate L1 (ADR-017).
   `missing_num` matters for the same reason: an unnumbered node inherits its parent's eId, silently
   merging two provisions into one identifier. A backwards number is the table-of-contents bleed
   signature — 1..12, then 1 again — which is precisely the failure ADR-022's design exists to avoid
   and therefore the one to check for.

2. **Only coverage has a threshold, and it is measured over *distinct* tokens of the extractor's own
   view of the markdown.** Both halves of that are load-bearing. The extractor is instructed to drop
   Arrangement entries, and an Arrangement entry contributes **no new distinct word** — the body
   provision it lists prints the same words — so a distinct-token measure is insensitive to how long
   a document's contents page is, while still catching what actually matters: a dropped page, clause
   or schedule removes whole distinct words from the tree. Measuring against `strip_markdown_line`'s
   filtered text rather than raw markdown keeps the threshold from tracking page-boundary comments
   and heading punctuation, which the tree was never meant to carry. A multiset ratio over the same
   text is reported beside the verdict and never blocks: it is a useful calibration number and a
   terrible gate.

   The denominator is also taken from the document's first Part, provision or Schedule heading
   onward, not from the top of the file. A real bill PDF opens with a cover page, a long title, the
   presenter's name, an enacting formula and often a whole Arrangement of Sections, and a provision
   tree contains none of it — the parser attaches pre-provision text to its synthetic root and the
   walk skips it. Counting it made a *faithful* reading of a real bill score **0.71-0.81**, so the
   0.95 default would have rejected essentially the entire corpus while presenting itself as a
   quality bar. This was found by review, on a realistic fixture, after the threshold had already
   been reasoned about at length against provision-only test markdown — which is the lesson: a
   threshold can only be calibrated against the shape of the real input. The cost is stated rather
   than hidden: front matter is now unchecked. It was never meaningfully checked, because no tree can
   hold it and its absence was indistinguishable from a correct reading; if it ever becomes
   structured output beyond the long title, it needs its own check rather than a share of this one.

   The denominator also excludes the words that *name* a structure — `BAHAGIAN`, `JADUAL`,
   `SUSUNAN FASAL` and their English equivalents, derived from `NODE_LABELS` and `SCHEDULE_ORDINALS`
   so the two cannot drift apart. Every parser here consumes those words and keeps only the number
   and the title, so no faithful tree can ever contain them, and a measure that charges a tree for
   missing them is scoring formatting rather than fidelity. This is not a rounding correction: on a
   short real bill those three words alone were **5.2% of distinct tokens**, enough on their own to
   fail a perfectly correct reading at the 0.95 default, while costing almost nothing on a long
   document — so leaving them in would have made the gate quietly stricter for short documents than
   for long ones, which is not a threshold anybody could calibrate. With them excluded a faithful
   reading scores exactly 1.0, which is what lets the threshold mean what it says.

3. **The threshold is a `Settings` value** (`AKN_GATE_MIN_TEXT_COVERAGE`, default 0.95), because the
   real corpus is unmeasured (A15) and a number nobody has calibrated should not be compiled in.
   Exact where exactness is defensible; configurable where it is a judgement. It also carries its
   own code version (`AKN_FIDELITY_GATE_VERSION`, separate from `AKN_VERSION`), so tightening it
   re-judges every document without implying the XML changed.

4. **Sequence continuity is checked at the scope each provision type actually uses.** Clauses and
   sections are one document-wide run; chapters, subsections, paragraphs and subparagraphs restart
   inside their parent. This is the ADR-017 constraint applied concretely: the parser nests clauses under
   the open Part, so checking every sibling list would demand that Part II's first clause be
   numbered 1 and would fire on nearly every multi-Part bill. The one legitimate irregularity in
   Malaysian drafting — an inserted `5A` between `5` and `6` — is modelled rather than absorbed as
   slack, so real gaps stay visible.

   Two numbers are also only comparable once you know what *kind* of numbering they are, and that
   is keyed on the node type: Parts, Chapters and subparagraphs are numbered in roman, paragraphs in
   letters, everything else in arabic numerals with an optional inserted-provision suffix. This is
   not tidiness. `I` is simultaneously a valid roman numeral and a valid paragraph letter, and the
   first draft of this gate compared them without consulting the type — so `BAHAGIAN I` followed by
   `BAHAGIAN II` was read as a letter sequence, the expected successor of `i` was computed as `j`,
   and a `sequence_gap` was reported on the containers of essentially every multi-Part bill in the
   corpus. It was caught by review before it landed, and it is worth recording because it was
   precisely the ADR-017 failure this ADR opens by quoting: a gate that fires on almost every
   document. An unrecognised token now yields no opinion and no finding, because a gate that guesses
   at a numbering scheme it does not understand invents gaps that are not there.

   Two further scope corrections came out of the same review, both the same failure mode. Chapters
   restart inside each Part — `BAHAGIAN II` opening at `Bab 1` is correct drafting — so `chapter`
   belongs with the restarting types rather than in a document-wide run; treating it document-wide
   rejected every multi-Part bill that uses chapters. And a document-wide run has to be assembled
   depth-first, in document order: collecting it level by level meant a tree with one provision type
   at two depths (a document with an unheaded opening section, then Parts) was compared out of order
   and reported gaps that were not in the document.

5. **Continuity is not enough on its own: the run is anchored.** Comparing adjacent pairs is blind
   to a constant offset. A tree numbered 3, 4, 5 for a document printed 1, 2, 3 is continuous by
   construction, and set coverage barely moves because all the provision *text* is still there and
   only the numbers are wrong — so it passed at coverage 1.0 with every eId, provision IRI and
   citation in the document off by two. `unanchored_run` checks that the document-wide run of the
   unit type starts at 1 or 2, which is the one anchor the document itself supplies. Two rather than
   one because an amendment bill occasionally opens at 2.

   Relatedly, a tree is no longer passed against a source with nothing scoreable in it. When the
   coverage check cannot run there is no basis for saying a tree accounts for a document, and this is
   not hypothetical: it is exactly what the MinerU reading produces for a scan it recovered nothing
   from — a file of `<!-- page N -->` markers — where the old behaviour would have published an
   invented tree, under permanent IRIs, against a document nobody had read. The status is
   `no_source_text` and it blocks.

6. **A rejected document is a review item, not a discard**, exactly as ADR-017 requires of Gate L1.
   `document.akn.gate.json` is written on **every** path — pass, blocking mismatch, and the failure
   that happened before a tree even existed — so a document's verdict is always on disk and always
   countable. On failure the rendered XML is kept as `document.akn.rejected.xml` and
   `document.akn.xml` is **not** written, because in this pipeline `has_akn` is the promotion flag
   every later step reads: a tree that cannot account for its source must not become the graph, the
   published Manifestation, or anyone's citation.

   That rule has to apply to a *re-read* as well, which the first draft got wrong. When a document
   already converted was re-read and the new reading failed, the failing verdict was written but the
   previously promoted `document.akn.xml` was left in place — so the corpus served one render while
   the confidence statement printed beside it described a different one, telling a reader that the
   reading they were looking at had been checked when the check they were shown belonged to another.
   `store.withdraw_akn` now removes the published Expression and its provenance, keeping the verdict
   and the rejected render. Withdrawal is the same rule as first conversion, applied consistently:
   the gate decides whether the file exists.

7. **The gate is replayable offline from stored files, with no model call.** Its inputs are the
   stored markdown, the tree, the gate version and the threshold. That is what makes a threshold
   change a re-judgement rather than a re-extraction, and it is why the corpus-wide pass rate can
   eventually be measured without spending a single vLLM request.

8. **The rendered XML is validated against the vendored OASIS Akoma Ntoso 3.0 XSD, and invalidity is
   our defect rather than the document's.** `akn_schema.validate_akn` returns the schema errors;
   `convert_to_akn` raises `AknSchemaError` and counts the document `failed`, not `rejected`, and
   names the first errors in the failure list. The distinction is deliberate: a gate mismatch says
   something about a document, a schema violation says something about our renderer, and filing the
   second as the first would put a code defect on a review queue for source material.

   The schema is **vendored** (`pipeline/schemas/`, both files byte-identical to OASIS with recorded
   SHA-256 digests), so validation never touches the network — not in a test run and not inside a
   container with no egress. **`xmlschema` was chosen over `lxml`**: it is pure Python with no
   native code to audit, it ships `py.typed` so strict mypy needs no escape hatch, and this project
   has no CI, which makes a manual dependency review the only control on every native dependency it
   takes on — the same reasoning ADR-016 used to reject `pdfplumber`'s imaging stack in an image
   whose contents are reviewed by hand. Schema building is cached; over a corpus of a couple of
   thousand documents the 239 KB parse amortises to nothing. If profiling ever argues for libxml2's
   speed, the swap happens inside one function.

### Alternatives rejected

**Reuse Gate L1's oracle — parse the Arrangement separately and compare the two trees.** This was
the obvious candidate and it is a genuinely stronger check, so it deserves a recorded refusal. It
cannot work here: the LLM extractor is instructed to *drop* the Arrangement, because separating it
from the body is the problem it was introduced to solve (ADR-022). Reinstating the comparison would
mean asking the same model for the Arrangement as a second output and diffing two readings by one
model — which looks like an independent oracle and is not. Gate L1 keeps that job in the
Postgres-backed Stage L1, where page geometry supplies a genuinely independent second reading
(ADR-016). Gate P1 is deliberately a weaker check that is actually independent of the model.

**A total-token coverage ratio.** Rejected: it measures how long the Arrangement is, not whether the
tree accounts for the document, so the threshold would have to be re-tuned per typesetting.

**Making schema validity a gate finding.** Rejected per decision 7.

## Consequences

- **The pass rate over the real corpus is unmeasured, and the default threshold is not calibrated.**
  Every fixture is constructed markdown; the 1,264 stored documents are not reachable from a clean
  checkout, which is the same limit ADR-017 and TODO 1.8 already record for Gate L1. TODO 1.10
  carries the measurement. Nothing here should be read as a measured pass rate, and 0.95 is a
  starting point rather than a finding.
- **Gate P1 cannot detect a fabrication.** Coverage asks whether the source's words reached the
  tree; it says nothing about tree text that was never in the source. A model that invents a
  subsection while preserving every real word passes. This is stated rather than fixed because it is
  the obvious next check and it is not built: it needs a reverse measure (tree tokens absent from
  source) whose false-positive behaviour on legitimately normalised text is unknown.
- **Headings are not compared to anything**, for the reason ADR-017 gives: a section's heading is
  routinely printed as an abbreviated marginal note, so heading equality fires on almost every real
  document.
- **A rejected document leaves review artifacts nobody is yet assigned to read.** That is the same
  unstaffed-queue question ADR-017 raised for Gate L1 and TODO 1.5/1.8/1.10 still carry; it should
  be answered once for all of them, not three times.
- The locked dependency set grows by `xmlschema` and its one transitive dependency (`elementpath`);
  HANDOFF 20's dependency review is the control, and it is now stale (`docs/operations.md`).
- Refreshing the vendored schema is a manual, recorded decision, not an update: a schema change can
  invalidate the whole published corpus, so if a previously published document stops validating that
  is a corpus migration to plan rather than a test to relax (`pipeline/schemas/README.md`).
