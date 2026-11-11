"""Controlled vocabulary for Malaysian legislative structure (HANDOFF 26.2).

Pure data and pure functions: nothing here reads a file, makes a request, or knows what a store
is. That is what lets the same classification serve the regex extractor, the fidelity gate and the
published `definitions/structural-vocabulary.json` without any of them importing each other.

Bills use *Fasal*/Clause and Acts use *Seksyen*/Section. A clause becomes a section on
enactment, so both are the same kind of node carrying a different name: `NODE_TYPES` holds one
entry per structural kind and `enacted_type` performs the rename as a first-class transition
rather than a special case (HANDOFF 26.2, "Bills use Fasal/Clause; Acts use Seksyen/Section").
"""

import re
from types import MappingProxyType

# Every structural node kind, with the Akoma Ntoso element it serialises to in Stage 2 and the
# eId prefix that names it. The AKN column is recorded here so Stage 2 has one place to read it
# from; this package does not itself emit AKN.
NODE_TYPES = frozenset(
    {
        "preamble",
        "part",
        "chapter",
        "article",
        "section",
        "clause",
        "subsection",
        "paragraph",
        "subparagraph",
        "list",
        "schedule",
    }
)

EID_PREFIXES = MappingProxyType(
    {
        "part": "part",
        "chapter": "chp",
        "article": "art",
        "section": "sec",
        "clause": "cl",
        "subsection": "subsec",
        "paragraph": "para",
        "subparagraph": "subpara",
        "list": "list",
        "schedule": "sched",
    }
)

AKN_ELEMENTS = MappingProxyType(
    {
        "preamble": "preamble",
        "part": "part",
        "chapter": "chapter",
        # A treaty set out in a Schedule is divided into Articles (ADR-043).
        "article": "article",
        "section": "section",
        "clause": "clause",
        "subsection": "subsection",
        "paragraph": "paragraph",
        "subparagraph": "subparagraph",
        # A lettered list that restarts under one parent — each defined term's own `(a)`, `(b)` in
        # an interpretation clause — is one of several lists, numbered by position (ADR-043).
        # Rendered as an hcontainer so its items stay hierarchy elements the gate can check.
        "list": "hcontainer",
        # A schedule is an hcontainer inside <attachments>, not an element of its own.
        "schedule": "hcontainer",
    }
)

# The node types whose Akoma Ntoso element is an `hcontainer`, told apart by its `name` attribute.
HCONTAINER_TYPES = frozenset(
    kind for kind, element in AKN_ELEMENTS.items() if element == "hcontainer"
)

assert set(EID_PREFIXES) <= NODE_TYPES
assert set(AKN_ELEMENTS) == NODE_TYPES

# The published Malay and English words for each kind. Malay is listed first because Malay is
# the authoritative language for federal legislation.
NODE_LABELS = MappingProxyType(
    {
        "preamble": ("Mukadimah", "Preamble"),
        "part": ("Bahagian", "Part"),
        "chapter": ("Bab", "Chapter"),
        "article": ("Perkara", "Article"),
        "section": ("Seksyen", "Section"),
        "clause": ("Fasal", "Clause"),
        "subsection": ("Subseksyen", "Subsection"),
        "paragraph": ("Perenggan", "Paragraph"),
        "subparagraph": ("Subperenggan", "Subparagraph"),
        "list": ("Senarai", "List"),
        "schedule": ("Jadual", "Schedule"),
    }
)

assert set(NODE_LABELS) == NODE_TYPES

# The bare unit words a document prints as a *label* rather than as text: the column header over
# the clause list in an Arrangement of Clauses, reprinted above each Part's group of entries. A
# line that is one of these words and nothing else is never legal text — no provision, heading or
# note in the corpus consists of the single word "Fasal" — so the reader can drop it as the table
# furniture it is (measured: 228 such lines leak into the body across the corpus).
_UNIT_LABELS = frozenset(
    label.casefold()
    # Only the provision units. A bare "Jadual" or "Bahagian" is a *heading* — `schedule_heading`
    # reads an unnumbered `JADUAL` as schedule 1 — so listing them here would delete real
    # structure rather than furniture.
    for node_type in ("section", "clause")
    for label in NODE_LABELS[node_type]
)


def is_bare_unit_label(text: str) -> bool:
    """Whether a line is one bare unit word — an Arrangement column header, not content."""
    return text.strip().strip(".:").casefold() in _UNIT_LABELS


# The rename an enactment performs. Only the clause/section pair moves; everything else keeps
# its name, and applying this to an already-enacted tree is a no-op.
_ENACTMENT_RENAME = MappingProxyType({"clause": "section"})


def enacted_type(node_type: str) -> str:
    """The node kind this becomes when the bill it belongs to is enacted.

    `wId` is unchanged by this: a clause and the section it becomes are the same provision, which
    is the whole reason the rename is modelled rather than reparsed (HANDOFF 26.2).
    """
    if node_type not in NODE_TYPES:
        raise ValueError(f"unknown node type: {node_type!r}")
    return _ENACTMENT_RENAME.get(node_type, node_type)


