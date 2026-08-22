"""Gate L1: the Arrangement of Sections is the oracle the corpus supplies for free.

HANDOFF 26.3.
"""

from billwatcher.legislation.gate import evaluate_document
from billwatcher.legislation.layout import extract_layout
from billwatcher.legislation.structure import parse_body, split_regions
from tests.support.pdfs import (
    BODY,
    INDENT,
    MARGIN,
    Placement,
    act_with_missing_section,
    act_without_arrangement,
    build_pdf,
    sample_act,
    sample_bill,
)


def trees(pdf: bytes) -> tuple[list[str], list[str]]:
    from billwatcher.legislation.structure import parse_arrangement

    lines = extract_layout(pdf).lines
    arrangement_lines, body_lines, unit, language = split_regions(lines)
    arrangement = parse_arrangement(arrangement_lines, unit=unit, language=language)
    body = parse_body(body_lines, unit=unit, language=language)
    return [node.eid for node in arrangement.walk()], [node.eid for node in body.walk()]


def test_an_act_whose_contents_match_its_body_passes_in_both_languages() -> None:
    for pdf in (sample_act(), sample_act(language="en")):
        result = evaluate_document(extract_layout(pdf).lines)
        assert result.status == "passed"
        assert result.unit == "section"
        assert result.arrangement_count == 6  # two Parts and four sections
        assert not result.blocking


def test_a_bill_is_read_as_clauses_and_never_as_sections() -> None:
    """A clause becomes a section on enactment; conflating the two is HANDOFF 26.2's warning."""
    result = evaluate_document(extract_layout(sample_bill()).lines)
    assert result.status == "passed"
    assert result.unit == "clause"
    arrangement, body = trees(sample_bill())
    assert arrangement == ["cl_1", "cl_2"]
    assert body == ["cl_1", "cl_2"]


def test_a_dropped_section_fails_the_gate_and_names_what_is_missing() -> None:
    """The failure Gate L1 exists to catch: the body lost a provision the contents page lists."""
    result = evaluate_document(extract_layout(act_with_missing_section()).lines)
    assert result.status == "mismatch"
    assert [(item.kind, item.eid) for item in result.blocking] == [("missing_in_body", "sec_3")]
    assert result.arrangement_count == 3
    assert result.body_count == 2


def test_a_document_with_no_contents_page_reports_that_rather_than_passing() -> None:
    """An explanatory statement has no Arrangement of Sections.

    The gate then has no oracle to apply, and says so rather than passing.
    """
    result = evaluate_document(extract_layout(act_without_arrangement()).lines)
    assert result.status == "no_arrangement"
    assert not result.blocking


def test_the_body_begins_at_its_own_part_heading_not_at_its_first_section() -> None:
    """The enacting text opens under `BAHAGIAN I`, which belongs to the body, not the contents."""
    arrangement, body = trees(sample_act())
    assert arrangement == [
        "part_I",
        "part_I__sec_1",
        "part_I__sec_2",
        "part_II",
        "part_II__sec_3",
        "part_II__sec_4",
    ]
    assert body[:3] == ["part_I", "part_I__sec_1", "part_I__sec_2"]


def test_the_body_carries_detail_the_contents_page_never_lists() -> None:
    """An arrangement never enumerates subsections, so the gate compares only what it lists."""
    _, body = trees(sample_act())
    assert "part_II__sec_3__subsec_1" in body
    assert "part_II__sec_3__subsec_1__para_a" in body
    assert evaluate_document(extract_layout(sample_act()).lines).status == "passed"


def test_a_heading_difference_is_reported_without_blocking() -> None:
    """A reprint abbreviates the marginal note; that is typography, not a defective parse."""
    result = evaluate_document(extract_layout(sample_act()).lines)
    headings = [item for item in result.differences if item.kind == "heading"]
    assert headings, "the sample abbreviates section 1's marginal note on purpose"
    assert all(not item.is_blocking for item in headings)
    assert result.status == "passed"


