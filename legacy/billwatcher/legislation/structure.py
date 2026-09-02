"""The two provision trees Gate L1 compares (HANDOFF 26.3).

Every Malaysian Act and bill opens with an Arrangement of Sections — *Susunan Seksyen*, or
*Susunan Fasal* in a bill. It is a table of contents the drafter published, which makes it a
validation oracle the corpus supplies for free: parse it as its own artifact, parse the body
independently, and assert the two agree. A dropped page, a failed extraction, or a
mis-detected hierarchy shows up here, before any of it can propagate into an amendment
operation or a consolidated text.

Both parses produce the same `Node` shape so that comparing them is a comparison of data rather
than of two parsers' opinions.
"""

import re
from dataclasses import dataclass, field

from billwatcher.legislation.layout import Line
from billwatcher.legislation.vocabulary import (
    EID_PREFIXES,
    arrangement_heading,
    container_heading,
    parenthesised,
    provision_number,
    resolve_letter,
    schedule_heading,
)

# A marginal note sits on the provision's own baseline. Anything within this many points of it
# vertically is annotating that provision rather than the next one.
_MARGIN_BASELINE_TOLERANCE = 4.0


@dataclass(frozen=True, slots=True)
class Node:
    """One provision, in the tree of the document it was read from."""

    node_type: str
    num: str
    heading: str | None
    eid: str
    page: int
    children: tuple["Node", ...] = ()

    def walk(self) -> "list[Node]":
        """This node and every descendant, in document order."""
        found = [self]
        for child in self.children:
            found.extend(child.walk())
        return found


@dataclass(frozen=True, slots=True)
class Tree:
    """One parse of one document region."""

    source: str
    unit: str
    language: str | None
    nodes: tuple[Node, ...] = ()
    error: str | None = None

    def walk(self) -> list[Node]:
        found: list[Node] = []
        for node in self.nodes:
            found.extend(node.walk())
        return found


@dataclass
class _Builder:
    """Mutable scaffolding for one tree; converted to frozen `Node`s on completion."""

    node_type: str
    num: str
    heading: str | None
    page: int
    children: list["_Builder"] = field(default_factory=list)

    def freeze(self, prefix: str = "") -> Node:
        eid = f"{prefix}__{self._own_eid()}" if prefix else self._own_eid()
        return Node(
            node_type=self.node_type,
            num=self.num,
            heading=self.heading,
            eid=eid,
            page=self.page,
            children=tuple(child.freeze(eid) for child in self.children),
        )

    def _own_eid(self) -> str:
        return f"{EID_PREFIXES[self.node_type]}_{self.num}"


# Which node kinds may contain which. A subsection nests under a section, never under a Part
# directly; a paragraph nests under whichever of the two is open.
_DEPTH = {
    "part": 0,
    "chapter": 1,
    "schedule": 0,
    "section": 2,
    "clause": 2,
    "subsection": 3,
    "paragraph": 4,
    "subparagraph": 5,
}


def _sort_key(num: str) -> tuple[int, str]:
    """Order `5` before `5A` before `6`, which a string sort gets wrong."""
    match = re.match(r"^(\d+)([A-Z]*)$", num)
    if not match:
        return (0, num)
    return (int(match.group(1)), match.group(2))


def find_arrangement(lines: tuple[Line, ...]) -> tuple[int, str, str] | None:
    """Locate the Arrangement of Sections heading: `(line index, language, unit)`."""
    for index, line in enumerate(lines):
        if line.role not in {"heading", "provision", "body"}:
            continue
        found = arrangement_heading(line.text)
        if found:
            return index, found[0], found[1]
    return None


