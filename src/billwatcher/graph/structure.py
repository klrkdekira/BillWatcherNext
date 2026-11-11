"""A bill's provision hierarchy, read out of markdown. The domain object, not a serialisation.

This is what the pipeline is *about*: Bahagian and Fasal, Seksyen and Jadual — the structure a
Malaysian bill is printed with. Akoma Ntoso is one rendering of it, produced at the end by
`graph.render`, and it is deliberately not what this module knows or cares about. The tree here is
complete and meaningful with no XML anywhere near it, which is why Gate P1 (`graph.fidelity`) can
judge a reading against its markdown without a renderer in the loop.

Split out of the former `graph.akn`, which held the tree and the serialisation in one file. That
module's own docstring had already drawn the line — "What stays deterministic, and always will:
`Node`, `render_akn`, and `assign_eids`" — and ADR-030 splits the *steps* along the same seam
(`extract-structure`, then `render-akn`), so the modules now match the decision.

An extractor decides only *what* provisions exist and their printed numbers and text. eId
assignment is never an extractor's business: `assign_eids` owns it, so a tree from the regex
reader, from a handoff answer, or from a model all receive identical identifiers for identical
structure. `RegexMarkdownStructureExtractor` (deterministic, offline) is the default;
`graph.handoff.FileStructureExtractor` reads answers produced elsewhere; both satisfy
`MarkdownStructureExtractor`.

The vocabulary this reads with — Bahagian/Part, Seksyen/Section, Fasal/Clause, eId prefixes, roman
numerals and paragraph letters — is `graph.vocabulary`, pure text classification with no dependency
on a database or on PDF geometry, so it applies to markdown lines exactly as it applied to a
database-backed reading.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from billwatcher.graph.tree import Node, body_start, strip_markdown_line
from billwatcher.graph.vocabulary import (
    CONTAINER_RANK,
    EID_PREFIXES,
    arrangement_heading,
    back_matter_heading,
    begins_with_mark,
    closes_straight_quotation,
    container_heading,
    continues_run,
    ends_in_citation,
    ends_in_reference,
    is_doubled_letter,
    is_roman,
    is_sentence_tail,
    opens_quotation,
    opens_straight_quotation,
    parenthesised,
    provision_number,
    quotation_marks,
    roman_value,
    schedule_heading,
    to_roman,
)

__all__ = [
    "MAX_MARGINAL_NOTE_CHARS",
    "MarkdownStructureExtractor",
    "Node",
    "RegexMarkdownStructureExtractor",
    "StructureUnavailable",
    "assign_eids",
    "infer_language_and_unit",
    "parse_markdown_structure",
    "split_marginal_note",
    "strip_markdown_line",
]


# A marginal note is a short label, not a sentence: `Tajuk ringkas`, `Kewajipan untuk melaporkan`,
# `Penalti`. 80 characters is not a fresh guess — it is the same bound
# `legislation.layout._MARGIN_MAX_CHARS` already uses to tell a marginal note from an indented block
# when it has the page geometry to look at. The number is duplicated rather than imported because
# that module pulls in pdfminer and this pipeline is deliberately PDF-free (ADR-021).
MAX_MARGINAL_NOTE_CHARS = 80

_SENTENCE_ENDINGS = (".", ";", ":", "!", "?")


def split_marginal_note(rest: str) -> tuple[str | None, str]:
    """Split the text after a provision number into `(marginal note, body text)`.

    Malaysian bills print a provision two ways. Usually the marginal note is on its own line and
    the body follows: `5. Kewajipan untuk melaporkan` then the prose. But an amendment bill
    typically has no note at all and runs the whole provision in after the number —
    `2. Kanun Keseksaan [Akta 574] dipinda dalam seksyen 375 dengan menggantikan ...` — and the
    printed line is then indistinguishable in shape from the first case.

    Getting this wrong is not cosmetic. `heading` and body text are published under *different*
    rights rules: headings are published in metadata-only mode and body text is withheld
    (ADR-027). Treating a run-in sentence as a heading therefore publishes drafted legislative text
    while the rights review is open. So the test is deliberately conservative — a note has to be
    short and has to not read as a sentence — and anything else is returned as body text, which is
    the safe classification. `pipeline.redact` enforces the same bound independently, because this
    parser is not the only producer of a tree.
    """
    text = rest.strip()
    if not text:
        return None, ""
    if parenthesised(text) is not None:
        # `1. (1) Akta ini ...` — the text opens a subsection, so the provision has no note of its
        # own. The same rule `legislation.structure` applies for the Postgres-backed reading.
        return None, text
    if len(text) > MAX_MARGINAL_NOTE_CHARS or text.endswith(_SENTENCE_ENDINGS):
        return None, text
    return text, ""


# How far ahead of the last clause a number may sit and still be read as the next one. Not zero,
# because a reading that loses a clause to OCR must be able to pick the sequence up again rather
# than discard every clause after the hole; not large, because the whole point is to reject the
# principal Act's numbering, which runs far ahead of the bill's.
_CLAUSE_LOOKAHEAD = 3

# No bill has a thousand clauses. A number this large printed as if it opened one is a year in a
# cited Act — `... Act 1955.`, `... 2001.` — which the provision pattern reads as a number because
# it is one.
_IMPLAUSIBLE_CLAUSE = 1000


def _is_clause_number(num: str, last_clause: int | None) -> bool:
    """Whether this printed number can be a clause of *this bill* at this point in it.

    A bill numbers its clauses densely from 1. Two things it prints look like clause numbers and
    are not: the year in a cited Act, and the sections an amendment bill inserts, which carry the
    principal Act's numbering and so leap far ahead of the bill's own — `1, 2, 3, 47, 48, ... 55,
    4` is one real reading, in which only `1, 2, 3, 4` are clauses at all. Both produce exactly the
    duplicate eIds and order findings Gate P1 blocks on.

    Only those two are refused, and the distinction is the point. A number that runs *backwards*,
    or a Part that restarts its numbering at 1, is not a misprint this function should absorb — it
    is a misreading, and `sequence_order` and `unanchored_run` exist to name it. Silently declining
    to record it would leave the gate with nothing to find and the document looking clean, which is
    the opposite of what the gate is for. So the parser rejects only what cannot be a clause, and
    leaves everything that merely *should not* be one to be judged.
    """
    digits = re.match(r"\d+", num)
    if digits is None:
        # A number this function cannot read is left to the gate rather than silently dropped.
        return True
    value = int(digits.group())
    if value >= _IMPLAUSIBLE_CLAUSE:
        return False
    if last_clause is None:
        # The opening clause is not checked against a sequence there is none of yet. A run that
        # starts at the wrong number is `unanchored_run`, and the gate says so.
        return True
    if value < last_clause and num[len(digits.group()) :]:
        # `7B` after clause 11, `1A` after clause 3: a number that runs backwards *and* carries an
        # insertion letter is a section the bill inserts into the principal Act, quoted with its
        # marks lost. A bill's own clauses do not run backwards, and the one misreading that
        # makes them appear to — an Arrangement read as a second body — prints plain numbers,
        # which stay with the gate.
        return False
    return value <= last_clause + _CLAUSE_LOOKAHEAD


def _resumes_clause_sequence(text: str, last_clause: int | None) -> bool:
    """Whether this line is the bill's next clause, and so cannot be inside a quotation.

    The escape hatch for a quotation that never closes. An amendment bill quotes the sections it
    inserts, and those carry the *principal Act's* numbering, so they must not be read as clauses —
    but when the closing mark is lost, as OCR regularly loses it, the quotation would otherwise run
    to the end of the bill and swallow every real clause after it. In one document that cost
    clauses 22 to 25: section 32A's closing mark was missing, and the span ran on until an
    unrelated line happened to carry an odd mark.

    A bill numbers its clauses 1, 2, 3 without gaps, and a quoted section almost never lands
    exactly on the next one — the numbers it carries are the Act's, which are far ahead. So the
    successor is the one line that can be trusted to end a runaway quotation. Being strict costs
    nothing: a bill that really has skipped a number is a `sequence_gap`, which Gate P1 blocks
    anyway.
    """
    if last_clause is None:
        return False
    match = provision_number(text)
    if match is None:
        return False
    digits = re.match(r"\d+", match[0])
    return digits is not None and int(digits.group()) == last_clause + 1


class _OpenLists:
    """The lettered and numbered lists open beneath the current provision, outermost first.

    Malaysian drafting nests four depths under a provision — `(1)` subsections, `(a)` paragraphs,
    `(i)` subparagraphs, and `(A)` beneath those — and a token is placed by the list it *continues*,
    not by its shape: `(i)` after `(h)` is the ninth paragraph, `(iii)` after `(C)` closes the
    capital-lettered list and resumes the roman one two levels up. A single "last letter" cannot
    answer the second case, which is why this is a stack: the walk runs from the innermost open
    list outward and the first list whose successor matches wins, closing everything deeper.

    A list that *restarts* under a parent that already holds it — a second `(a)` beneath the same
    subsection, a second `(1)` beneath the same clause — is not structure this tree can hold, and
    it is read as prose. Two things print that way. An interpretation clause gives each defined
    term its own `(a)`, `(b)` list, so one subsection carries several lists that no eId scheme with
    one `para_a` per parent can name apart (measured: 514 rejected readings carried such a
    restart, the largest remaining cause). And an amendment clause inserting several sections
    prints each with its own `(1)`, `(2)`; when the quotation marks are lost, those subsections read
    as the clause's own. In both cases every line stays in the tree as the parent's text — the
    coverage measure is whole, and what is lost is a sub-structure the gate could otherwise only
    reject. Modelling definition lists as their own container (AKN's `blockList`) is a decision for
    the vocabulary, the renderer and the published schema together, and is deliberately not made
    here.
    """

    def __init__(self, provision: Node) -> None:
        self.provision = provision
        self.nodes: list[Node] = []  # e.g. [subsection, paragraph, subparagraph, subparagraph]
        self._prose_only: set[int] = set()  # ids of nodes whose lists were flattened to text

    @property
    def innermost(self) -> Node:
        return self.nodes[-1] if self.nodes else self.provision

    def place(self, kind: str, token: str) -> Node | None:
        """Attach a `(token)` opening; `None` means the line is prose of `innermost` instead."""
        if kind == "subsection":
            return self._attach(self.provision, "subsection", token, depth=0)
        return self._place_letter(token)

    def _place_letter(self, token: str) -> Node | None:
        for depth in range(len(self.nodes) - 1, -1, -1):
            sibling = self.nodes[depth]
            if sibling.node_type == "subsection":
                break
            if sibling.node_type == "list":
                continue
            if continues_run(sibling.num or "", token, sibling.node_type):
                parent = self.nodes[depth - 1] if depth else self.provision
                if parent.node_type == "list":
                    # The sibling sits inside one of several lists; the node that *holds* the
                    # lists is what `_attach` continues or renumbers them on.
                    holder = self.nodes[depth - 2] if depth >= 2 else self.provision
                    return self._attach(holder, sibling.node_type, token, depth=depth - 1)
                return self._attach(parent, sibling.node_type, token, depth=depth)
        # Nothing continued. Two misreadings are rescued before a new list is allowed to open,
        # each at the one position where the printed token cannot be right: `(h)` straight after
        # `(a)` is `(b)` — no lettered list skips six letters at its second entry, and the reading
        # confuses the two glyphs constantly in the 1990s typeface (measured: the largest single
        # cause of paragraph findings) — and a lone capital equal to the open lower-case list's
        # next letter (`(I)` after `(h)`) is that letter, since a capital list opens at `(A)`.
        for depth in range(len(self.nodes) - 1, -1, -1):
            sibling = self.nodes[depth]
            if sibling.node_type in ("subsection", "list"):
                continue
            rescued = _misread_letter(sibling.num or "", token, sibling.node_type)
            if rescued is not None:
                return self._place_letter(rescued)
            break
        # A lower-case roman numeral beyond an open roman list's last entry — `(vii)` beneath a
        # list standing at `(v)`, its `(vi)` lost to the reading — is that list's next entry with
        # a hole before it, not a new paragraph list opening at `(vii)`: the gate then names the
        # missing `(vi)` where it is missing, and `(b)` after the run still finds its `(a)`.
        if _is_list_numeral(token) and roman_value(token) > 1:
            for depth in range(len(self.nodes) - 1, -1, -1):
                sibling = self.nodes[depth]
                if sibling.node_type == "subsection":
                    break
                if (
                    sibling.node_type == "subparagraph"
                    and (sibling.num or "").islower()
                    and is_roman(sibling.num or "")
                    and 0 < roman_value(sibling.num or "") < roman_value(token)
                ):
                    parent = self.nodes[depth - 1] if depth else self.provision
                    if parent.node_type == "list":
                        holder = self.nodes[depth - 2] if depth >= 2 else self.provision
                        return self._attach(holder, "subparagraph", token, depth=depth - 1)
                    return self._attach(parent, "subparagraph", token, depth=depth)
        # A new list opens. Capitals and a leading roman `i` nest one level beneath whatever
        # lettered list is open; a lower-case letter starts the paragraph list under the
        # subsection or the provision itself.
        if (
            token.isupper()
            or is_doubled_letter(token)
            or (is_roman(token) and roman_value(token) == 1)
        ):
            return self._attach(self.innermost, "subparagraph", token, depth=len(self.nodes))
        if self.nodes and self.nodes[0].node_type == "subsection":
            return self._attach(self.nodes[0], "paragraph", token, depth=1)
        return self._attach(self.provision, "paragraph", token, depth=0)

    def _attach(self, parent: Node, node_type: str, token: str, *, depth: int) -> Node | None:
        """Create the node under `parent` at stack `depth`, handling a restart of the same list.

        A restarting *lettered* list — a second `(a)` beneath the parent that already holds one —
        becomes the next of several lists (ADR-043): the items already there are wrapped as
        `list_1`, the new item opens `list_2`, and each list numbers its own items, so an
        interpretation clause's defined terms keep their structure with distinct identifiers. A
        restarting *subsection* list is different: a clause has one `(1)`, and a second one is an
        inserted section of another Act whose marks were lost, so the clause's subsections are read
        as its prose instead.
        """
        if id(parent) in self._prose_only:
            self.nodes = self.nodes[:depth]
            return None
        existing = [child for child in parent.children if child.node_type == node_type]
        duplicate = any(child.num == token for child in existing)
        restarts = bool(existing) and (
            duplicate
            or (
                node_type != "subsection"
                and _opens_a_list(token)
                and not continues_run(existing[-1].num or "", token, node_type)
            )
        )
        if restarts:
            if node_type == "subsection":
                for child in parent.children:
                    parent.paragraphs.extend(_lines_of(child))
                parent.children = []
                self._prose_only.add(id(parent))
                self.nodes = self.nodes[:depth]
                return None
            last_item = parent.children[-1]
            if last_item.node_type == node_type and _introduces_list(last_item):
                # `(d) dalam subseksyen (3)—` then `(a) dalam perenggan (a)...`: the new list is
                # the last item's own, introduced by the dash its one line ends with, and nests
                # beneath it, so `(e)` after it still continues `(d)`. A restart after further
                # prose — a defined term's `"term" means—` appended to the item before — is the
                # next of several sibling lists instead.
                node = Node(node_type, token, None, _eid_of(last_item, node_type, token))
                last_item.children.append(node)
                self.nodes = [*self.nodes[:depth], last_item, node]
                return node
            if not (parent.children and parent.children[-1].node_type == "list"):
                first = Node("list", "1", None, _eid_of(parent, "list", "1"))
                first.children = parent.children
                parent.children = [first]
            ordinal = str(len(parent.children) + 1)
            group = Node("list", ordinal, None, _eid_of(parent, "list", ordinal))
            parent.children.append(group)
            node = Node(node_type, token, None, _eid_of(group, node_type, token))
            group.children.append(node)
            self.nodes = [*self.nodes[:depth], group, node]
            return node
        if (
            node_type != "subsection"
            and parent.children
            and parent.children[-1].node_type == "list"
        ):
            # The parent already holds several lists: a token that continues the last list's last
            # item joins that list, and any other — `(a)` again, or a letter out of sequence —
            # opens the next one. A subsection never joins one: the lists hold lettered items,
            # and a clause's `(1)` after them is the clause's own.
            group = parent.children[-1]
            last = group.children[-1] if group.children else None
            continues = last is not None and continues_run(last.num or "", token, last.node_type)
            if any(c.num == token for c in group.children) or (
                _opens_a_list(token) and not continues
            ):
                ordinal = str(len(parent.children) + 1)
                group = Node("list", ordinal, None, _eid_of(parent, "list", ordinal))
                parent.children.append(group)
            node = Node(node_type, token, None, _eid_of(group, node_type, token))
            group.children.append(node)
            self.nodes = [*self.nodes[:depth], group, node]
            return node
        node = Node(node_type, token, None, _eid_of(parent, node_type, token))
        parent.children.append(node)
        self.nodes = [*self.nodes[:depth], node]
        return node

    def paragraph_list_at_k(self) -> bool:
        """Whether the open paragraph list stands at `(k)`, so the next token should be `(l)`.

        `(l)`, `(1)` and `(I)` are one glyph apart in most faces, and the reading prints the
        twelfth paragraph as a subsection `(1)` or a capital `(I)` often enough to have rejected
        over a hundred readings between them. Only this one position is rescued: after `(k)`, a
        `(1)` cannot be a subsection — a clause with paragraphs directly beneath it does not then
        open subsections — and a lone capital `(I)` beneath a `(k)` has no list to belong to.
        """
        paragraph = next((n for n in reversed(self.nodes) if n.node_type == "paragraph"), None)
        return paragraph is not None and paragraph.num == "k"


# The highest numeral a subparagraph list is read up to. `c`, `d`, `l` and `m` are roman numerals
# too, and `(d)` after `(c)` is the fourth paragraph, never the five-hundredth subparagraph.
_MAX_LIST_NUMERAL = 40


def _is_list_numeral(token: str) -> bool:
    """Whether a token is a lower-case roman numeral as subparagraph lists actually use them."""
    return (
        token.islower()
        and is_roman(token)
        and not is_doubled_letter(token)
        and 0 < roman_value(token) <= _MAX_LIST_NUMERAL
        and (len(token) > 1 or token in "ivx")
    )


def _misread_letter(previous: str, token: str, previous_type: str) -> str | None:
    """The letter a token was misread from, when the sequence leaves no other reading."""
    if previous_type not in ("paragraph", "subparagraph") or not previous.islower():
        return None
    if token == "h" and previous == "a":
        return "b"
    if (
        len(token) == 1
        and token.isupper()
        and continues_run(previous, token.lower(), previous_type)
    ):
        return token.lower()
    return None


def _introduces_list(item: Node) -> bool:
    """Whether an item's own opening line, and nothing after it, introduces a list beneath it."""
    return (
        len(item.paragraphs) == 1
        and not item.children
        and item.paragraphs[0].rstrip().endswith(("—", "–", ":", "-"))
    )


def _opens_a_list(token: str) -> bool:
    """Whether a letter token is the first of a list — `a`, `i`, `A`, `aa` — not a later one.

    What tells a list *restarting* from a list with a hole in it: `(a)` after `(c)` is a new list
    and gets a container of its own, while `(d)` after `(b)` stays in the run, where the gate can
    name the missing `(c)`.
    """
    return token.casefold() in {"a", "i", "aa"}


def _lines_of(node: Node) -> list[str]:
    """A node and its descendants back as the printed lines they were read from, in order."""
    head = f"({node.num})" if node.num else ""
    lines: list[str] = []
    if node.paragraphs:
        lines.append(f"{head} {node.paragraphs[0]}".strip())
        lines.extend(node.paragraphs[1:])
    elif head:
        lines.append(head)
    for child in node.children:
        lines.extend(_lines_of(child))
    return lines


def _eid_of(parent: Node, node_type: str, token: str) -> str:
    piece = f"{EID_PREFIXES[node_type]}_{token}"
    return f"{parent.eid}__{piece}" if parent.eid else piece


# `(c), perenggan baru (d)`, `(2), (3), (4) dan (5)`, `(a) dan (b)`: the token that opens the
# line is the tail of a cross-reference, not a provision opening — it is glued to a comma or a
# conjunction leading straight into another token.
# `(b); or` is the number of a reference wrapped onto its own line too, and so is `(1)(d), ...`: a
# real opener is followed by its text, never straight by a semicolon, a full stop, or a second
# bracketed token and a comma.
_REFERENCE_TAIL_RE = re.compile(
    r"^(?:,|[;.](?:\s|$)|(?:dan|and|atau|or|hingga|to)\s+\(|\(\w{1,4}\)\s*[,.;])"
)

# A marginal note spliced onto the provision it labels, ahead of the number: `Pindaan 4. Seksyen
# HB Akta ibu...`, `Keanggotaan 9. ...`. The layout reader separates a note from the text it
# annotates when it has the geometry to (ADR-016), and this is the residue where it did not. The
# prefix is short, has no sentence punctuation, and is not itself a structural token; the number is
# the bill's exact next clause, which is the one thing that makes the reading safe — 146 of the 264
# readings rejected for a skipped clause carried the missing number in exactly this position.
_SPLICED_NOTE_RE = re.compile(
    r"^(?P<note>[^\d(\[.;:\s][^.;:]{0,79}?\.?)\s+(?P<num>\d{1,4}[A-Z]{0,2})\.\s+(?P<rest>\S.*)$"
)

# A note that closes with its own full stop — `Penalty.`, `Activity.`, in the older typesetting —
# is accepted only when it is as short as a label: a sentence tail before a number would be body
# text read as a heading, which ADR-027 publishes under a different rule, so the bound is tight.
_SPLICED_NOTE_WITH_STOP_MAX_WORDS = 5


# The full stop after a clause number read as a comma — `3, Maka adalah dengan ini ditubuhkan` —
# which `provision_number` rightly refuses in general (a bare number and a comma is a list), or
# the number's digits split by a space — `4 1. Any person who commits` — which it reads as a bare
# `1`. Either is a clause when, and only when, the number is the bill's exact next one.
_MISPRINTED_STOP_RE = re.compile(r"^(?P<num>\d{1,4}[A-Z]{0,2}),\s+(?P<rest>\S.*)$")
_SPLIT_DIGITS_RE = re.compile(r"^(?P<num>\d(?: \d){1,2})\.\s+(?P<rest>\S.*)$")


def _misprinted_provision(text: str, last_clause: int | None) -> tuple[str, str] | None:
    """`(num, rest)` for a clause whose number the reading misprinted, when it is the next one."""
    if last_clause is None:
        return None
    match = _MISPRINTED_STOP_RE.match(text) or _SPLIT_DIGITS_RE.match(text)
    if match is None:
        return None
    num = match.group("num").replace(" ", "")
    digits = re.match(r"\d+", num)
    if digits is None or int(digits.group()) != last_clause + 1:
        return None
    return num.upper(), match.group("rest").strip()


# A subsection opening the reading misprinted: `(3 The Minister may` with its closing bracket lost,
# `(1.0) Mana-mana orang` with a stop inside the number. Read as the subsection only when it is the
# exact next one beneath the open provision, so a stray bracket cannot open anything.
_UNCLOSED_SUBSECTION_RE = re.compile(r"^\((?P<num>\d{1,3})\s+(?P<rest>[A-Z\"“].*)$")
_DOTTED_SUBSECTION_RE = re.compile(r"^\((?P<num>\d\.\d|\d{1,2}\.)\)\s*(?P<rest>.*)$")


# A paragraph opening whose bracket the reading garbled: `Cd) struktur tambang`, `if) dalam hal
# seseorang anggota`, `{f) in the event of his resignation`. Read as the paragraph only when the
# letter continues the open lettered list.
_GARBLED_LETTER_RE = re.compile(r"^[Ci{\[](?P<num>[a-z])\)\s+(?P<rest>\S.*)$")


def _misprinted_letter(text: str, lists: "_OpenLists") -> tuple[str, str] | None:
    """`(letter, rest)` for the open lettered list's next entry, printed with a garbled bracket."""
    match = _GARBLED_LETTER_RE.match(text)
    if match is None:
        return None
    token = match.group("num")
    for sibling in reversed(lists.nodes):
        if sibling.node_type in ("paragraph", "subparagraph") and continues_run(
            sibling.num or "", token, sibling.node_type
        ):
            return token, match.group("rest").strip()
    return None


def _misprinted_subsection(text: str, lists: "_OpenLists") -> tuple[str, str] | None:
    """`(num, rest)` for the provision's next subsection, printed with a broken bracket."""
    match = _UNCLOSED_SUBSECTION_RE.match(text) or _DOTTED_SUBSECTION_RE.match(text)
    if match is None:
        return None
    num = match.group("num").replace(".", "")
    subsections = [n for n in lists.provision.children if n.node_type == "subsection"]
    if not subsections or not (subsections[-1].num or "").isdigit():
        return None
    if int(num) != int(subsections[-1].num or "0") + 1:
        return None
    return num, match.group("rest").strip()


# A subsection or paragraph opening glued onto the end of the previous one by the reading —
# `...ditetapkan oleh Majlis. (2) Mesyuarat agung luar biasa...`, `...under— (i) paragraph 10(1)(a);
# (ii) ...`. The opener follows a sentence's end or the dash or colon that introduces a list; a
# cross-reference (`subsections (1), (2) and (3)`) never sits after one of those, so the split
# cannot cut a reference in two.
_GLUED_OPENER_RE = re.compile(r"(?<=[.;:—–])\s+(?=\(\s?(?:\d{1,3}[A-Z]?|[a-z]{1,4})\s?\)\s)")


def _split_glued_openers(text: str) -> list[str]:
    """The line as one piece per glued opening; `8. (1) ...` stays whole, being one provision."""
    pieces: list[str] = []
    for piece in _GLUED_OPENER_RE.split(text):
        if not piece:
            continue
        if (
            pieces
            and _NUMBER_BEFORE_OPENER_RE.match(pieces[-1])
            and not ends_in_reference(
                pieces[-1].rstrip(
                    " .0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                )
            )
        ):
            pieces[-1] = f"{pieces[-1]} {piece}"
        else:
            pieces.append(piece)
    return pieces


# The piece before a glued opener is a provision number, alone or behind a word or two of marginal
# note (`1. (1) Akta ini...`, `Registrar, 8. (1) The Director General...`): the ordinary printed
# form of a provision opening with its first subsection, which `open_provision` reads whole. A
# sentence that ends on a reference (`...in accordance with section 6. (2) Of the twelve...`) is not
# that, and is split; nor is a year (`...Income Tax Act 1967. (2) Perenggan 10(a)...`).
_NUMBER_BEFORE_OPENER_RE = re.compile(r"^(?:\S+\s+){0,3}\d{1,3}[A-Za-z]{0,2}\.$")


_NOTE_WITH_NUMBER_RE = re.compile(
    r"^(?P<note>[^\d(\[.;:\s][^.;:]{0,79}?)\s+(?P<num>\d{1,4}[A-Z]{0,2})\.$"
)


def _hanging_number_on_note(note: str, last_clause: int | None) -> tuple[str, str] | None:
    """`(note, num)` when a marginal note ends in the hanging number of the bill's next clause.

    Only the exact next number, and only when the note does not end in a word that takes a
    number: `Pindaan seksyen 5.` beside clause 4 is a note about section 5 and not clause 5's
    number, while `Amendment of 5.` can be nothing but the number — a note does not end in "of".
    """
    if last_clause is None:
        return None
    match = _NOTE_WITH_NUMBER_RE.match(" ".join(note.split()))
    if match is None:
        return None
    digits = re.match(r"\d+", match.group("num"))
    if digits is None or int(digits.group()) != last_clause + 1:
        return None
    text = match.group("note").strip()
    if ends_in_reference(text) or ends_in_citation(text) or text[0].islower():
        return None
    return text, match.group("num").upper()


def _spliced_provision(text: str, last_clause: int | None) -> tuple[str, str, str] | None:
    """`(note, num, rest)` when a marginal note has been read onto the front of the next clause."""
    if last_clause is None:
        return None
    match = _SPLICED_NOTE_RE.match(text)
    if match is None:
        return None
    digits = re.match(r"\d+", match.group("num"))
    if digits is None or int(digits.group()) != last_clause + 1:
        return None
    note = match.group("note").strip()
    if not note or len(note) > MAX_MARGINAL_NOTE_CHARS:
        return None
    if note[0].islower() and len(note.split()) > _SPLICED_LOWERCASE_NOTE_MAX_WORDS:
        # A lower-case opening is a sentence's middle, not a note — except for the tail of a note
        # that wrapped (`publication 30. (1) Where the subscriber accepts`, the note being
        # "Publication of issued and accepted certificate"), which is a word or two at most.
        return None
    if note.endswith(".") and len(note.split()) > _SPLICED_NOTE_WITH_STOP_MAX_WORDS:
        return None
    return note, match.group("num").upper(), match.group("rest").strip()


_SPLICED_LOWERCASE_NOTE_MAX_WORDS = 2


# How much deeper than the bill's own clause column a provision number has to sit before it is
# read as quoted from another Act. A subsection's first-line indent is about an em (12pt at the
# corpus's body size); a quoted section is block-indented further, 40–80pt in the pages measured.
# The bound sits between the two with room for a hanging number on either side.
_QUOTED_DEPTH_TOLERANCE = 18.0


def parse_markdown_structure(
    markdown_text: str,
    *,
    unit: str = "clause",
    blocks: Sequence[Mapping[str, Any]] | None = None,
) -> Node:
    """Build the provision tree from markdown text.

    `unit` is `"clause"` for a bill or `"section"` for an Act (HANDOFF 26.2) — every document in
    this pipeline is a Parliament bill PDF, so the default is `"clause"`; `infer_unit` overrides
    it when the markdown's own Arrangement heading says otherwise.

    `blocks` is the reading's geometry, one record per markdown block (ADR-042). With it, the
    parser reads depth: a provision number set deeper than the shallowest numbered line on its
    page — where the bill's own clauses hang — is a section quoted from the Act being amended,
    and everything at that depth after it is the quoted text, until a line returns to the bill's
    own column. Quotation marks are still read,
    but the page's indentation says the same thing more reliably than marks the reading may have
    lost. Without `blocks` the parser reads exactly as before.
    """
    root = Node(node_type="body", num=None, heading=None, eid="")
    containers: list[Node] = []  # open part/chapter/schedule ancestors, root-most first
    provision: Node | None = None
    lists: _OpenLists | None = None
    in_schedule = False
    in_quotation = False
    last_clause: int | None = None
    depths = _depths_for_lines(markdown_text, blocks)
    quoted_depth: float | None = None  # the depth of the quoted block being read, if any
    quoted_page: int | None = None  # and the page it was measured on: depths compare per page
    # The previous content line and whether it was printed as a heading: what tells a wrapped
    # sentence tail (`... dinyatakan dalam` / `Jadual.`) apart from a heading, and a wrapped
    # reference (`... under subsection` / `(1), subsection 13(3) ...`) apart from an opener.
    previous_text = ""
    previous_was_heading = False

    def innermost_open() -> Node:
        if lists is not None:
            return lists.innermost
        if containers:
            return containers[-1]
        return root

    # A quoted *word* that wrapped: `...dengan memotong perkataan ‘dan` / `“undang-undang
    # sekuriti” ’;`. The first line carries an odd mark without opening anything, and the second
    # begins with a mark and is odd too — which is the shape of an insertion's first line, and
    # read as one it swallowed the paragraphs after it. The dangling mark says the second line is
    # the first one's tail.
    dangling_mark = False

    def open_provision(node_type: str, num: str, note: str | None, leading: str) -> None:
        nonlocal provision, lists, last_clause, dangling_mark
        parent = containers[-1] if containers else root
        if in_schedule and node_type == "paragraph":
            parent = _schedule_item_holder(parent, num)
        node = Node(node_type, num, note, _eid_of(parent, node_type, num))
        parent.children.append(node)
        provision, lists = node, _OpenLists(node)
        dangling_mark = False
        if not in_schedule:
            digits = re.match(r"\d+", num)
            if digits is not None:
                last_clause = int(digits.group())
        if leading:
            # Body text that ran in after the provision number. It is the provision's own
            # prose, so it belongs in its paragraphs — never in `heading`, which is published
            # under a different rights rule (ADR-027). When it opens a subsection, that
            # subsection becomes the open one so a following `(2)` continues the same list
            # rather than attaching to the provision.
            inline = parenthesised(leading)
            if inline is not None and inline[0] == "subsection":
                _, token, remainder = inline
                child = lists.place("subsection", token)
                if child is not None and remainder:
                    child.paragraphs.append(remainder)
            else:
                node.paragraphs.append(leading)

    raw_lines = markdown_text.splitlines()
    lines = [strip_markdown_line(raw_line) for raw_line in raw_lines]
    raw_lines, lines, depths = _expand_glued_openers(raw_lines, lines, depths)
    start = body_start(lines)
    # A straight-single-quoted insertion (`' "term" means ...;'`) is open; see
    # `vocabulary.opens_straight_quotation`. Tracked apart from `in_quotation` because it closes
    # on its own mark, not on the parity of the double marks the definitions inside it carry.
    in_straight = False

    def next_container_num(node_type: str) -> str | None:
        """The number the next container of this type would carry, from the open one."""
        open_same = next((c for c in reversed(containers) if c.node_type == node_type), None)
        return _successor_num(open_same.num) if open_same is not None else None

    clause_floor = _clause_floors(lines, depths, start) if depths is not None else {}
    for index in range(start, len(lines)):
        text = lines[index]
        if not text:
            comment = _MARGINAL_COMMENT_RE.match(raw_lines[index].strip())
            if comment is not None:
                note = comment.group("text")
                if quotation_marks(note) % 2 == 1:
                    # The printed page puts the opening mark of a quoted section on its
                    # *marginal note* — `"Cess on rubber.` beside `7. (1) The Minister may...` —
                    # and the closing mark of a quoted table in the margin column beside its
                    # last row (`and fine”;`); either travels into a comment. The mark is on the
                    # paper whichever column carried it, so a note that begins with one opens the
                    # quotation and a note that ends with one closes it. An opening mark inside a
                    # quotation the introducing colon already opened is that same mark, not a
                    # close (measured: the inserted section `1B` read as a clause after its
                    # note's mark shut the span).
                    if _NOTE_OPENS_RE.match(note):
                        in_quotation = True
                    elif in_quotation and (
                        _NOTE_CLOSES_RE.match(note) or _CLOSING_MARK_AT_END_RE.search(note)
                    ):
                        in_quotation = False
                hanging = _hanging_number_on_note(note, last_clause) if not in_schedule else None
                if hanging is not None and not in_quotation:
                    # `Amendment of 5.`: the clause's hanging number, set beside the column on the
                    # note's own baseline and read onto the end of the note. The body line that
                    # follows is the clause's text.
                    open_provision(unit, hanging[1], hanging[0], "")
            continue
        is_heading = raw_lines[index].lstrip().startswith("#")
        # `previous` is the content line before this one; `continues_sentence` says it was prose
        # rather than a heading, so its ending can be read for whether the sentence ran on.
        previous, continues_sentence = (
            previous_text,
            bool(previous_text) and not previous_was_heading,
        )
        previous_text, previous_was_heading = text, is_heading
        if arrangement_heading(text) is not None:
            # Only reachable for a document whose body opening `body_start` could not find, so the
            # Arrangement could not be bounded and the whole document is being read. Skipping the
            # heading line itself keeps that fallback behaving exactly as it did before.
            continue
        if root.children and back_matter_heading(text):
            # The HURAIAN and everything after it. Its prose numbers its own paragraphs from the
            # bill's low numbers over again, so reading on would append a second clause 2 to the
            # tree — the duplicate the gate then rightly rejects. Only once the body has begun: a
            # committee-stage amendment paper opens with a short HURAIAN of its own and reprints
            # the whole bill after it.
            break

        if _HEADING_WORD_ALONE_RE.fullmatch(text):
            # A heading word with its number on the next line — `BAHAGIAN` / `II`, `JADUAL` /
            # `KEDUA` typeset over two lines (measured: 178 readings, 165 of them rejected because
            # every Part after the first went unread), or `Jadual` / `Pertama.` as a marginal note
            # the reading split. Joined, the first reads as the heading it is and the second as
            # the sentence tail it is; apart, a Part is lost or a first schedule invented.
            following_index = next(
                (j for j in range(index + 1, len(lines)) if raw_lines[j].strip()), None
            )
            following = _heading_number_line(raw_lines, lines, following_index)
            if following is not None and following_index is not None:
                joined = f"{text} {following}"
                if container_heading(joined) is not None or schedule_heading(joined) is not None:
                    text = joined
                    lines[following_index] = ""
        # Text an amendment bill quotes from the Act it amends. It carries the *Act's* numbering —
        # `12A.`, `13.`, `95A.` — so reading it as structure gives the bill a second clause 13 and
        # a sequence that leaps to 95 and back, which after the Arrangement is the largest single
        # reason Gate P1 rejects a reading. It is still the bill's *text*, since the clause is what
        # inserts it, so it goes into the introducing provision's paragraphs rather than being
        # dropped: that is both true and what keeps the gate's coverage measure whole.
        #
        # A span opens only on a line that carries an odd number of marks and either begins with
        # one or introduces one after a colon or dash (`... yang berikut: "(d) ...`), so a defined
        # term (`"revised law" means...`, balanced) is left alone; it shuts on the next odd-marked
        # line, or on the bill's next clause, whichever comes first.
        odd_marks = quotation_marks(text) % 2 == 1
        # A quotation introduced mid-line — `3. Akta ibu dipinda dengan memasukkan ... yang
        # berikut: " Akses 53A. (1) ...` — opens *after* this line has been read for what it is:
        # the clause, paragraph or prose that introduces it. Reading the whole line as quoted
        # text lost the introducing clause itself (measured, on the first attempt).
        introduces = odd_marks and opens_quotation(text) and not begins_with_mark(text)
        # The bill's own next Part, set as a heading, inside a quotation that never closed — an
        # interpretation clause whose closing mark the reading printed as an apostrophe (`"Ketua
        # Pegawai Eksekutif' ertinya...`) opened a span that ran on to the next clause and
        # swallowed `BAHAGIAN II` on the way (measured: every Part after it then read as a gap). A
        # quoted insertion does not carry the bill's own next Part number, so the heading is where
        # the quotation is known to have ended.
        heading_ahead = container_heading(text) if is_heading else None
        own_next_heading = heading_ahead is not None and heading_ahead[1] == next_container_num(
            heading_ahead[0]
        )
        # Deliberately *not* an escape: a subparagraph that continues the bill's open roman list
        # (`(iv)` beneath a list standing at `(iii)`). An inserted paragraph's own `(i)`, `(ii)`,
        # `(iii)`, `(iv)` reaches the same numeral as readily, and reading it as the bill's turned
        # the rest of the quotation into the bill's structure (measured: five readings lost).
        if in_straight:
            if own_next_heading:
                in_straight = False
            elif not _resumes_clause_sequence(text, last_clause):
                innermost_open().paragraphs.append(text)
                if closes_straight_quotation(text):
                    in_straight = False
                continue
            else:
                in_straight = False
        elif opens_straight_quotation(raw_lines[index]) and not closes_straight_quotation(text):
            in_straight = True
            innermost_open().paragraphs.append(text)
            continue
        if in_quotation:
            if own_next_heading:
                in_quotation = False
            elif not _resumes_clause_sequence(text, last_clause):
                innermost_open().paragraphs.append(text)
                if odd_marks:
                    in_quotation = False
                continue
            else:
                in_quotation = False
        elif (
            odd_marks
            and begins_with_mark(text)
            and not (dangling_mark and _DANGLING_CLOSE_RE.match(text))
        ):
            in_quotation = True
            innermost_open().paragraphs.append(text)
            continue
        dangling_mark = bool(odd_marks and not introduces and _DANGLING_OPEN_RE.search(text))

        located = depths[index] if depths is not None and not is_heading else None
        depth = located[0] if located is not None else None
        if located is not None and depth is not None and not in_schedule:
            if quoted_depth is not None and located[1] != quoted_page:
                # Indent is measured from each page's own column, so a depth taken on one page
                # says nothing on the next: the region ends with its page, and a quoted section
                # that runs on re-opens it from that page's own floor if it is still set deeper.
                quoted_depth = None
            if quoted_depth is not None:
                if depth >= quoted_depth - _QUOTED_DEPTH_TOLERANCE:
                    # Still inside the quoted block: the Act's own subsections, paragraphs and
                    # run-on lines, at the depth the quotation was set at or deeper.
                    innermost_open().paragraphs.append(text)
                    continue
                quoted_depth = None
            floor = clause_floor.get(located[1])
            if (
                floor is not None
                and depth > floor + _QUOTED_DEPTH_TOLERANCE
                and provision_number(text) is not None
            ):
                # A provision number set well deeper than the bill's own clauses: a section of
                # the Act being amended, printed inside the clause that inserts it. Its text stays
                # with that clause; its numbering belongs to the other document.
                quoted_depth, quoted_page = depth, located[1]
                innermost_open().paragraphs.append(text)
                continue

        container = container_heading(text)
        schedule_num = schedule_heading(text) if container is None else None
        if (container is not None or schedule_num is not None) and (
            is_sentence_tail(text) and continues_sentence and not _ends_sentence(previous)
        ):
            # `... yang dinyatakan dalam` then `Jadual.`: the tail of a sentence that wrapped onto
            # its own line and was read as a heading for being short. A heading is a label and
            # does not end in a full stop; a sentence does, and the line before it broke off
            # mid-sentence. Read as a false schedule, it swallowed every clause after it.
            innermost_open().paragraphs.append(text)
            continue
        if container is not None:
            node_type, num, heading = container
            open_same = next((c for c in reversed(containers) if c.node_type == node_type), None)
            if open_same is not None and open_same.num == num:
                # The heading of the Part already open, printed again: the running head a
                # continued page carries, or a heading line the reading drew twice. It names no
                # new Part, and reading it as one gave every Part in the corpus that ran past a
                # page a duplicate eId (measured: 116 readings).
                innermost_open().paragraphs.append(text)
                continue
            expected = next_container_num(node_type)
            if continues_sentence and previous.endswith(":") and last_clause is not None:
                # `...the following Part:` then `PART IIA`: an amendment inserting a whole Part,
                # whose quotation mark the reading lost. The Part's number is the principal Act's
                # and its sections are the Act's; both stay the introducing clause's text.
                innermost_open().paragraphs.append(text)
                in_quotation = True
                continue
            if (
                continues_sentence
                and not _ends_sentence(previous)
                and not _introduces_what_follows(previous)
                and len(previous.split()) >= _CONTINUATION_MIN_WORDS
                and num != expected
                and not (open_same is None and num in _FIRST_CONTAINER_NUMBERS)
            ):
                # `...kesalahan di bawah` then `Bahagian IV Akta Suruhanjaya Pencegahan Rasuah`:
                # a cross-reference wrapped onto its own line, set as a heading for being short
                # and title-cased. The sentence before it did not end, and the number is not the
                # one the bill's next Part would carry, so it is the sentence continuing.
                innermost_open().paragraphs.append(text)
                continue
            # A Part, Chapter or Article closes every open container of its own rank or deeper
            # and opens under the nearest shallower one. Inside a Schedule the schedule stays the
            # root of that stack — a treaty's chapters and articles, a Supply Bill's parts, belong
            # to the schedule; leaving it re-rooted them in the body and turned the schedule's
            # numbered items back into clauses.
            base = (
                containers[:1]
                if in_schedule and containers and containers[0].node_type == "schedule"
                else []
            )
            kept = base + [
                c
                for c in containers[len(base) :]
                if CONTAINER_RANK[c.node_type] < CONTAINER_RANK[node_type]
            ]
            parent = kept[-1] if kept else root
            containers = kept
            if not base:
                in_schedule = False
            node = Node(node_type, num, heading or None, _eid_of(parent, node_type, num))
            parent.children.append(node)
            containers.append(node)
            provision, lists = None, None
            continue

        if (
            schedule_num is not None
            and not in_schedule
            and _is_schedule_note(text, lines, index, last_clause)
        ):
            # `Schedule.` set as a heading and followed by `7. (1) The provisions of the Schedule
            # shall apply...`: the marginal note of the clause beneath it, which the reading gave a
            # heading's rank. A schedule's heading carries no full stop and is never followed by
            # the bill's next clause; read as a schedule, it turned every clause after it into a
            # schedule paragraph (measured: two readings, each losing its whole second half).
            innermost_open().paragraphs.append(text)
            continue
        if schedule_num is not None:
            if any(c.node_type == "schedule" and c.num == schedule_num for c in root.children):
                # `JADUAL PERTAMA` again at the top of the schedule's next page: the running head,
                # not a second first schedule. A document has one schedule of each number.
                innermost_open().paragraphs.append(text)
                continue
            if continues_sentence and previous.endswith(":") and last_clause is not None:
                # `...substituting for the Schedule the following Schedules:` then `SCHEDULE`:
                # the principal Act's schedule, quoted; see the Part case above.
                innermost_open().paragraphs.append(text)
                in_quotation = True
                continue
            node = Node("schedule", schedule_num, None, _eid_of(root, "schedule", schedule_num))
            root.children.append(node)
            containers = [node]
            provision, lists = None, None
            in_schedule = True
            continue

        hanging_heading = (
            _hanging_number_on_note(text, last_clause)
            if is_heading and not in_schedule and provision_number(text) is None
            else None
        )
        if hanging_heading is not None:
            # `### Tafsiran 95.`: the marginal note set as a heading, with the clause's hanging
            # number read onto its end — the heading-line form of the marginal-comment case above.
            open_provision(unit, hanging_heading[1], hanging_heading[0], "")
            in_quotation = introduces
            continue

        provision_match = provision_number(text)
        if provision_match is not None:
            num, rest = provision_match
            node_type = "paragraph" if in_schedule else unit
            exact_next = _resumes_clause_sequence(text, last_clause)
            if (
                not rest
                and last_clause is not None
                and (not exact_next or (continues_sentence and ends_in_reference(previous)))
            ):
                # A bare `26.` on a line of its own, with nothing after it, is the tail of a
                # sentence that wrapped (`...dengan memotong seksyen` / `26.`) unless it is the
                # bill's exact next number: a provision has text, or at least is the next one.
                # Even the next number is the tail when the line before it broke off inside a
                # reference (`...memotong seksyen` / `8.`, beside a clause 7 deleting section 8).
                innermost_open().paragraphs.append(text)
                in_quotation = introduces
                continue
            if (
                node_type == unit
                and last_clause is not None
                and continues_sentence
                and previous.endswith(":")
                and len(previous.split()) >= _INTRODUCTION_MIN_WORDS
            ):
                # `...memasukkan selepas seksyen 3 seksyen yang berikut:` then `3A. An officer
                # appointed...`: the inserted section, whose quotation mark the reading lost (or
                # carried on a marginal note). A bill's own clause never follows a colon — the one
                # colon a clause does follow is the enacting formula's, before any clause exists —
                # so the number is the principal Act's — even when it happens to be the bill's
                # next number too, as clause 18 substituting section 19 prints — and the text is
                # quoted until the mark that closes it or the bill's next clause. The colon line
                # has to be a sentence of its own: a reading that set the fragment `the following
                # section:` above the clause it belongs to (the two lines swapped) would
                # otherwise lose that clause.
                innermost_open().paragraphs.append(text)
                in_quotation = True
                continue
            if (
                node_type == unit
                and last_clause is not None
                and not exact_next
                and continues_sentence
                and (
                    ends_in_reference(previous)
                    or (
                        len(previous.split()) >= _CONTINUATION_MIN_WORDS
                        and not _ends_sentence(previous)
                        and not _introduces_what_follows(previous)
                    )
                )
            ):
                # `11. The principal Act is amended by inserting after section` then `7A. 7 the
                # following section:` — the hanging number of the marginal note, read onto the
                # front of the sentence's second line. The line before broke off mid-sentence and
                # this number is not the bill's next, so this is that sentence continuing.
                innermost_open().paragraphs.append(text)
                in_quotation = introduces
                continue
            if node_type == unit and not _is_clause_number(num, last_clause):
                # Not a clause: a cited year, or a section of the Act this bill amends printed
                # without the quotation marks that would have marked it. It is still text the
                # bill prints, so it joins the prose rather than disappearing.
                innermost_open().paragraphs.append(text)
                in_quotation = introduces
                continue
            note, leading = split_marginal_note(rest)
            open_provision(node_type, num, note, leading)
            in_quotation = introduces
            continue

        # Not after a colon: `...substituting for section 4 the following section:` is followed by
        # the Act's section 4, quoted, and when the reading has lost the quotation marks and the
        # Act's number happens to be the bill's next, the splice rule is the one thing that would
        # read it as a clause (measured: two readings, both this shape).
        spliced = (
            _spliced_provision(text, last_clause)
            if not in_schedule and not (continues_sentence and previous.endswith(":"))
            else None
        )
        if spliced is not None:
            note, num, rest = spliced
            open_provision(unit, num, note, rest)
            in_quotation = introduces
            continue

        if (
            not in_schedule
            and last_clause is not None
            and continues_sentence
            and previous.endswith(":")
            and len(previous.split()) >= _INTRODUCTION_MIN_WORDS
            and _LEADING_NUMBER_RE.match(text)
        ):
            # `...the following section:` then `Patent and 17c. (1) If an applicant...`: the
            # inserted section with its marginal note spliced ahead of its number — the same
            # quotation the colon rule above reads when the number opens the line.
            innermost_open().paragraphs.append(text)
            in_quotation = True
            continue

        misprinted = _misprinted_provision(text, last_clause) if not in_schedule else None
        if misprinted is not None:
            num, rest = misprinted
            note, leading = split_marginal_note(rest)
            open_provision(unit, num, note, leading)
            in_quotation = introduces
            continue

        parenthesised_match = parenthesised(text) if lists is not None else None
        if parenthesised_match is None and lists is not None:
            misprinted_subsection = _misprinted_subsection(text, lists)
            misprinted_letter = _misprinted_letter(text, lists)
            if misprinted_subsection is not None:
                parenthesised_match = ("subsection", *misprinted_subsection)
            elif misprinted_letter is not None:
                parenthesised_match = ("letter", *misprinted_letter)
        if parenthesised_match is not None:
            assert lists is not None  # guarded above; narrows for the placement below
            kind, token, rest = parenthesised_match
            if _REFERENCE_TAIL_RE.match(rest) or (
                continues_sentence
                and (ends_in_reference(previous) or _REFERENCE_PAIR_HEAD_RE.search(previous))
            ):
                # `(1), subsection 13(3) shall...` after a line ending `under subsection`: the
                # number of a cross-reference, wrapped onto the next line, wearing the shape of a
                # subsection opening. It is the sentence continuing, so it stays prose.
                lists.innermost.paragraphs.append(text)
                in_quotation = introduces
                continue
            if token in ("1", "I") and lists.paragraph_list_at_k():
                kind, token = "letter", "l"
            placed = lists.place(kind, token)
            if placed is None:
                lists.innermost.paragraphs.append(text)
            elif rest:
                placed.paragraphs.append(rest)
            in_quotation = introduces
            continue

        innermost_open().paragraphs.append(text)
        in_quotation = introduces

    return root


# `...by substituting for paragraphs (a) and` then `(b) the following paragraphs:`: the second
# half of a pair of references, wrapped. A bracketed token and a conjunction end the line before
# (a stray bullet after them is the reading's); a list item ending `; and`, or a quoted `"(4) or";`
# closed by its mark, does not match, so the paragraph after it still opens.
_REFERENCE_PAIR_HEAD_RE = re.compile(
    r"\(\w{1,4}\)\s+(?:and|or|dan|atau|to|hingga)[\s•·]*$", re.IGNORECASE
)

# A marginal note that opens a quotation begins with an opening mark and a word (`"Cess on
# rubber.`, `“Assessment`); one that closes it begins with a closing mark (`”; dan`, `".`) or ends
# with one (`and fine”;`, `...Registrar.".`).
_NOTE_OPENS_RE = re.compile(r"^(?:[“‘]|\"\s*\w)")
_NOTE_CLOSES_RE = re.compile(r"^(?:[”’]|\"\s*[;.,])")
_CLOSING_MARK_AT_END_RE = re.compile(r"[\"”’]\s*[;.,]?\s*$")

# A quoted word or phrase that wrapped onto the next line: the opening mark sits on one of the
# line's last three words (`...memotong perkataan ‘dan`), and the next line begins with a mark and
# closes it within its first words (`“undang-undang sekuriti” ’;`).
_DANGLING_OPEN_RE = re.compile(r"(?:^|\s)[‘“\"]\S+(?:\s+\S+){0,2}$")
_DANGLING_CLOSE_RE = re.compile(r"^[‘“\"].{0,60}?[’”\"]\s*[’”\"]?[;.,:)]")

# A provision number within the first words of a line, behind a spliced marginal note.
_LEADING_NUMBER_RE = re.compile(r"^(?:\S+\s+){1,3}\d{1,4}[A-Za-z]{0,2}\.\s+\S")

# How many words a colon-ended line has to carry before the numbered line after it is read as the
# text it introduces. `...dengan menggantikan seksyen 19 dengan seksyen yang berikut:` is a
# clause's own sentence; `the following section:` alone is a fragment the reading set out of order.
_INTRODUCTION_MIN_WORDS = 5

# How many words a wrapped line has to carry before a provision number after it is read as the
# sentence continuing rather than a clause. A marginal note printed as plain text is a few words
# and does not end a sentence either, and the clause beneath it must still open.
_CONTINUATION_MIN_WORDS = 6

# What the first container of a type is numbered when none is open: `BAHAGIAN I`, `Bab 1`.
_FIRST_CONTAINER_NUMBERS = frozenset({"I", "1"})


def _schedule_item_holder(parent: Node, num: str) -> Node:
    """The node a schedule's next numbered item belongs under: the schedule, or one of its lists.

    A schedule numbers its items once — except where it does not: a worked `Illustration` numbers
    its steps 1, 2, 3 beneath paragraph 5, and a table of rates numbers its rows from 1 again.
    A second `1.` under a schedule that already holds a `1.` is the ADR-043 case exactly — one of
    several numbered lists under one parent — and is held the same way: the items already there
    become `list_1`, the new item opens `list_2`, and each list numbers its own items.
    """
    items = [child for child in parent.children if child.node_type == "paragraph"]
    groups = [child for child in parent.children if child.node_type == "list"]
    digits = re.match(r"\d+", num)
    restarts = bool(items or groups) and (
        any(child.num == num for child in items)
        or (digits is not None and int(digits.group()) == 1)
    )
    if groups:
        last = groups[-1]
        if not restarts and not any(child.num == num for child in last.children):
            return last
        ordinal = str(len(parent.children) + 1)
        group = Node("list", ordinal, None, _eid_of(parent, "list", ordinal))
        parent.children.append(group)
        return group
    if not restarts:
        return parent
    first = Node("list", "1", None, _eid_of(parent, "list", "1"))
    first.children = parent.children
    parent.children = [first]
    group = Node("list", "2", None, _eid_of(parent, "list", "2"))
    parent.children.append(group)
    return group


def _is_schedule_note(text: str, lines: list[str], index: int, last_clause: int | None) -> bool:
    """Whether a schedule-shaped heading is a clause's marginal note rather than a schedule."""
    if text.rstrip().endswith(("—", "–", ":")):
        # `Jadual Pertama—`: a sentence that wrapped onto the heading word, still introducing
        # what follows. A full stop alone does not decide it — `Jadual.` after a closed sentence
        # is a heading the reading gave a stop — so that case is settled by the line beneath.
        return True
    if last_clause is None:
        return False
    following = next((line for line in lines[index + 1 :] if line), None)
    return following is not None and _resumes_clause_sequence(following, last_clause)


def _successor_num(num: str | None) -> str | None:
    """`II` after `I`, `3` after `2`, `IIA`'s successor unknown: the next container's number."""
    if not num:
        return None
    if is_roman(num):
        return to_roman(roman_value(num) + 1).upper()
    if num.isdigit():
        return str(int(num) + 1)
    return None


def _expand_glued_openers(
    raw_lines: list[str],
    lines: list[str],
    depths: list[tuple[float, int] | None] | None,
) -> tuple[list[str], list[str], list[tuple[float, int] | None] | None]:
    """Split a line carrying a glued subsection or paragraph opener into one line per opening.

    The reading joins two blocks into one line when their baselines meet (`...oleh Majlis. (2)
    Mesyuarat agung luar biasa...`), and a `(2)` mid-line is invisible to every rule that reads a
    line's first token. Each piece keeps its line's geometry and heading status, so nothing after
    this sees the join. Headings are left whole: a heading is not two provisions.
    """
    out_raw: list[str] = []
    out_lines: list[str] = []
    out_depths: list[tuple[float, int] | None] = []
    for index, (raw_line, text) in enumerate(zip(raw_lines, lines, strict=True)):
        pieces = (
            _split_glued_openers(text) if text and not raw_line.lstrip().startswith("#") else [text]
        )
        if len(pieces) == 1:
            out_raw.append(raw_line)
            out_lines.append(text)
        else:
            out_raw.extend(pieces)
            out_lines.extend(pieces)
        if depths is not None:
            out_depths.extend([depths[index]] * len(pieces))
    return out_raw, out_lines, (out_depths if depths is not None else None)


# `BAHAGIAN`, `Part`, `Jadual` alone on a line: a heading whose number wrapped onto the next —
# and that next line has to be the number alone, `II` or `Kedua.`, never `27. Pindaan seksyen`,
# or the join reads the clause after a stray `Bahagian` as Part 27 (measured: three readings).
_HEADING_WORD_ALONE_RE = re.compile(
    r"(?i)bahagian|part|bab|chapter|article|perkara|jadual|schedule"
)


def _clause_floors(
    lines: list[str], depths: list[tuple[float, int] | None], start: int
) -> dict[int, float]:
    """The shallowest provision-numbered line on each page: where that page's clauses hang.

    Per page, because the reading measures indent from the page's own text column and the
    columns of a bound book's recto and verso differ; and the shallowest, because a bill's clause
    number hangs at or left of the column while a section quoted inside the clause is block-
    indented from it. A page carrying only quoted sections gives their depth as its floor, and
    they then read as they do without geometry — by the bill's own numbering.
    """
    floors: dict[int, float] = {}
    for index in range(start, len(lines)):
        placed = depths[index] if index < len(depths) else None
        if placed is None or not lines[index] or provision_number(lines[index]) is None:
            continue
        depth, page = placed
        if depth < -_HANGING_REACH:
            # Far into the margin: a numbered stray — a note, a table cell, a page number the
            # reader kept — not where a clause hangs. Measured: one such line at -113pt set a
            # page's floor so low that every clause on it read as quoted.
            continue
        floors[page] = min(depth, floors.get(page, depth))
    return floors


# How far left of the text column a clause number can hang. A hanging number sits within an em or
# two of the column; the corpus's widest measured hang is 25pt.
_HANGING_REACH = 40.0


def _depths_for_lines(
    markdown_text: str, blocks: Sequence[Mapping[str, Any]] | None
) -> list[tuple[float, int] | None] | None:
    """Each markdown line's `(block indent, page)`, or None when the geometry does not fit the text.

    The reading writes one block per paragraph and separates blocks with a blank line, so the
    geometry lines up with `markdown_text.split("\n\n")`; a block that has been edited to span
    lines still maps every one of its lines to the block's record. Geometry that does not fit is
    dropped whole rather than applied approximately.
    """
    if blocks is None:
        return None
    parts = markdown_text.split("\n\n")
    if len(parts) != len(blocks):
        return None
    depths: list[tuple[float, int] | None] = []
    for position, (part, block) in enumerate(zip(parts, blocks, strict=True)):
        indent, page = block.get("indent"), block.get("page")
        value = (
            (float(indent), int(page))
            if isinstance(indent, (int, float)) and isinstance(page, int)
            else None
        )
        depths.extend([value] * (len(part.splitlines()) or 1))
        if position < len(parts) - 1:
            depths.append(None)
    if len(depths) != len(markdown_text.splitlines()):
        return None
    return depths


_HEADING_NUMBER_ALONE_RE = re.compile(
    r"(?i)(?:[IVXLCDM]+|\d+[A-Z]?|pertama|kedua|ketiga|keempat|kelima|keenam|ketujuh|kelapan|"
    r"kesembilan|kesepuluh)\.?"
)

# The reader files a heading's number as a marginal note when the two share a baseline and the
# number is short: `## CHAPTER` then `<!-- marginal: II -->`. The comment is furniture to every
# other rule, but here it is the number the heading is missing.
_MARGINAL_COMMENT_RE = re.compile(r"^<!--\s*marginal:\s*(?P<text>.*?)\s*-->$")


def _heading_number_line(raw_lines: list[str], lines: list[str], index: int | None) -> str | None:
    """The bare number a heading word's next line carries, from text or a marginal comment."""
    if index is None:
        return None
    comment = _MARGINAL_COMMENT_RE.match(raw_lines[index].strip())
    candidate = comment.group("text") if comment else lines[index]
    return candidate if _HEADING_NUMBER_ALONE_RE.fullmatch(candidate) else None


# A line that closes its sentence. A colon or a dash does not: both introduce what follows —
# `Jadual Pertama Akta ibu adalah dipinda—` then `Jadual` / `Pertama.` — so the line after them
# is the same sentence still running.
_SENTENCE_END_RE = re.compile(r"[.;!?](?:[\"“”'’)\]]*)$")


def _ends_sentence(text: str) -> bool:
    return _SENTENCE_END_RE.search(text.strip()) is not None


def _introduces_what_follows(text: str) -> bool:
    """Whether a line ends on the dash that introduces a list — a complete thought, not a wrap.

    `...menghendaki makna yang lain—` is a clause's whole opening sentence; the numbered line after
    it is not that sentence continuing, whatever number it carries.
    """
    return text.rstrip().endswith(("—", "–", "-"))


def assign_eids(root: Node) -> None:
    """Assign every descendant's `eId` from its parent's, in place.

    The one piece of bookkeeping never delegated to an extractor, LLM or regex alike: an eId is
    an identifier, and guessing one from a model's output would repeat exactly the mistake
    HANDOFF 26.2 warns against for `wId` — a node's numbering must come from what it printed, not
    from anything invented on top of it. A node with no `num` (should not happen for a
    well-formed tree) falls back to its parent's eId rather than breaking the walk.
    """

    def walk(node: Node, parent_eid: str) -> None:
        for child in node.children:
            if child.num:
                piece = f"{EID_PREFIXES[child.node_type]}_{child.num}"
                child.eid = f"{parent_eid}__{piece}" if parent_eid else piece
            else:
                child.eid = parent_eid
            walk(child, child.eid)

    walk(root, "")


class StructureUnavailable(RuntimeError):
    """No reading is available for this document — which is not a failure of a reading.

    An extractor raises this to say "not yet", and `convert_to_akn` counts it apart from a genuine
    error: it writes no gate verdict and withdraws nothing. The distinction is load-bearing on the
    handoff path (ADR-037), where a corpus is answered incrementally: treating an unanswered packet
    as a failure stamped every one of them with a failed Gate P1 verdict for not having been read
    yet, and buried the real failures under a thousand non-events — which is how a report teaches
    an operator to stop reading it (ADR-017).
    """


class MarkdownStructureExtractor(Protocol):
    """What `convert_to_akn` needs from whatever reads a document's provision hierarchy.

    The identity attributes are part of the contract because the step has to record *what* read a
    document's structure, not merely that something did. Without them a prompt improvement or a
    model swap leaves every existing artifact looking current, and the corpus silently mixes
    readings from different producers with no way to tell which is which.
    """

    name: str
    model_id: str | None
    prompt_sha256: str | None

    def extract(
        self,
        markdown_text: str,
        *,
        unit: str,
        blocks: Sequence[Mapping[str, Any]] | None = None,
    ) -> Node: ...


class RegexMarkdownStructureExtractor:
    """Deterministic, offline, no LLM: wraps `parse_markdown_structure`.

    The default route in, and the only one that needs no model and no network. It reads the
    Arrangement/body split, the quotation marks around amended text, and the bill's own clause
    sequence, which is what carries just over half the corpus through Gate P1; the rest is where
    `graph.handoff` earns its place, and the gate is what tells the two apart. Its distinct `name`
    is what makes a regex-built artifact correctly read as stale once another extractor produces
    the same document, rather than being mistaken for an equivalent reading.
    """

    name = "regex"
    model_id: str | None = None
    prompt_sha256: str | None = None

    def extract(
        self,
        markdown_text: str,
        *,
        unit: str,
        blocks: Sequence[Mapping[str, Any]] | None = None,
    ) -> Node:
        return parse_markdown_structure(markdown_text, unit=unit, blocks=blocks)


def infer_language_and_unit(markdown_text: str) -> tuple[str | None, str]:
    """`(language, unit)` from the markdown's own Arrangement heading.

    The unit decides whether this is a `<bill>` of clauses or an `<act>` of sections (HANDOFF
    26.2); everything in this pipeline is a Parliament bill, so `clause` is the right default even
    with no Arrangement heading at all.

    The language is returned separately, and as `None` when the document declares nothing, because
    it is not a thing to default. It becomes a permanent component of the Expression IRI, so
    guessing it — the previous renderer hard-coded `msa` for every document — mints a permanent
    identifier asserting a fact nobody established. HANDOFF 26.7 blesses the Arrangement heading as
    the source for it and warns specifically against sniffing the language out of the document's
    URL or filename, which upstream spells inconsistently.
    """
    for raw_line in markdown_text.splitlines():
        text = strip_markdown_line(raw_line)
        if not text:
            continue
        classified = arrangement_heading(text)
        if classified is not None:
            return classified[0], classified[1]
    return None, "clause"


# The organisations an FRBR block may point at. AKN requires every `FRBRauthor` to reference a
# declared TLCOrganization, so the `references` block and these hrefs are one fact in two places.
