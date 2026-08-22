"""Controlled vocabulary for Malaysian legislative structure (HANDOFF 26.2).

Pure data and pure functions. Nothing here performs I/O or imports the database, exactly as
`billwatcher.domain.vocabulary` does for the bill-listing vocabulary.

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


def container_heading(text: str) -> tuple[str, str, str] | None:
    """Classify a line as a Part or Chapter heading, returning `(type, num, heading)`."""
    match = _CONTAINER_RE.match(" ".join(text.split()))
    if not match:
        return None
    node_type = _CONTAINER_TYPE[match.group("word").casefold()]
    return node_type, match.group("num").upper(), match.group("heading").strip(" .")


# `Jadual Pertama`, `JADUAL KEDUA`, `First Schedule`, `SCHEDULE`. Schedules restart their own
# numbering, so recognising one is what stops a schedule's paragraph 1 from being read as a
# second section 1.
_SCHEDULE_RE = re.compile(
    r"^\s*(?:(?P<ordinal_en>first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+)?"
    r"(?P<word>jadual|schedule)"
    r"(?:\s+(?P<ordinal_ms>pertama|kedua|ketiga|keempat|kelima|keenam|ketujuh|kelapan|"
    r"kesembilan|kesepuluh)|\s+(?P<num>[IVXLCDM]+|\d+))?\W*$",
    re.IGNORECASE,
)

# Public because coverage measurement needs to know which words *name* a schedule rather than
# being part of its text; see `pipeline.fidelity`.
SCHEDULE_ORDINALS = MappingProxyType(
    {
        "pertama": "1", "first": "1",
        "kedua": "2", "second": "2",
        "ketiga": "3", "third": "3",
        "keempat": "4", "fourth": "4",
        "kelima": "5", "fifth": "5",
        "keenam": "6", "sixth": "6",
        "ketujuh": "7", "seventh": "7",
        "kelapan": "8", "eighth": "8",
        "kesembilan": "9", "ninth": "9",
        "kesepuluh": "10", "tenth": "10",
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
    if previous is not None and previous_type in {"paragraph", "subparagraph"}:
        if previous_type == "paragraph" and token.casefold() == alpha_successor(previous):
            return "paragraph"
        if (
            previous_type == "subparagraph"
            and is_roman(token)
            and token.casefold() == roman_successor(previous)
        ):
            return "subparagraph"
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
        "am": "amendment", "pin": "amendment",
        "ins": "insertion", "mas": "insertion",
        "subs": "substitution", "gan": "substitution",
        "del": "deletion", "ptg": "deletion",
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
