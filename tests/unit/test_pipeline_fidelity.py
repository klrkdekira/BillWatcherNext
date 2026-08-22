"""Gate P1: does the provision tree account for the markdown it was read from?

The gate stands between a language model's reading of a document and the published corpus, so
these tests are written from the failure end: each one names a way a plausible-looking tree can be
wrong, and pins that the gate refuses it. The legitimate irregularities are pinned too — an
inserted `2A`, a Chapter restarting inside each Part, a bill opening at clause 2 — because a gate
that fires on correct documents is the failure ADR-017 warns about.
"""

from billwatcher.pipeline import fidelity
from billwatcher.pipeline.akn import assign_eids, parse_markdown_structure
from billwatcher.pipeline.tree import Node

# A short bill with no Part headings: clauses numbered straight through, one clause carrying a
# subsection/paragraph/subparagraph list, and a schedule that restarts its own numbering. Every
# word the tree can legitimately carry is here, so a faithful reading covers the document.
#
# Typeset as Parliament typesets it: a marginal note is a short label with no final stop and a body
# sentence has one, which is the distinction `akn.split_marginal_note` classifies on.
MARKDOWN = """\
1. Tajuk ringkas dan permulaan kuat kuasa

Akta ini bolehlah dinamakan Akta Pelaporan Kuari 2026.

2. Tafsiran

Dalam Akta ini, melainkan jika konteksnya menghendaki makna yang lain -

3. Kewajipan untuk melaporkan

(1) Seseorang hendaklah melaporkan kepada Pesuruhjaya dalam tempoh empat belas hari.

(a) melalui cara pertama yang ditetapkan; atau

(i) secara elektronik melalui portal rasmi;

(ii) secara bertulis kepada pejabat daerah;

(b) melalui cara kedua yang ditetapkan.

4. Penalti

Seseorang yang melanggar fasal 3 melakukan suatu kesalahan dan boleh dikenakan denda.

## JADUAL PERTAMA

1. Borang notis pelaporan bagi maksud fasal 3.

2. Kadar denda yang ditetapkan bagi maksud fasal 4.
"""

# The same bill split into two Parts, with the clause numbering running on across the boundary as
# Malaysian drafting requires: Part I ends at clause 2 and Part II opens at clause 3.
PARTS_CONTINUING = """\
## BAHAGIAN I

1. Tajuk ringkas dan permulaan kuat kuasa

Akta ini bolehlah dinamakan Akta Pelaporan Kuari 2026.

2. Tafsiran

Dalam Akta ini, melainkan jika konteksnya menghendaki makna yang lain -

## BAHAGIAN II

3. Kewajipan untuk melaporkan

Seseorang hendaklah melaporkan kepada Pesuruhjaya dalam tempoh empat belas hari.

4. Penalti

Seseorang yang melanggar fasal 3 melakukan suatu kesalahan dan boleh dikenakan denda.
"""

# The same document with Part II restarting at clause 1 — the reading a model produces when it
# mistakes each Part for a document of its own.
PARTS_RESTARTING = PARTS_CONTINUING.replace(
    "3. Kewajipan untuk melaporkan", "1. Kewajipan untuk melaporkan"
).replace("4. Penalti", "2. Penalti")


def tree_of(markdown: str, *, unit: str = "clause") -> Node:
    return with_eids(parse_markdown_structure(markdown, unit=unit))


def with_eids(root: Node) -> Node:
    assign_eids(root)
    return root


def evaluate(markdown: str, *, unit: str = "clause") -> fidelity.FidelityResult:
    return fidelity.evaluate(tree_of(markdown, unit=unit), markdown, unit=unit)


def clause_findings(result: fidelity.FidelityResult) -> list[fidelity.Finding]:
    """Only the findings about the document's clause sequence, ignoring container numbering."""
    return [item for item in result.findings if "cl_" in item.eid]


def kinds(result: fidelity.FidelityResult) -> list[str]:
    return sorted({item.kind for item in result.findings})


def clause(num: str, heading: str, text: str) -> Node:
    """One clause built by hand, for the trees no markdown reading would produce."""
    return Node(node_type="clause", num=num, heading=heading, eid="", paragraphs=[text])


def every_eid(root: Node) -> list[str]:
    found = [root.eid] if root.eid else []
    for child in root.children:
        found.extend(every_eid(child))
    return sorted(found)


def test_a_tree_that_accounts_for_its_markdown_passes() -> None:
    result = evaluate(MARKDOWN)
    assert result.status == "passed"
    assert result.passed is True
    assert result.findings == ()
    assert result.unit == "clause"
    # Four clauses, a subsection, two paragraphs, two subparagraphs, a schedule and its two items.
    assert result.node_count == 12
    # Exactly 1.0, and that matters: the words a faithful tree cannot carry are the ones that *name*
    # a structure (`JADUAL`, `BAHAGIAN`, `SUSUNAN FASAL`), which the parsers consume and which are
    # excluded from the denominator. A ceiling below 1.0 would make the threshold mean something
    # different on a short document than on a long one.
    assert result.source_tokens == result.covered_tokens
    assert result.coverage == 1.0


