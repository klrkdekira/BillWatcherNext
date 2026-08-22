"""Stage 1 reads geometry, not just characters (HANDOFF 26.1).

Every assertion here is about a shape Malaysian legislative typography actually uses, built at
known coordinates by `tests/support/pdfs.py` so a reviewer can see why the answer is right.
"""

from billwatcher.legislation.layout import EXTRACTOR_NAME, extract_layout
from billwatcher.version import LAYOUT_EXTRACTOR_VERSION
from tests.support.pdfs import (
    BODY,
    MARGIN,
    Placement,
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
