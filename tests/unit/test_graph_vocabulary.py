"""The structural vocabulary is domain data; these assertions are the specification of it."""

from billwatcher.graph.vocabulary import (
    EID_PREFIXES,
    NODE_LABELS,
    NODE_TYPES,
    alpha_successor,
    amendment_annotations,
    arrangement_heading,
    container_heading,
    enacted_type,
    parenthesised,
    provision_number,
    resolve_letter,
    roman_successor,
    schedule_heading,
)


def test_every_node_type_has_a_label_in_both_languages() -> None:
    assert set(NODE_LABELS) == NODE_TYPES
    assert all(len(pair) == 2 and all(pair) for pair in NODE_LABELS.values())


def test_enactment_renames_a_clause_to_a_section_and_nothing_else() -> None:
    assert enacted_type("clause") == "section"
    for node_type in NODE_TYPES - {"clause"}:
        assert enacted_type(node_type) == node_type
    # Applying it twice is a no-op, so re-running the pipeline cannot rename twice.
    assert enacted_type(enacted_type("clause")) == "section"


def test_arrangement_heading_reports_language_and_unit() -> None:
    assert arrangement_heading("SUSUNAN SEKSYEN") == ("ms", "section")
    assert arrangement_heading("Susunan Fasal") == ("ms", "clause")
    assert arrangement_heading("ARRANGEMENT OF SECTIONS") == ("en", "section")
    assert arrangement_heading("Arrangement of Clauses") == ("en", "clause")
    assert arrangement_heading("BAHAGIAN I") is None


def test_a_bill_is_never_asked_to_match_a_section_tree() -> None:
    """The unit is what keeps Fasal and Seksyen apart; conflating them is HANDOFF 26.2's warning."""
    assert arrangement_heading("SUSUNAN FASAL") == ("ms", "clause")
    assert arrangement_heading("SUSUNAN SEKSYEN") == ("ms", "section")


def test_container_headings_in_both_languages_and_both_numbering_systems() -> None:
    assert container_heading("BAHAGIAN I") == ("part", "I", "")
    assert container_heading("Part IV PRELIMINARY") == ("part", "IV", "PRELIMINARY")
    assert container_heading("Bab 2") == ("chapter", "2", "")
    assert container_heading("1. Tafsiran") is None


def test_schedule_headings_including_the_unnumbered_single_schedule() -> None:
    assert schedule_heading("JADUAL PERTAMA") == "1"
    assert schedule_heading("Second Schedule") == "2"
    assert schedule_heading("JADUAL") == "1"
    assert schedule_heading("Jadual 3") == "3"
    assert schedule_heading("Jadual waktu bekerja") is None


def test_provision_numbers_require_the_trailing_stop() -> None:
    assert provision_number("5A. Kewajipan untuk melaporkan") == (
        "5A",
        "Kewajipan untuk melaporkan",
    )
    # A bare number at the margin is a page number or a cross-reference, never a provision.
    assert provision_number("5") is None
    assert provision_number("seksyen 5 melakukan") is None


def test_a_numeric_parenthesis_is_a_subsection_and_a_letter_is_left_undecided() -> None:
    assert parenthesised("(1) Seseorang hendaklah") == ("subsection", "1", "Seseorang hendaklah")
    assert parenthesised("(2A) Menteri boleh") == ("subsection", "2A", "Menteri boleh")
    # A letter token is genuinely ambiguous, so the vocabulary refuses to decide it here.
    assert parenthesised("(a) melalui apa-apa cara") == ("letter", "a", "melalui apa-apa cara")
    assert parenthesised("(iv) suatu perkara") == ("letter", "iv", "suatu perkara")
    assert parenthesised("plain text") is None


def test_the_drafting_sequences_advance_the_way_drafters_write_them() -> None:
    assert alpha_successor("a") == "b"
    assert alpha_successor("h") == "i"
    assert alpha_successor("z") == "aa"
    assert alpha_successor("az") == "ba"
    assert roman_successor("i") == "ii"
    assert roman_successor("iii") == "iv"
    assert roman_successor("viii") == "ix"


def test_an_overlapping_letter_is_resolved_by_the_list_it_continues() -> None:
    """`i`, `v`, `x`, `l`, `c`, `d` and `m` are each both a paragraph letter and a numeral.

    Reading `(i)` after `(h)` as a subparagraph would renumber every provision beneath it, so
    the sequence decides, not the token.
    """
    assert resolve_letter("i", previous="h", previous_type="paragraph") == "paragraph"
    assert resolve_letter("ii", previous="i", previous_type="subparagraph") == "subparagraph"
    assert resolve_letter("v", previous="u", previous_type="paragraph") == "paragraph"
    assert resolve_letter("c", previous="b", previous_type="paragraph") == "paragraph"
    # Nothing to continue: a leading roman `i` opens a subparagraph list, `a` a paragraph list.
    assert resolve_letter("i", previous=None, previous_type=None) == "subparagraph"
    assert resolve_letter("a", previous=None, previous_type=None) == "paragraph"


def test_eid_prefixes_follow_the_akoma_ntoso_naming_convention() -> None:
    assert EID_PREFIXES["section"] == "sec"
    assert EID_PREFIXES["clause"] == "cl"
    assert EID_PREFIXES["subsection"] == "subsec"
    assert EID_PREFIXES["subparagraph"] == "subpara"


def test_marginal_amendment_annotations_are_captured_in_both_languages() -> None:
    assert amendment_annotations("[Am. Act A1234]") == (("amendment", "Act A1234"),)
    assert amendment_annotations("[Ins. Akta A660]") == (("insertion", "Akta A660"),)
    assert amendment_annotations("text [Subs. Act A99] more [Del. Akta A1]") == (
        ("substitution", "Act A99"),
        ("deletion", "Akta A1"),
    )
    assert amendment_annotations("no annotation here") == ()