def test_a_duplicated_clause_number_is_blocking_and_names_the_duplicated_eid() -> None:
    """Two provisions resolving to one identifier: nothing downstream can detect it.

    `assign_eids` mints `cl_1` twice without complaint, and every citation, `hasPart` edge and
    provision IRI beneath it then has two possible referents. The repeat also trips the sequence
    check, which is why only the duplicate finding is asserted exactly here.
    """
    root = with_eids(
        Node(
            node_type="body",
            num=None,
            heading=None,
            eid="",
            children=[
                Node("clause", "1", "Tajuk ringkas", "", ["Akta ini dinamakan Akta Contoh."]),
                Node("clause", "1", "Tajuk ringkas lagi", "", ["Akta ini dinamakan Akta Contoh."]),
            ],
        )
    )
    result = fidelity.evaluate(root, "1. Tajuk ringkas", unit="clause")
    duplicates = [item for item in result.findings if item.kind == "duplicate_eid"]
    assert [(item.eid, item.found) for item in duplicates] == [("cl_1", "2")]
    assert all(item.is_blocking for item in duplicates)
    assert result.status == "mismatch"
    assert result.passed is False


def test_a_provision_with_no_printed_number_is_blocking() -> None:
    """`assign_eids` falls back to the parent's eId for a node with no `num`.

    That silently merges two provisions into one identifier — the subsection here inherits
    `cl_1` from the clause above it — so the missing number shows up as a duplicate as well.
    Refusing the tree is the only reading that keeps an eId a unique name.
    """
    subsection = Node("subsection", None, None, "", ["Seseorang hendaklah melaporkan."])
    root = with_eids(
        Node(
            node_type="body",
            num=None,
            heading=None,
            eid="",
            children=[Node("clause", "1", "Kewajipan", "", [], [subsection])],
        )
    )
    assert subsection.eid == "cl_1"  # the merge this finding exists to catch
    result = fidelity.evaluate(root, "1. Kewajipan", unit="clause")
    assert ("missing_num", "cl_1") in [(item.kind, item.eid) for item in result.blocking]
    assert ("duplicate_eid", "cl_1") in [(item.kind, item.eid) for item in result.blocking]
    assert result.status == "mismatch"


def test_a_skipped_clause_number_is_a_sequence_gap_naming_expected_and_found() -> None:
    markdown = MARKDOWN.replace("3. Kewajipan untuk melaporkan", "5. Kewajipan untuk melaporkan")
    result = evaluate(markdown)
    gaps = [item for item in result.findings if item.kind == "sequence_gap"]
    assert [(item.eid, item.expected, item.found) for item in gaps] == [("cl_5", "3", "5")]
    assert result.status == "mismatch"


def test_a_backwards_clause_number_is_a_sequence_order_finding() -> None:
    """1, 2, 3, then 1 again is the table-of-contents bleed signature.

    A model that reads the Arrangement of Sections as body provisions produces exactly this: a
    plausible run of clauses followed by the document starting over. A set comparison would never
    see it, which is why continuity is checked and not merely membership.
    """
    markdown = MARKDOWN.replace("4. Penalti", "1. Penalti")
    result = evaluate(markdown)
    out_of_order = [item for item in result.findings if item.kind == "sequence_order"]
    assert [(item.eid, item.expected, item.found) for item in out_of_order] == [
        ("cl_1", "after 3", "1")
    ]
    assert result.status == "mismatch"


def test_a_clause_inserted_as_2a_between_2_and_3_passes() -> None:
    """The one legitimate irregularity in Malaysian numbering, modelled rather than tolerated.

    The run still starts at 1, because a document-wide run that starts anywhere else is itself a
    blocking finding — a bill printed 1, 2, 3 and read as 5, 5A, 6 is continuous by construction and
    wrong in every eId it mints.
    """
    markdown = """\
1. Tajuk ringkas

Akta ini bolehlah dinamakan Akta Pelaporan Kuari 2026.

2. Kewajipan untuk melaporkan

Seseorang hendaklah melaporkan kepada Pesuruhjaya.

2A. Kewajipan tambahan untuk melaporkan

Seseorang hendaklah juga melaporkan kepada Pendaftar.

3. Penalti

Seseorang yang melanggar melakukan suatu kesalahan.
"""
    result = evaluate(markdown)
    assert [child.num for child in tree_of(markdown).children] == ["1", "2", "2A", "3"]
    assert result.status == "passed"
    assert result.findings == ()


def test_clause_numbering_continues_across_a_part_boundary_rather_than_restarting() -> None:
    """Scope is the subtlest thing this gate gets right.

    Clauses do not restart inside a Part, but the parser nests them under the open Part — so a
    gate that checked every sibling list would demand that Part II's first clause be numbered 1
    and would fire on almost every multi-Part bill. Part II opening at clause 3 is correct
    drafting and must produce no clause finding at all.
    """
    result = evaluate(PARTS_CONTINUING)
    assert clause_findings(result) == []
    assert result.status == "passed"


