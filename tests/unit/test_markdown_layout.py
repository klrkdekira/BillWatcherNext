"""Stage 1 reads geometry, not just characters (HANDOFF 26.1).

Every assertion here is about a shape Malaysian legislative typography actually uses, built at
known coordinates by `tests/support/pdfs.py` so a reviewer can see why the answer is right.
"""

from billwatcher.markdown.layout import EXTRACTOR_NAME, extract_layout
from billwatcher.version import LAYOUT_EXTRACTOR_VERSION
from tests.support.pdfs import (
    BODY,
    MARGIN,
    MARGINAL,
    Placement,
    amending_bill,
    build_pdf,
    sample_act,
    sample_bill,
)


def roles(pdf: bytes) -> list[tuple[str, str]]:
    return [(line.role, line.text) for line in extract_layout(pdf).lines]


def test_a_document_that_is_not_a_pdf_is_a_bounded_failure() -> None:
    result = extract_layout(b"<html>File does not exist (1)</html>")
    assert result.status == "failed"
    assert result.error == "input does not have PDF magic bytes"
    assert result.lines == ()
    assert result.extractor_name == EXTRACTOR_NAME
    assert result.extractor_version == LAYOUT_EXTRACTOR_VERSION


def test_a_marginal_note_is_not_spliced_into_the_provision_it_annotates() -> None:
    """The failure this whole module exists to prevent.

    A marginal note is typeset on the provision's own baseline, so a reader that joins a
    baseline into one line puts the note inside the legal text.
    """
    result = extract_layout(sample_act())
    provisions = [line for line in result.lines if line.role == "provision"]
    assert any(line.text == "1. Tajuk ringkas dan permulaan kuat kuasa." for line in provisions)
    marginals = [line.text for line in result.lines if line.role == "marginal"]
    assert "Tajuk ringkas" in marginals
    assert "[Am. Akta A1234]" in marginals
    assert not any(
        "Tajuk ringkas dan permulaan kuat kuasa. Tajuk" in line.text for line in result.lines
    )


def test_running_heads_and_page_numbers_are_furniture_but_keep_their_page() -> None:
    result = extract_layout(sample_act())
    assert [line.text for line in result.lines if line.role == "header"] == [
        "Akta Contoh 2026",
        "Akta Contoh 2026",
    ]
    numbers = [line for line in result.lines if line.role == "page_number"]
    assert [line.text for line in numbers] == ["1", "2", "3"]
    # Every line still names the page it came from, so pinpoint citation survives the discard.
    assert {line.page for line in result.content_lines()} == {1, 2, 3}
    assert all(line.role != "page_number" for line in result.content_lines())


def test_a_running_head_that_carries_the_page_number_still_repeats() -> None:
    """`Akta 710   12` and `Akta 710   13` are one running head, not two lines."""
    pages = [
        [
            Placement(MARGIN, 800, f"Akta 710 {number}", 9.0),
            Placement(BODY, 700, f"Perenggan badan pada halaman {number}."),
        ]
        for number in range(1, 6)
    ]
    result = extract_layout(build_pdf(pages))
    assert [line.role for line in result.lines].count("header") == 5
    assert all("Akta 710" not in line.text for line in result.content_lines())


def test_a_short_document_keeps_everything_because_nothing_can_repeat() -> None:
    """With too few pages there is no repetition to observe, so no line is called furniture."""
    result = extract_layout(sample_bill())
    assert not [line for line in result.lines if line.role in {"header", "footer"}]


def test_headings_are_recognised_by_size_and_by_capitals() -> None:
    roles_and_text = roles(sample_act())
    assert ("heading", "SUSUNAN SEKSYEN") in roles_and_text
    assert ("heading", "BAHAGIAN I") in roles_and_text
    assert ("heading", "PERMULAAN") in roles_and_text


def test_geometry_survives_a_different_paper_size() -> None:
    """Thresholds are fractions of the page box, so a letter-size reprint reads the same."""
    a4 = extract_layout(sample_act())
    letter = extract_layout(sample_act(width=612.0, height=792.0))
    assert letter.status == "succeeded"
    assert [line.role for line in letter.lines] == [line.role for line in a4.lines]
    assert [line.text for line in letter.lines] == [line.text for line in a4.lines]


def test_a_part_heading_near_the_top_of_every_page_is_not_erased_as_a_running_head() -> None:
    """Real Part headings can look like a running head, and must not be discarded as one.

    `_furniture_key` masks digits so `Akta 710   12` and `Akta 710   13` are recognised as one
    running head. Without also recognising the line as a Part heading, `BAHAGIAN 1` on page 1
    and `BAHAGIAN 2` on page 2 mask to the same key and repeat at a fixed baseline near the top
    of every page — exactly what a running head looks like — and would be silently deleted.
    """
    pages = [
        [
            Placement(MARGIN, 800, f"BAHAGIAN {number}", 12.0),
            Placement(BODY, 700, f"Teks perenggan halaman {number}."),
        ]
        for number in range(1, 6)
    ]
    result = extract_layout(build_pdf(pages))
    headings = [line.text for line in result.lines if line.role == "heading"]
    assert headings == [f"BAHAGIAN {number}" for number in range(1, 6)]
    assert not any(line.role in {"header", "footer"} for line in result.lines)


