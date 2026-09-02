# Status

Written 2026-08-27, after the reorganisation.

## What the project is now

Three stages over local files — download, markdown, graph — and a static publication of the
result. No database, no application server, no model endpoint. `README.md` describes the shape;
this file records where it actually stands.

## Measured, on the real corpus

Numbers from a full `make build` on 2026-08-27:

| | |
| --- | --- |
| Bills downloaded | 1,269 |
| Document PDFs stored | 1,265 |
| Markdown readings | 1,253 |
| Readings flagged `suspect` | 252 (20%) |
| Structures passing Gate P1 | **146 of 1,253 (12%)** |
| Expressions published | 1,192 |
| — with a markdown reading | 1,192 |
| — with a JSON-LD/N-Quads graph | 139 |
| Files in `docs/` | 1,483 |

## Both languages: crawled in code, not yet in the corpus

ADR-040 (2026-08-27) added the four English entry points, the per-document language, and the
wrong-language guard. **The 1,269 bills measured above are still the Malay half of what Parliament
publishes**: the numbers in that table predate the change and no crawl has run since.

- `make download-listings` then `make download` fetches the English half. The listings roughly
  double (69 → ~137 documents) and the document queue is expected to grow by ~1,100 English PDFs,
  about fifty minutes at the crawl delay. Nothing already stored is refetched.
- `make download-listings`'s parse half alone migrates the existing records — `statuses_raw`,
  `source_urls`, `documents[].languages` — offline, from stored bytes, and rewrites all 1,269.
- Whether upstream honours `lang=en` for every target is verified only for the Dewan Rakyat's
  current listing and 2024 archive year (the 2026-08-18 sweep). The rest is expected to behave the
  same way and will report `listings_wrong_language` if it does not.

## Gate P1's pass rate: 28% to 52%, on 2026-08-30

The rejections were a property of the deterministic parser, not of the corpus, and three of the
causes turned out to be nameable and cheap. `AKN_VERSION` 1.3.0 addresses them, measured over all
2,479 stored readings:

| | before | after |
| --- | --- | --- |
| Passing Gate P1 | 690 (27.8%) | **1,292 (52.1%)** |
| `duplicate_eid` | 1,547 | 998 |
| `sequence_order` | 1,704 | 1,107 |
| `sequence_gap` | 1,434 | 737 |
| Published `.jsonld` | 648 | 1,202 |

603 documents gained, **one** lost (`dr-16-2023`, `sequence_gap`); its two stale published files
were left in place by ADR-038 rather than deleted. What the parser stopped doing:

- **Reading the Arrangement of Clauses as clauses.** A bill that prints a contents page prints its
  whole clause list twice, and the parser skipped only the *heading*. It now cuts to the bill's own
  opening — the title block or the enacting formula. `tree.body_start` is shared with the gate's
  coverage view, because the two must cut a document in the same place.
- **Reading quoted amendments as structure.** An amendment bill prints the sections it inserts in
  quotation marks, carrying the *principal Act's* numbering; those became a second clause 13 and a
  sequence leaping to 95 and back. They are now the introducing clause's prose, which is what they
  are, and so still count toward coverage.
- **Reading impossible numbers as clauses.** A cited year (`... Act 1955.`) and a section number
  far ahead of the bill's own sequence are refused. Only those two: a number that runs *backwards*,
  or a Part restarting at 1, is still recorded, because `sequence_order` and `unanchored_run` exist
  to name it and a parser that quietly absorbed it would leave the gate nothing to find.

**What was left was the harder half.** 1,187 readings still failed, and the remaining findings were
no longer one signature — they included genuinely damaged OCR, bills whose clause numbering the
reading lost, and structures a line-by-line reader cannot recover. This is where `structure-handoff`
earns its place: `make handoff OUT=…` writes one packet per document and `make akn FROM=…` reads the
answers back through the identical gate.

## Gate P1's pass rate: 52% to 78%, on 2026-09-02

An audit of the markdown parser against every stored reading: the current parser and gate were run
over all 2,479 readings, each failure was traced back to the markdown line that produced it, and
the failures were grouped by signature before anything was changed. Most of the remaining half was
not one cause but a dozen printed shapes the line-by-line reader had not been shown, and each was
measured before it was addressed. `AKN_VERSION` 1.4.0 and `STRUCTURE_GATE_VERSION` 1.2.0:

| | before | after |
| --- | --- | --- |
| Passing Gate P1 | 1,292 (52.1%) | **1,933 (78.0%)** |
| `duplicate_eid` findings | 7,861 | 1,901 |
| `sequence_order` findings | 6,464 | 954 |
| `sequence_gap` findings | 2,863 | 840 |

644 documents gained and **three** lost: two where a wrapped line is genuinely ambiguous, and one
(`dr-19-2024`) whose earlier pass was a tree built from its own explanatory statement — the body
opening had matched a sentence in the HURAIAN — so the loss is a correction. What the parser
stopped doing, by how many rejected readings carried the shape:

- **Reading a sentence tail as a heading** (124). `...yang dinyatakan dalam` wrapped to a line
  reading `Jadual.`, which the reader had promoted to a heading for being short; the false schedule
  then swallowed every clause after it as a schedule paragraph. A heading is a label and does not
  end in a full stop, and the line before it broke off mid-sentence.
- **Reading a wrapped cross-reference as an opener** (285). `...under subsection` / `(1),
  subsection 13(3) shall have effect...` gave the clause a second subsection (1). A line ending on
  a structural noun, or a token glued to a comma or conjunction, is the sentence continuing.
- **Losing every Part after the first** (165). `BAHAGIAN` with its number on the next line —
  sometimes filed by the reader as a marginal note — never matched. The two lines are one heading.
- **Breaking the paragraph run on the deeper lists** (265 for `(A)`, `(B)`; more for the doubled
  `(aa)`, `(bb)` of older drafting, and the inserted `(aa)` between `(a)` and `(b)`). The parser
  now keeps a stack of the open lists and places each token by the list it continues, case
  included; the gate models the inserted letter and the doubled step as it already modelled `5A`.
- **Reading `(l)` as a subsection** (57 as `(1)`, 59 as `(I)`). Only the position after `(k)` is
  rescued.
- **Hiding a clause behind its spliced marginal note** (146). `Pindaan 4. Seksyen HB Akta ibu...`:
  the note is the heading and the number opens the clause, but only for the bill's exact next
  number and never after an introducing colon, where the same shape is a quoted section.
- **Missing a quotation introduced mid-line** (65), and **missing the back-matter heading run into
  its first sentence** (32), which had let the explanatory statement's numbered paragraphs become
  clauses.
- **Re-rooting a Part printed inside a Schedule** (the gate now numbers a schedule's Parts as
  the schedule's own run, as it already did a Part's Chapters), and **stopping the Arrangement short** of a
  bill whose title block is the bare word `bernama` or whose enacting formula opens `MAKA, OLEH
  YANG DEMIKIAN` (22 readings had no bounded Arrangement; five remain).