def split_regions(
    lines: tuple[Line, ...],
) -> tuple[tuple[Line, ...], tuple[Line, ...], str, str | None]:
    """Split a document into its arrangement region and its body.

    The body always restarts the provision numbering the arrangement just finished listing, so
    the first provision number that does not advance on the previous one is where the
    arrangement ends. That rule is deterministic and needs no page heuristics; a document with
    no arrangement heading yields an empty arrangement region and the whole document as body.
    """
    content = tuple(line for line in lines if line.is_content)
    found = find_arrangement(content)
    if found is None:
        return (), content, "section", None
    start, language, unit = found

    previous: tuple[int, str] | None = None
    for offset, line in enumerate(content[start + 1 :], start=start + 1):
        parsed = provision_number(line.text)
        if parsed is None or line.role not in {"provision", "body"}:
            continue
        key = _sort_key(parsed[0])
        if previous is not None and key <= previous:
            boundary = _open_body_at(content, offset)
            return content[start + 1 : boundary], content[boundary:], unit, language
        previous = key
    # Every provision number advanced, so no body was found after the arrangement. Publishing an
    # empty body is what Gate L1 is for: it is reported, never quietly treated as a match.
    return content[start + 1 :], (), unit, language


def _open_body_at(content: tuple[Line, ...], offset: int) -> int:
    """Move the arrangement/body boundary back over the headings that open the body.

    The enacting text starts on a fresh page beneath its own `BAHAGIAN I` heading, so those
    heading lines belong to the body even though they precede its first provision. A marginal
    note moves with them: it is typeset beside the body's first provision and annotates it. Only
    lines sharing a page with that provision are moved, so an arrangement's own trailing entries
    — a listed schedule, for instance — are on the page before and stay where they are.
    """
    page = content[offset].page
    boundary = offset
    while (
        boundary - 1 > 0
        and content[boundary - 1].role in {"heading", "marginal"}
        and content[boundary - 1].page == page
    ):
        boundary -= 1
    return boundary


def parse_arrangement(lines: tuple[Line, ...], *, unit: str, language: str | None) -> Tree:
    """Read the table of contents into a tree of containers and numbered provisions."""
    roots: list[_Builder] = []
    stack: list[_Builder] = []
    pending_container: _Builder | None = None

    def push(builder: _Builder) -> None:
        depth = _DEPTH[builder.node_type]
        while stack and _DEPTH[stack[-1].node_type] >= depth:
            stack.pop()
        if stack:
            stack[-1].children.append(builder)
        else:
            roots.append(builder)
        stack.append(builder)

    for line in lines:
        if line.role == "marginal":
            continue
        container = container_heading(line.text)
        if container is not None:
            node_type, num, heading = container
            pending_container = _Builder(node_type, num, heading or None, line.page)
            push(pending_container)
            continue
        schedule = schedule_heading(line.text)
        if schedule is not None:
            pending_container = _Builder("schedule", schedule, None, line.page)
            push(pending_container)
            continue
        parsed = provision_number(line.text)
        if parsed is not None:
            num, heading = parsed
            pending_container = None
            push(_Builder(unit, num, _clean_heading(heading), line.page))
            continue
        # A container heading set on its own line belongs to the container just opened.
        if pending_container is not None and pending_container.heading is None and line.text:
            pending_container.heading = _clean_heading(line.text)
            pending_container = None

    return Tree(
        source="arrangement",
        unit=unit,
        language=language,
        nodes=tuple(builder.freeze() for builder in roots),
    )