# The heading that opens the table of contents every Malaysian Act and bill carries. Both
# languages, and both the Act (Seksyen/Sections) and bill (Fasal/Clauses) wordings. Matching is
# case-insensitive and whitespace-tolerant because the heading is typeset, not tagged.
_ARRANGEMENT_HEADINGS = (
    ("ms", "section", r"susunan\s+seksyen"),
    ("ms", "clause", r"susunan\s+fasal"),
    ("en", "section", r"arrangement\s+of\s+sections?"),
    ("en", "clause", r"arrangement\s+of\s+clauses?"),
)

_ARRANGEMENT_RE = tuple(
    (language, unit, re.compile(rf"^\W*{pattern}\W*$", re.IGNORECASE))
    for language, unit, pattern in _ARRANGEMENT_HEADINGS
)


def arrangement_heading(text: str) -> tuple[str, str] | None:
    """Classify a line as the Arrangement of Sections heading.

    Returns `(language, unit)` where unit is `section` for an Act and `clause` for a bill, or
    `None` if the line is not that heading. The unit is what tells Gate L1 which node kind the
    entries below it name, so a bill is never asked to match a section tree.
    """
    value = " ".join(text.split())
    for language, unit, pattern in _ARRANGEMENT_RE:
        if pattern.match(value):
            return language, unit
    return None


# `Bahagian I`, `PART IV`, `Bab 2`, `Chapter 2`, `ARTICLE 5`, `Perkara 5`. The number may be roman
# or arabic; both are published. A heading may follow on the same line or the next one.
def _spaced(word: str) -> str:
    """A pattern for `word` with the reading's stray spaces inside it: `P A RT`, `S CHEDULE`.

    The layout reader rejoins letterspaced lines from glyph geometry, but a heading set in a
    display face still comes through with a space or two inside the word now and then, and a
    heading that is not recognised turns a Schedule's items into clauses.
    """
    return r"\s?".join(re.escape(letter) for letter in word)


_CONTAINER_RE = re.compile(
    r"^\s*(?P<word>"
    + "|".join(_spaced(w) for w in ("bahagian", "part", "bab", "chapter", "article", "perkara"))
    + r")\s+"
    r"(?P<num>[IVXLCDM]+|\d+[A-Z]?)\b\W*(?P<heading>.*)$",
    re.IGNORECASE,
)

_CONTAINER_TYPE = MappingProxyType(
    {
        "bahagian": "part",
        "part": "part",
        "bab": "chapter",
        "chapter": "chapter",
        "article": "article",
        "perkara": "article",
    }
)

# How containers nest: a Chapter sits inside a Part, an Article inside either. A new container
# closes every open one of its own rank or deeper.
CONTAINER_RANK = MappingProxyType({"part": 1, "chapter": 2, "article": 3})


# Words a heading may carry in lower case without being prose: connectives, in both languages.
_HEADING_FUNCTION_WORDS = frozenset(
    {
        "dan",
        "atau",
        "yang",
        "di",
        "ke",
        "bagi",
        "untuk",
        "dengan",
        "of",
        "and",
        "or",
        "the",
        "to",
        "for",
        "in",
        "on",
        "by",
        "under",
        "dalam",
        "tentang",
        "relating",
        "berhubungan",
    }
)


def _reads_as_prose(heading: str) -> bool:
    """Whether a heading's text is a sentence fragment rather than a title.

    `Bahagian III hingga VI Akta ini dan kesalahan-kesalahan yang` is the long title wrapped onto a
    line that begins with a Part reference; `Bahagian 1 Jadual 4, orang berdaftar itu hendaklah
    mematuhi apa-` is a clause. A title is set in capitals or title case — `BAHAGIAN II
    PENDAFTARAN`, `Part II Registration` — so a heading that opens with a lower-case word, or runs
    to several words most of which are lower-case, is the sentence it looks like.
    """
    words = heading.split()
    if not words:
        return False
    if words[0][0].islower() or words[0][0] in ",;":
        # `Part III, IV, V or VI, by order published...`: a list of Parts referred to, wrapped
        # onto its own line. A title does not begin with a comma.
        return True
    lower = [
        word
        for word in words
        if word[0].islower() and word.casefold() not in _HEADING_FUNCTION_WORDS
    ]
    return len(words) >= 4 and len(lower) > len(words) / 2


def container_heading(text: str) -> tuple[str, str, str] | None:
    """Classify a line as a Part or Chapter heading, returning `(type, num, heading)`.

    A line that merely *begins* with a Part reference — a wrapped long title, a clause — is not one:
    see `_reads_as_prose`.
    """
    match = _CONTAINER_RE.match(" ".join(text.split()))
    if not match:
        return None
    heading = match.group("heading").strip(" .")
    if _reads_as_prose(heading):
        return None
    node_type = _CONTAINER_TYPE[match.group("word").replace(" ", "").casefold()]
    return node_type, match.group("num").upper(), heading


