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
    opens_quotation,
    parenthesised,
    provision_number,
    quotation_marks,
    resolve_letter,
    schedule_heading,
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


def parse_markdown_structure(markdown_text: str, *, unit: str = "clause") -> Node:
    """Build the provision tree from markdown text.

    `unit` is `"clause"` for a bill or `"section"` for an Act (HANDOFF 26.2) — every document in
    this pipeline is a Parliament bill PDF, so the default is `"clause"`; `infer_unit` overrides
    it when the markdown's own Arrangement heading says otherwise.
    """
    root = Node(node_type="body", num=None, heading=None, eid="")
    containers: list[Node] = []  # open part/chapter/schedule ancestors, root-most first
    provision: Node | None = None
    open_subsection: Node | None = None
    open_paragraph: Node | None = None
    last_letter: tuple[str, str] | None = None
    in_schedule = False
    in_quotation = False
    last_clause: int | None = None

    def eid_of(parent: Node, node_type: str, token: str) -> str:
        piece = f"{EID_PREFIXES[node_type]}_{token}"
        return f"{parent.eid}__{piece}" if parent.eid else piece

    def reset_provision_state() -> None:
        nonlocal provision, open_subsection, open_paragraph, last_letter
        provision, open_subsection, open_paragraph, last_letter = None, None, None, None

    def innermost_open() -> Node:
        if open_paragraph is not None:
            return open_paragraph
        if open_subsection is not None:
            return open_subsection
        if provision is not None:
            return provision
        if containers:
            return containers[-1]
        return root

    lines = [strip_markdown_line(raw_line) for raw_line in markdown_text.splitlines()]
    for index in range(body_start(lines), len(lines)):
        text = lines[index]
        if not text:
            continue
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
        # A span opens only on a line that begins with a mark and carries an odd number of them, so
        # a defined term (`"revised law" means...`, balanced) is left alone; it shuts on the next
        # odd-marked line, or on the bill's next clause, whichever comes first.
        odd_marks = quotation_marks(text) % 2 == 1
        if in_quotation:
            if not _resumes_clause_sequence(text, last_clause):
                innermost_open().paragraphs.append(text)
                if odd_marks:
                    in_quotation = False
                continue
            in_quotation = False
        elif odd_marks and opens_quotation(text):
            in_quotation = True
            innermost_open().paragraphs.append(text)
            continue

        container = container_heading(text)
        if container is not None:
            node_type, num, heading = container
            if node_type == "part":
                parent, containers = root, []
            elif containers and containers[0].node_type == "part":
                parent, containers = containers[0], containers[:1]
            else:
                parent, containers = root, []
            node = Node(node_type, num, heading or None, eid_of(parent, node_type, num))
            parent.children.append(node)
            containers.append(node)
            reset_provision_state()
            in_schedule = False
            continue

        schedule_num = schedule_heading(text)
        if schedule_num is not None:
            node = Node("schedule", schedule_num, None, eid_of(root, "schedule", schedule_num))
            root.children.append(node)
            containers = [node]
            reset_provision_state()
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
                continue
            parent = containers[-1] if containers else root
            note, leading = split_marginal_note(rest)
            node = Node(node_type, num, note, eid_of(parent, node_type, num))
            parent.children.append(node)
            provision, open_subsection, open_paragraph, last_letter = node, None, None, None
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
                    child = Node("subsection", token, None, eid_of(node, "subsection", token))
                    if remainder:
                        child.paragraphs.append(remainder)
                    node.children.append(child)
                    open_subsection = child
                else:
                    node.paragraphs.append(leading)
            continue

        parenthesised_match = parenthesised(text) if provision is not None else None
        if parenthesised_match is not None:
            assert provision is not None  # guarded above; narrows for the parent lookups below
            kind, token, rest = parenthesised_match
            if kind == "subsection":
                node = Node("subsection", token, None, eid_of(provision, "subsection", token))
                provision.children.append(node)
                open_subsection, open_paragraph, last_letter = node, None, None
            else:
                resolved = resolve_letter(
                    token,
                    previous=last_letter[0] if last_letter else None,
                    previous_type=last_letter[1] if last_letter else None,
                )
                if resolved == "paragraph":
                    parent = open_subsection or provision
                    node = Node("paragraph", token, None, eid_of(parent, "paragraph", token))
                    parent.children.append(node)
                    open_paragraph = node
                else:
                    parent = open_paragraph or open_subsection or provision
                    node = Node("subparagraph", token, None, eid_of(parent, "subparagraph", token))
                    parent.children.append(node)
                last_letter = (token, resolved)
            if rest:
                node.paragraphs.append(rest)
            continue

        innermost_open().paragraphs.append(text)

    return root


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
