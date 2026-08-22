# ADR-017: Gate L1 blocks on structure and reports heading differences

Status: accepted
Date: 2026-08-19

## Context

HANDOFF 26.3 makes the Arrangement of Sections a validation oracle: parse it separately, parse
the body independently, assert they agree. The source specification words the assertion as "same
numbers, same order, same headings", and makes the whole of it blocking.

Applied literally, the heading half fails almost every real document, for a reason that is not a
defect. A section's heading is printed **as a marginal note** in AGC reprints and inline in other
typesettings, and the marginal note is routinely an abbreviation of the contents-page entry. The
constructed fixture in `tests/support/pdfs.py` reproduces this on purpose: the contents page lists
`Tajuk ringkas dan permulaan kuat kuasa` and the margin prints `Tajuk ringkas`. Both are correct
readings of the same document.

A gate that fires on almost everything is not a gate. It trains an operator to clear a queue
without reading it, which is worse than not having the check.

## Decision

Gate L1 is blocking on **structure** — which provisions exist, and in what order — and reports
heading differences as findings that do not block.

- Blocking difference kinds: `missing_in_body`, `missing_in_arrangement`, `order`,
  `duplicate_eid`.
- Non-blocking: `heading`.
- `duplicate_eid` is blocking and is checked *before* the tree comparison, because comparing the
  two trees as sets collapses a duplicate and reports the document as passing. A body with two
  section 1s is ambiguous for every later citation and amendment anchor, and it would also violate
  `uq_provision_nodes_eid` at write time — so catching it in the gate turns a write error into a
  reported review item.
- Comparison is restricted to the node kinds an Arrangement actually lists: Part, Chapter,
  Schedule, and Section or Clause. No arrangement enumerates subsections, so comparing deeper
  would fail every document. The body legitimately carries detail the contents page never lists.
- Order is compared over the provisions both sides agree exist, so one dropped section is reported
  once as missing rather than again as every following provision being out of order.

The narrowing is one constant, `BLOCKING_DIFFERENCES` in `legislation/gate.py`. Widening it when
heading extraction is good enough is a one-line change and this ADR is then superseded.

Two further scope decisions, recorded here because they are easy to mistake for oversights:

**Gate L1 is per document, in whichever language that document is written.** The source
specification asks for the check "for both BM and EN". That is two different checks: this one,
and a *pairwise* comparison across the two language editions of one bill. The pairwise check is
Gate L4 (HANDOFF 26.4) and cannot run today — `documents.language` is written as `"unknown"` at
creation and never updated, so the corpus cannot be partitioned into pairs. Gate L1 sidesteps
that entirely by reading the language from the document's own Arrangement heading (`Susunan
Seksyen` / `Arrangement of Sections`), which is better evidence than a listing column anyway.
Gate L1 is therefore not blocked on classification; Gate L4 is.

**A document with no Arrangement of Sections is `no_arrangement`, not a failure.** An explanatory
statement legitimately has no contents page; the gate simply has no oracle to apply and says so.
A document the extractor found *no text at all* in is `no_text` and **is** blocking, recorded
separately: the 22 known scans are the documents most likely to be wrong, and filing them as
"has no contents page" would make them indistinguishable from legitimate ones and invisible in
every count.

## Consequences

A reading that fails the gate is stored and never promoted; it is a review item, not a discard.
A newer parser that fails the gate does **not** demote a reading that passed — otherwise a parser
regression would silently withdraw a good tree from everything downstream, which is the opposite
of what an additive record is for.

One failing document is a work item. A failure *rate* above baseline means the parser or the
upstream typography changed, and raises `structure_gate_failure_spike` at `warn`, carrying the
full status histogram so an operator can see *which way* the gate is failing without querying.
This mirrors `extraction_failure_spike` exactly, including its severity: `warn` rather than
`critical`, because `make doctor` is a release gate and a corpus-wide review backlog is not an
outage.

Heading differences are still recorded on every row. They are the raw material for deciding
whether the heading half can ever be made blocking, and they cost nothing to keep.
