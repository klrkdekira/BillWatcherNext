import hashlib
import io
import time
from dataclasses import dataclass

from pypdf import PdfReader

from billwatcher.scraper.normalize import normalize_text
from billwatcher.version import EXTRACTOR_VERSION


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    extractor_name: str
    extractor_version: str
    mode: str
    status: str
    text: str
    text_sha256: str
    pages: tuple[str, ...]
    page_count: int
    char_count: int
    duration_ms: int
    error: str | None = None


def extract_pdf(content: bytes) -> ExtractedDocument:
    """Extract page-aware text without mutating or fetching the source document."""
    started = time.monotonic()
    if not content.startswith(b"%PDF-"):
        return _failed(started, "input does not have PDF magic bytes")
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        pages = tuple(normalize_text(page.extract_text() or "") for page in reader.pages)
    except Exception as error:  # pypdf exposes several parser-specific exception types
        return _failed(started, f"{type(error).__name__}: {error}")
    text = "\n\n".join(
        f"--- Page {page_number} ---\n{page}" for page_number, page in enumerate(pages, start=1)
    )
    status = "succeeded" if any(pages) else "empty"
    return ExtractedDocument(
        extractor_name="pypdf",
        extractor_version=EXTRACTOR_VERSION,
        mode="native",
        status=status,
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        pages=pages,
        page_count=len(pages),
        char_count=len(text),
        duration_ms=round((time.monotonic() - started) * 1000),
    )


def _failed(started: float, error: str) -> ExtractedDocument:
    return ExtractedDocument(
        extractor_name="pypdf",
        extractor_version=EXTRACTOR_VERSION,
        mode="native",
        status="failed",
        text="",
        text_sha256=hashlib.sha256(b"").hexdigest(),
        pages=(),
        page_count=0,
        char_count=0,
        duration_ms=round((time.monotonic() - started) * 1000),
        error=error[:1000],
    )
