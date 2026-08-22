"""Gate L1: the Arrangement of Sections must match the extracted body tree (HANDOFF 26.3).

This is the highest-value check Stage 1 has, and the corpus supplies its answer key for free.
A dropped page, a failed extraction, or a mis-detected hierarchy shows up as a difference
between two independently parsed trees, before it can propagate into an amendment operation or
a consolidated statement of law.

The gate is blocking on *structure* — which provisions exist, and in what order. It reports
heading differences without blocking on them, because a section's heading is printed as a
marginal note in some reprints and inline in others, so a heading difference is very often a
typographic fact about the source rather than a defect in the parse. That narrowing is
deliberate and recorded in ADR-017; widening it later needs only this constant to change.
"""

from dataclasses import dataclass, field

from billwatcher.legislation.layout import Line
from billwatcher.legislation.structure import Node, Tree

# The node kinds an Arrangement of Sections actually lists. Comparing deeper than this would
# fail every document: no arrangement enumerates subsections.
COMPARED_TYPES = frozenset({"part", "chapter", "schedule", "section", "clause"})

# Difference kinds that fail the gate. A heading difference is reported, not fatal.
BLOCKING_DIFFERENCES = frozenset(
    {"missing_in_body", "missing_in_arrangement", "order", "duplicate_eid"}
)

# `no_text` is raised by the persistence layer for a document the extractor found no text in
# at all — a scan. It is a gate outcome even though the comparator never runs.
STATUSES = frozenset(
    {"passed", "mismatch", "no_arrangement", "empty_body", "failed", "no_text"}
)


@dataclass(frozen=True, slots=True)
class Difference:
    kind: str
    eid: str
    arrangement: str | None = None
    body: str | None = None

    @property
    def is_blocking(self) -> bool:
        return self.kind in BLOCKING_DIFFERENCES


@dataclass(frozen=True, slots=True)
class GateResult:
    """The outcome of one Gate L1 evaluation, in a shape that can be stored and shown."""

    status: str
    unit: str
    language: str | None
    arrangement_count: int
    body_count: int
    differences: tuple[Difference, ...] = ()
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def blocking(self) -> tuple[Difference, ...]:
        return tuple(item for item in self.differences if item.is_blocking)

    def as_detail(self) -> dict[str, object]:
        """A JSON-serialisable record for an anomaly's `detail_json` or a status page."""
        return {
            "status": self.status,
            "unit": self.unit,
            "language": self.language,
            "arrangement_count": self.arrangement_count,
            "body_count": self.body_count,
            "blocking_count": len(self.blocking),
            "differences": [
                {
                    "kind": item.kind,
                    "eid": item.eid,
                    "arrangement": item.arrangement,
                    "body": item.body,
                }
                # Bounded: an unparseable document must not write an unbounded row.
                for item in self.differences[:50]
            ],
            "truncated": len(self.differences) > 50,
            "error": self.error,
        }


@dataclass
class _Side:
    order: list[str] = field(default_factory=list)
    headings: dict[str, str | None] = field(default_factory=dict)


def _compared(tree: Tree) -> _Side:
    side = _Side()
    for node in tree.walk():
        if node.node_type not in COMPARED_TYPES:
            continue
        side.order.append(node.eid)
        side.headings[node.eid] = node.heading
    return side


def evaluate(arrangement: Tree, body: Tree) -> GateResult:
    """Compare the two trees and decide whether the extraction may be trusted."""
    left, right = _compared(arrangement), _compared(body)
    if not left.order:
        return GateResult(
            status="no_arrangement",
            unit=arrangement.unit,
            language=arrangement.language,
            arrangement_count=0,
            body_count=len(right.order),
        )
    if not right.order:
        return GateResult(
            status="empty_body",
            unit=arrangement.unit,
            language=arrangement.language,
            arrangement_count=len(left.order),
            body_count=0,
        )

    differences: list[Difference] = []

    # A repeated eId makes the tree ambiguous: every later reference to it — a citation, an
    # `amends` target, a consolidation anchor — would have two possible referents. It also has to
    # be caught *here* rather than at write time, because the set comparison below collapses
    # duplicates and would otherwise report a document with two section 1s as passing.
    for side, name in ((left, "arrangement"), (right, "body")):
        for eid in _repeated(side.order):
            differences.append(
                Difference("duplicate_eid", eid, **{name: str(side.order.count(eid))})
            )

    left_set, right_set = set(left.order), set(right.order)
    for eid in left.order:
        if eid not in right_set:
            differences.append(
                Difference("missing_in_body", eid, arrangement=left.headings.get(eid))
            )
    for eid in right.order:
        if eid not in left_set:
            differences.append(
                Difference("missing_in_arrangement", eid, body=right.headings.get(eid))
            )

    # Order is compared over the provisions both sides agree exist, so one missing section is
    # reported once as missing rather than again as every following provision being out of order.
    shared = left_set & right_set
    left_shared = [eid for eid in left.order if eid in shared]
    right_shared = [eid for eid in right.order if eid in shared]
    if left_shared != right_shared:
        for position, (expected, found) in enumerate(zip(left_shared, right_shared, strict=False)):
            if expected != found:
                differences.append(
                    Difference("order", expected, arrangement=str(position), body=found)
                )
                break

    for eid in left_shared:
        listed = left.headings.get(eid)
        printed = right.headings.get(eid)
        if listed is None or printed is None:
            continue
        if _comparable(listed) != _comparable(printed):
            differences.append(Difference("heading", eid, arrangement=listed, body=printed))

    blocking = [item for item in differences if item.is_blocking]
    return GateResult(
        status="mismatch" if blocking else "passed",
        unit=arrangement.unit,
        language=arrangement.language,
        arrangement_count=len(left.order),
        body_count=len(right.order),
        differences=tuple(differences),
    )


def _repeated(order: list[str]) -> list[str]:
    """Every eId appearing more than once, in first-appearance order."""
    seen: set[str] = set()
    repeated: list[str] = []
    for eid in order:
        if eid in seen and eid not in repeated:
            repeated.append(eid)
        seen.add(eid)
    return repeated


def _comparable(heading: str) -> str:
    """Headings differ in case and punctuation between the contents page and the body."""
    return "".join(character for character in heading.casefold() if character.isalnum())


def evaluate_document(lines: tuple[Line, ...]) -> GateResult:
    """Run the whole of Stage 1's structural check over one document's classified lines."""
    from billwatcher.legislation.structure import parse_arrangement, parse_body, split_regions

    arrangement_lines, body_lines, unit, language = split_regions(lines)
    if not arrangement_lines:
        return GateResult(
            status="no_arrangement",
            unit=unit,
            language=language,
            arrangement_count=0,
            body_count=0,
        )
    arrangement = parse_arrangement(arrangement_lines, unit=unit, language=language)
    body = parse_body(body_lines, unit=unit, language=language)
    return evaluate(arrangement, body)


def node_rows(tree: Tree) -> list[Node]:
    """Every node of a tree in document order, ready to be persisted."""
    return tree.walk()
