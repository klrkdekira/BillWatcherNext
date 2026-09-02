# ADR-042: The reading's geometry is kept beside the markdown, and the structure parser reads depth from it

Status: accepted
Date: 2026-09-02

## Context

The audit of the structure parser on 2026-09-02 (`documentation/status.md`) took Gate P1's pass
rate from 52% to 78% by teaching the parser a dozen printed shapes, and every one of those fixes
recovered information the reader already had. `markdown.layout` knows each line's column position,
its indent from the page's text column, and the weight of its first glyph. `markdown.reading`
flattens that into prose blocks, and `graph.structure` then re-derives structure from the shape of
the text alone.

Indentation is the signal the parser most often lacked. On the page, a section quoted from the Act
being amended is block-indented; the bill's own clause hangs at the column. A list's items sit at
the depth of the list they continue. A wrapped continuation line sits at the paragraph's
continuation indent, not the first-line indent. None of that survives into markdown, so the parser
guessed it from quotation marks the reading may have lost, from word lists, and from the bill's
numbering — and the largest remaining cause of rejection after the audit, sections quoted from a
principal Act with their marks lost, is exactly the case indentation settles.

ADR-021 made markdown the interface so a reading produced by any tool could enter the pipeline.
That property matters and is kept: the markdown stays the plain reading a person or another tool
can consume unchanged, and nothing is encoded into it.

## Decision

1. **The assembly writes the reading's geometry beside the markdown**, as `document.blocks.json`:
   one record per markdown block, in the block's order, so `markdown.split("\n\n")` and the list
   line up index for index. Each record carries the block's page, its first line's indent from the
   page's text column in points, its role, and the emphasis of its first glyph. Page markers and
   marginal comments are blocks too and carry records.
2. **It is part of the `markdown` artifact, not an artifact of its own.** `import_markdown` writes
   it under the markdown's provenance record as a second output, refuses geometry that does not
   line up with the text block for block, and withdraws any sidecar when a reading produced
   elsewhere replaces a local one — a sidecar describing a different text is worse than none.
   `verify` re-hashes it as it does every listed output.
3. **The structure parser takes the geometry as an optional input and reads depth from it.** A
   provision number set deeper than the bill's own clause column, by more than a subsection's
   first-line indent, is a section quoted from another Act; everything at that depth after it is
   the quoted text, until a line returns to the bill's column. Quotation marks are still read.
   Without geometry the parser reads exactly as before, so an imported reading loses nothing it
   had.
4. **The geometry is a staleness input of the structure.** `convert-to-akn` names
   `document.blocks.json` among its source files when present, so a re-read that moves a block's
   depth regenerates the tree.

## Consequences

- The parser is no longer blind to the one thing the reader measured that the text cannot carry,
  and the reader's classification and the parser's structure are now judged on the same corpus by
  the same loop: `make audit` (`billwatcher audit-structure`) parses and gates every stored reading
  against the recorded verdicts and writes `documentation/structure-audit.md`, tracked so a parser
  change's reach shows in `git diff`.
- Every stored reading is re-read on the next `make markdown` (`LOCAL_READING_VERSION` 1.7.0 is
  the carrier), which is what writes the sidecars; until then the parser reads without them. The
  step also treats a local reading with no sidecar as stale, so a corpus that was built between
  the version bump and the sidecar cannot be skipped as current.
- The threshold for "deeper than the clause column" is a measured constant in the parser
  (`_QUOTED_DEPTH_TOLERANCE`), not a configuration setting: it describes Malaysian legislative
  typesetting, not an operator's preference.