def test_a_provision_landing_in_the_header_band_is_not_erased_as_furniture() -> None:
    """A section's own opening line can sit above the header threshold, not just a Part heading.

    A short Act, or a page whose preceding text runs long, can leave `Seksyen 1.` on one page and
    `Seksyen 2.` on the next both above the header band, masking to the same digit-free key at a
    shared baseline — exactly what a running head looks like. The fix for Part headings alone
    does not cover this: a numbered provision is a different structural signal.
    """
    pages = [
        [
            Placement(MARGIN, 800, f"BAHAGIAN {number}", 12.0),
            Placement(MARGIN, 777.7, f"{number}. Seksyen {number}."),
            Placement(BODY, 759.7, "Teks bagi seksyen."),
        ]
        for number in range(1, 4)
    ]
    result = extract_layout(build_pdf(pages))
    provisions = [line.text for line in result.lines if line.role == "provision"]
    assert provisions == [f"{number}. Seksyen {number}." for number in range(1, 4)]
    assert not any(line.role in {"header", "footer"} for line in result.lines)


def test_a_schedule_in_table_type_does_not_redefine_what_the_body_size_is() -> None:
    """The defect that made whole documents read as one long heading.

    An amending bill is mostly schedule, and a schedule is set two points smaller than the prose.
    Taking the size carrying the most characters therefore took the *table's* size as the body,
    and every line of actual legal text then cleared `_HEADING_SIZE_RATIO` above it. Measured on
    `DR 11/2024 BI`: 10pt table type carried 3,649 characters against the prose's 1,267, and the
    reading came back 60% headings.
    """
    result = extract_layout(amending_bill())
    prose = [line for line in result.lines if line.size == 12.0 and line.role != "header"]
    assert prose, "the fixture must contain prose set larger than its schedule"
    # Not one line of prose is a heading merely for being bigger than the table under it.
    assert [line.text for line in prose if line.role == "heading"] == [
        "A BILL",
        "Short title and commencement",
        "Amendment of Third Schedule",
    ]


def test_a_section_heading_is_recognised_by_its_weight_not_its_size() -> None:
    """`Short title and commencement` is set in the body's own size, in bold.

    Reading headings by size alone missed every one of them, so they were classified as body and
    joined into the paragraph that followed — which is how a page of legislation became one
    run-on sentence with its headings buried inside it.
    """
    headings = [
        line.text for line in extract_layout(amending_bill()).lines if line.role == "heading"
    ]
    assert "Short title and commencement" in headings
    assert "Amendment of Third Schedule" in headings


def test_a_provision_is_recognised_when_it_is_indented_rather_than_hung() -> None:
    """A subsection is set with a first-line indent, so it never starts at the body margin.

    The old test asked only whether a line hung at the margin, so `(2)` and `(a)` were read as
    continuations of the sentence above them and merged into it. What marks them is that their
    opening token is set apart from the rest of the line — bold for a number, italic for a letter.
    """
    provisions = [
        line.text for line in extract_layout(amending_bill()).lines if line.role == "provision"
    ]
    assert provisions == [
        "1. (1) This Act may be cited as the Example Act 2024.",
        "(2) This Act comes into operation on a date",
        "2. The Third Schedule is amended-",
    ]


def test_running_heads_that_alternate_recto_and_verso_are_both_furniture() -> None:
    """A bound book sets two running heads, so neither appears on more than half the pages.

    Ten pages, because the defect only shows once half the pages is fewer than
    `_REPEAT_FRACTION` of all of them: each head appears five times against a threshold of six, so
    neither cleared it, both were kept as content, and every other page of every reading carried a
    stray `Bill 2` block. Counted within one parity, five of five clears it.
    """
    pages = [
        [
            Placement(178, 664, "Akta Contoh 2026" if number % 2 else "Bill", 12.0),
            Placement(BODY, 600, f"Teks perenggan yang berlainan pada halaman {number}.", 12.0),
        ]
        for number in range(1, 11)
    ]
    result = extract_layout(build_pdf(pages, width=540.9, height=750.7))
    assert [line.text for line in result.lines if line.role == "header"] == (
        ["Akta Contoh 2026", "Bill"] * 5
    )
    assert all(line.text != "Bill" for line in result.content_lines())


