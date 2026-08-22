"""Assemble MinerU `ContentBlock` lists into markdown.

MinerU's own two-stage layout analysis already determines reading order (HANDOFF 27.7); this
module trusts the order the model returns rather than re-deriving one from bounding boxes, which
is exactly the kind of naive assumption that goes wrong on multi-column legislative typesetting.
"""

from collections.abc import Sequence
from typing import Any, Protocol

# Running heads, footers, and page furniture contribute nothing to the body, mirroring Stage L1's
# own treatment of the same signal in `billwatcher.legislation.layout` (HANDOFF 26.1).
_FURNITURE_TYPES = frozenset({"header", "footer", "page_number", "page_footnote"})
_MATH_TYPES = frozenset({"equation", "equation_block"})
_HEADING_LEVELS = {"doc_title": 1, "title": 2, "paragraph_title": 3}


class _BlockLike(Protocol):
    """The subset of `mineru_vl_utils.structs.ContentBlock` this module depends on."""

    type: str
    content: str | None

    def get(self, key: str, default: Any = None) -> Any: ...


def block_to_markdown(block: _BlockLike) -> str | None:
    """One block's markdown fragment, or `None` if it contributes nothing to the body."""
    if block.type in _FURNITURE_TYPES:
        return None
    content = block.content
    if content is None or not content.strip():
        return None
    text = content.strip()
    if block.type in _MATH_TYPES:
        return f"$$\n{text}\n$$"
    if block.type == "table":
        return text  # already HTML, per the model's own output contract
    if block.type in _HEADING_LEVELS:
        return f"{'#' * _HEADING_LEVELS[block.type]} {text}"
    if block.type == "list_item":
        return f"- {text}"
    return text


def page_to_markdown(blocks: Sequence[_BlockLike]) -> str:
    """One page's blocks joined into markdown, honouring the model's `merge_prev` continuations."""
    parts: list[str] = []
    for block in blocks:
        fragment = block_to_markdown(block)
        if fragment is None:
            continue
        if block.type == "text" and block.get("merge_prev", False) and parts:
            parts[-1] = f"{parts[-1]} {fragment}"
        else:
            parts.append(fragment)
    return "\n\n".join(parts)


def pages_to_markdown(pages: Sequence[Sequence[_BlockLike]]) -> str:
    """Join per-page markdown behind an HTML page-boundary comment.

    Mirrors `parse_document.extract_pdf`'s `--- Page N ---` convention so both readings cite
    pages the same way, without the marker being mistaken for document content.
    """
    rendered: list[str] = []
    for number, blocks in enumerate(pages, start=1):
        body = page_to_markdown(blocks)
        marker = f"<!-- page {number} -->"
        rendered.append(f"{marker}\n\n{body}" if body else marker)
    return "\n\n".join(rendered)