def test_a_part_that_restarts_its_clause_numbering_is_caught() -> None:
    """The other half of the same rule: per-Part numbering is a misreading, not a dialect."""
    result = evaluate(PARTS_RESTARTING)
    found = [(item.kind, item.eid, item.expected, item.found) for item in clause_findings(result)]
    assert found == [("sequence_order", "part_II__cl_1", "after 2", "1")]
    assert result.status == "mismatch"


def test_a_run_that_is_continuous_but_starts_at_the_wrong_number_is_caught() -> None:
    """Adjacent-pair checking is blind to a constant offset, and this is the offset that matters.

    A tree numbered 3, 4, 5 for a document printed 1, 2, 3 is continuous by construction, and set
    coverage does not move at all, because every word of the provision text is still there and only
    the numbers are wrong. Every eId, every provision IRI and every citation in the document is then
    off by two — a well-formed reading that is wrong about the one thing an identifier must get
    right. The first number is the one anchor the document itself supplies.
    """
    markdown = """\
3. Tajuk ringkas dan permulaan kuat kuasa

Akta ini bolehlah dinamakan Akta Pelaporan Kuari 2026.

4. Tafsiran

Dalam Akta ini, melainkan jika konteksnya menghendaki makna yang lain -

5. Penalti

Seseorang yang melanggar fasal 3 melakukan suatu kesalahan.
"""
    result = evaluate(markdown)

    assert [(item.kind, item.eid, item.expected, item.found) for item in result.findings] == [
        ("unanchored_run", "cl_3", "one of ['1', '2']", "3")
    ]
    assert result.status == "mismatch"
    # Nothing else noticed: the run is continuous and the words are all accounted for.
    assert result.coverage == 1.0
    assert sorted(fidelity.ANCHOR_NUMBERS) == ["1", "2"]


def test_a_document_whose_first_clause_is_numbered_2_is_accepted() -> None:
    """An amendment bill occasionally opens at 2, after a clause 1 that is only its short title, so
    the anchor is a small set rather than a bare `== "1"`."""
    markdown = """\
2. Kewajipan untuk melaporkan

Seseorang hendaklah melaporkan kepada Pesuruhjaya dalam tempoh empat belas hari.

3. Penalti

Seseorang yang melanggar melakukan suatu kesalahan dan boleh dikenakan denda.
"""
    result = evaluate(markdown)
    assert result.findings == ()
    assert result.status == "passed"


def test_one_provision_type_at_two_depths_is_read_in_document_order() -> None:
    """A document-wide run has to be assembled depth-first, which is document order.

    This is what a bill with an unheaded opening section looks like once an extractor reads it:
    clause 3 sits directly under the body, between two Parts that hold the others. Collected level
    by level the run comes out 3, 1, 2, 4 — a backwards step and a gap that are nowhere in the
    document — so the findings were fabricated by the traversal rather than found in the tree.
    """
    markdown = """\
## BAHAGIAN I

1. Tajuk ringkas

Akta ini bolehlah dinamakan Akta Contoh 2026.

2. Tafsiran

Dalam Akta ini, perkataan tersebut mempunyai makna yang diberikan kepadanya.

3. Kewajipan untuk melaporkan

Seseorang hendaklah melaporkan kepada Pesuruhjaya dalam tempoh yang ditetapkan.

## BAHAGIAN II

4. Penalti

Seseorang yang melanggar melakukan suatu kesalahan dan boleh dikenakan denda.
"""
    clause_1 = clause("1", "Tajuk ringkas", "Akta ini bolehlah dinamakan Akta Contoh 2026.")
    clause_2 = clause(
        "2",
        "Tafsiran",
        "Dalam Akta ini, perkataan tersebut mempunyai makna yang diberikan kepadanya.",
    )
    clause_3 = clause(
        "3",
        "Kewajipan untuk melaporkan",
        "Seseorang hendaklah melaporkan kepada Pesuruhjaya dalam tempoh yang ditetapkan.",
    )
    clause_4 = clause(
        "4",
        "Penalti",
        "Seseorang yang melanggar melakukan suatu kesalahan dan boleh dikenakan denda.",
    )
    root = with_eids(
        Node(
            node_type="body",
            num=None,
            heading=None,
            eid="",
            children=[
                Node("part", "I", None, "", [], [clause_1, clause_2]),
                clause_3,
                Node("part", "II", None, "", [], [clause_4]),
            ],
        )
    )
    # Clause 3 hangs directly off the body, between the two Parts that hold the others.
    assert set(every_eid(root)) == {
        "part_I",
        "part_I__cl_1",
        "part_I__cl_2",
        "cl_3",
        "part_II",
        "part_II__cl_4",
    }

    result = fidelity.evaluate(root, markdown, unit="clause")
    assert result.findings == ()
    assert result.status == "passed"


def test_roman_numbered_parts_in_sequence_pass() -> None:
    """`BAHAGIAN I` then `BAHAGIAN II` is how Malaysian bills are drafted, not a gap.

    `I` is both a valid roman numeral and a valid paragraph letter, so a comparison that ignores
    the node type reads this as a letter sequence and expects `j` — which would reject essentially
    every multi-Part bill in the corpus on its container numbering alone, the exact "fires on
    almost every document" failure ADR-017 warns against.
    """
    result = evaluate(PARTS_CONTINUING)
    assert [item for item in result.findings if item.eid.startswith("part_")] == []
    assert result.status == "passed"


