"""Central version identifiers for every derived artifact.

Each stage's output records the version of the code that produced it, so a bump re-derives exactly
the artifacts that depend on it and leaves the rest alone. They are separate constants for that
reason: a serialisation fix should not invalidate every structural reading, and tightening a gate
threshold should not imply the XML changed.
"""

__version__ = "0.2.0"

# The listing/archive HTML and XML parsers, and the normalisation applied to what they read.
PARSER_VERSION = "1.0.0"
NORMALIZER_VERSION = "1.0.0"
# The geometric reading of a legislative PDF into classified, position-bearing lines (ADR-016).
# 2.0.0: the body size is the largest size carrying a real share of the text rather than the
# modal one, headings are read by weight as well as by size, a provision is recognised when it
# is indented rather than hung, and the header band reaches the height Parliament actually
# sets a running head at. Every stored reading is re-derived by this.
# 2.1.0: a line printed on the same baseline as a page number is a running head, recognised from
# its own page rather than from repetition across pages (a two-page bill has none to observe, and
# that was the largest single source of leaked furniture: 2,851 stray blocks across the corpus);
# the bare unit word an Arrangement prints over each group of entries is table furniture, not
# legal text (1,064); a margin-column line of pure punctuation is half a bracket pair, not a
# marginal note (2,365); and every line now records whether a block of space precedes it.
# 2.2.0: a line pdfminer read as a scatter of single letters — tracked (letterspaced) body text,
# the dominant cause of suspect readings — is rebuilt from glyph geometry: the median positive
# inter-glyph gap is the tracking, and a word break is any gap comfortably above it. Only lines
# already broken by pdfminer's word inference are rebuilt, so an ordinarily set line cannot be
# re-segmented into something worse.
# 2.3.0: a flourish letterspaced with real space glyphs ("b e r n a m a", "i n t i t u l e d")
# collapses to its word too — space glyphs are dropped from a tracked line and only the geometry
# decides where the words are. The word is the text; the spacing is presentation.
# 2.4.0: a tracked *run* inside an ordinary line ("This B i l l seeks…", "s u a tu") triggers the
# rebuild too — the trigger is three consecutive single-letter tokens, which no real sentence
# produces — and the word-break threshold gains an absolute arm of a quarter em, which is what
# separates letters from words on a line that is only partly tracked.
# 2.5.0: a marginal note in the *left* margin — the outer margin of a verso page in the 1990s
# printings, in small type — is a note, where it used to be sorted into the body by baseline and
# spliced into the provision it annotates (`Pindaan 4. Seksyen HB Akta ibu...`); the text column's
# margin is measured per page, because a bound book's verso and recto columns sit at different
# offsets and one document-wide margin was wrong on half the pages. And a line set in
# a small-capitals face (`Times-Roman-SC700`) is read as the capitals it prints, its words rebuilt
# from glyph geometry: `FIrst s chedule` was `FIRST SCHEDULE`, `BAhAgiAN` was `BAHAGIAN`. And text
# drawn from outside the page box — a mis-registered second layer that duplicated every line of
# its pages — is not on the page.
# 2.6.0: a page number never wears brackets, is among the first or last lines printed on its page,
# and has no bracketed text beside it on its baseline. `(c)` or `(3)` at the very top of a page —
# the paragraph or subsection that happens to open it — and `7.` at the very bottom — a clause
# number hanging on the last baseline, its `(1)` beside it — were read as page numbers, and the
# line beside either as the running head, so the first or last line of the page was lost
# (measured: 16 readings rejected by Gate P1 for exactly the paragraph that opened a page).
LAYOUT_EXTRACTOR_VERSION = "2.6.0"
# The local, layout-driven markdown reading (ADR-035). Versioned apart from
# LAYOUT_EXTRACTOR_VERSION because this is the markdown *assembly* on top of that reading — a
# change to how roles become markdown re-reads the corpus without the geometry itself having moved.
# 1.1.0: headings carry a level — `##` for a Part, Chapter or Schedule, `###` for one
# provision's own heading — and the heading ratio counts both.
# 1.2.0: a paragraph break marked by vertical space alone ends a block. The reader used to end
# one only at a role change or a page boundary, so the long title, the citation bracket and the
# enacting formula ran together; a marginal note had been hiding this by forcing a flush between
# them, which it no longer does now that half a bracket pair is not read as a note.
# 1.3.0: re-derives every reading over LAYOUT_EXTRACTOR_VERSION 2.2.0, which rejoins tracked
# (letterspaced) body text from glyph geometry — the assembly itself is unchanged, but the
# provenance producer version is this constant, so it carries the bump that restages the corpus.
# 1.4.0: the same carrier bump for LAYOUT_EXTRACTOR_VERSION 2.3.0, which reads a letterspaced
# flourish as the word it spells.
# 1.5.0: carrier for LAYOUT_EXTRACTOR_VERSION 2.4.0 (tracked runs inside ordinary lines), and
# `measure` stops counting the real one-letter words "a"/"A"/"I", reports its sample sizes, and
# `suspect` refuses to read a ratio taken over almost nothing.
# 1.6.0: carrier for LAYOUT_EXTRACTOR_VERSION 2.5.0 (left-margin notes, small-capitals faces), and
# for `vocabulary.container_heading` refusing a line that merely begins with a Part reference
# (`Bahagian III hingga VI Akta ini...`, a wrapped long title) — `_heading_level` reads that
# classifier, so such a line is now a `###` provision heading rather than a `##` division.
# 1.7.0: carrier for LAYOUT_EXTRACTOR_VERSION 2.5.0 (left-margin notes, small-capitals faces,
# off-page text, the text column measured as the leftmost substantial one), and the assembly now
# writes the reading's geometry beside the markdown, one record per block (`document.blocks.json`,
# ADR-042), under the same provenance record. 1.6.0 had already been built and committed before
# either change, so a corpus at 1.6.0 was skipped as current and never got its sidecars — which
# is why a local reading without one is also treated as stale by the step itself.
# 1.8.0: carrier for LAYOUT_EXTRACTOR_VERSION 2.6.0 (a bracketed token at the top of a page, or a
# number with a provision's text beside it at the bottom, is not a page number).
LOCAL_READING_VERSION = "1.8.0"
# The cross-check comparison (ADR-035 decisions 5 and 6): the tokenisation two readings are
# compared over and the agreement measure taken across it. Its own version because the threshold
# and the measure re-judge every pair without either reading having moved.
CROSSCHECK_VERSION = "1.0.0"
# The markdown -> Akoma Ntoso conversion: eId assignment, FRBR identification, AKN serialisation.
# 1.2.0: the structure parser stops at the back-matter heading (HURAIAN / EXPLANATORY STATEMENT)
# once the body has begun, instead of reading the statement's numbered paragraphs as clauses —
# which duplicated the bill's own low numbers and had the gate reject the whole document. Surfaced
# by LAYOUT_EXTRACTOR_VERSION 2.2.0: a letterspaced HURAIAN used to be unparseable glyph scatter,
# and rejoining it put parseable clause-like lines where the parser had never seen any.
# 1.3.0: the parser stops reading three things as clauses that never were, which together were
# the reason Gate P1 rejected 72% of the corpus. The Arrangement of Clauses — a contents page
# printing the whole bill's clause list before the bill — is skipped to the bill's own opening,
# instead of being read as a first copy of every clause. Text an amendment bill quotes from the
# Act it amends is read as the introducing clause's prose rather than as structure, since it
# carries the *Act's* numbering. And a printed number that cannot be this bill's next clause — a
# cited year, or a section number leaping far ahead of the sequence — is read as the prose it sits
# in. Measured over the 2,479 stored readings: 690 passing before, 1,292 after, one document lost.
# 1.4.0: the parser stops misreading eight more printed shapes, each measured on the corpus before
# it was touched. A sentence tail wrapped onto its own line (`...dinyatakan dalam` / `Jadual.`) was
# a first schedule that swallowed every clause after it; a cross-reference wrapped onto the next
# line (`...under subsection` / `(1), subsection 13(3)...`) was a second `(1)`; a Part or Schedule
# heading typeset with its number on the next line (`BAHAGIAN` / `II`) lost every Part after the
# first; `(A)`, `(B)` beneath `(ii)`, the doubled `(aa)`, `(bb)` of older drafting, and an inserted
# `(aa)` between `(a)` and `(b)` were all paragraph-run breaks; `(l)` read as `(1)` or `(I)` after
# `(k)` was a subsection; a marginal note spliced ahead of the clause number (`Pindaan 4. Seksyen
# HB...`) hid the clause; a quotation introduced mid-line (`...yang berikut: "Akses 53A. (1)...`)
# was not one; and the back-matter heading run into its first sentence (`EXPLANATORY STATEMENT This
# Bill seeks...`) was not seen, so the statement's paragraphs became clauses. One modelling change:
# a list that restarts under the parent that already holds it — each defined term's own `(a)`,
# `(b)` in an interpretation clause, or inserted sections' `(1)`, `(2)` with their quotation marks
# lost — is read as the parent's prose, since one `para_a` per parent cannot name the lists apart
# and the gate could otherwise only reject them (the largest single remaining cause, 514 readings).
# Measured over the 2,479 stored readings: 1,292 passing before, 1,933 after; three lost, one of
# which had passed on a tree built from its own explanatory statement.
# 1.5.0: the parser reads depth from the reading's geometry (ADR-042) — a provision number set
# deeper than the bill's own clause column is a section quoted from the Act being amended, and
# what follows at that depth is the quoted text — so a quotation whose marks the reading lost no
# longer becomes a second clause 7. Two node types join the vocabulary (ADR-043): a lettered list
# that restarts under one parent becomes the next of several numbered `list` containers instead of
# the parent's prose, and `ARTICLE N` / `PERKARA N` inside a Schedule is an `article`. Containers
# nest by rank (Part, Chapter, Article), inside a Schedule as well as in the body.
# 1.6.0: the parser stops misreading another set of printed shapes, each measured over the corpus
# before it was touched (documentation/status.md, "Second audit"). Quotations: a straight-single-
# quoted insertion (`' "term" means...;'`), a curly-single opening (`‘ “value”—`), a mark carried
# by a marginal note closing as well as opening, a quoted word wrapped across two lines, and the
# bill's own next Part heading ending a quotation that never closed. Quoted sections: a numbered
# line after `...the following section:` — with or without its marginal note spliced ahead of the
# number — is the section quoted, and so is a Part or Schedule heading after that colon; a number
# that runs backwards with an insertion letter (`7B` after clause 11) cannot be this bill's. Wraps:
# a provision number or Part heading opening a line that continues the unfinished sentence before
# it, the second half of a reference pair (`paragraphs (a) and` / `(b) ...`), `(b); or`, and a
# glued `(2)` mid-line split onto its own line. Furniture: the running head of the open Part or
# Schedule printed again, `Schedule.` as a clause's marginal note, and a heading word with a stray
# space inside it. Misprints, each accepted only at the one position it must be: `(h)` for `(b)`
# straight after `(a)`, `(I)` for the next lower-case letter, `( 1)`, `(3 The`, `(1.0)`, `Cd)`,
# `{f)`, `4 1.` and `(3.)`. Two modelling changes, ADR-044: a Schedule's numbered items that
# restart under it are one of several `list` containers, and a lettered list introduced by an
# item's own dash nests beneath that item.
AKN_VERSION = "1.6.0"
# Gate P1, the AKN fidelity gate: the deterministic check that a provision tree accounts for the
# markdown it was read from. Its own version because a threshold change re-judges every document
# without re-rendering any of them.
# 1.2.0: the gate models two more legitimate irregularities in a lettered run — an inserted `(aa)`
# between `(a)` and `(b)`, the lettered form of `5A`, and the doubled-letter list `(cc)` -> `(dd)`
# older drafting prints beneath `(i)`, `(ii)`, which read as numerals is 200 -> 500 — and its view
# of the body moves with the shared classifiers (`back_matter_heading` run into its first sentence,
# `container_heading` refusing a wrapped long title, the added body openings). A Schedule's Parts
# are numbered as the schedule's own run, as a Part's Chapters already were.
# 1.3.0: document-wide runs are scoped to the Schedule they sit in — a Schedule's Parts number from
# I and a treaty's Articles from 1 whatever the body did, and two Schedules each begin again — and
# `list` restarts per parent like the lists it holds.
# 1.4.0: a paragraph run printed in roman numerals (`(i)`, `(ii)`... directly beneath a clause) is
# judged as the numerals it prints rather than walked as letters, and the coverage view begins at
# the first structural marker after the enacting formula in every printed form of it — including
# one split over two lines, and mid-sentence (`PURSUANT to Article 76..., ENACTED by`) — and
# never at a year wrapped onto its own line (`2009. [ ]`).
STRUCTURE_GATE_VERSION = "1.4.0"
# The Akoma Ntoso -> ELI JSON-LD / RDF N-Quads graph construction (ADR-023, ADR-028).
SEMANTIC_VERSION = "1.0.0"
# The corpus -> published site tree projection (ADR-029, ADR-033): definition shapes, catalogue,
# redaction boundary and checksum format.
# 1.1.0: the published structural vocabulary gains `article` and `list` (ADR-043).
STATIC_EXPORT_VERSION = "1.1.0"
