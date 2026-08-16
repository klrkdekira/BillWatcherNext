import io

from pypdf import PdfWriter

from billwatcher.scraper.parse_document import extract_pdf


def blank_pdf() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)
    return output.getvalue()


def test_empty_native_pdf_is_distinct_from_failure() -> None:
    result = extract_pdf(blank_pdf())
    assert result.status == "empty"
    assert result.page_count == 1
    assert result.pages == ("",)
    assert result.error is None


def test_invalid_pdf_is_a_bounded_failure() -> None:
    result = extract_pdf(b"<html>not a pdf</html>")
    assert result.status == "failed"
    assert result.page_count == 0
    assert result.error == "input does not have PDF magic bytes"
