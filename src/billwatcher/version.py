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
LAYOUT_EXTRACTOR_VERSION = "2.4.0"
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
# 1.6.0: carrier for `vocabulary.container_heading` refusing a line that merely begins with a Part
# reference (`Bahagian III hingga VI Akta ini...`, a wrapped long title) — `_heading_level` reads
# that classifier, so such a line is now a `###` provision heading rather than a `##` division. A
# few lines in a few readings; bumped because the same bytes in must give the same bytes out.
LOCAL_READING_VERSION = "1.6.0"
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
AKN_VERSION = "1.4.0"
# Gate P1, the AKN fidelity gate: the deterministic check that a provision tree accounts for the
# markdown it was read from. Its own version because a threshold change re-judges every document
# without re-rendering any of them.
# 1.2.0: the gate models two more legitimate irregularities in a lettered run — an inserted `(aa)`
# between `(a)` and `(b)`, the lettered form of `5A`, and the doubled-letter list `(cc)` -> `(dd)`
# older drafting prints beneath `(i)`, `(ii)`, which read as numerals is 200 -> 500 — and its view
# of the body moves with the shared classifiers (`back_matter_heading` run into its first sentence,
# `container_heading` refusing a wrapped long title, the added body openings). A Schedule's Parts
# are numbered as the schedule's own run, as a Part's Chapters already were.
STRUCTURE_GATE_VERSION = "1.2.0"
# The Akoma Ntoso -> ELI JSON-LD / RDF N-Quads graph construction (ADR-023, ADR-028).
SEMANTIC_VERSION = "1.0.0"
# The corpus -> published site tree projection (ADR-029, ADR-033): definition shapes, catalogue,
# redaction boundary and checksum format.
STATIC_EXPORT_VERSION = "1.0.0"
