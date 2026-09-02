import pytest
from pypdfium2 import PdfiumError

from billwatcher.mineru.render import render_pdf_pages
from tests.support.pdfs import sample_act, sample_bill


def test_renders_one_image_per_page() -> None:
    images = render_pdf_pages(sample_act(), dpi=72)
    assert len(images) == 3
    for image in images:
        assert image.mode == "RGB"
        assert image.width > 0 and image.height > 0


def test_higher_dpi_produces_a_larger_image() -> None:
    low = render_pdf_pages(sample_bill(), dpi=72)[0]
    high = render_pdf_pages(sample_bill(), dpi=144)[0]
    assert high.width == low.width * 2
    assert high.height == low.height * 2


def test_garbage_bytes_raise_rather_than_silently_producing_no_pages() -> None:
    with pytest.raises(PdfiumError):
        render_pdf_pages(b"not a pdf at all", dpi=72)