def test_a_genuinely_skipped_roman_part_is_still_caught() -> None:
    """Reading roman numerals correctly must not mean declining to judge them."""
    markdown = PARTS_CONTINUING.replace("BAHAGIAN II", "BAHAGIAN III")
    result = evaluate(markdown)
    parts = [item for item in result.findings if item.eid.startswith("part_")]
    assert [(item.kind, item.expected, item.found) for item in parts] == [
        ("sequence_gap", "II", "III")
    ]


def test_an_arabic_numbered_part_sequence_passes() -> None:
    """Both spellings are published; neither is the one the gate happens to understand."""
    markdown = PARTS_CONTINUING.replace("BAHAGIAN I", "BAHAGIAN 1").replace(
        "BAHAGIAN II", "BAHAGIAN 2"
    )
    result = evaluate(markdown)
    assert [item for item in result.findings if item.eid.startswith("part_")] == []
    assert result.status == "passed"


def test_a_chapter_restarting_inside_each_part_is_correct_drafting_and_passes() -> None:
    """A Chapter is numbered within its Part, so `BAHAGIAN II` opening at `Bab 1` is not a repeat.

    Treating chapters as one document-wide run rejected every bill that uses them — the same
    "fires on correct documents" failure ADR-017 warns against, one level down from the Part/clause
    scope distinction.
    """
    markdown = """\
## BAHAGIAN I

### Bab 1

1. Tajuk ringkas

Akta ini bolehlah dinamakan Akta Contoh 2026.

## BAHAGIAN II

### Bab 1

2. Tafsiran

Dalam Akta ini, perkataan tersebut mempunyai makna yang diberikan.
"""
    result = evaluate(markdown)

    assert "chapter" in fidelity.RESTARTING_TYPES
    assert result.findings == ()
    assert result.status == "passed"
    # Each Part's Chapter 1 is a different provision with an identifier of its own.
    eids = every_eid(tree_of(markdown))
    assert "part_I__chp_1" in eids and "part_II__chp_1" in eids


def test_subsections_and_paragraphs_restart_under_each_parent_without_a_gap() -> None:
    """Every clause has a subsection (1); every subsection a paragraph (a). That is not a repeat.

    Continuity is per sibling list for the types that genuinely restart, so two clauses each
    opening `(1)` is correct and must not be read as a duplicate or a backwards step.
    """
    markdown = """\
1. Kewajipan untuk melaporkan

(1) Seseorang hendaklah melaporkan kepada Pesuruhjaya.

(a) melalui cara pertama yang ditetapkan;

(b) melalui cara kedua yang ditetapkan.

(2) Laporan itu hendaklah dibuat dalam tempoh empat belas hari.

2. Penalti

(1) Seseorang yang melanggar fasal 1 melakukan suatu kesalahan.

(a) bagi kesalahan pertama, denda tidak melebihi lima ribu ringgit;

(b) bagi kesalahan kedua, denda tidak melebihi sepuluh ribu ringgit.
"""
    result = evaluate(markdown)
    assert result.status == "passed"
    assert result.findings == ()
    eids = every_eid(tree_of(markdown))
    assert "cl_1__subsec_1__para_a" in eids
    assert "cl_2__subsec_1__para_a" in eids  # paragraph (a) again, under its own parent


def test_a_tree_that_drops_a_whole_schedule_fails_on_low_text_coverage() -> None:
    """The failure no structural check can see: a well-formed tree missing a chunk of the page."""
    root = tree_of(MARKDOWN)
    root.children = [child for child in root.children if child.node_type != "schedule"]
    result = fidelity.evaluate(root, MARKDOWN, unit="clause")
    coverage = [item for item in result.findings if item.kind == "low_text_coverage"]
    assert [(item.eid, item.expected) for item in coverage] == [("", ">=0.9500")]
    assert coverage[0].is_blocking
    assert result.status == "mismatch"
    assert result.coverage is not None and result.coverage < fidelity.MIN_TEXT_COVERAGE


def test_an_arrangement_of_sections_the_tree_omits_still_passes_coverage() -> None:
    """Why coverage is measured over *distinct* tokens rather than every word.

    A correct extractor drops the Arrangement of Sections, and every entry in it repeats the
    marginal note of the body provision it lists — so it contributes no new distinct word, and set
    coverage is insensitive to how long the contents page is. A multiset ratio over the same text
    would charge the tree for every entry and fail a correct reading of a long bill.
    """
    arrangement = """\
# SUSUNAN FASAL

1. Tajuk ringkas dan permulaan kuat kuasa

2. Tafsiran

3. Kewajipan untuk melaporkan

4. Penalti

"""
    body_only = fidelity.evaluate(tree_of(MARKDOWN), MARKDOWN, unit="clause")
    result = fidelity.evaluate(tree_of(MARKDOWN), arrangement + MARKDOWN, unit="clause")
    assert result.status == "passed"
    assert result.findings == ()
    # Four extra contents entries cost nothing at all. Every word in the entries is already in the
    # body provision it lists, and the heading's own words (`susunan`, `fasal`) name a structure
    # rather than belonging to one, so they are not in the denominator either. Prepending a whole
    # contents page therefore leaves the score exactly where it was.
    assert result.coverage == body_only.coverage == 1.0
    assert result.source_tokens == body_only.source_tokens
    # The multiset ratio, by contrast, does move — which is precisely why it never blocks.
    assert result.repeated_token_ratio is not None and body_only.repeated_token_ratio is not None
    assert result.repeated_token_ratio > body_only.repeated_token_ratio


