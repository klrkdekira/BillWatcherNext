# ADR-035: The cheap reading comes first; MinerU becomes the cross-reference

Status: accepted
Date: 2026-08-23

## Context

Directed on 2026-08-23: read the corpus with the best and fastest available PDF parser, and spend
MinerU on cross-reference rather than on first contact, because MinerU is the expensive tier.

The corpus this now applies to is real and measured: **1,265 documents, 27,833 pages**, 0
unreadable, averaging 22 pages. At one model call per page a MinerU-first corpus costs ~27,833
calls. The same budget spent *second* buys something a MinerU-first corpus cannot have — a check on
the reading — because of a property of Gate P1 that is easy to miss:

```python
def evaluate(root: Node, markdown_text: str, *, unit, min_coverage) -> FidelityResult:
    """Judge one provision tree against the markdown it was read from."""
```

Gate P1 scores a provision tree against **the markdown**, never against the page. So whatever
produced that markdown is unchecked. A reading that drops a subsection, joins a marginal note into
a provision, or returns letter-spaced fragments passes the gate exactly as a faithful one does,
provided the tree faithfully reproduces it. One reading of a document — however good the reader —
cannot close that hole. Two readings with disjoint failure modes can.

### What was measured, not assumed

Speed and yield, on 443 real pages from this corpus:

| Extractor | Throughput | Full corpus | Licence | Locked? |
| --- | --- | --- | --- | --- |
| `pypdfium2` raw | 975 p/s | ~29 s | BSD-3/Apache-2.0 | yes (ADR-020) |
| `pypdf` | 124 p/s | ~3.7 min | BSD-3 | yes |
| `pdftext` plain | 98 p/s | ~4.7 min | Apache-2.0 | no |
| `pdftext` structured | 74 p/s | ~6.3 min | Apache-2.0 | no |
| `pdfminer.six` | 50 p/s | ~9.2 min | MIT | yes (ADR-016) |
| MinerU | 1 call/page | 27,833 calls | Apache-2.0 client | yes |

Yield is 1,593–1,754 characters per page across all of them, so nothing here trades text for time.
The corpus is also **born-digital**: 46 of 48 sampled documents carry a real text layer at
~1,400–1,700 chars/page, the 1990s included. This is not a scan-recovery problem, which is the
usual reason to reach for a vision-language model first.

Where the cheap tier actually breaks, found by hunting text clusters that share a baseline:

- **Marginal gazette and chapter references** — `24 dengan seksyen yang berikut:` + `Bab 45`;
  `[PN. (U) 1874.]`. Present in 4 of 8 sampled 1990s bills. This is ADR-016's case, in the wild.
- **Tables and schedules** — Supply Bill columns collapse to `MaksudTajuk` + `Amaun`. A Supply Bill
  *is* a table, so this is not a cosmetic loss.
- **Heading inflation** — 20 of 120 sampled documents (~17%) come back more than half headings,
  worst 90%, in every decade. A reprint set in an unusual font defeats the size-ratio test.
- **Body letter-spacing** — 15 of 120 (~12%) exceed 6 lone letters per 1,000 characters, worst 49:
  kerned glyphs read as separate words (`Suatu Akta u n t uk meminda`). Measured on the body only,
  because a bill's cover prints `b e r n a m a` letter-spaced *on purpose* and counting page one
  flags the whole corpus for something that is in the paper.
- **Glyph-encoding damage** — negligible: 3 of 60 files, essentially one broken-`I` token
  (`IMPL1KASI`). No text extractor can repair it; only a reader of the rendered image can.

## Decision

1. **The local tier is `billwatcher.legislation.layout`, which already exists.** ADR-016 built a
   geometric reader on `pdfminer.six` specifically because *a marginal note is typeset on the same
   baseline as the provision it annotates*, and it already classifies lines into
   `provision`/`heading`/`marginal`/`body` and drops running furniture. `pipeline.reading` is only
   the markdown *assembly* on top of it, versioned separately (`LOCAL_READING_VERSION`).

