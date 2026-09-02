"""The second reading and the divergence report — the only check on the reading itself (ADR-035).

No network and no model: `PageBlockExtractor` is a project-owned protocol precisely so a test can
inject a fake one (ADR-020), and nothing here constructs the vendor client.
"""

import io
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from pypdf import PdfWriter

from billwatcher.pipeline.crosscheck import (
    DIVERGENCE_THRESHOLD,
    compare_readings,
    cross_reference,
)
from billwatcher.pipeline.documents import doc_key
from billwatcher.pipeline.store import FileStore


def pdf(pages: int = 1) -> bytes:
    """A real PDF: the step renders pages to images before the extractor ever sees them, so the
    bytes have to survive `pypdfium2` even though the fake extractor ignores their content."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


PDF = pdf()


@dataclass
class _Block:
    type: str
    content: str

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class _FakeExtractor:
    """Returns one text block per rendered page, from a script the test supplies."""

    def __init__(self, pages: list[str]) -> None:
        self.pages = pages
        self.calls = 0

    def extract_pages(self, images: Sequence[Any]) -> list[list[_Block]]:
        self.calls += 1
        return [[_Block("text", text)] for text in self.pages[: len(images)]]


def seed(store: FileStore, *, slug: str, url: str, markdown: str) -> str:
    key = doc_key(url)
    store.save_bill(slug, {"identifier": {"slug": slug}, "documents": [{"url": url}]})
    store.save_document(
        bill_slug=slug, doc_key=key, version=1, content=PDF, metadata={"source_url": url}
    )
    store.save_markdown(bill_slug=slug, doc_key=key, version=1, content=markdown)
    return key


def test_two_readings_of_the_same_text_agree() -> None:
    agreement, local_only, crosscheck_only = compare_readings(
        "1. Akta ini bolehlah dinamakan Akta Contoh 2026.",
        "1. Akta ini bolehlah dinamakan Akta Contoh 2026.",
    )
    assert agreement == 1.0
    assert (local_only, crosscheck_only) == (0, 0)


def test_agreement_ignores_page_markers_and_marginal_comments() -> None:
    """Formatting the two producers were never going to render identically must not read as
    disagreement about the document."""
    agreement, _, _ = compare_readings(
        "<!-- page 1 -->\n\n<!-- marginal: Tajuk ringkas -->\n\nAkta ini dipinda.",
        "<!-- page 1 -->\n\nAkta ini dipinda.",
    )
    assert agreement == 1.0


def test_agreement_is_symmetric_because_neither_reading_is_the_reference() -> None:
    left = "satu dua tiga empat"
    right = "satu dua"
    forward, _, _ = compare_readings(left, right)
    backward, _, _ = compare_readings(right, left)
    assert forward == backward == pytest.approx(0.5)


def test_a_diverging_document_is_named_with_both_directions_of_the_difference(tmp_path) -> None:
    store = FileStore(tmp_path)
    key = seed(
        store,
        slug="dr-15-2026",
        url="https://www.parlimen.gov.my/a.pdf",
        markdown="1. Akta ini bolehlah dinamakan Akta Contoh 2026.",
    )
    extractor = _FakeExtractor(["Sesuatu yang lain sekali sama sekali berbeza"])

    result = cross_reference(store, extractor=extractor, dpi=150)

    assert result.counts["diverged"] == 1
    assert result.counts["agreed"] == 0
    (failure,) = result.failures
    assert failure.label == f"dr-15-2026/{key}/v001"
    assert "readings diverge" in failure.reason
    assert "only in the local reading" in failure.reason
    # The expensive reading is kept, so resolving the divergence needs no second model run.
    assert store.load_crosscheck(bill_slug="dr-15-2026", doc_key=key, version=1) is not None
    assert (
        store.load_provenance(bill_slug="dr-15-2026", doc_key=key, version=1, artifact="crosscheck")
        is not None
    )


def test_an_agreeing_document_is_not_reported_as_a_failure(tmp_path) -> None:
    store = FileStore(tmp_path)
    text = "1. Akta ini bolehlah dinamakan Akta Contoh 2026."
    seed(store, slug="dr-15-2026", url="https://www.parlimen.gov.my/a.pdf", markdown=text)

    result = cross_reference(store, extractor=_FakeExtractor([text]), dpi=150)

    assert result.counts["agreed"] == 1
    assert result.failures == ()


def test_a_stored_cross_check_is_not_read_again(tmp_path) -> None:
    """One model call per page makes this the most expensive step by two orders of magnitude; an
    interrupted run must not pay for the same pages twice."""
    store = FileStore(tmp_path)
    text = "1. Akta ini bolehlah dinamakan Akta Contoh 2026."
    seed(store, slug="dr-15-2026", url="https://www.parlimen.gov.my/a.pdf", markdown=text)

    first = _FakeExtractor([text])
    cross_reference(store, extractor=first, dpi=150)
    assert first.calls == 1

    second = _FakeExtractor([text])
    result = cross_reference(store, extractor=second, dpi=150)

    assert second.calls == 0
    assert result.counts["skipped"] == 1
    assert result.counts["read"] == 0
    assert result.counts["agreed"] == 1


def test_a_document_with_no_local_reading_is_skipped_not_read_expensively(tmp_path) -> None:
    """A second opinion on a document that has no first one is not what this budget is for."""
    store = FileStore(tmp_path)
    url = "https://www.parlimen.gov.my/a.pdf"
    key = doc_key(url)
    store.save_bill("dr-15-2026", {"identifier": {"slug": "dr-15-2026"}})
    store.save_document(
        bill_slug="dr-15-2026", doc_key=key, version=1, content=PDF, metadata={"source_url": url}
    )
    extractor = _FakeExtractor(["anything"])

    result = cross_reference(store, extractor=extractor, dpi=150)

    assert result.counts["no_local_reading"] == 1
    assert extractor.calls == 0


def test_the_divergence_threshold_is_looser_than_the_fidelity_gate() -> None:
    """Two independent readings of one page legitimately differ on hyphenation and furniture; this
    is a "these disagree about the substance" line, not a fidelity score."""
    from billwatcher.pipeline.fidelity import MIN_TEXT_COVERAGE

    assert DIVERGENCE_THRESHOLD < MIN_TEXT_COVERAGE