def test_a_faithful_reading_of_a_bill_with_a_cover_page_and_an_enacting_formula_scores_one() -> (
    None
):
    """The fix that decided whether this gate was usable at all on the real corpus.

    A real bill PDF opens with a cover page, the long title, the presenter and the enacting formula.
    No provision tree contains any of it — the parser attaches pre-provision text to the tree's
    synthetic root and the walk skips it — so counting it scored a *faithful* reading of a real bill
    0.71-0.81, and the 0.95 default would have rejected essentially the whole corpus while looking
    like a strict quality bar. Coverage is measured from the document's first structural marker,
    which is the text the tree is answerable for.
    """
    front_matter = """\
RANG UNDANG-UNDANG

bernama

Suatu Akta untuk mengadakan peruntukan bagi pelaporan kuari dan bagi perkara yang berkaitan
dengannya.

DIPERBUAT oleh Parlimen Malaysia seperti yang berikut:

"""
    body_only = fidelity.evaluate(tree_of(MARKDOWN), MARKDOWN, unit="clause")
    with_front_matter = fidelity.evaluate(
        tree_of(front_matter + MARKDOWN), front_matter + MARKDOWN, unit="clause"
    )

    assert with_front_matter.status == "passed"
    assert with_front_matter.findings == ()
    assert with_front_matter.coverage == 1.0
    # The same denominator either way: the front matter is not merely forgiven, it is not counted.
    assert with_front_matter.source_tokens == body_only.source_tokens
    assert with_front_matter.covered_tokens == body_only.covered_tokens


def test_a_huraian_and_implikasi_kewangan_back_matter_is_not_counted() -> None:
    """The first real-corpus finding: every one of 181 pilot documents carried a "HURAIAN"
    (Explanatory Statement) section, usually followed by an "IMPLIKASI KEWANGAN" (Financial
    Implications) note, and neither is enacted text -- no tree holds either, any more than it
    holds the front matter the previous test excludes."""
    back_matter = """\

## HURAIAN

Rang Undang-Undang ini bertujuan untuk mengadakan peruntukan bagi pelaporan kuari. Fasal 3
bertujuan untuk mengadakan peruntukan bagi kewajipan melaporkan.

## IMPLIKASI KEWANGAN

Rang Undang-Undang ini tidak melibatkan Kerajaan Persekutuan dalam apa-apa perbelanjaan.
"""
    body_only = fidelity.evaluate(tree_of(MARKDOWN), MARKDOWN, unit="clause")
    with_back_matter = fidelity.evaluate(
        tree_of(MARKDOWN), MARKDOWN + back_matter, unit="clause"
    )

    assert with_back_matter.status == "passed"
    assert with_back_matter.findings == ()
    assert with_back_matter.coverage == 1.0
    assert with_back_matter.source_tokens == body_only.source_tokens
    assert with_back_matter.covered_tokens == body_only.covered_tokens


def test_a_bare_arrangement_before_the_enacting_formula_does_not_widen_the_denominator() -> (
    None
):
    """The Arrangement-bleed bug in a form the existing regex-heading tests do not reach.

    Printed as a markdown heading (`# SUSUNAN FASAL`), the Arrangement is invisible to
    `container_heading`/`provision_number` and is skipped by construction. Printed as bare text --
    what a real Malaysian bill's cover page actually looks like -- its own listing ("BAHAGIAN I",
    "1. Tajuk ringkas...") satisfies those same patterns just as well as the real body does, so the
    naive "first match" scan locks onto the Arrangement instead of skipping past it, and every word
    of the long title and enacting formula *between* the Arrangement and the real body gets swept
    into the denominator. The enacting formula can never be preceded by the bill's own text, so it
    is the more reliable anchor once it is found after that first, ambiguous match.
    """
    bare_front_matter = """\
BAHAGIAN I

1. Tajuk ringkas dan permulaan kuat kuasa

2. Tafsiran

3. Kewajipan untuk melaporkan

4. Penalti

Suatu Akta untuk mengadakan peruntukan bagi pelaporan kuari dan bagi perkara yang berkaitan
dengannya.

DIPERBUAT oleh Parlimen Malaysia seperti yang berikut:

"""
    body_only = fidelity.evaluate(tree_of(MARKDOWN), MARKDOWN, unit="clause")
    result = fidelity.evaluate(
        tree_of(MARKDOWN), bare_front_matter + MARKDOWN, unit="clause"
    )

    assert result.status == "passed"
    assert result.findings == ()
    assert result.coverage == 1.0
    assert result.source_tokens == body_only.source_tokens
    assert result.covered_tokens == body_only.covered_tokens