One change is a modelling decision rather than a repair, and is recorded as such in
`graph.structure._OpenLists`. A list that **restarts under the parent that already holds it** —
each defined term's own `(a)`, `(b)` in an interpretation clause, or inserted sections' `(1)`,
`(2)` with their quotation marks lost — is read as the parent's prose. It was the largest single
remaining cause (514 rejected readings carried one). One `para_a` per parent cannot name two lists
apart, so the choice was between a rejected tree and a tree that keeps every word and gives up a
sub-structure it has no element for. Modelling definition lists as their own container (Akoma
Ntoso's `blockList`) is a decision for the vocabulary, the renderer and the published schema
together, and has not been made.

**What is left** (545 readings) is now mostly reading damage rather than parser blindness: a
document duplicated by an overlaid "RAHSIA" watermark layer, clause numbers spliced into the middle
of a sentence (`menggantikan seksyen 7. seksyen 7`), Part numbers lost to letter-spacing (`FIrst
s chedule`), quoted replacement schedules whose marks are gone, and treaty schedules whose
`ARTICLE N` divisions have no node type. The largest remaining finding families are duplicate
clause numbers (159 readings) and a clause sequence running backwards (205) — the signature of a
reprinted body or of an Act's sections quoted without marks — then paragraph-letter gaps (193).

### The reading behind the remaining failures, same day

The 545 readings still rejected are 275 from the 1990s, and their damage was traced back to the
PDF geometry rather than to the parser. `LAYOUT_EXTRACTOR_VERSION` 2.5.0 (carried by
`LOCAL_READING_VERSION` 1.6.0) fixes what the geometry showed, each measured over the failing set:

- **Marginal notes in the left margin** (249 of the 546 failing readings have such a column). The
  1990s printings set the note in the *outer* margin, so on a verso page it sits left of the text
  column in small type. pdfminer separates it cleanly; the reader knew only a right-hand margin and
  sorted the note into the body by baseline, so its words landed inside the provision (`Pindaan 4.
  Seksyen HB Akta ibu adalah dipinda, dalam subsekyen seksyen HB. (2), dengan...`). A line that
  ends before the column begins is now a note — measured against the page's *own* column, because
  a bound book's verso and recto margins differ and one document-wide margin was wrong on half the
  pages.
- **Small-capitals faces.** `Times-Roman-SC700` prints capitals; the reading carried `FIrst s
  chedule` and `BAhAgiAN`. The face names itself, so the line is read in capitals with its words
  rebuilt from glyph geometry.
- **Text drawn off the page.** One reading carried its last pages twice, the second copy drawn from
  x = -9 beside `RAHSIA` stamps. Text that begins outside the page box is not printed.

The parser learned the three shapes the corrected reading exposes: a quotation mark carried by a
marginal note (`"Cess on rubber.` opens the quoted section beside it), the clause's hanging number
read onto the end of its note (`Amendment of 5.`), and a bare wrapped `26.` or a decimal
`26.7936”` that are not provision numbers. **Measured by re-reading every failing PDF**: 65 of the
546 pass on the fresh reading, and 2 of a 300-document sample of passing readings stop passing —
both quoted sections of an Act whose marks the reading lost, which the splice had been hiding.
Realising this in the corpus needs `make markdown` (every PDF is re-read, about twenty minutes)
followed by `make build`; the pass rates above were measured before that re-read.

What still fails after the fresh reading is no longer a reading defect at all: an Act consolidated
whole inside a Schedule, treaty `ARTICLE N` divisions, and sections quoted from a principal Act
with their marks lost — the modelling decisions named above.

### Fixing it for good: geometry beside the markdown, two node types, and an audit step

Every parser fix above recovered information the reader had and the markdown boundary discarded.
ADR-042 and ADR-043 (same day) change the shape rather than adding rules:

- **The reading's geometry is kept beside the markdown** as `document.blocks.json`, one record per
  markdown block — page, indent from the page's text column, role, lead emphasis — written by the
  same import under the same provenance record, and re-hashed by `verify`. The markdown itself is
  unchanged, so ADR-021's import path is untouched and a reading from elsewhere still enters
  without geometry.
- **The parser reads depth from it.** A provision number set deeper than the shallowest numbered
  line on its page — where the bill's own clauses hang — is a section quoted from the Act being
  amended, and what follows at that depth is the quoted text. That is the largest remaining
  rejection cause after the audit, and quotation marks the reading lost no longer decide it. The
  text column is now the *leftmost* column carrying a real share of a page's text rather than the
  most populous one, because a page of quoted text made the quotation's column the reference.
- **`list` and `article` join the vocabulary.** A lettered list restarting under one parent — each
  defined term's own `(a)`, `(b)` — becomes the next of several numbered `list` containers
  (`cl_2__list_2__para_c`) instead of the parent's prose; `ARTICLE N` / `PERKARA N` inside a
  Schedule is an `article`; containers nest by rank inside a Schedule as in the body, and the gate
  scopes its document-wide runs per Schedule. The curly single quote that wraps an inserted
  *definition* (`‘ “harvesting” means…’`) is now counted as a quotation mark, a closing `’` only
  before punctuation or the end of the line, so `shareholders’ fund` is not one.
- **`make audit`** (`billwatcher audit-structure`) parses and gates every stored reading with the
  checkout's code against the recorded verdicts and writes `documentation/structure-audit.md`,
  tracked. The loop that found every fix in this file is now a step.

**Measured, over every PDF re-read with the new reader** (2,479 documents):

| | passing Gate P1 |
| --- | --- |
| Stored readings, parser as committed in `cd72c46` | 1,933 |
| Fresh reading, text only | 1,952 |
| Fresh reading with geometry | **1,972 (79.5%)** |

Geometry passes 21 readings the text alone cannot and loses one, a bill printing two clauses
`6A`. Against the stored verdicts the fresh reading gains 97 and loses 58, and the losses are the
honest cost of two changes: 22 carry a finding inside a `list` container, where the old reading
flattened an interleaved quoted sub-list into prose and the container now shows the interleaving,
and 13 are sections quoted without indentation *or* surviving marks, which the spliced marginal
note used to hide from the parser. Over the stored readings alone, with no geometry, the parser
would pass 1,936 (`documentation/structure-audit.md`). The corpus takes the new reading on the
next `make markdown`, which writes the sidecars (`LOCAL_READING_VERSION` 1.7.0), then `make akn`
and `make audit`.

The published dataset is now a **corpus of readings** (2,352 markdown expressions) with a **graph
over three quarters of it**.

## What the reorganisation changed

- The Postgres/FastAPI stack moved to `legacy/`, frozen. See `legacy/README.md`.
- Two model-backed steps were dropped: the MinerU cross-check, and LLM-assisted structure
  extraction. Both are recoverable from commit `b0bfb77`; the second one's prompt and parsing
  survive in `graph/handoff.py`.
- The published tree moved from `dist/` to `docs/`, which GitHub Pages serves from this repository,
  and is now shared between the dataset writer and a React frontend that reads the same files a
  `curl` user would.
- `SITE_PREFIX` became the single authority for both `CNAME` and the base of every published FRBR
  IRI. **This fixed a live defect**: the previously published graph carried
  `http://127.0.0.1:8000/...` as the base of its identifiers, which dereferenced to nothing.
- `make build` over an unchanged corpus went from ~11 minutes to 15 seconds: the markdown step now
  consults provenance before reading a PDF rather than after.
- Configuration dropped from ~50 settings to 16, and the runtime dependency set from 19 packages
  to 6. `src/` went from 180 files to 36.

## Open, and not decided here

- **A licence for the project's own output.** `SITE_LICENCE` is deliberately empty; the site says
  so plainly rather than implying terms nobody granted. A published dataset needs one.
- **`robots.txt` is fetched and stored as evidence, but not enforced.** Enforcement lived in the
  legacy crawler. The parser survives at `download/robots.py` and the live smoke test still
  exercises it, but no step in the pipeline consults it.
- **Repository growth.** `docs/` is committed, so every rebuild that changes bytes adds a revision
  to history. A version bump that re-derives the whole corpus rewrites the whole tree. Whether to
  accept that, squash it, or publish from an orphan branch is recorded in
  `history/TODO.md §0` and is still open.
- **`public-cache/` is left in the working tree deliberately, and should not be deleted casually.**
  It is the old export root of a step that no longer exists, so nothing writes it any more. It held
  84 files that could not be regenerated — JSON-LD for 2024–2026 bills whose structures were read by
  the LLM-assisted path dropped in ADR-039, and which the deterministic parser could not get past
  Gate P1. **`AKN_VERSION` 1.3.0 recovered most of them: 81 of its 99 files are now published from
  the corpus, and 18 remain absent** (2026-08-30).

  Those 18 are what a good extraction produced and this parser still cannot, which makes them the
  sharpest comparison target the project has for handoff answers — a small, named set rather than a
  directory-sized one. It is untracked and will
  show up in `git status`; keep it out of any `git add .` until it has been looked at.

- **`make verify` currently exits non-zero on 91 issues**, all one condition: 91 bills each have
  two stored documents that would mint the same Expression IRI. Publication selection is
  deterministic so the published tree is stable, but the underlying data has not been reviewed.
  This predates the reorganisation; it stood at 42 before `AKN_VERSION` 1.3.0 and grew only because
  more documents now pass the gate and so claim an IRI at all. It is ADR-024's recorded
  consequence — the scheme carries no version component — and detection is the designed behaviour,
  not a defect in the reading.

- **`skipped_duplicate_expression: 127` and `conflicting_expressions: 4`** (2026-08-30) — two bills
  competing for one Expression IRI. Selection is deterministic, so the published tree is stable, but the
  underlying data condition has not been reviewed.