# `Jadual Pertama`, `JADUAL KEDUA`, `First Schedule`, `SCHEDULE`. Schedules restart their own
# numbering, so recognising one is what stops a schedule's paragraph 1 from being read as a
# second section 1.
_SCHEDULE_RE = re.compile(
    r"^\s*(?:(?P<ordinal_en>first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+)?"
    r"(?P<word>" + _spaced("jadual") + "|" + _spaced("schedule") + r")"
    r"(?:\s+(?P<ordinal_ms>pertama|kedua|ketiga|keempat|kelima|keenam|ketujuh|kelapan|"
    r"kesembilan|kesepuluh)|\s+(?P<num>[IVXLCDM]+|\d+))?"
    # `FIRST SCHEDULE [Section 14]`: the enabling provision, bracketed on the heading line.
    r"(?:\s*\[[^\]]*\])?\W*$",
    re.IGNORECASE,
)

# Public because coverage measurement needs to know which words *name* a schedule rather than
# being part of its text; see `pipeline.fidelity`.
SCHEDULE_ORDINALS = MappingProxyType(
    {
        "pertama": "1",
        "first": "1",
        "kedua": "2",
        "second": "2",
        "ketiga": "3",
        "third": "3",
        "keempat": "4",
        "fourth": "4",
        "kelima": "5",
        "fifth": "5",
        "keenam": "6",
        "sixth": "6",
        "ketujuh": "7",
        "seventh": "7",
        "kelapan": "8",
        "eighth": "8",
        "kesembilan": "9",
        "ninth": "9",
        "kesepuluh": "10",
        "tenth": "10",
    }
)


def schedule_heading(text: str) -> str | None:
    """Classify a line as a Schedule heading, returning its number as a string.

    An unnumbered `JADUAL` is schedule `1`: a document with one schedule does not number it.
    """
    match = _SCHEDULE_RE.match(" ".join(text.split()))
    if not match:
        return None
    ordinal = match.group("ordinal_ms") or match.group("ordinal_en")
    if ordinal:
        return SCHEDULE_ORDINALS[ordinal.casefold()]
    return (match.group("num") or "1").upper()


# A section or clause number opening a provision: `5.`, `5A.`, `12 .`. The trailing stop is
# required — a bare `5` at the left margin is far more likely to be a page number or a
# cross-reference than a provision.
# A bill's own back matter: an "Explanatory Statement" narrating every clause in prose, and a
# "Financial Implications" note, both standard on every printed Malaysian bill and neither part of
# the enacted text. Matched as a heading line naming *only* the section, so a clause that merely
# mentions the word inline is not mistaken for it. Shared by the structure parser (which must not
# read the statement's numbered paragraphs as clauses — they restart at the bill's own numbers and
# collide with the real ones) and the fidelity gate (which excludes the same text from coverage).
#
# The heading is matched alone *or* run into the statement's own first words. A printed heading
# sits on its own line, but the local reading joins it onto the paragraph beneath when the two
# share a block — `EXPLANATORY STATEMENT This Bill seeks to amend...`, `HURAIAN Rang Undang-Undang
# ini bertujuan...` — and a heading the parser then failed to see left every numbered paragraph of
# the statement to be read as a clause (measured: 32 readings rejected for exactly this). What may
# follow is deliberately narrow: the statement opens, in every bill measured, with "This Bill" /
# "The ... Bill" or "Rang Undang-Undang". Anything else after the word is not the heading — a Penal
# Code amendment prints `Huraian 1—Perkataan "kelakuan"...` as an *Explanation* inside a quoted
# section, and a rule that took any trailing text would cut the body open there. `HURA1AN` is the
# reading's own `I`, as one bill prints it.
_BACK_MATTER_HEADING_RE = re.compile(
    r"^(?:(?:hura[i1l]an|implikasi\s+kewangan)(?:\s+rang\s+undang-?undang\b.*)?"
    r"|(?:explanatory\s+statement|financial\s+implications)(?:\s+(?:this|the)\b.*)?)$",
    re.IGNORECASE,
)


def back_matter_heading(text: str) -> bool:
    """Whether this line is the heading that opens a bill's back matter."""
    return _BACK_MATTER_HEADING_RE.match(" ".join(text.split())) is not None