def test_html_table_markup_is_not_counted_and_does_not_glue_adjacent_cells_together() -> None:
    """MinerU renders a schedule as literal HTML (`<table><tr><td>...`), never as the plain
    numbered lines the regex extractor and the LLM's own tree both produce for it. A faithful
    reading must not be charged for tag names or entities -- and stripping a tag must not glue two
    cells' text into one fictitious word. (A table's own header-row words, e.g. "Bil."/"Perihalan",
    are a separate, smaller and still-open gap: real documents score comfortably above threshold
    without also excluding them, so this test does not claim they are handled.)
    """
    html_schedule = MARKDOWN.replace(
        """\
## JADUAL PERTAMA

1. Borang notis pelaporan bagi maksud fasal 3.

2. Kadar denda yang ditetapkan bagi maksud fasal 4.
""",
        """\
## JADUAL PERTAMA

<table><tr><td>1.</td><td>Borang notis pelaporan &quot;bagi&#x27; maksud fasal 3.</td></tr>
<tr><td>2.</td><td>Kadar denda yang ditetapkan bagi maksud fasal 4.</td></tr></table>
""",
    )
    assert html_schedule != MARKDOWN  # the replacement actually matched something

    body_only = fidelity.evaluate(tree_of(MARKDOWN), MARKDOWN, unit="clause")
    result = fidelity.evaluate(tree_of(MARKDOWN), html_schedule, unit="clause")

    assert result.status == "passed"
    assert result.findings == ()
    assert result.coverage == 1.0
    # Not merely "still passes" -- the exact same denominator, so the tags and the entities
    # contributed nothing at all.
    assert result.source_tokens == body_only.source_tokens
    view = fidelity._tokens(fidelity._extractor_view(html_schedule))
    assert "borang" in view
    assert "notis" in view
    # If the `<td>` boundary between "notis" and the next cell's text were not replaced with a
    # space, the two would run together into one token instead of two adjacent ones.
    assert "notispelaporan" not in view


def test_an_escaped_angle_bracket_inside_a_table_cell_does_not_delete_real_text() -> None:
    """Found in review: unescaping entities *before* stripping tags is backwards. An escaped
    "&lt;" inside a cell's own text decodes to a literal "<", which the tag-stripping regex would
    then read as a real tag opening and consume everything up to the next real ">" -- silently
    deleting whatever body text happened to sit in between, in the direction that hides a real
    extraction failure rather than flags one."""
    html_schedule = MARKDOWN.replace(
        """\
## JADUAL PERTAMA

1. Borang notis pelaporan bagi maksud fasal 3.

2. Kadar denda yang ditetapkan bagi maksud fasal 4.
""",
        """\
## JADUAL PERTAMA

<table><tr><td>1.</td><td>Umur &lt; 18 tahun: notis pelaporan bagi maksud fasal 3.</td></tr>
<tr><td>2.</td><td>Kadar denda yang ditetapkan bagi maksud fasal 4.</td></tr></table>
""",
    )
    view = fidelity._tokens(fidelity._extractor_view(html_schedule))
    # A real, later word that a backwards ordering would delete along with the "<18 tahun..." run.
    assert "denda" in view
    assert "ditetapkan" in view


def test_an_isolated_table_cell_reading_huraian_is_not_mistaken_for_the_back_matter() -> None:
    """Found in review: "huraian" ("particulars"/"description") is an entirely ordinary column
    header, and MinerU may lay a cell's text on its own physical line. `_BACK_MATTER_HEADING_RE`
    matches a whole line, so without collapsing a table to one line first, that isolated header
    line is indistinguishable from the real back-matter section title and truncates everything
    after it -- including the rest of the schedule."""
    html_schedule = MARKDOWN.replace(
        """\
## JADUAL PERTAMA

1. Borang notis pelaporan bagi maksud fasal 3.

2. Kadar denda yang ditetapkan bagi maksud fasal 4.
""",
        """\
## JADUAL PERTAMA

<table>
<tr><td>Bil.</td><td>
Huraian
</td></tr>
<tr><td>1.</td><td>Borang notis pelaporan bagi maksud fasal 3.</td></tr>
<tr><td>2.</td><td>Kadar denda yang ditetapkan bagi maksud fasal 4.</td></tr>
</table>
""",
    )
    view = fidelity._tokens(fidelity._extractor_view(html_schedule))
    assert "denda" in view
    assert "ditetapkan" in view