2. **`pdftext` is rejected, on dependency grounds.** It was the strongest external candidate —
   Apache-2.0, same PDFium engine, and it demonstrably fixes both the table and marginal cases. But
   `pdftext==0.7.1` pins `pypdfium2==5.10.1` exactly, and this project requires `>=5.13.0` for the
   MinerU render path (ADR-020). Taking it means pinning the whole project's PDF renderer to an
   exact version chosen by a transitive dependency. It buys layout analysis this project already
   owns, at that price. PyMuPDF and `marker-pdf` stay rejected on licence (AGPL-3.0/GPL-3.0),
   unchanged from ADR-016: a publicly reachable service (ADR-031, ADR-033) cannot take that on
   incidentally. `docling` is MIT but drags a torch layout stack, putting it nearer MinerU's cost
   than pdfminer's; untested here.

3. **A marginal note is emitted as an HTML comment, not as text.** `<!-- marginal: ... -->`. It is
   an annotation on the enacted text, not part of it. Inline it would do precisely what ADR-016
   exists to prevent, *and* it would depress Gate P1's coverage — an annotation no provision tree
   can contain would count against a faithful reading. As a comment it survives in the artifact for
   a human, is dropped by `_extractor_view` alongside the page markers, and can never be spliced.
   `-->` and `>` inside a note are replaced, or the note could terminate its own comment and leak
   into the body.

4. **The reading declares when it should not be trusted.** `heading_ratio` and `lone_letter_rate`,
   with thresholds set from the measured medians above, mark a reading `suspect`. A suspect reading
   is still written — it is the best local reading there is — and is still named in the manifest.
   It is a statement about *where to spend the cross-check first*.

5. **MinerU becomes `pipeline cross-reference`**, storing its reading in its own artifact slot
   (`document.crosscheck.md` + provenance) and reporting per-document agreement against the local
   reading. It **never promotes its reading over the first**: a divergence is a finding for a human,
   because when two readings disagree this step knows that one is wrong, not which.

6. **Agreement is symmetric distinct-word overlap** over Gate P1's own tokenisation
   (`tokens_for_comparison`), thresholded at 0.75 — deliberately far below the gate's 0.95. Two
   independent readings of one page legitimately differ on hyphenation, furniture and table
   rendering; this is a "these disagree about the substance" line, not a fidelity score. Symmetric
   because neither reading is the reference, and a one-sided measure hides the direction it does not
   look in. Measured over the whole reading rather than `_extractor_view`'s body slice, because that
   slice's start is found by scanning for the first structural marker and two readings can locate it
   at different offsets — a divergence measured there would partly measure disagreement about where
   the body begins.

## Consequences

**ADR-021's boundary is amended, deliberately and narrowly.** That ADR put PDF parsing outside the
pipeline — "the operator has a vLLM endpoint for that, separately" — and markdown entered through
`import-markdown`. Reading 27,833 pages through a model to get a *first* draft is what that boundary
was avoiding, and it is now the thing being avoided by crossing it. `extract-markdown` does not
become a second writer: it produces text and hands it to `import_markdown`, which keeps sole
ownership of provenance, the language cross-check, and compare-before-write.

No new dependency. Nothing is added to the locked set, which is what ADR-016 spent five packages to
buy and what `pdftext` would have re-litigated.

**A latent bug surfaced and was fixed.** `verify._artifact_present` ended in
`return store.has_semantic(...)`, so every artifact it did not recognise was answered for as if it
were the semantic pair. Adding `crosscheck` to `ARTIFACTS` made verify report a missing provenance
record for a file that was never there, on every document. It is now exhaustive and raises on an
unknown name. Any future artifact would have hit the same trap.

**Measured on the real corpus**, in one run: 1,265 documents read in **11.4 minutes**, 1,253
markdown readings written, **270 suspect (21.3%)**, 12 with no text layer at all. The throughput
table above measures raw text extraction; the step is slower than 50 p/s implies because
`extract_layout` also runs pdfminer's `LAParams` analysis, per-character font collection and
furniture classification across pages. 11 minutes against ~27,800 model calls is the whole argument
for this ordering, and it survives the correction comfortably.

**The honest limits.** The local tier is unreliable for roughly a fifth of the corpus and now says
which fifth, but it does not repair any of it. Table structure is not recovered — a Supply Bill's
schedule reads as prose. And a cross-reference over the whole corpus is ~27,833 model calls: at even
two seconds a page that is upwards of fifteen hours of endpoint time, resumable, and it produces a
list of divergences for a human to work through, not a corrected corpus.