# A line that stops mid-reference: `...suspended under subsection` / `...selepas sahaja perenggan`,
# with the number it points at wrapped onto the next line. That next line — `(1), subsection 13(3)
# shall...`, `(c), perenggan baru (d) berikut:` — then opens with exactly the token a real
# subsection or paragraph opens with, and reading it as one gives the provision a second `(1)` and
# a paragraph run that jumps backwards (measured: 285 rejected readings carried such a line). The
# words are the structural nouns that take a number in either language. A real opener is never
# preceded by one of them without punctuation: a sentence that ends on the bare word "subsection"
# ends with a full stop, and a list is introduced by a colon or a dash.
_REFERENCE_WORD_RE = re.compile(
    r"\b(?:sub-?sections?|subseksyen|sections?|seksyen|sub-?paragraphs?|subperenggan|"
    r"paragraphs?|perenggan|clauses?|fasal|items?|butiran|articles?|perkara|sub-?items?|"
    r"subbutiran|regulations?|peraturan|subperaturan|rules?|kaedah|subkaedah|schedules?|jadual|"
    r"parts?|bahagian|chapters?|bab|proviso|provisos)$",
    re.IGNORECASE,
)


def ends_in_reference(text: str) -> bool:
    """Whether this line breaks off inside a cross-reference, its number wrapped onto the next.

    True only for a line ending on a structural noun (`under subsection`, `perenggan`). A comma is
    deliberately not enough: a subsection whose full stop the reading printed as a comma is
    common, and treating the next `(3)` as its continuation lost real subsections (measured).
    Trailing quotation marks and brackets are ignored so `...in paragraph"` behaves as
    `...in paragraph`.
    """
    stripped = " ".join(text.split()).rstrip("\"“”')]")
    return _REFERENCE_WORD_RE.search(stripped) is not None


# The words that take an Act's number: `Akta 3.` in a margin is the citation of Act 3, not a note
# ending in the hanging number of clause 3. Kept apart from `_REFERENCE_WORD_RE`: a body line that
# ends on "Act" is a sentence that wrapped, and the `(2)` beneath it is the next subsection, not a
# reference's number (measured: three readings lost a subsection when the two were merged).
_CITATION_WORD_RE = re.compile(r"\b(?:acts?|akta|ordinances?|ordinan)$", re.IGNORECASE)


def ends_in_citation(text: str) -> bool:
    """Whether this line ends on the word an Act's number follows: `...Akta`, `...under the Act`."""
    return _CITATION_WORD_RE.search(" ".join(text.split())) is not None


# What a heading-shaped line may end with and still be a heading. A Part or Schedule heading is a
# label; the reading that produced `Jadual.` or `Bahagian IV.` was the tail of a sentence — `...
# yang dinyatakan dalam Jadual.` — that wrapped onto its own line and was read as a heading for
# being short. Measured: 199 such `Jadual.` / `Schedule.` lines across 145 readings, 124 of them
# rejected, because the false schedule swallowed every clause after it as a schedule paragraph.
_SENTENCE_TAIL_RE = re.compile(r"[.;:,—–](?:[\"“”'’)\]]*)$")


def is_sentence_tail(text: str) -> bool:
    """Whether a heading-shaped line ends like a sentence rather than like a label."""
    return _SENTENCE_TAIL_RE.search(text.strip()) is not None


# Where a bill's own text begins — and therefore where an Arrangement of Clauses above it ends.
#
# This is the mirror of the back matter, and it exists for the same reason. The Arrangement is a
# table of contents: it prints every clause number and heading the bill is about to print, so
# reading it as structure reads the whole bill twice, giving every clause a duplicate eId and a
# sequence that runs backwards. Unlike the back matter it has no heading of its own to stop at;
# what bounds it is the bill's formal opening, and a printed bill carries that in two forms — the
# title block (`A BILL`, `RANG UNDANG-UNDANG`) and the enacting formula that follows the long
# title. Both are matched, because neither is universal.
#
# The Malay title carries a negative lookahead, and it is not decoration. Every printed bill ends
# with a Financial Implications note opening "Rang Undang-Undang **ini** akan melibatkan Kerajaan
# dalam perbelanjaan..." — a sentence *about* the bill, a few lines from the end of the document,
# which the title pattern otherwise matches exactly as well as a real title block. Eight bills cut
# their body open past their own last clause and were read as empty trees before `ini` was
# excluded. A title block is a title; it is never followed by "this".
#
# Measured over the 2,479 stored readings: of the 619 that print an Arrangement, 613 print a title
# block after it, 536 print an enacting formula, and 614 print at least one of the two. The five
# that print neither are read whole, as before — see `tree.body_start`, which will not truncate a
# bill on a marker it cannot find.
#
# Re-measured over the 22 readings the first set of forms left unbounded: the title block also
# prints as the bare word `bernama` / `intituled` on its own line (the title itself having been
# read as the cover's), or as `ABILL` with its space lost — never a bare `BILL`, which is the
# running header on every page of an English bill and sits inside the Arrangement as readily as
# after it; and the enacting formula opens `MAKA,
# OLEH YANG DEMIKIAN, DIPERBUAT oleh Parlimen...` or `NOW, THEREFORE, IT IS ENACTED...`, with the
# words this pattern used to anchor on several words in. Each added form is a whole-line word or a
# formula no clause begins with.
_BODY_OPENING_RE = re.compile(
    r"^(a\s*bill\b"
    r"|(suatu\s+)?rang\s+undang-?undang\b(?!\s+ini\b)"
    r"|bernama$"
    r"|intituled$"
    r"|be\s+i[tx]\s+enacted\b"
    r"|(now,?\s+therefore,?\s+)?it\s+is\s+enacted\b"
    r"|enacted\s+by\b"
    r"|diperbuat\s+oleh\b"
    r"|maka,?\s+(inilah|oleh\s+yang\s+demikian)\b)",
    re.IGNORECASE,
)