def test_a_schedule_restarts_numbering_without_creating_a_second_section_one() -> None:
    """A schedule's paragraph 1 is not a second section 1, and must not renumber the Act."""
    pdf = build_pdf(
        [
            [
                Placement(MARGIN, 780, "SUSUNAN SEKSYEN", 13.0),
                Placement(MARGIN, 740, "1. Tajuk ringkas"),
                Placement(MARGIN, 722, "2. Tafsiran"),
            ],
            [
                Placement(MARGIN, 760, "1. Tajuk ringkas."),
                Placement(BODY, 742, "Akta ini bolehlah dinamakan Akta Contoh 2026."),
                Placement(MARGIN, 710, "2. Tafsiran."),
                Placement(BODY, 692, "Dalam Akta ini -"),
                Placement(MARGIN, 640, "JADUAL PERTAMA", 12.0),
                Placement(MARGIN, 610, "1. Perkara pertama dalam Jadual."),
                Placement(MARGIN, 592, "2. Perkara kedua dalam Jadual."),
            ],
        ]
    )
    _, body = trees(pdf)
    assert body.count("sec_1") == 1
    assert "sched_1" in body
    # The schedule's own numbering hangs beneath it and never reopens the Act's section list.
    assert any(eid.startswith("sched_1__") for eid in body)


def test_an_overlapping_letter_list_keeps_its_level() -> None:
    """`(i)` after `(h)` is the ninth paragraph. Reading it as a subparagraph renumbers the rest."""
    pdf = build_pdf(
        [
            [
                Placement(MARGIN, 780, "SUSUNAN SEKSYEN", 13.0),
                Placement(MARGIN, 740, "1. Tafsiran"),
            ],
            [
                Placement(MARGIN, 760, "1. Tafsiran."),
                Placement(BODY, 742, "(1) Dalam Akta ini -"),
                Placement(INDENT, 724, "(g) perkara ketujuh;"),
                Placement(INDENT, 706, "(h) perkara kelapan;"),
                Placement(INDENT, 688, "(i) perkara kesembilan;"),
            ],
        ]
    )
    _, body = trees(pdf)
    assert "sec_1__subsec_1__para_g" in body
    assert "sec_1__subsec_1__para_h" in body
    assert "sec_1__subsec_1__para_i" in body
    assert not any("subpara" in eid for eid in body)


def test_a_section_printed_after_a_schedule_is_caught_rather_than_absorbed() -> None:
    """Schedules are terminal in Malaysian drafting, so the parser assumes they are.

    Where that assumption is wrong the section is absorbed into the schedule — and then goes
    missing from the body tree, which is exactly what Gate L1 is for. The reading is reported
    and never promoted; it does not quietly become a wrong statement of structure.
    """
    pdf = build_pdf(
        [
            [
                Placement(MARGIN, 780, "SUSUNAN SEKSYEN", 13.0),
                Placement(MARGIN, 740, "1. Tajuk ringkas"),
                Placement(MARGIN, 722, "2. Tafsiran"),
            ],
            [
                Placement(MARGIN, 760, "1. Tajuk ringkas."),
                Placement(BODY, 742, "Akta ini bolehlah dinamakan Akta Contoh 2026."),
                Placement(MARGIN, 700, "JADUAL PERTAMA", 12.0),
                Placement(MARGIN, 670, "1. Butiran jadual."),
                Placement(MARGIN, 620, "2. Tafsiran."),
                Placement(BODY, 602, "Dalam Akta ini -"),
            ],
        ]
    )
    result = evaluate_document(extract_layout(pdf).lines)
    assert result.status == "mismatch"
    blocking = {(item.kind, item.eid) for item in result.blocking}
    assert ("missing_in_body", "sec_2") in blocking
    # The schedule is also unlisted, because this contents page does not name it. Both are
    # reported: the gate says what it found, not only what it expected.
    assert ("missing_in_arrangement", "sched_1") in blocking


def test_a_contents_page_with_no_body_is_reported_rather_than_passing() -> None:
    pdf = build_pdf(
        [
            [
                Placement(MARGIN, 780, "SUSUNAN SEKSYEN", 13.0),
                Placement(MARGIN, 740, "1. Tajuk ringkas"),
                Placement(MARGIN, 722, "2. Tafsiran"),
            ]
        ]
    )
    assert evaluate_document(extract_layout(pdf).lines).status == "empty_body"


