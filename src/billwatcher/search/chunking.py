"""Section- and page-aware chunking for semantic retrieval (HANDOFF 12.3).

Chunks are built from the page-delimited text an extraction produced, so every chunk can name
the pages it came from and a citation resolves to specific stored bytes.
"""

import hashlib
import re
from dataclasses import dataclass

from billwatcher.version import CHUNKER_VERSION

# Roughly four characters per model token for mixed Malay and English legal prose. The handoff
# asks for 500-800 token chunks with 10-15% overlap.
CHARS_PER_TOKEN = 4
TARGET_TOKENS = 650
MAX_TOKENS = 800
OVERLAP_FRACTION = 0.12

_PAGE_MARKER = re.compile(r"^--- Page (\d+) ---$", re.MULTILINE)
# A numbered provision such as "12. Tafsiran" or "(3) Menteri boleh" starts a new logical block.
_PROVISION = re.compile(r"^\s*(?:\(\d+[A-Za-z]?\)|\d+[A-Za-z]?\.)\s+\S")


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_index: int
    content: str
    heading: str | None
    page_start: int | None
    page_end: int | None
    token_count: int
    content_sha256: str


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def split_pages(text: str) -> list[tuple[int | None, str]]:
    """Recover (page number, page text) pairs from an extraction's page-delimited output."""
    matches = list(_PAGE_MARKER.finditer(text))
    if not matches:
        return [(None, text.strip())] if text.strip() else []
    pages: list[tuple[int | None, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if body:
            pages.append((int(match.group(1)), body))
    return pages


def _blocks(page_text: str) -> list[str]:
    """Split a page into provision-aligned blocks so a numbered clause stays whole."""
    lines = page_text.splitlines() or [page_text]
    blocks: list[list[str]] = []
    for line in lines:
        if not blocks or _PROVISION.match(line):
            blocks.append([line])
        else:
            blocks[-1].append(line)
    return ["\n".join(block).strip() for block in blocks if "\n".join(block).strip()]


def _heading_of(content: str) -> str | None:
    first = content.strip().splitlines()[0].strip() if content.strip() else ""
    return first[:200] or None


def chunk_extraction(text: str) -> list[Chunk]:
    """Produce overlapping, provision-aware chunks that never exceed the maximum size."""
    max_chars = MAX_TOKENS * CHARS_PER_TOKEN
    target_chars = TARGET_TOKENS * CHARS_PER_TOKEN
    overlap_chars = int(target_chars * OVERLAP_FRACTION)

    chunks: list[Chunk] = []
    buffer = ""
    buffer_pages: list[int] = []

    def emit() -> None:
        """Close the current chunk and carry a short tail forward as the overlap."""
        nonlocal buffer, buffer_pages
        content = buffer.strip()
        if not content:
            buffer, buffer_pages = "", []
            return
        chunks.append(
            Chunk(
                chunk_index=len(chunks),
                content=content,
                heading=_heading_of(content),
                page_start=min(buffer_pages) if buffer_pages else None,
                page_end=max(buffer_pages) if buffer_pages else None,
                token_count=estimate_tokens(content),
                content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            )
        )
        buffer = content[-overlap_chars:].lstrip() if overlap_chars else ""
        buffer_pages = buffer_pages[-1:] if buffer_pages else []

    # Splitting at the target rather than the maximum leaves room for the carried overlap, so
    # no emitted chunk can exceed MAX_TOKENS.
    for page_number, page_text in split_pages(text):
        for block in _blocks(page_text):
            for piece in _hard_split(block, target_chars):
                candidate = f"{buffer}\n\n{piece}" if buffer else piece
                if len(candidate) > target_chars and len(buffer.strip()) > overlap_chars:
                    emit()
                    candidate = f"{buffer}\n\n{piece}" if buffer else piece
                buffer = candidate
                if page_number is not None and page_number not in buffer_pages:
                    buffer_pages.append(page_number)
                if len(buffer) >= max_chars:
                    emit()
    if buffer.strip() and (not chunks or chunks[-1].content != buffer.strip()):
        emit()
    return chunks


def _hard_split(block: str, max_chars: int) -> list[str]:
    """A single provision longer than the maximum is split on whitespace, never mid-word."""
    if len(block) <= max_chars:
        return [block]
    pieces: list[str] = []
    remaining = block
    while len(remaining) > max_chars:
        cut = remaining.rfind(" ", 0, max_chars)
        if cut < max_chars // 2:
            cut = max_chars
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def chunker_version() -> str:
    return CHUNKER_VERSION
