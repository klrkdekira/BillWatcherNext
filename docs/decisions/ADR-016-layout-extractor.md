# ADR-016: Layout-aware extraction uses pdfminer.six, as a second reading

Status: accepted
Date: 2026-08-19

## Context

HANDOFF 26.1 requires a geometric reading of a legislative PDF: each line's page, baseline, left
edge, font, and size. The structure this pipeline depends on is carried in position, and one case
decides the library choice. A **marginal note is typeset on the same baseline as the provision it
annotates**. A reader that reports only a line's starting position joins the two, splicing an
annotation into the middle of the legal text — and it does so silently, producing text that looks
well-formed.

Four options were measured on a constructed PDF placing `Tajuk ringkas` at x=430 on the same
baseline as `1. Tajuk ringkas dan permulaan kuat kuasa.` at x=72. Measured, not assumed: the
assumption that `pypdf` would serve is the one this ADR exists to correct.

| Option | Geometry | Text | Cost |
| --- | --- | --- | --- |
| `pypdf` `visitor_text` | **Wrong** — reports the *line's* starting x (72) for both runs | Correct, decoded | None; already locked |
| `pypdf` `visitor_operand_before` | Correct — reports x=430 | **Wrong** — raw font-encoded bytes, undecoded | None; already locked |
| `pdfminer.six` | Correct — x0=430.00 as its own text line | Correct, decoded, paired | +5 packages |
| `pdfplumber` | Correct | Correct | +8 packages, incl. `pillow` and `pypdfium2` |
| PyMuPDF | Correct | Correct | AGPL-3.0 or a commercial licence |

`pypdf` can give accurate geometry *or* correctly decoded text, and not both paired. The two
callbacks cannot be zipped together reliably: pypdf merges and splits text chunks on its own
schedule, so the pairing is positional guesswork on exactly the documents where it matters.

## Decision

Stage L1 reads with **`pdfminer.six`**, added as a core dependency.

- `pdfplumber` is rejected: it is a wrapper around this same engine and additionally pulls
  `pillow` and `pypdfium2` — an imaging stack this project has no use for, into an image whose
  contents are security-reviewed (`docs/operations.md`).
- PyMuPDF is rejected on licence. AGPL-3.0 for a publicly reachable service is a commitment this
  project has not made and should not make incidentally.
- `pypdf` **stays**, and `scraper/parse_document.py` is untouched. It continues to produce the
  flat, page-delimited text that search is built on. Nothing in the 27,575 indexed pages is
  invalidated by this ADR.

Stage L1 is a **second, independently versioned reading** of the same stored bytes, under its own
extractor name (`pdfminer-layout`) and its own `LAYOUT_EXTRACTOR_VERSION`. Two readings of one
document version coexist by design.

Its output is stored in `document_structures` and `provision_nodes`, **not** in
`document_extractions`. That is deliberate and load-bearing: `scraper/service.py`'s
`persist_current_extraction` demotes every `is_current` extraction for a version regardless of
extractor name, and `jobs/retention.py`'s `_prune_extractions` keeps two rows per version ordered
by creation time without partitioning by extractor either. Both are correct while one extractor
writes that table and become data loss the moment a second one does. Writing to separate tables
sidesteps both without changing behaviour that is currently right; the hazard is recorded in
`TODO.md` for whoever adds the OCR tier, which is the change that will actually trip it.

## Consequences

The locked dependency set grows by five: `pdfminer.six`, and transitively `cryptography`, `cffi`,
`pycparser`, and `charset-normalizer`. `cryptography` is a native crypto library with an active
advisory history, and this project has no CI, so HANDOFF 20's dependency review is the control.
It was re-run on 2026-08-19: 67 locked requirements, no known vulnerabilities from PyPI advisories
or OSV (`docs/operations.md`). It must be re-run before each release, as it already must be.

The dependency is a **core** requirement, not an extra. `tests/unit/test_deployment_consistency.py`
constrains optional dependencies only, so it neither permits nor detects this change; there is no
test pinning the runtime dependency set, and this ADR does not add one — the lockfile plus the
dated review is the mechanism this project chose.

`pdfminer.six` is pure Python and slower than a C parser. Stage L1 runs offline as a backfill over
stored bytes (`make restructure`), never in a request path, so throughput is not a constraint.
Reading is bounded at 2,000 pages per document so one malformed file cannot occupy a worker
indefinitely.

### Addendum, 2026-08-19: furniture detection must not discard structural signals

A combinatorial stress sweep (varying part/section counts, subsections, schedules, and page
geometry together) found that the running-head heuristic in `_classify` — masking digits and
requiring a fixed baseline across most pages — could erase genuine content, not just page
furniture. Three distinct signals were found affected and are now checked *before* the furniture
test rather than after: a Part/Chapter/Schedule heading, a numbered provision's opening line, and
a marginal note, each of which can land above the header threshold or below the footer one when a
page's preceding content runs short, and each of which then masks and repeats exactly like a
running head. The fix and its tests are in `layout.py` and `test_legislation_layout.py`; a
residual, lower-severity limit — a plain body-text sentence in the same position is not yet
protected — is documented in `layout.py` rather than fixed, since it does not affect Gate L1's
structural comparison and widening the protection further risks reintroducing the opposite
failure (a genuine running head no longer recognised as one).
