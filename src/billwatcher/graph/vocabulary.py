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
        "section",
        "clause",
        "subsection",
        "paragraph",
        "subparagraph",
        "schedule",
    }
)

EID_PREFIXES = MappingProxyType(
    {
        "part": "part",
        "chapter": "chp",
        "section": "sec",
        "clause": "cl",
        "subsection": "subsec",
        "paragraph": "para",
        "subparagraph": "subpara",
        "schedule": "sched",
    }
)

AKN_ELEMENTS = MappingProxyType(
    {
        "preamble": "preamble",
        "part": "part",
        "chapter": "chapter",
        "section": "section",
        "clause": "clause",
        "subsection": "subsection",
        "paragraph": "paragraph",
        "subparagraph": "subparagraph",
        # A schedule is an hcontainer inside <attachments>, not an element of its own.
        "schedule": "hcontainer",
    }
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
        "section": ("Seksyen", "Section"),
        "clause": ("Fasal", "Clause"),
        "subsection": ("Subseksyen", "Subsection"),
        "paragraph": ("Perenggan", "Paragraph"),
        "subparagraph": ("Subperenggan", "Subparagraph"),
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


# `Bahagian I`, `PART IV`, `Bab 2`, `Chapter 2`. The number may be roman or arabic; both are
# published. A heading may follow on the same line or the next one.
_CONTAINER_RE = re.compile(
    r"^\s*(?P<word>bahagian|part|bab|chapter)\s+(?P<num>[IVXLCDM]+|\d+[A-Z]?)\b\W*(?P<heading>.*)$",
    re.IGNORECASE,
)

_CONTAINER_TYPE = MappingProxyType(
    {"bahagian": "part", "part": "part", "bab": "chapter", "chapter": "chapter"}
)


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
    if words[0][0].islower():
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
    node_type = _CONTAINER_TYPE[match.group("word").casefold()]
    return node_type, match.group("num").upper(), heading


# `Jadual Pertama`, `JADUAL KEDUA`, `First Schedule`, `SCHEDULE`. Schedules restart their own
# numbering, so recognising one is what stops a schedule's paragraph 1 from being read as a
# second section 1.
_SCHEDULE_RE = re.compile(
    r"^\s*(?:(?P<ordinal_en>first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+)?"
    r"(?P<word>jadual|schedule)"
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


# What a heading-shaped line may end with and still be a heading. A Part or Schedule heading is a
# label; the reading that produced `Jadual.` or `Bahagian IV.` was the tail of a sentence — `...
# yang dinyatakan dalam Jadual.` — that wrapped onto its own line and was read as a heading for
# being short. Measured: 199 such `Jadual.` / `Schedule.` lines across 145 readings, 124 of them
# rejected, because the false schedule swallowed every clause after it as a schedule paragraph.
_SENTENCE_TAIL_RE = re.compile(r"[.;:,](?:[\"“”'’)\]]*)$")


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


def body_opening(text: str) -> bool:
    """Whether this line opens the bill's own text, closing any Arrangement above it."""
    return _BODY_OPENING_RE.match(" ".join(text.split())) is not None


# An amendment bill prints the text it inserts into the principal Act inside quotation marks, and
# those marks are the only thing separating that text from the bill's own clauses. The numbers
# inside them belong to the Act being amended — `12A.`, `13.`, `95A.` — so a reader that takes them
# for clauses of the bill gives itself a second clause 13, a sequence that jumps to 95 and back,
# and the duplicate eIds Gate P1 rejects. Straight and curly double quotes both occur; the single
# quote is deliberately not here, because an apostrophe would open a span on every possessive.
QUOTE_CHARS = '"\u201c\u201d'
_QUOTE_CHARS = QUOTE_CHARS
_QUOTE_OPEN_RE = re.compile(f"^[{_QUOTE_CHARS}]")


# The quotation may also open mid-line, after the words that introduce it — `...perenggan yang
# berikut: "(d) melantik anggota...` — with the introducing clause and the first quoted line
# sharing one printed line. The last mark on such a line follows a colon or a dash and nothing
# closes it; a mark anywhere else mid-line is a defined term or a quoted word, which the parity
# test already leaves alone.
_QUOTE_INTRODUCED_RE = re.compile(f"[:—–-]\\s*[{_QUOTE_CHARS}][^{_QUOTE_CHARS}]*$")


def opens_quotation(text: str) -> bool:
    """Whether this line opens a quotation — the first line of amended text.

    Either the line begins with a mark, or its last mark is introduced by a colon or dash and
    left unclosed (`...the following paragraph: "(d) ...`). The caller still decides by parity
    whether the quotation runs on past this line.
    """
    return _QUOTE_OPEN_RE.match(text) is not None or _QUOTE_INTRODUCED_RE.search(text) is not None


def quotation_marks(text: str) -> int:
    """How many quotation marks this line carries.

    Parity is what tells a quotation that *runs on* from one that closes where it opened, and it
    settles two cases a "does it end with a mark" test gets wrong in opposite directions. A defined
    term — `"revised law" means the revised edition...` — opens with a mark and carries two, so it
    is balanced and quotes nothing beyond itself; a real insertion — `"Powers of examination and
    search` — carries one, and stays open until the mark that shuts it. Counting also survives the
    mark landing mid-line, which is where an amendment usually puts it — `..."; and`, `...".`.
    """
    return sum(text.count(mark) for mark in _QUOTE_CHARS)


_PROVISION_NUM_RE = re.compile(r"^\s*(?P<num>\d{1,4}[A-Z]{0,2})\s*\.\s*(?P<rest>.*)$")

# `(1)`, `(2A)` open a subsection; `(a)`, `(bb)` a paragraph; `(i)`, `(iv)` a subparagraph.
# The letter forms genuinely overlap — `i`, `v`, `x`, `l`, `c`, `d` and `m` are each both a
# paragraph letter and a roman numeral — so `parenthesised` only splits the token out. Which kind
# it is cannot be decided from the token alone; `resolve_letter` decides it from the sequence the
# token continues. Guessing here is how a paragraph list silently becomes a subparagraph list,
# which changes every eId beneath it.
_SUBSECTION_RE = re.compile(r"^\s*\((?P<num>\d{1,3}[A-Z]{0,2})\)\s*(?P<rest>.*)$")
_LETTER_RE = re.compile(r"^\s*\((?P<num>[A-Za-z]{1,4})\)\s*(?P<rest>.*)$")

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
        return "letter", match.group("num"), match.group("rest").strip()
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

    The lettered counterpart of `5` -> `5A` -> `6`: a paragraph inserted after `(a)` is `(aa)`,
    and the list resumes at `(b)` — `by inserting after paragraph (a) the following paragraph:
    "(aa) ..."` is how the bill itself puts it. Both steps, `a` -> `aa` and `aa` -> `b`, are
    consecutive; `aa` -> `ab` (a second insertion) already is under the plain letter order.
    """
    left, right = previous.casefold(), current.casefold()
    if right == "ii":
        # `(ii)` after `(i)` is the roman list `(i)` opened, never an insertion: an `(i)` read as
        # the ninth paragraph is the known ambiguity, and this is where it resolves itself.
        return False
    if is_doubled_letter(right) and right[0] == left and len(left) == 1:
        return True
    return is_doubled_letter(left) and len(right) == 1 and right == alpha_successor(left[0])


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