def test_a_spurious_early_huraian_heading_does_not_truncate_the_real_body() -> None:
    """The edge case a first-corpus committee-stage amendment paper actually carried: a short
    "## HURAIAN" note on the single amendment itself, printed *before* the reprinted bill's own
    body even starts, followed much later by the bill's real, full Explanatory Statement. Matching
    the first "HURAIAN" anywhere would truncate the measured text down to that opening sliver and
    discard the entire well-covered body from the denominator -- the back-matter search has to
    start no earlier than the real body does.
    """
    premature_note = """\
## HURAIAN

Pindaan ini bertujuan untuk meminda subseksyen 5(2) Akta ibu.

"""
    body_only = fidelity.evaluate(tree_of(MARKDOWN), MARKDOWN, unit="clause")
    result = fidelity.evaluate(
        tree_of(MARKDOWN), premature_note + MARKDOWN, unit="clause"
    )

    assert result.status == "passed"
    assert result.findings == ()
    assert result.coverage == 1.0
    assert result.source_tokens == body_only.source_tokens
    assert result.covered_tokens == body_only.covered_tokens


def test_a_quoted_section_of_the_act_being_amended_is_not_checked_against_the_bill_numbering() -> (
    None
):
    """A clause-numbered bill can contain a "section"-typed node: an existing Act's section,
    quoted in full because this clause substitutes or inserts it. That section's own number (its
    identity in the *other* Act) has nothing to do with this bill's clause sequence, so a bill that
    quotes sections 31 and 50A back to back must not be read as a "section" run with a fictitious
    gap between them."""
    root = tree_of(MARKDOWN)
    quoted = Node("section", "31", "Peruntukan asal", "", paragraphs=["Teks seksyen 31."])
    quoted_far = Node("section", "50A", "Peruntukan baru", "", paragraphs=["Teks seksyen 50A."])
    # Appended under the same clause a real "substitute this section" instruction would use.
    root.children[2].children.append(quoted)
    root.children[3].children.append(quoted_far)
    assign_eids(root)

    result = fidelity.evaluate(root, MARKDOWN, unit="clause")

    sequence_findings = {finding.kind for finding in result.findings}
    assert not sequence_findings & {"sequence_gap", "sequence_order"}


def test_the_bills_own_provisions_mistyped_as_the_wrong_unit_are_still_checked() -> None:
    """The quotation exclusion above is conditional on nesting, not on type alone.

    A "section"-typed node that never sits inside a real clause of this bill is not a quotation —
    it is the extractor's own reading of the document's real provisions, typed wrong, which is
    exactly the "model drops or mistypes a provision" failure this gate exists to catch. Skipping
    it purely because its type does not match `unit` would silently defeat that."""
    root = Node("body", None, None, "")
    root.children = [
        Node("section", "1", "Tajuk ringkas", "", paragraphs=["Teks."]),
        Node("section", "2", "Tafsiran", "", paragraphs=["Teks."]),
        # Clause 3 is missing entirely -- the reading the gate must still catch.
        Node("section", "4", "Penalti", "", paragraphs=["Teks."]),
    ]
    assign_eids(root)

    result = fidelity.evaluate(root, MARKDOWN, unit="clause")

    gaps = [finding for finding in result.findings if finding.kind == "sequence_gap"]
    assert [(item.expected, item.found) for item in gaps] == [("3", "4")]


def test_a_lettered_subparagraph_run_that_also_looks_like_roman_numerals_is_not_a_false_gap() -> (
    None
):
    """`subparagraph` is numbered in roman at one depth (`i`, `ii`) and in plain letters at
    another (`A`, `B`, `C`...) -- the node type alone cannot say which a given run is, and every
    single letter from `c`/`d`/`i`/`l`/`m`/`v`/`x` is *also* a valid roman numeral. A real `A, B, C,
    D` run was read as a jump from roman 100 to roman 500 and rejected expecting `CI`."""
    root = Node("body", None, None, "")
    clause = Node("clause", "1", "Pindaan", "", paragraphs=["Akta ibu dipinda—"])
    subpara_a = Node("subparagraph", "A", None, "", paragraphs=["dengan memasukkan seksyen 5A;"])
    subpara_b = Node("subparagraph", "B", None, "", paragraphs=["dengan memasukkan seksyen 5B;"])
    subpara_c = Node("subparagraph", "C", None, "", paragraphs=["dengan memasukkan seksyen 5C;"])
    subpara_d = Node("subparagraph", "D", None, "", paragraphs=["dengan memasukkan seksyen 5D."])
    clause.children = [subpara_a, subpara_b, subpara_c, subpara_d]
    root.children = [clause]
    assign_eids(root)

    result = fidelity.evaluate(root, "1. Pindaan\n\nA. x\n\nB. x\n\nC. x\n\nD. x\n", unit="clause")

    sequence_findings = {finding.kind for finding in result.findings}
    assert not sequence_findings & {"sequence_gap", "sequence_order"}


def test_a_genuine_gap_in_a_roman_numbered_subparagraph_run_is_still_caught() -> None:
    """The letter-reading rescue must not swallow a real roman gap: `i`, `ii` then `iv` is not
    the letter sequence `i, ii, iv` (which is not consecutive either), it is roman 1, 2, 4."""
    root = Node("body", None, None, "")
    clause = Node("clause", "1", "Pindaan", "", paragraphs=["Akta ibu dipinda—"])
    subpara_i = Node("subparagraph", "i", None, "", paragraphs=["dengan memasukkan seksyen 5A;"])
    subpara_ii = Node("subparagraph", "ii", None, "", paragraphs=["dengan memasukkan seksyen 5B;"])
    subpara_iv = Node("subparagraph", "iv", None, "", paragraphs=["dengan memasukkan seksyen 5D."])
    clause.children = [subpara_i, subpara_ii, subpara_iv]
    root.children = [clause]
    assign_eids(root)

    result = fidelity.evaluate(root, "1. Pindaan\n\ni. x\n\nii. x\n\niv. x\n", unit="clause")

    gaps = [finding for finding in result.findings if finding.kind == "sequence_gap"]
    assert [(item.expected, item.found) for item in gaps] == [("iii", "iv")]


