"""Turn stored PDF bytes into one markdown document via a hosted MinerU model.

Mirrors `billwatcher.scraper.parse_document.extract_pdf`'s shape and status vocabulary
(`succeeded`/`empty`/`failed`) so the two readings are easy to compare, while staying a fully
separate code path: nothing here writes to `document_extractions` (HANDOFF 27.7).
"""

import hashlib
import time
from dataclasses import dataclass

from billwatcher.mineru.client import PageBlockExtractor
from billwatcher.mineru.markdown import block_to_markdown, pages_to_markdown
from billwatcher.mineru.render import render_pdf_pages
from billwatcher.version import MINERU_EXTRACTOR_VERSION

EXTRACTOR_NAME = "mineru"
MODE = "vlm"


@dataclass(frozen=True, slots=True)
class MineruExtraction:
    extractor_name: str
    extractor_version: str
    mode: str
    status: str
    markdown: str
    markdown_sha256: str
    page_count: int
    char_count: int
    duration_ms: int
    model_name: str | None = None
    error: str | None = None


def extract_document_markdown(
    content: bytes,
    *,
    extractor: PageBlockExtractor,
    dpi: int,
) -> MineruExtraction:
    """Render every page, send each to MinerU, and assemble the result into markdown.

    A page-render failure or an extractor error is recorded as `failed`, distinctly from
    `empty` (rendered fine, nothing recognisable came back) — the same distinction
    `extract_pdf` already draws, kept for the same reason: a transport/parse failure and a
    legitimately empty document are different facts and must not be conflated (HANDOFF 8).
    """
    started = time.monotonic()
    if not content.startswith(b"%PDF-"):
        return _failed(started, "input does not have PDF magic bytes")
    try:
        images = render_pdf_pages(content, dpi=dpi)
    except Exception as error:
        return _failed(started, f"render: {type(error).__name__}: {error}")
    if not images:
        return _finished(started, status="empty", markdown="", page_count=0)
    try:
        pages = extractor.extract_pages(images)
    except Exception as error:
        return _failed(started, f"extract: {type(error).__name__}: {error}")
    markdown = pages_to_markdown(pages)
    # `markdown` always carries a page-boundary marker per page (§27.7), so checking it for
    # emptiness would never trigger; whether the reading recovered anything is decided from the
    # blocks themselves, before the markers are added.
    has_body_content = any(block_to_markdown(block) is not None for page in pages for block in page)
    model_name = getattr(extractor, "model_name", None)
    return _finished(
        started,
        status="succeeded" if has_body_content else "empty",
        markdown=markdown,
        page_count=len(images),
        model_name=model_name,
    )


def _finished(
    started: float,
    *,
    status: str,
    markdown: str,
    page_count: int,
    model_name: str | None = None,
) -> MineruExtraction:
    return MineruExtraction(
        extractor_name=EXTRACTOR_NAME,
        extractor_version=MINERU_EXTRACTOR_VERSION,
        mode=MODE,
        status=status,
        markdown=markdown,
        markdown_sha256=hashlib.sha256(markdown.encode()).hexdigest(),
        page_count=page_count,
        char_count=len(markdown),
        duration_ms=round((time.monotonic() - started) * 1000),
        model_name=model_name,
    )


def _failed(started: float, error: str) -> MineruExtraction:
    return MineruExtraction(
        extractor_name=EXTRACTOR_NAME,
        extractor_version=MINERU_EXTRACTOR_VERSION,
        mode=MODE,
        status="failed",
        markdown="",
        markdown_sha256=hashlib.sha256(b"").hexdigest(),
        page_count=0,
        char_count=0,
        duration_ms=round((time.monotonic() - started) * 1000),
        error=error[:1000],
    )
