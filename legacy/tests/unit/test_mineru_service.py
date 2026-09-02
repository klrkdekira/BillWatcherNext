from collections.abc import Sequence

from mineru_vl_utils.structs import ContentBlock
from PIL import Image

from billwatcher.mineru.service import extract_document_markdown
from tests.support.pdfs import sample_act


class FakeExtractor:
    """Returns one fixed text block per page, tagged with the page's index for assertions."""

    def __init__(
        self, *, model_name: str = "fake-model", blocks_per_page: list[ContentBlock] | None = None
    ) -> None:
        self.model_name = model_name
        self._blocks_per_page = blocks_per_page
        self.received_image_count: int | None = None

    def extract_pages(self, images: Sequence[Image.Image]) -> list[list[ContentBlock]]:
        self.received_image_count = len(images)
        if self._blocks_per_page is not None:
            return [self._blocks_per_page for _ in images]
        return [
            [ContentBlock(type="text", bbox=[0.1, 0.1, 0.9, 0.2], content=f"page {index}")]
            for index in range(1, len(images) + 1)
        ]


class FailingExtractor:
    def extract_pages(self, images: Sequence[Image.Image]) -> list[list[ContentBlock]]:
        raise RuntimeError("endpoint unreachable")


def test_extracts_markdown_from_every_rendered_page() -> None:
    extractor = FakeExtractor()
    result = extract_document_markdown(sample_act(), extractor=extractor, dpi=72)
    assert result.status == "succeeded"
    assert result.page_count == 3
    assert extractor.received_image_count == 3
    assert "page 1" in result.markdown
    assert "page 3" in result.markdown
    assert result.model_name == "fake-model"
    assert result.error is None


def test_non_pdf_bytes_are_a_failed_status_not_an_exception() -> None:
    result = extract_document_markdown(b"not a pdf", extractor=FakeExtractor(), dpi=72)
    assert result.status == "failed"
    assert result.error is not None
    assert result.page_count == 0


def test_an_extractor_error_is_recorded_as_failed_not_raised() -> None:
    result = extract_document_markdown(sample_act(), extractor=FailingExtractor(), dpi=72)
    assert result.status == "failed"
    assert "endpoint unreachable" in (result.error or "")


def test_blocks_with_no_recoverable_content_are_an_empty_status_not_failed() -> None:
    furniture_only = [ContentBlock(type="page_number", bbox=[0.1, 0.1, 0.9, 0.2], content="1")]
    extractor = FakeExtractor(blocks_per_page=furniture_only)
    result = extract_document_markdown(sample_act(), extractor=extractor, dpi=72)
    assert result.status == "empty"
    # Page-boundary markers still appear even when nothing recoverable was found on any page.
    assert result.markdown == "<!-- page 1 -->\n\n<!-- page 2 -->\n\n<!-- page 3 -->"
    assert result.error is None


def test_status_is_deterministically_hashed() -> None:
    extractor = FakeExtractor()
    first = extract_document_markdown(sample_act(), extractor=extractor, dpi=72)
    second = extract_document_markdown(sample_act(), extractor=FakeExtractor(), dpi=72)
    assert first.markdown == second.markdown
    assert first.markdown_sha256 == second.markdown_sha256