def test_the_recto_and_verso_heads_of_a_short_bill_are_furniture_too() -> None:
    result = extract_layout(amending_bill())
    assert [line.text for line in result.lines if line.role == "header"] == [
        "Employees’ Social Security (Amendment)",
        "Bill",
        "Employees’ Social Security (Amendment)",
        "Bill",
    ]
    assert [line.text for line in result.lines if line.role == "page_number"] == [
        "1",
        "2",
        "3",
        "4",
    ]


def test_a_row_of_money_is_not_a_heading_for_having_capital_letters() -> None:
    """`RM25.75 RM115.90` is two cells of a contribution table. Its only letters are the currency
    prefix — four of them, all capital, which was enough to make every such row a heading."""
    pages = [
        [
            Placement(MARGIN, 700, "BAHAGIAN I", 12.0),
            Placement(BODY, 660, "RM25.75 RM115.90", 10.0),
            Placement(BODY, 640, "Teks perenggan biasa yang panjang di sini.", 10.0),
        ]
    ]
    roles_and_text = roles(build_pdf(pages))
    assert ("heading", "BAHAGIAN I") in roles_and_text
    assert ("body", "RM25.75 RM115.90") in roles_and_text


def test_a_marginal_note_landing_in_the_header_band_is_not_erased_as_furniture() -> None:
    """A note beside the first provision on a page can sit above the header threshold too."""
    pages = [
        [
            Placement(MARGIN, 800, f"{number}. Seksyen {number}."),
            Placement(430, 800, f"Nota pinggir {number}", 9.0),
            Placement(90, 780, f"Teks perenggan bagi seksyen {number}."),
        ]
        for number in range(1, 4)
    ]
    result = extract_layout(build_pdf(pages))
    marginals = [line.text for line in result.lines if line.role == "marginal"]
    assert marginals == [f"Nota pinggir {number}" for number in range(1, 4)]


def test_a_running_head_beside_the_page_number_is_furniture_on_a_two_page_bill() -> None:
    """The largest measured source of leaked furniture: a bill too short to repeat anything.

    `_repeated_furniture` needs three pages to observe a repeat and six to observe a recto/verso
    pair, so on the two-page bills that make up much of the corpus the running head was kept as
    content and turned up as a stray paragraph under the page marker. The page number is
    recognised from its own text on its own page, so the line sharing its baseline is the running
    head beside it — evidence that needs no second page.
    """
    pages = [
        [
            Placement(180.0, 770.0, head, 12.0),
            Placement(426.0, 769.8, str(number), 12.0),
            Placement(MARGIN, 500, f"Perenggan badan pada halaman {number}."),
        ]
        for number, head in enumerate(["Suruhanjaya Tenaga (Pindaan)", "Rang Undang-Undang"], 1)
    ]
    result = extract_layout(build_pdf(pages))

    assert [line.text for line in result.lines if line.role == "header"] == [
        "Suruhanjaya Tenaga (Pindaan)",
        "Rang Undang-Undang",
    ]
    assert all("Rang Undang-Undang" not in line.text for line in result.content_lines())
    # The body is untouched: only the line level with the number is discarded, not the page.
    assert {line.page for line in result.content_lines()} == {1, 2}


def test_a_body_line_merely_high_on_the_page_is_not_taken_for_a_running_head() -> None:
    """The risk the shared-baseline rule creates, and the edge-rank test that contains it.

    A page whose preceding text ran short can begin its body high enough to sit in the header
    band. What it cannot do is be printed *above* the running head — so a line that is not among
    the first printed on its page is safe even when it is level with a page number.
    """
    pages = [
        [
            Placement(MARGIN, 800, "Akta Contoh 2026", 9.0),
            Placement(426.0, 800, str(number), 9.0),
            Placement(MARGIN, 780, "Perenggan yang bermula tinggi pada halaman ini."),
        ]
        for number in (1, 2)
    ]
    result = extract_layout(build_pdf(pages))

    kept = [line.text for line in result.content_lines()]
    assert "Perenggan yang bermula tinggi pada halaman ini." in kept
    assert "Akta Contoh 2026" not in kept


def test_the_arrangement_column_header_is_not_read_as_legal_text() -> None:
    """`Fasal` over a group of Arrangement entries is a table column header, not a provision.

    It repeats at whatever height the preceding group ended, so neither a baseline test nor a
    repetition test can see it; recognising the bare unit word is what drops it.
    """
    pages = [
        [
            Placement(MARGIN, 780, "SUSUNAN FASAL", 13.0),
            Placement(MARGIN, 750, "BAHAGIAN I", 12.0),
            Placement(MARGIN, 730, "Fasal"),
            Placement(MARGIN, 712, "1. Tajuk ringkas dan permulaan kuat kuasa"),
            Placement(MARGIN, 640, "BAHAGIAN II", 12.0),
            Placement(MARGIN, 620, "Fasal"),
            Placement(MARGIN, 602, "11. Pelantikan Komisioner"),
            Placement(300, 40, "1", 9.0),
        ]
    ]
    result = extract_layout(build_pdf(pages))

    assert all(line.text != "Fasal" for line in result.content_lines())
    # The structure around it survives: the column header is dropped, the Parts and entries stay.
    kept = [line.text for line in result.content_lines()]
    assert "BAHAGIAN II" in kept
    assert "11. Pelantikan Komisioner" in kept