# The title-block forms alone: the ones a running head can also print. The enacting-formula forms
# need no confirmation — no running head reads `DIPERBUAT oleh Parlimen`.
_TITLE_BLOCK_RE = re.compile(
    r"^(a\s*bill\b|(suatu\s+)?rang\s+undang-?undang\b(?!\s+ini\b))", re.IGNORECASE
)

# What follows a real title block within a few lines: the word introducing the long title, the
# long title itself, or the enacting formula.
_TITLE_BLOCK_CONFIRMATION_RE = re.compile(
    r"^(bernama\b|intituled\b|suatu\s+akta\b|an\s+act\b|be\s+i[tx]\s+enacted\b|it\s+is\s+enacted\b"
    r"|enacted\s+by\b|diperbuat\s+oleh\b|maka,?\s+(inilah|oleh\s+yang\s+demikian)\b)",
    re.IGNORECASE,
)


def body_opening(text: str, *, title_block_only: bool = False) -> bool:
    """Whether this line opens the bill's own text, closing any Arrangement above it.

    With `title_block_only`, whether it does so as a title block (`A BILL`, `RANG UNDANG-UNDANG`)
    rather than as the enacting formula — the forms a running head can also print, which
    `tree.body_start` therefore confirms against the lines that follow.
    """
    pattern = _TITLE_BLOCK_RE if title_block_only else _BODY_OPENING_RE
    return pattern.match(" ".join(text.split())) is not None


def confirms_title_block(text: str) -> bool:
    """Whether this line is what a title block is followed by: `bernama`, the long title, ..."""
    return _TITLE_BLOCK_CONFIRMATION_RE.match(" ".join(text.split())) is not None


# An amendment bill prints the text it inserts into the principal Act inside quotation marks, and
# those marks are the only thing separating that text from the bill's own clauses. The numbers
# inside them belong to the Act being amended — `12A.`, `13.`, `95A.` — so a reader that takes them
# for clauses of the bill gives itself a second clause 13, a sequence that jumps to 95 and back,
# and the duplicate eIds Gate P1 rejects. Straight and curly double quotes both occur; the single
# quote is deliberately not here, because an apostrophe would open a span on every possessive.
QUOTE_CHARS = '"\u201c\u201d'
_QUOTE_CHARS = QUOTE_CHARS
# The curly single quotes, counted apart. An amendment inserting a *definition* nests its marks —
# `the following definition: ‘ "harvesting" means taking...’` — with the inserted text in single
# curly quotes and the defined term in double ones inside them, so counting doubles alone found the
# line balanced and read the definition's own `(a)`, `(b)` as the bill's paragraphs (measured: 70
# readings). The opening `‘` is never anything but a quotation mark; the closing `’` is also the
# apostrophe in `Minister’s` and `shareholders’ fund`, so it counts only where a quotation closes:
# before punctuation, another mark, or the end of the line.
_SINGLE_OPEN = "\u2018"
_SINGLE_CLOSE_RE = re.compile('\u2019(?=[.;,:)\\]"\u201d\u2019\u2018]|\\s*$)')
_QUOTE_OPEN_RE = re.compile(f"^[{_QUOTE_CHARS}{_SINGLE_OPEN}]")


# The quotation may also open mid-line, after the words that introduce it — `...perenggan yang
# berikut: "(d) melantik anggota...` — with the introducing clause and the first quoted line
# sharing one printed line. The last mark on such a line follows a colon or a dash and nothing
# closes it; a mark anywhere else mid-line is a defined term or a quoted word, which the parity
# test already leaves alone.
_QUOTE_INTRODUCED_RE = re.compile(f"[:—–-]\\s*[{_QUOTE_CHARS}{_SINGLE_OPEN}]")


def opens_quotation(text: str) -> bool:
    """Whether this line opens a quotation — the first line of amended text.

    Either the line begins with a mark, or a mark is introduced by a colon or dash somewhere on
    it (`...the following paragraph: "(d) ...`, `...the following definition: ‘ "harvesting"...`).
    The caller decides by parity whether the quotation runs on past this line, which is what keeps
    a definition quoted and closed on one line from opening anything.
    """
    return begins_with_mark(text) or _QUOTE_INTRODUCED_RE.search(text) is not None