def test_the_repeated_token_ratio_is_reported_and_never_blocks() -> None:
    """A useful calibration number and a terrible gate, so it is recorded and not judged."""
    result = evaluate(MARKDOWN)
    assert result.repeated_token_ratio is not None
    assert result.repeated_token_ratio > 1.0  # the sample repeats plenty of words
    assert result.status == "passed"
    assert result.as_detail()["repeated_token_ratio"] == round(result.repeated_token_ratio, 4)
    assert not any("repeat" in kind for kind in fidelity.BLOCKING_FINDINGS)
    assert sorted(fidelity.BLOCKING_FINDINGS) == [
        "duplicate_eid",
        "low_text_coverage",
        "missing_num",
        "no_source_text",
        "sequence_gap",
        "sequence_order",
        "unanchored_run",
    ]


def test_a_source_with_nothing_to_cover_is_reported_rather_than_scored_or_passed() -> None:
    """Two failures in one, and the second is the dangerous one.

    Scoring an empty source 1.0 would report a perfect reading of nothing at all, so coverage is
    `None` and simply absent from the verdict. But a tree cannot be said to account for a document
    there is no text for either, so the verdict blocks: this is exactly what MinerU produces for a
    scan it recovered nothing from, and passing it would publish an invented tree against a document
    nobody has read.
    """
    result = fidelity.evaluate(tree_of(MARKDOWN), "", unit="clause")
    assert result.source_tokens == 0
    assert result.coverage is None
    assert result.repeated_token_ratio is None
    assert "coverage" not in result.as_detail()
    assert result.status == "no_source_text"
    assert result.passed is False
    assert [(item.kind, item.is_blocking) for item in result.findings] == [("no_source_text", True)]


def test_a_tree_invented_against_page_markers_alone_is_blocked_not_passed() -> None:
    """What a failed scan looks like: a markdown file of `<!-- page N -->` markers and nothing else.

    The page comments carry no text of their own, so there is nothing to score the tree against —
    and the tree here is a plausible-looking clause that no document supports.
    """
    invented = Node(
        node_type="body",
        num=None,
        heading=None,
        eid="",
        children=[
            Node("clause", "1", "Tajuk ringkas", "cl_1", ["Akta ini dinamakan Akta Hantu 2026."])
        ],
    )
    result = fidelity.evaluate(invented, "<!-- page 1 -->\n\n<!-- page 2 -->\n", unit="clause")

    assert result.status == "no_source_text"
    assert result.status in fidelity.STATUSES
    assert result.passed is False
    assert result.node_count == 1
    finding = result.findings[0]
    assert (finding.kind, finding.found) == ("no_source_text", "1")
    assert finding.is_blocking
    assert result.as_detail()["blocking_count"] == 1


def test_an_empty_tree_is_reported_as_such_rather_than_as_a_pass() -> None:
    root = Node(node_type="body", num=None, heading=None, eid="")
    result = fidelity.evaluate(root, MARKDOWN, unit="clause")
    assert result.status == "empty_tree"
    assert result.node_count == 0
    assert result.passed is False


def test_as_detail_bounds_its_findings_and_says_that_it_truncated() -> None:
    """A verdict with ten thousand lines is not read by anybody (the same rule Gate L1 follows).

    The source is the one word the tree does carry, so the only findings are the sixty being
    counted: an unscoreable source would add a `no_source_text` finding of its own.
    """
    root = Node(
        node_type="body",
        num=None,
        heading=None,
        eid="",
        children=[Node("clause", None, None, f"cl_{index}", ["Teks."]) for index in range(1, 61)],
    )
    result = fidelity.evaluate(root, "Teks.", unit="clause")
    assert len(result.findings) == 60
    assert kinds(result) == ["missing_num"]
    detail = result.as_detail()
    assert len(detail["findings"]) == 50
    assert detail["truncated"] is True
    assert detail["blocking_count"] == 60
    assert detail["gate"] == "P1"
    assert detail["status"] == "mismatch"


def test_a_failure_verdict_carries_the_error_and_no_tree() -> None:
    """The verdict for a document whose extraction raised before a tree existed."""
    result = fidelity.failure("RuntimeError: the endpoint timed out")
    assert result.status == "failed"
    assert result.passed is False
    assert result.node_count == 0
    assert result.coverage is None
    detail = result.as_detail()
    assert detail["error"] == "RuntimeError: the endpoint timed out"
    assert detail["min_coverage"] == fidelity.MIN_TEXT_COVERAGE
    assert detail["findings"] == []
