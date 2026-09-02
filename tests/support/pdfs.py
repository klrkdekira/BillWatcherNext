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


# The three faces Malaysian legislative typography actually uses, keyed by the resource name they
# are registered under. Weight is load-bearing, not decoration: a section heading is set in the
# same size as the provision beneath it and differs only in being bold, so a fixture that can only
# write one face cannot express the shape the classifier reads.
FONTS = {
    "F1": "Times-Roman",
    "F2": "Times-Bold",
    "F3": "Times-Italic",
    # A small-capitals face, named the way the corpus's own PDFs name it. Not a base-14 face, so
    # `build_pdf` gives it a descriptor and uniform widths of its own; what the test needs from it
    # is the name pdfminer reports, not its metrics.
    "F4": "Times-Roman-SC700",
}
ROMAN, BOLD, ITALIC, SMALL_CAPS = "F1", "F2", "F3", "F4"
_BASE14 = {"Times-Roman", "Times-Bold", "Times-Italic"}


@dataclass(frozen=True, slots=True)
class Placement:
    """One line of text at a baseline origin in PDF user space (origin bottom-left).

    `lead` sets the face of the first `lead_chars` characters, which is how a provision number is
    printed: `2.` in bold, the sentence after it in roman, on one typeset line.
    """

    x: float
    y: float
    text: str
    size: float = 11.0
    font: str = ROMAN
    lead: str | None = None
    lead_chars: int = 0
    # Extra space between every pair of glyphs, in points: the PDF `Tc` operator. This is how a
    # bill's HURAIAN pages are letterspaced — tracked glyphs with no space characters between them.
    tracking: float = 0.0


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

    def font_object(base: str) -> bytes:
        if base in _BASE14:
            return b"<< /Type /Font /Subtype /Type1 /BaseFont /%s >>" % base.encode()
        # pdfminer has no metrics for a face it does not know, so a non-standard face carries a
        # descriptor and a width for every code, or every glyph would be zero points wide.
        descriptor = add(
            b"<< /Type /FontDescriptor /FontName /%s /Flags 32 /FontBBox [0 -200 1000 900] "
            b"/ItalicAngle 0 /Ascent 700 /Descent -200 /CapHeight 700 /StemV 80 "
            b"/MissingWidth 500 >>" % base.encode()
        )
        widths = b" ".join([b"500"] * 224)
        return (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /FirstChar 32 /LastChar 255 "
            b"/Widths [%s] /FontDescriptor %d 0 R >>" % (base.encode(), widths, descriptor)
        )

    font_ids = {name: add(font_object(base)) for name, base in FONTS.items()}
    pages_id = add(b"")  # reserved; the Pages node needs its kids' ids
    page_ids: list[int] = []

    for placements in pages:
        parts = [b"BT\n"]
        for item in placements:
            size = f"{item.size:g}".encode()
            # A run per face. The text matrix places the first run; the ones after it follow on
            # the same line, which is what makes a bold number and a roman sentence one line.
            runs = (
                [
                    (item.lead, item.text[: item.lead_chars]),
                    (item.font, item.text[item.lead_chars :]),
                ]
                if item.lead and item.lead_chars
                else [(item.font, item.text)]
            )
            parts.append(b"1 0 0 1 %s %s Tm\n" % (f"{item.x:g}".encode(), f"{item.y:g}".encode()))
            parts.append(b"%s Tc\n" % f"{item.tracking:g}".encode())
            for face, chunk in runs:
                if not chunk:
                    continue
                parts.append(
                    b"/%s %s Tf\n(%s) Tj\n" % ((face or ROMAN).encode(), size, _escape(chunk))
                )
        parts.append(b"ET\n")
        stream = b"".join(parts)
        contents_id = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        page_ids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %s %s] "
                b"/Resources << /Font << %s >> >> /Contents %d 0 R >>"
                % (
                    pages_id,
                    f"{width:g}".encode(),
                    f"{height:g}".encode(),
                    b" ".join(
                        b"/%s %d 0 R" % (name.encode(), font_id)
                        for name, font_id in font_ids.items()
                    ),
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


def amending_bill() -> bytes:
    """The shape most of the real corpus has, and the one the reader kept getting wrong.

    Reproduced from `DR 11/2024 BI`, measured: an amending bill is mostly *schedule*, and a
    schedule is set in table type two points smaller than the prose. Three things follow, and each
    of them broke a different rule:

    - The small type carries more characters than the prose does, so the size carrying the most
      text is the *table's*, not the body's.
    - A section heading is set in the same size as the provision under it and differs only in
      being bold.
    - A subsection is indented rather than hung, so it does not start at the body margin.

    The running heads alternate recto and verso, so neither appears on more than half the pages.
    """
    prose, table = 12.0, 10.0
    body_margin, indent = 88.0, 100.0
    head = "Employees' Social Security (Amendment)"

    page_one = [
        Placement(178, 664, head, prose, font=ITALIC),
        Placement(447, 664, "1", prose),
        Placement(264, 640, "A BILL", prose),
        Placement(body_margin, 560, "Short title and commencement", prose, font=BOLD),
        Placement(
            body_margin,
            532,
            "1. (1) This Act may be cited as the Example Act 2024.",
            prose,
            lead=BOLD,
            lead_chars=2,
        ),
        Placement(indent, 504, "(2) This Act comes into operation on a date", prose),
        Placement(body_margin, 490, "appointed by the Minister.", prose),
        Placement(body_margin, 448, "Amendment of Third Schedule", prose, font=BOLD),
        Placement(
            body_margin, 420, "2. The Third Schedule is amended-", prose, lead=BOLD, lead_chars=2
        ),
    ]
    # The schedule: enough small type to outweigh the prose above, as the real bills do.
    rows = [
        Placement(
            184, 380 - index * 11, f'"{55 + index}. When wages exceed RM{5000 + index * 100}', table
        )
        for index in range(8)
    ]
    page_two = [
        Placement(245, 664, "Bill", prose, font=ITALIC),
        Placement(87, 664, "2", prose),
        *[
            Placement(
                184,
                640 - index * 11,
                f"RM{88 + index}.35 RM{25 + index}.25 RM{113 + index}.60”;",
                table,
            )
            for index in range(8)
        ],
    ]
    page_three = [
        Placement(178, 664, head, prose, font=ITALIC),
        Placement(447, 664, "3", prose),
        *[
            Placement(
                184,
                640 - index * 11,
                f'"{79 + index}. When wages exceed RM{7400 + index * 100}',
                table,
            )
            for index in range(8)
        ],
    ]
    page_four = [
        Placement(245, 664, "Bill", prose, font=ITALIC),
        Placement(87, 664, "4", prose),
        *[
            Placement(
                184,
                640 - index * 11,
                f"RM{112 + index}.35 RM{49 + index}.25 RM{161 + index}.60”;",
                table,
            )
            for index in range(8)
        ],
    ]
    return build_pdf([page_one + rows, page_two, page_three, page_four], width=540.9, height=750.7)


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
