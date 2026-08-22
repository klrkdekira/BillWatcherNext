"""Build small PDFs whose text sits at known coordinates.

The legislation fixtures are *constructed typography*, not captured upstream bytes, so they are
built here in readable code rather than committed as opaque binaries: a reviewer can see that a
marginal note is at x=430 because the test put it there. Fixtures that capture what Parliament
actually publishes stay in `tests/fixtures/`, where they belong.

Nothing here depends on a PDF writer library. A legislative PDF needs only Type 1 base-14 text
placed by a text matrix, which is a few hundred bytes of PDF by hand.
"""

from dataclasses import dataclass

A4_WIDTH = 595.0
A4_HEIGHT = 842.0


@dataclass(frozen=True, slots=True)
class Placement:
    """One line of text at a baseline origin in PDF user space (origin bottom-left)."""

    x: float
    y: float
    text: str
    size: float = 11.0


def _escape(value: str) -> bytes:
    escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return escaped.encode("latin-1", "replace")


def build_pdf(
    pages: list[list[Placement]],
    *,
    width: float = A4_WIDTH,
    height: float = A4_HEIGHT,
) -> bytes:
    """Assemble one PDF from a list of pages, each a list of placements."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_id = add(b"")  # reserved; the Pages node needs its kids' ids
    page_ids: list[int] = []

    for placements in pages:
        parts = [b"BT\n"]
        for item in placements:
            parts.append(
                b"/F1 %s Tf\n1 0 0 1 %s %s Tm\n(%s) Tj\n"
                % (
                    f"{item.size:g}".encode(),
                    f"{item.x:g}".encode(),
                    f"{item.y:g}".encode(),
                    _escape(item.text),
                )
            )
        parts.append(b"ET\n")
        stream = b"".join(parts)
        contents_id = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        page_ids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %s %s] "
                b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                % (
                    pages_id,
                    f"{width:g}".encode(),
                    f"{height:g}".encode(),
                    font_id,
                    contents_id,
                )
            )
        )

    kids = b" ".join(b"%d 0 R" % page_id for page_id in page_ids)
    objects[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))
    catalog_id = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog_id,
        xref_at,
    )
    return bytes(out)


# Column geometry shared by the sample documents below, chosen to look like a printed Act: a
# body column at x=85, section numbers hanging at x=72, and marginal notes at x=430.
MARGIN = 72.0
BODY = 85.0
MARGINAL = 430.0
INDENT = 105.0


def sample_act(
    *, language: str = "ms", width: float = A4_WIDTH, height: float = A4_HEIGHT
) -> bytes:
    """A three-page Act whose Arrangement of Sections matches its body exactly.

    Two Parts, four sections, one subsection, one paragraph, a marginal note, a repeated running
    head, page numbers, and one `[Am. Akta A1234]` annotation — the shapes Stage 1 must survive.
    """
    if language == "ms":
        heading = "SUSUNAN SEKSYEN"
        part_one, part_two = "BAHAGIAN I", "BAHAGIAN II"
        part_one_title, part_two_title = "PERMULAAN", "KEWAJIPAN MELAPORKAN"
        entries = [
            "1. Tajuk ringkas dan permulaan kuat kuasa",
            "2. Tafsiran",
            "3. Kewajipan untuk melaporkan",
            "4. Penalti",
        ]
        body_text = [
            "Akta ini bolehlah dinamakan Akta Contoh 2026.",
            "Dalam Akta ini, melainkan jika konteksnya menghendaki makna yang lain -",
            "Seseorang hendaklah melaporkan kepada Pesuruhjaya",
            "melalui apa-apa cara yang ditetapkan.",
            "Seseorang yang melanggar seksyen 3 melakukan suatu kesalahan.",
        ]
        note = "Tajuk ringkas"
    else:
        heading = "ARRANGEMENT OF SECTIONS"
        part_one, part_two = "PART I", "PART II"
        part_one_title, part_two_title = "PRELIMINARY", "DUTY TO REPORT"
        entries = [
            "1. Short title and commencement",
            "2. Interpretation",
            "3. Duty to report",
            "4. Penalty",
        ]
        body_text = [
            "This Act may be cited as the Example Act 2026.",
            "In this Act, unless the context otherwise requires",
            "A person shall report to the Commissioner",
            "in such manner as may be prescribed.",
            "A person who contravenes section 3 commits an offence.",
        ]
        note = "Short title"

    running_head = "Akta Contoh 2026"

    front = [
        Placement(MARGIN, 780, heading, 13.0),
        Placement(MARGIN, 745, part_one, 12.0),
        Placement(MARGIN, 728, part_one_title, 12.0),
        Placement(MARGIN, 700, entries[0]),
        Placement(MARGIN, 682, entries[1]),
        Placement(MARGIN, 650, part_two, 12.0),
        Placement(MARGIN, 633, part_two_title, 12.0),
        Placement(MARGIN, 605, entries[2]),
        Placement(MARGIN, 587, entries[3]),
        Placement(300, 40, "1", 9.0),
    ]
    page_two = [
        Placement(MARGIN, 800, running_head, 9.0),
        Placement(MARGIN, 760, part_one, 12.0),
        Placement(MARGIN, 743, part_one_title, 12.0),
        Placement(MARGIN, 710, entries[0] + "."),
        Placement(MARGINAL, 710, note, 9.0),
        Placement(BODY, 692, body_text[0]),
        Placement(MARGIN, 660, entries[1] + "."),
        Placement(BODY, 642, body_text[1]),
        Placement(300, 40, "2", 9.0),
    ]
    page_three = [
        Placement(MARGIN, 800, running_head, 9.0),
        Placement(MARGIN, 760, part_two, 12.0),
        Placement(MARGIN, 743, part_two_title, 12.0),
        Placement(MARGIN, 710, entries[2] + "."),
        Placement(BODY, 692, "(1) " + body_text[2]),
        Placement(INDENT, 674, "(a) " + body_text[3]),
        Placement(MARGINAL, 692, "[Am. Akta A1234]", 9.0),
        Placement(MARGIN, 640, entries[3] + "."),
        Placement(BODY, 622, body_text[4]),
        Placement(300, 40, "3", 9.0),
    ]
    return build_pdf([front, page_two, page_three], width=width, height=height)


def sample_bill() -> bytes:
    """A bill: the same shape, but Fasal/Clauses rather than Seksyen/Sections."""
    front = [
        Placement(MARGIN, 780, "SUSUNAN FASAL", 13.0),
        Placement(MARGIN, 740, "1. Tajuk ringkas dan permulaan kuat kuasa"),
        Placement(MARGIN, 722, "2. Tafsiran"),
        Placement(300, 40, "1", 9.0),
    ]
    body = [
        Placement(MARGIN, 760, "1. Tajuk ringkas dan permulaan kuat kuasa."),
        Placement(BODY, 742, "Akta ini bolehlah dinamakan Akta Contoh 2026."),
        Placement(MARGIN, 710, "2. Tafsiran."),
        Placement(BODY, 692, "Dalam Akta ini -"),
        Placement(300, 40, "2", 9.0),
    ]
    return build_pdf([front, body])


def act_with_missing_section() -> bytes:
    """An Act whose body drops section 3 — the dropped-page failure Gate L1 exists to catch."""
    front = [
        Placement(MARGIN, 780, "SUSUNAN SEKSYEN", 13.0),
        Placement(MARGIN, 740, "1. Tajuk ringkas dan permulaan kuat kuasa"),
        Placement(MARGIN, 722, "2. Tafsiran"),
        Placement(MARGIN, 704, "3. Kewajipan untuk melaporkan"),
        Placement(300, 40, "1", 9.0),
    ]
    body = [
        Placement(MARGIN, 760, "1. Tajuk ringkas dan permulaan kuat kuasa."),
        Placement(BODY, 742, "Akta ini bolehlah dinamakan Akta Contoh 2026."),
        Placement(MARGIN, 710, "2. Tafsiran."),
        Placement(BODY, 692, "Dalam Akta ini -"),
        Placement(300, 40, "2", 9.0),
    ]
    return build_pdf([front, body])


def act_without_arrangement() -> bytes:
    """A document with no Arrangement of Sections at all: Gate L1 has no oracle to apply."""
    body = [
        Placement(MARGIN, 760, "1. Tajuk ringkas dan permulaan kuat kuasa."),
        Placement(BODY, 742, "Akta ini bolehlah dinamakan Akta Contoh 2026."),
        Placement(300, 40, "1", 9.0),
    ]
    return build_pdf([body])
