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
from typing import Protocol

from billwatcher.graph.tree import Node, body_start, strip_markdown_line
from billwatcher.graph.vocabulary import (
    EID_PREFIXES,
    arrangement_heading,
    back_matter_heading,
    container_heading,
    continues_run,
    ends_in_reference,
    is_doubled_letter,
    is_roman,
    is_sentence_tail,
    opens_quotation,
    parenthesised,
    provision_number,
    quotation_marks,
    roman_value,
    schedule_heading,
)
from billwatcher.graph.vocabulary import (
    QUOTE_CHARS as _QUOTE_CHARS,
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
            if continues_run(sibling.num or "", token, sibling.node_type):
                parent = self.nodes[depth - 1] if depth else self.provision
                return self._attach(parent, sibling.node_type, token, depth=depth)
        # Nothing continued: a new list opens. Capitals and a leading roman `i` nest one level
        # beneath whatever lettered list is open; a lower-case letter starts the paragraph list
        # under the subsection or the provision itself.
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
        """Create the node under `parent` at stack `depth`, or flatten `parent` on a restart."""
        if id(parent) in self._prose_only:
            self.nodes = self.nodes[:depth]
            return None
        if any(child.node_type == node_type and child.num == token for child in parent.children):
            for child in parent.children:
                parent.paragraphs.extend(_lines_of(child))
            parent.children = []
            self._prose_only.add(id(parent))
            self.nodes = self.nodes[:depth]
            return None
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
_REFERENCE_TAIL_RE = re.compile(r"^(?:,|(?:dan|and|atau|or|hingga|to)\s+\()")

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
    if not note or note[0].islower() or len(note) > MAX_MARGINAL_NOTE_CHARS:
        return None
    if note.endswith(".") and len(note.split()) > _SPLICED_NOTE_WITH_STOP_MAX_WORDS:
        return None
    return note, match.group("num").upper(), match.group("rest").strip()


def parse_markdown_structure(markdown_text: str, *, unit: str = "clause") -> Node:
    """Build the provision tree from markdown text.

    `unit` is `"clause"` for a bill or `"section"` for an Act (HANDOFF 26.2) — every document in
    this pipeline is a Parliament bill PDF, so the default is `"clause"`; `infer_unit` overrides
    it when the markdown's own Arrangement heading says otherwise.
    """
    root = Node(node_type="body", num=None, heading=None, eid="")
    containers: list[Node] = []  # open part/chapter/schedule ancestors, root-most first
    provision: Node | None = None
    lists: _OpenLists | None = None
    in_schedule = False
    in_quotation = False
    last_clause: int | None = None
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

    def open_provision(node_type: str, num: str, note: str | None, leading: str) -> None:
        nonlocal provision, lists, last_clause
        parent = containers[-1] if containers else root
        node = Node(node_type, num, note, _eid_of(parent, node_type, num))
        parent.children.append(node)
        provision, lists = node, _OpenLists(node)
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
    for index in range(body_start(lines), len(lines)):
        text = lines[index]
        if not text:
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
        introduces = odd_marks and opens_quotation(text) and text[0] not in _QUOTE_CHARS
        if in_quotation:
            if not _resumes_clause_sequence(text, last_clause):
                innermost_open().paragraphs.append(text)
                if odd_marks:
                    in_quotation = False
                continue
            in_quotation = False
        elif odd_marks and text[0] in _QUOTE_CHARS:
            in_quotation = True
            innermost_open().paragraphs.append(text)
            continue

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
            if in_schedule and containers and containers[0].node_type == "schedule":
                # A Part or Chapter *inside* a Schedule — a treaty's chapters, a Supply Bill's
                # parts — stays inside it. Leaving the schedule here re-rooted the Part in the body
                # and turned the schedule's numbered items back into clauses.
                schedule = containers[0]
                if node_type == "part" or len(containers) == 1:
                    parent, containers = schedule, [schedule]
                else:
                    parent, containers = containers[1], containers[:2]
            elif node_type == "part":
                parent, containers, in_schedule = root, [], False
            elif containers and containers[0].node_type == "part":
                parent, containers, in_schedule = containers[0], containers[:1], False
            else:
                parent, containers, in_schedule = root, [], False
            node = Node(node_type, num, heading or None, _eid_of(parent, node_type, num))
            parent.children.append(node)
            containers.append(node)
            provision, lists = None, None
            continue

        if schedule_num is not None:
            node = Node("schedule", schedule_num, None, _eid_of(root, "schedule", schedule_num))
            root.children.append(node)
            containers = [node]
            provision, lists = None, None
            in_schedule = True
            continue

        provision_match = provision_number(text)
        if provision_match is not None:
            num, rest = provision_match
            node_type = "paragraph" if in_schedule else unit
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

        parenthesised_match = parenthesised(text) if lists is not None else None
        if parenthesised_match is not None:
            assert lists is not None  # guarded above; narrows for the placement below
            kind, token, rest = parenthesised_match
            if _REFERENCE_TAIL_RE.match(rest) or (
                continues_sentence and ends_in_reference(previous)
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


# `BAHAGIAN`, `Part`, `Jadual` alone on a line: a heading whose number wrapped onto the next —
# and that next line has to be the number alone, `II` or `Kedua.`, never `27. Pindaan seksyen`,
# or the join reads the clause after a stray `Bahagian` as Part 27 (measured: three readings).
_HEADING_WORD_ALONE_RE = re.compile(r"(?i)bahagian|part|bab|chapter|jadual|schedule")
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

    def extract(self, markdown_text: str, *, unit: str) -> Node: ...


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

    def extract(self, markdown_text: str, *, unit: str) -> Node:
        return parse_markdown_structure(markdown_text, unit=unit)


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