def test_a_numbered_clause_is_never_mistaken_for_the_bare_column_header() -> None:
    result = extract_layout(sample_bill())
    assert any(line.text.startswith("1. Tajuk ringkas") for line in result.content_lines()), (
        "a real provision must survive the bare-unit-label rule"
    )


def test_half_a_bracket_pair_is_not_a_marginal_note() -> None:
    """A cover page prints an empty citation bracket: `[` in the text column, `]` far right.

    The right-hand half lands in the margin column and was read as an annotation — 1,793
    `<!-- marginal: ] -->` comments across the corpus, each one half of a pair torn apart. A note
    says something; a bracket does not.
    """
    pages = [
        [
            Placement(MARGIN, 500, "Suatu Akta untuk meminda Akta Contoh 2001."),
            Placement(264.0, 460, "["),
            Placement(MARGINAL, 460, "]"),
            Placement(MARGIN, 420, "DIPERBUAT oleh Parlimen Malaysia seperti yang berikut:"),
            Placement(300, 40, "1", 9.0),
        ]
    ]
    result = extract_layout(build_pdf(pages))

    assert all(line.role != "marginal" for line in result.lines)
    # It is kept, not dropped: the bracket is printed on the page and the gate scores every token.
    assert "]" in [line.text for line in result.content_lines()]


def test_a_real_marginal_note_is_still_a_marginal_note() -> None:
    """The rule above must not cost the annotations the whole module exists to separate."""
    result = extract_layout(sample_act())
    assert "Tajuk ringkas" in [line.text for line in result.lines if line.role == "marginal"]


def test_tracked_body_text_is_rejoined_into_words() -> None:
    # The HURAIAN pages of a bill are letterspaced: every glyph is set apart by the `Tc` operator,
    # with no space characters between letters, and pdfminer's word inference reads each letter as
    # its own word. The reading must come back as the sentence the paper prints.
    document = extract_layout(
        build_pdf(
            [
                [
                    Placement(BODY, 700.0, "Rang Undang-Undang ini bertujuan untuk", tracking=1.0),
                    Placement(BODY, 680.0, "An ordinarily set line stays exactly as it is."),
                ]
            ]
        )
    )
    texts = [line.text for line in document.lines]
    assert "Rang Undang-Undang ini bertujuan untuk" in texts
    assert "An ordinarily set line stays exactly as it is." in texts


def test_a_flourish_letterspaced_with_real_spaces_reads_as_its_word() -> None:
    # A cover letterspaces "bernama" with actual space glyphs, one per letter pair, and an English
    # bill does the same to "intituled". The word is the text; the spacing is presentation — and
    # a reader searching the corpus for "bernama" must find it.
    document = extract_layout(
        build_pdf(
            [
                [
                    Placement(BODY, 700.0, "b e r n a m a"),
                    Placement(BODY, 680.0, "i n t i t u l e d"),
                    Placement(BODY, 660.0, "Suatu Akta untuk meminda Akta Contoh 2001."),
                ]
            ]
        )
    )
    texts = [line.text for line in document.lines]
    assert "bernama" in texts
    assert "intituled" in texts
    assert "Suatu Akta untuk meminda Akta Contoh 2001." in texts


def test_a_tracked_run_inside_an_ordinary_line_is_rejoined_in_place() -> None:
    # "This B i l l seeks to amend…": one word tracked, the rest of the line set ordinarily.
    # The run triggers the rebuild, and the quarter-em threshold keeps the ordinary words apart
    # while the tracked letters rejoin.
    document = extract_layout(
        build_pdf([[Placement(BODY, 700.0, "This Bill seeks to amend the Act.", tracking=0.0)]])
    )
    plain = [line.text for line in document.lines]
    assert "This Bill seeks to amend the Act." in plain

    tracked = extract_layout(
        build_pdf(
            [
                [
                    Placement(BODY, 700.0, "This ", tracking=0.0),
                    Placement(BODY + 26.0, 700.0, "Bill", tracking=1.6),
                    Placement(BODY + 52.0, 700.0, " seeks to amend the Act.", tracking=0.0),
                ]
            ]
        )
    )
    texts = " ".join(line.text for line in tracked.lines)
    assert "B i l l" not in texts
    assert "Bill" in texts