def test_a_single_clause_bill_still_finds_where_its_body_starts() -> None:
    """Nothing 'restarts' when there is one provision, which is the boundary rule's edge case."""
    pdf = build_pdf(
        [
            [
                Placement(MARGIN, 780, "SUSUNAN FASAL", 13.0),
                Placement(MARGIN, 740, "1. Tajuk ringkas"),
            ],
            [
                Placement(MARGIN, 760, "1. Tajuk ringkas."),
                Placement(BODY, 742, "Akta ini bolehlah dinamakan Akta Contoh 2026."),
            ],
        ]
    )
    result = evaluate_document(extract_layout(pdf).lines)
    assert result.status == "passed"
    assert result.unit == "clause"


def test_numbering_that_inserts_a_lettered_section_stays_in_order() -> None:
    """5, 5A, 6 is how an inserted section is numbered; a string sort would call it out of order."""
    pdf = build_pdf(
        [
            [
                Placement(MARGIN, 780, "SUSUNAN SEKSYEN", 13.0),
                Placement(MARGIN, 740, "5. Lima"),
                Placement(MARGIN, 722, "5A. Lima A"),
                Placement(MARGIN, 704, "6. Enam"),
            ],
            [
                Placement(MARGIN, 760, "5. Lima."),
                Placement(BODY, 742, "Teks."),
                Placement(MARGIN, 710, "5A. Lima A."),
                Placement(BODY, 692, "Teks."),
                Placement(MARGIN, 660, "6. Enam."),
                Placement(BODY, 642, "Teks."),
            ],
        ]
    )
    result = evaluate_document(extract_layout(pdf).lines)
    assert result.status == "passed"
    _, body = trees(pdf)
    assert body == ["sec_5", "sec_5A", "sec_6"]


def test_a_repeated_provision_number_fails_the_gate_rather_than_passing() -> None:
    """A body with two section 1s is ambiguous, and the set comparison alone would miss it.

    Every later reference — a citation, an amendment anchor, a consolidation target — would have
    two possible referents, so this is a structural failure and not a cosmetic one.
    """
    pdf = build_pdf(
        [
            [
                Placement(MARGIN, 780, "SUSUNAN SEKSYEN", 13.0),
                Placement(MARGIN, 740, "1. Tajuk"),
                Placement(MARGIN, 722, "2. Tafsiran"),
            ],
            [
                Placement(MARGIN, 760, "1. Tajuk."),
                Placement(BODY, 742, "Teks."),
                Placement(MARGIN, 700, "2. Tafsiran."),
                Placement(BODY, 682, "Teks."),
                Placement(MARGIN, 640, "1. Tajuk lagi."),
                Placement(BODY, 622, "Teks berulang."),
            ],
        ]
    )
    result = evaluate_document(extract_layout(pdf).lines)
    assert result.status == "mismatch"
    assert [(item.kind, item.eid) for item in result.blocking] == [("duplicate_eid", "sec_1")]
    # The count says how many times it appeared, so a reviewer knows the scale without re-parsing.
    assert result.differences[0].body == "2"


def test_an_all_caps_provision_is_read_as_a_provision_not_a_heading() -> None:
    """Some reprints set a provision's opening line in capitals.

    `_looks_like_heading` cannot tell that apart from a genuine all-capitals heading by shape
    alone, so a line that opens with a recognisable provision number must be classified as a
    provision regardless of case — checked before, not after, the heading test.
    """
    pdf = build_pdf(
        [
            [
                Placement(MARGIN, 780, "SUSUNAN SEKSYEN", 13.0),
                Placement(MARGIN, 740, "1. TAJUK RINGKAS DAN PERMULAAN KUAT KUASA"),
                Placement(MARGIN, 722, "2. TAFSIRAN"),
            ],
            [
                Placement(MARGIN, 760, "1. TAJUK RINGKAS DAN PERMULAAN KUAT KUASA."),
                Placement(BODY, 742, "Akta ini bolehlah dinamakan Akta Contoh 2026."),
                Placement(MARGIN, 700, "2. TAFSIRAN."),
                Placement(BODY, 682, "Dalam Akta ini -"),
            ],
        ]
    )
    result = evaluate_document(extract_layout(pdf).lines)
    assert result.status == "passed"
    assert result.body_count == 2
