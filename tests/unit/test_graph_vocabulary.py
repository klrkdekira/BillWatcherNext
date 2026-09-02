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


# --- The classifiers added for AKN_VERSION 1.4.0 ---


def test_a_list_continues_by_the_kind_of_list_it_is_and_by_case() -> None:
    from billwatcher.graph.vocabulary import continues_run

    assert continues_run("h", "i", "paragraph")
    assert continues_run("a", "aa", "paragraph")  # an inserted paragraph
    assert continues_run("aa", "b", "paragraph")  # and the list resuming after it
    assert not continues_run("i", "ii", "paragraph")  # `(ii)` is the roman list, never an insertion
    assert not continues_run("a", "A", "paragraph")  # case is a different depth
    assert continues_run("ii", "iii", "subparagraph")
    assert not continues_run("ii", "b", "subparagraph")
    assert continues_run("A", "B", "subparagraph")
    assert continues_run("C", "D", "subparagraph")  # a letter step, though both are numerals
    assert continues_run("aa", "bb", "subparagraph")
    assert continues_run("cc", "dd", "subparagraph")  # not 200 -> 500
    assert not continues_run("C", "iii", "subparagraph")


def test_letter_insertions_and_doubled_steps() -> None:
    from billwatcher.graph.vocabulary import is_doubled_step, is_letter_insertion

    assert is_letter_insertion("a", "aa") and is_letter_insertion("aa", "b")
    assert is_letter_insertion("e", "ea") and is_letter_insertion("ea", "eb")
    assert is_letter_insertion("eb", "f") and not is_letter_insertion("eb", "g")
    assert not is_letter_insertion("a", "b") and not is_letter_insertion("i", "ii")
    assert not is_letter_insertion("b", "aa")
    assert is_doubled_step("aa", "bb") and is_doubled_step("CC", "DD")
    assert not is_doubled_step("aa", "cc") and not is_doubled_step("aa", "BB")
    assert not is_doubled_step("ii", "iii")


def test_a_line_that_breaks_off_inside_a_reference_is_recognised() -> None:
    from billwatcher.graph.vocabulary import ends_in_reference

    assert ends_in_reference("Where a detention order is suspended under subsection")
    assert ends_in_reference("dengan memasukkan, selepas sahaja perenggan")
    assert ends_in_reference('the words specified in paragraph"')
    assert not ends_in_reference("the following paragraph:")
    assert not ends_in_reference("comes into operation on a date to be appointed,")  # a comma alone
    assert not ends_in_reference("Seseorang hendaklah melaporkan kepada Pesuruhjaya.")


def test_a_heading_shaped_line_ending_like_a_sentence_is_told_apart_from_a_label() -> None:
    from billwatcher.graph.vocabulary import is_sentence_tail

    assert (
        is_sentence_tail("Jadual.")
        and is_sentence_tail("Bahagian IV.")
        and is_sentence_tail('Jadual.".')
    )
    assert not is_sentence_tail("JADUAL") and not is_sentence_tail("BAHAGIAN IV")


def test_a_quotation_may_be_introduced_mid_line_after_a_colon_or_dash() -> None:
    from billwatcher.graph.vocabulary import opens_quotation

    assert opens_quotation('"Powers of examination')
    assert opens_quotation('(c), perenggan-perenggan yang berikut: "(d) melantik anggota')
    assert opens_quotation("seksyen yang berikut: “Akses")
    assert not opens_quotation('by substituting for the word "twelve" the word "twenty-four".')
    assert not opens_quotation('the words "such company, firm,')


def test_the_back_matter_heading_may_run_into_the_statements_first_words_and_nothing_else() -> None:
    from billwatcher.graph.vocabulary import back_matter_heading

    assert back_matter_heading("HURAIAN") and back_matter_heading("EXPLANATORY STATEMENT")
    assert back_matter_heading("EXPLANATORY STATEMENT This Bill seeks to amend the Act.")
    assert back_matter_heading("EXPLANATORY STATEMENT the Bill")
    assert back_matter_heading("HURAIAN Rang Undang-Undang ini bertujuan untuk meminda Akta.")
    assert back_matter_heading("HURA1AN")  # the reading's own `I`
    assert not back_matter_heading('Huraian 1—Perkataan "kelakuan" dalam seksyen ini')
    assert not back_matter_heading("Huraian mengenai barang-barang")


def test_a_line_that_merely_begins_with_a_part_reference_is_not_a_part_heading() -> None:
    assert container_heading("BAHAGIAN II PENDAFTARAN") == ("part", "II", "PENDAFTARAN")
    assert container_heading("Part II Registration") == ("part", "II", "Registration")
    assert container_heading("BAHAGIAN III PENUBUHAN, KEANGGOTAAN DAN FUNGSI LEMBAGA") is not None
    assert container_heading("Bahagian III hingga VI Akta ini dan kesalahan-kesalahan yang") is None
    assert (
        container_heading("Bahagian 1 Jadual 4, orang berdaftar itu hendaklah mematuhi apa-")
        is None
    )


def test_a_schedule_heading_may_carry_its_enabling_provision_in_brackets() -> None:
    assert schedule_heading("FIRST SCHEDULE [Section 14]") == "1"
    assert schedule_heading("JADUAL KEDUA [Subseksyen 7(5)]") == "2"


def test_the_body_openings_include_the_bare_intituled_word_but_never_a_bare_running_header() -> (
    None
):
    from billwatcher.graph.vocabulary import body_opening

    for opening in (
        "bernama",
        "intituled",
        "ABILL",
        "A BILL",
        "MAKA, OLEH YANG DEMIKIAN, DIPERBUAT oleh Parlimen Malaysia seperti yang berikut:",
        "NOW, THEREFORE, IT IS ENACTED by the Parliament of Malaysia as follows:",
        "BE IX ENACTED by Duli Yang Maha Mulia",  # the reading's own `T`
    ):
        assert body_opening(opening), opening
    assert not body_opening("BILL")  # the running header on every page of an English bill
    assert not body_opening("Rang Undang-Undang ini akan melibatkan Kerajaan dalam perbelanjaan")