def begins_with_mark(text: str) -> bool:
    """Whether the line's first character is a quotation mark — double, or the curly single `‘`.

    The curly single is the mark an amendment inserting a *definition* opens with (`‘ “value”—`),
    and a parser that tested the first character against the double marks alone let that line's
    odd count pass without opening anything, so the definition's own `(a)`, `(b)` were read as
    the bill's paragraphs (measured: the paragraph run then jumped backwards from `(xxvi)`).
    """
    return _QUOTE_OPEN_RE.match(text) is not None


# The older typesetting quotes an inserted definition in *straight* single quotes, with the
# defined term in doubles inside: `' "amusement device" means any contrivance...;'`. The straight
# single is also the apostrophe, so it cannot be counted with the other marks; what makes these two
# positions unambiguous is that no apostrophe opens a line ahead of a double mark, and none closes
# a line straight after punctuation. `*` is the reading's own rendering of the opening mark in one
# face (`* "Director of Marine" means...`), and `''` of the mark before a bracketed paragraph
# (`''(ha) melantik ahli-ahli...`); the raw line is tested because the markdown reader would
# otherwise strip the `*` as a bullet.
_STRAIGHT_OPEN_RE = re.compile(r"^\s*['*](?=\s*[\"“‘('])")
_STRAIGHT_CLOSE_RE = re.compile(
    r"(?<=[.;,:\"”’)\]])['’](?=[.;,:)\]]|\s|$)"
    # `...Konvensyen Montreal;";` — the closing straight mark read as a double one. A double mark
    # right after the semicolon or stop that ends a definition, and nothing but punctuation after
    # it, closes an insertion; a definition's own marks wrap its term at the front.
    r"|(?<=[.;])[\"”](?=[;.]?\s*$)"
)


def opens_straight_quotation(raw_line: str) -> bool:
    """Whether this line opens a straight-single-quoted insertion: `' "term" means ...`."""
    return _STRAIGHT_OPEN_RE.match(raw_line.strip().lstrip("#")) is not None


def closes_straight_quotation(text: str) -> bool:
    """Whether this line carries the mark that ends a straight-single-quoted insertion.

    `...;'`, `...;';`, or `...[Act 443]', which is` — anywhere on the line, because the reading
    sometimes sets the words after the mark ahead of it, and a close that had to end the line
    left the span open to the next clause (measured: one Chapter heading swallowed that way).
    The curly `’` closes it too: the reading renders the same printed mark either way.
    """
    return _STRAIGHT_CLOSE_RE.search(text) is not None


def quotation_marks(text: str) -> int:
    """How many quotation marks this line carries.

    Parity is what tells a quotation that *runs on* from one that closes where it opened, and it
    settles two cases a "does it end with a mark" test gets wrong in opposite directions. A defined
    term — `"revised law" means the revised edition...` — opens with a mark and carries two, so it
    is balanced and quotes nothing beyond itself; a real insertion — `"Powers of examination and
    search` — carries one, and stays open until the mark that shuts it. Counting also survives the
    mark landing mid-line, which is where an amendment usually puts it — `..."; and`, `...".`.
    """
    return (
        sum(text.count(mark) for mark in _QUOTE_CHARS)
        + text.count(_SINGLE_OPEN)
        + len(_SINGLE_CLOSE_RE.findall(text))
    )


# `(?!\d)`: a digit straight after the stop is a decimal — `26.7936” East`, a coordinate in a
# schedule of wharves — and not the twenty-sixth item.
_PROVISION_NUM_RE = re.compile(r"^\s*(?P<num>\d{1,4}[A-Z]{0,2})\s*\.(?!\d)\s*(?P<rest>.*)$")

# `(1)`, `(2A)` open a subsection; `(a)`, `(bb)` a paragraph; `(i)`, `(iv)` a subparagraph.
# The letter forms genuinely overlap — `i`, `v`, `x`, `l`, `c`, `d` and `m` are each both a
# paragraph letter and a roman numeral — so `parenthesised` only splits the token out. Which kind
# it is cannot be decided from the token alone; `resolve_letter` decides it from the sequence the
# token continues. Guessing here is how a paragraph list silently becomes a subparagraph list,
# which changes every eId beneath it.
# A space inside the brackets — `( 1)`, `( d)` — is the reading's, not the drafter's.
_SUBSECTION_RE = re.compile(r"^\s*\(\s?(?P<num>\d{1,3}[A-Z]{0,2})\s?\)\s*(?P<rest>.*)$")
# A letter token is one or two letters (`a`, `aa`, `ea`, `A`) or a roman numeral (`viii`, `xviii`);
# `(Kagu)` and `(Boas)` in a schedule of species are words in brackets, not the fourth paragraph.
# The reading sometimes spaces the letters of a numeral apart — `( i i i)` — so they are gathered.
_LETTER_RE = re.compile(
    r"^\s*\(\s?(?P<num>[A-Za-z]{1,2}|[ivxlc]{3,7}|[IVXLC]{3,7}|(?:[ivx] ?){2,6})\s?\)"
    r"\s*(?P<rest>.*)$"
)

