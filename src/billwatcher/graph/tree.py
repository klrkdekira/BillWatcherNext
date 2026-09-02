"""The provision tree and the markdown reading primitives shared across step 4 and its gate.

These live below both `pipeline.akn` (which builds and renders a tree) and `pipeline.fidelity`
(which judges one against its source), because the gate has to measure coverage against exactly
the text the extractor was shown — the same `strip_markdown_line` filtering, not an approximation
of it. Putting the shared pair here keeps that guarantee without either module importing the other.
"""

from dataclasses import dataclass, field

from billwatcher.graph.vocabulary import arrangement_heading, body_opening

_BULLET_MARKERS = ("- ", "* ")


@dataclass
class Node:
    """One structural node in the tree step 4 builds and renders.

    Deliberately lighter than the structural node of the Postgres-backed reader (now `legacy/`):
    no `page`, because
    markdown carries no reliable page signal in general, and no frozen/tuple children, because
    this tree is built incrementally while scanning lines top to bottom.
    """

    node_type: str
    num: str | None
    heading: str | None
    eid: str
    paragraphs: list[str] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)


def strip_markdown_line(line: str) -> str:
    """Plain text from one markdown line, or "" if the line carries no content of its own."""
    text = line.strip()
    if not text:
        return ""
    if text.startswith("<!--") and text.endswith("-->"):
        # A page-boundary comment (HANDOFF 27.7's `<!-- page N -->` convention), or similar.
        return ""
    if text == "$$":
        return ""  # a display-math fence line; the equation body between fences is kept as-is
    if text.lstrip("#").startswith(" ") or set(text) == {"#"}:
        text = text.lstrip("#").strip()
    for marker in _BULLET_MARKERS:
        if text.startswith(marker):
            text = text[len(marker) :].strip()
            break
    return text


def body_start(lines: list[str]) -> int:
    """The index in `lines` where the bill's own text begins, past any Arrangement of Clauses.

    Shared by the parser and by Gate P1's coverage view, and it has to be, for the reason this
    module exists: the gate measures a tree against the text the extractor was shown, so the two
    must cut the document in the same place. When they disagreed, skipping the Arrangement in the
    parser alone made 81 faithful readings look as though they had lost the text the gate was
    still counting.

    A bill that prints an Arrangement prints its clause list twice — once as a contents page and
    once as the bill. Reading both is the largest single reason Gate P1 rejects a reading: every
    clause earns a duplicate eId, and the sequence runs backwards where the contents end and the
    body restarts at 1. The Arrangement has no closing heading of its own, so what bounds it is
    the bill's formal opening (`vocabulary.body_opening`).

    `lines` are already stripped by `strip_markdown_line`; empty entries are skipped, so a caller
    may pass the full line list or only the non-empty ones and get an index into what it passed.

    Returns 0 — read the whole document — both when there is no Arrangement and when there is one
    that nothing closes. The second case is the one worth stating: truncating a bill because a
    marker is missing would turn a merely duplicated reading into no reading at all, and a
    duplicate is at least reviewable.
    """
    arrangement = next(
        (i for i, text in enumerate(lines) if text and arrangement_heading(text) is not None),
        None,
    )
    if arrangement is None:
        return 0
    for index in range(arrangement + 1, len(lines)):
        if lines[index] and body_opening(lines[index]):
            return index
    return 0