def parse_body(lines: tuple[Line, ...], *, unit: str, language: str | None) -> Tree:
    """Read the enacting text into the same tree shape as the arrangement.

    A section's heading is taken from its marginal note when it has one, because that is where
    a reprint prints it; otherwise from the text following the number, unless that text opens a
    subsection, in which case the section has no heading of its own.
    """
    roots: list[_Builder] = []
    stack: list[_Builder] = []
    pending_container: _Builder | None = None
    in_schedule = False
    margins = _marginal_index(lines)

    def push(builder: _Builder) -> None:
        depth = _DEPTH[builder.node_type]
        while stack and _DEPTH[stack[-1].node_type] >= depth:
            stack.pop()
        if stack:
            stack[-1].children.append(builder)
        else:
            roots.append(builder)
        stack.append(builder)

    for line in lines:
        if line.role == "marginal":
            continue
        container = container_heading(line.text)
        if container is not None:
            node_type, num, heading = container
            in_schedule = False
            pending_container = _Builder(node_type, num, heading or None, line.page)
            push(pending_container)
            continue
        schedule = schedule_heading(line.text)
        if schedule is not None:
            # A schedule restarts numbering, so what follows is paragraphs of the schedule and
            # never a second section 1. Not modelling this is how a schedule corrupts a body tree.
            #
            # Known limit: schedules are terminal in Malaysian drafting, so this state is left
            # set until a Part or Chapter heading clears it. A section printed *after* a schedule
            # would be absorbed as a schedule paragraph. That is not silently wrong — the section
            # then goes missing from the body tree, so Gate L1 reports `missing_in_body` and the
            # reading is never promoted. A test pins that behaviour.
            in_schedule = True
            pending_container = _Builder("schedule", schedule, None, line.page)
            push(pending_container)
            continue

        parsed = provision_number(line.text)
        if parsed is not None and line.role == "provision":
            num, rest = parsed
            pending_container = None
            if in_schedule:
                # A schedule numbers its own items as paragraphs beneath it. They are not a
                # second section 1, and reading them as sections would renumber the whole Act.
                push(_Builder("paragraph", num, None, line.page))
                continue
            # A section's heading is its marginal note where it has one, because that is
            # where a reprint prints it; otherwise the text after the number, unless that text
            # opens a subsection, in which case the section has no heading of its own.
            note = margins.get((line.page, round(line.y)))
            if note is None and rest and parenthesised(rest) is None:
                note = rest
            push(_Builder(unit, num, _clean_heading(note) if note else None, line.page))
            continue

        inline = parenthesised(line.text)
        if inline is not None and stack:
            kind, num, _ = inline
            if kind == "subsection":
                # A schedule has no subsections; its `(1)` is a paragraph of the schedule.
                node_type = "paragraph" if in_schedule else "subsection"
            else:
                previous, previous_type = _open_list(stack)
                node_type = resolve_letter(num, previous=previous, previous_type=previous_type)
                num = num.casefold()
            pending_container = None
            push(_Builder(node_type, num, None, line.page))
            continue

        if pending_container is not None and pending_container.heading is None and line.text:
            pending_container.heading = _clean_heading(line.text)
            pending_container = None

    return Tree(
        source="body",
        unit=unit,
        language=language,
        nodes=tuple(builder.freeze() for builder in roots),
    )


def _open_list(stack: list[_Builder]) -> tuple[str | None, str | None]:
    """The last sibling of the innermost open paragraph or subparagraph list, and its kind.

    `resolve_letter` needs to know what a token could be continuing. The innermost such node on
    the stack *is* that list's most recent member, because a new sibling replaces it.
    """
    for builder in reversed(stack):
        if builder.node_type in {"paragraph", "subparagraph"}:
            return builder.num, builder.node_type
    return None, None


def _marginal_index(lines: tuple[Line, ...]) -> dict[tuple[int, int], str]:
    """Marginal notes keyed by the baseline they annotate, within a small tolerance."""
    index: dict[tuple[int, int], str] = {}
    for line in lines:
        if line.role != "marginal":
            continue
        for offset in range(
            -int(_MARGIN_BASELINE_TOLERANCE), int(_MARGIN_BASELINE_TOLERANCE) + 1
        ):
            index.setdefault((line.page, round(line.y) + offset), line.text)
    return index


_TRAILING = re.compile(r"[\s.;:,—–-]+$")


def _clean_heading(value: str) -> str | None:
    """Normalise a heading for comparison and display: no dot leaders, no trailing punctuation."""
    text = re.sub(r"[.…]{2,}\s*\d*\s*$", "", " ".join(value.split()))
    text = _TRAILING.sub("", text)
    return text or None