_ROMAN_VALUES = MappingProxyType({"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000})
_ROMAN_NUMERALS = (
    (1000, "m"),
    (900, "cm"),
    (500, "d"),
    (400, "cd"),
    (100, "c"),
    (90, "xc"),
    (50, "l"),
    (40, "xl"),
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
)


def provision_number(text: str) -> tuple[str, str] | None:
    """Split `5A. Kewajipan untuk melaporkan` into `("5A", "Kewajipan untuk melaporkan")`.

    The trailing stop is required. A bare `5` at the left margin is far more likely to be a page
    number or a cross-reference than the opening of a provision.
    """
    match = _PROVISION_NUM_RE.match(text)
    if not match:
        return None
    return match.group("num").upper(), match.group("rest").strip()


def parenthesised(text: str) -> tuple[str, str, str] | None:
    """Split a parenthesised opening into `(kind, num, rest)`.

    `kind` is `subsection` for a numeric token, which is unambiguous, and `letter` for an
    alphabetic one, which is not. A caller that needs a node type must pass a `letter` token
    through `resolve_letter` together with the sequence context.
    """
    match = _SUBSECTION_RE.match(text)
    if match:
        return "subsection", match.group("num").upper(), match.group("rest").strip()
    match = _LETTER_RE.match(text)
    if match:
        return "letter", match.group("num").replace(" ", ""), match.group("rest").strip()
    return None


def is_roman(token: str) -> bool:
    return bool(token) and all(character.casefold() in _ROMAN_VALUES for character in token)


def roman_value(token: str) -> int:
    """The value of a roman numeral, or 0 if the token is not one."""
    if not is_roman(token):
        return 0
    total = 0
    highest = 0
    for character in reversed(token.casefold()):
        value = _ROMAN_VALUES[character]
        total = total - value if value < highest else total + value
        highest = max(highest, value)
    return total


def to_roman(value: int) -> str:
    parts: list[str] = []
    for amount, numeral in _ROMAN_NUMERALS:
        while value >= amount:
            parts.append(numeral)
            value -= amount
    return "".join(parts)


def alpha_successor(token: str) -> str:
    """`a` to `b`, `z` to `aa`, `az` to `ba`: the paragraph-letter sequence drafters use."""
    letters = list(token.casefold())
    position = len(letters) - 1
    while position >= 0:
        if letters[position] != "z":
            letters[position] = chr(ord(letters[position]) + 1)
            return "".join(letters)
        letters[position] = "a"
        position -= 1
    return "a" + "".join(letters)


def roman_successor(token: str) -> str:
    return to_roman(roman_value(token) + 1)


def is_doubled_letter(token: str) -> bool:
    """`aa`, `bb`, `CC`: one letter written twice or more, which drafters use two ways."""
    return len(token) >= 2 and token.isalpha() and len(set(token.casefold())) == 1


def is_doubled_step(previous: str, current: str) -> bool:
    """`aa` -> `bb`, `cc` -> `dd`: consecutive entries of a doubled-letter list.

    The form older drafting used for the list beneath `(i)`, `(ii)`, where a later style prints
    `(A)`, `(B)`. Both letters of `cc` are roman numerals too, so read as numerals the step is
    200 -> 500 and a gate would report a gap expecting `cci`; the letter reading is the one drafters
    meant.
    """
    return (
        is_doubled_letter(previous)
        and is_doubled_letter(current)
        and len(previous) == len(current)
        and previous.isupper() == current.isupper()
        and current[0].casefold() == alpha_successor(previous[0])
    )


def is_letter_insertion(previous: str, current: str) -> bool:
    """Whether `current` follows `previous` through an inserted paragraph letter.

    The lettered counterpart of `5` -> `5A` -> `6`: a paragraph inserted after `(e)` is `(ea)`,
    a second one `(eb)`, and the list resumes at `(f)` — `by inserting after paragraph (e) the
    following paragraph: "(ea) ..."` is how the bill itself puts it. Each of those steps is
    consecutive. `(aa)` after `(a)` is the same convention at the first letter.
    """
    left, right = previous.casefold(), current.casefold()
    if right == "ii":
        # `(ii)` after `(i)` is the roman list `(i)` opened, never an insertion: an `(i)` read as
        # the ninth paragraph is the known ambiguity, and this is where it resolves itself.
        return False
    if len(left) == 1 and len(right) == 2 and right[0] == left and right[1] == "a":
        return True  # `(e)` -> `(ea)`, the first paragraph inserted after `(e)`; `(a)` -> `(aa)`
    if (
        len(left) == 2
        and len(right) == 2
        and right[0] == left[0]
        and right[1] == alpha_successor(left[1])
    ):
        return True  # `(ea)` -> `(eb)`, a second insertion
    return (
        len(left) == 2 and len(right) == 1 and right == alpha_successor(left[0])
    )  # `(eb)` -> `(f)`


def continues_run(previous: str, token: str, previous_type: str) -> bool:
    """Whether `token` is the next entry of the open list `previous` belongs to.

    Case is part of the answer. Malaysian drafting nests four lettered depths — `(a)` paragraphs,
    `(i)` subparagraphs, and beneath those `(A)`, `(B)` — and `(A)` after `(a)` is a new, deeper
    list, not the same letter twice. A paragraph list advances only by letter, allowing for an
    inserted `(aa)`; a subparagraph list advances by roman numeral when it is written in lower-case
    numerals, by letter when it is written in capitals (`C` -> `D` is a letter step there, as
    `fidelity._compare` also reads it, even though both are numerals too), and by doubled letter
    (`aa` -> `bb` -> `cc`) in the older drafting that used that form beneath `(i)`, `(ii)`.
    """
    if not previous or previous.isupper() != token.isupper():
        return False
    if previous_type == "paragraph":
        return token.casefold() == alpha_successor(previous) or is_letter_insertion(previous, token)
    if previous.islower() and is_roman(previous):
        # `ii` is a doubled letter as well as a numeral, so the numeral reading is tried first:
        # `(ii)` -> `(iii)` is the roman list advancing, `(cc)` -> `(dd)` the doubled one.
        if is_roman(token) and token.casefold() == roman_successor(previous):
            return True
        return is_doubled_step(previous, token)
    if is_doubled_letter(previous) and is_doubled_letter(token):
        return is_doubled_step(previous, token)
    if token.casefold() == alpha_successor(previous):
        return True
    return is_roman(previous) and is_roman(token) and token.casefold() == roman_successor(previous)


def resolve_letter(token: str, *, previous: str | None, previous_type: str | None) -> str:
    """Decide whether a letter token opens a paragraph or a subparagraph.

    A token that continues the open sibling list keeps that list's kind: `(i)` after `(h)` is the
    ninth paragraph, not the first subparagraph, and `(ii)` after `(i)` is the second
    subparagraph. Only when nothing is continued does the token open a new list, and then the
    reading is roman if it can be the first roman numeral and alphabetic otherwise.

    Known limit: this decides purely from the sequence, never from indentation, though the
    layout reading carries each line's `x0` and a genuinely new subparagraph list is usually
    indented further than the paragraph list it sits under. A subparagraph list that happens to
    open `(i)` immediately beneath a paragraph `(h)` is read as the ninth paragraph rather than a
    fresh subparagraph. Gate L1 does not compare below section/clause level — no Arrangement
    enumerates paragraphs — so this cannot turn a mismatch into a false `passed`; it can only
    misname a node the gate was never asked to check. Left unfixed until real corpus data shows
    whether indentation would help or would itself be an unreliable signal.
    """
    if (
        previous is not None
        and previous_type in {"paragraph", "subparagraph"}
        and continues_run(previous, token, previous_type)
    ):
        return previous_type
    if is_roman(token) and roman_value(token) == 1:
        return "subparagraph"
    return "paragraph"


# Amendment provenance a reprint carries in its margins or in square brackets: `[Am. Act A1234]`,
# `[Ins. Akta A660]`, `[Ditukar ganti Akta A1600]`. These are free amendment evidence and are
# captured rather than discarded (HANDOFF 26.1).
_ANNOTATION_RE = re.compile(
    r"\[\s*(?P<op>Am|Ins|Subs|Del|Pin|Mas|Ptg|Gan)[a-z.]*\s*\.?\s*"
    r"(?P<instrument>(?:Act|Akta|P\.U\.\s*\([AB]\))[^\]]*)\]",
    re.IGNORECASE,
)

_ANNOTATION_OPERATION = MappingProxyType(
    {
        "am": "amendment",
        "pin": "amendment",
        "ins": "insertion",
        "mas": "insertion",
        "subs": "substitution",
        "gan": "substitution",
        "del": "deletion",
        "ptg": "deletion",
    }
)


def amendment_annotations(text: str) -> tuple[tuple[str, str], ...]:
    """Every `[Am. Act A1234]`-style marginal annotation in a line, as `(operation, instrument)`.

    This records that an amendment touched the provision and which instrument did it. It is
    evidence for Stage 3, never a substitute for it: the operation itself is extracted from the
    amending Act's own words, not from the reprint's margin.
    """
    found = []
    for match in _ANNOTATION_RE.finditer(text):
        operation = _ANNOTATION_OPERATION[match.group("op").casefold()]
        found.append((operation, " ".join(match.group("instrument").split()).rstrip(" .")))
    return tuple(found)
