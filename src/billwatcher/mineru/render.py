"""Render stored PDF bytes to page images, the input a vision-language reader needs.

`pypdfium2` was chosen for the same reason ADR-016 chose `pdfminer.six` over the alternatives: it
is permissively licensed (BSD-3-Clause/Apache-2.0), unlike PyMuPDF (AGPL), and does not pull in an
imaging stack this project otherwise has no use for.
"""

from PIL import Image
from pypdfium2 import PdfDocument


def render_pdf_pages(content: bytes, *, dpi: int) -> list[Image.Image]:
    """One RGB image per page, at the given resolution.

    Raises `pypdfium2.PdfiumError` on bytes PDFium cannot parse; the caller catches it exactly as
    `parse_document.extract_pdf` catches pypdf's exceptions, and records a `failed` status rather
    than letting a bad document abort a batch.
    """
    scale = dpi / 72.0
    pages: list[Image.Image] = []
    with PdfDocument(content) as document:
        for index in range(len(document)):
            page = document.get_page(index)
            try:
                bitmap = page.render(scale=scale)
                try:
                    pages.append(bitmap.to_pil().convert("RGB"))
                finally:
                    bitmap.close()
            finally:
                page.close()
    return pages
