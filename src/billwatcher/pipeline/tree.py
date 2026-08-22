"""The provision tree and the markdown reading primitives shared across step 4 and its gate.

These live below both `pipeline.akn` (which builds and renders a tree) and `pipeline.fidelity`
(which judges one against its source), because the gate has to measure coverage against exactly
the text the extractor was shown — the same `strip_markdown_line` filtering, not an approximation
of it. Putting the shared pair here keeps that guarantee without either module importing the other.
"""

from dataclasses import dataclass, field

_BULLET_MARKERS = ("- ", "* ")


@dataclass
class Node:
    """One structural node in the tree step 4 builds and renders.

    Deliberately lighter than `billwatcher.legislation.structure.Node`: no `page`, because
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
