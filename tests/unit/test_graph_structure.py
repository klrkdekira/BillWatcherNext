"""Reading a bill's provision hierarchy out of markdown, and rendering it as Akoma Ntoso.

The tree is the domain object and the XML is one serialisation of it (`graph.structure` and
`graph.render`), so both are exercised here against the same fixtures: a renderer change that
silently altered what a provision *is* would otherwise pass a structure-only suite.
"""

from xml.etree import ElementTree as ET

import pytest

from billwatcher.frbr import FrbrIdentityError, identity_from_bill
from billwatcher.graph.akn_schema import validate_akn
from billwatcher.graph.render import AKN_NS, frbr_date, render_akn
from billwatcher.graph.structure import (
    MAX_MARGINAL_NOTE_CHARS,
    RegexMarkdownStructureExtractor,
    assign_eids,
    infer_language_and_unit,
    parse_markdown_structure,
    split_marginal_note,
)
from billwatcher.graph.tree import Node

# Typeset the way Parliament typesets it, which `tests/support/pdfs.py` captures from the real
# thing: a marginal note is a short label with no final stop (`Tajuk ringkas`), and a body sentence
# has one. The distinction is load-bearing rather than cosmetic — `split_marginal_note` classifies
# on it, and a note becomes the node's `heading`, which is published under a different rights rule
# from body text (ADR-027).
BODY_MARKDOWN = """\
## BAHAGIAN I

### PERMULAAN

1. Tajuk ringkas dan permulaan kuat kuasa

Akta ini bolehlah dinamakan Akta Contoh 2026.

2. Tafsiran

Dalam Akta ini, melainkan jika konteksnya menghendaki makna yang lain -

## BAHAGIAN II

### KEWAJIPAN MELAPORKAN

3. Kewajipan untuk melaporkan

(1) Seseorang hendaklah melaporkan kepada Pesuruhjaya

(a) melalui cara pertama yang ditetapkan.

(i) cara elektronik.

(ii) cara bertulis.

(b) atau cara kedua.

4. Penalti

Seseorang yang melanggar seksyen 3 melakukan suatu kesalahan.
"""

# An amendment bill, which is the shape that makes the classification matter: there is no marginal
# note at all and the whole provision runs in after the number.
AMENDMENT_MARKDOWN = """\
1. Tajuk ringkas

Akta ini bolehlah dinamakan Akta Kanun Keseksaan (Pindaan) 2026.

2. Kanun Keseksaan [Akta 574] dipinda dalam seksyen 375 dengan menggantikan perkataan "lima" \
dengan perkataan "sepuluh".
"""

RUN_IN_PROVISION = (
    'Kanun Keseksaan [Akta 574] dipinda dalam seksyen 375 dengan menggantikan perkataan "lima" '
    'dengan perkataan "sepuluh".'
)

# Every fact a permanent identifier is built from is on this record, because `identity_from_bill`
# refuses to guess any of them: the originating chamber (ADR-002), the year, and the number as
# printed. Both language readings' titles are present so the one-Work/two-Expressions property
# below can be checked on a single bill.
BILL = {
    "identifier": {
        "slug": "dr-15-2026",
        "normalized": "DR-15-2026",
        "originating_chamber": "dewan_rakyat",
        "year": 2026,
        "number": 15,
    },
    "titles": {"raw_ms": "RUU Contoh 2026", "raw_en": "Example Bill 2026"},
}


def find(node, node_type, num):
    for child in node.children:
        if child.node_type == node_type and child.num == num:
            return child
        found = find(child, node_type, num)
        if found is not None:
            return found
    return None


def render(markdown=BODY_MARKDOWN, *, language="ms", unit="clause", bill=BILL) -> ET.Element:
    """Render `markdown` the way `convert_to_akn` does, and hand back the parsed document."""
    root = parse_markdown_structure(markdown, unit=unit)
    assign_eids(root)
    identity = identity_from_bill(bill, doc_type="act" if unit == "section" else "bill")
    xml_bytes = render_akn(root, identity=identity, language=language, bill=bill)
    return ET.fromstring(xml_bytes)


def frbr_value(root: ET.Element, level: str, element: str, attribute: str = "value") -> str | None:
    """One value out of an FRBR block, whichever document element this is (`bill` or `act`)."""
    doc_el = next(iter(root))
    found = doc_el.find(
        f"{{{AKN_NS}}}meta/{{{AKN_NS}}}identification/{{{AKN_NS}}}{level}/{{{AKN_NS}}}{element}"
    )
    return found.get(attribute) if found is not None else None


def test_parts_group_their_clauses() -> None:
    root = parse_markdown_structure(BODY_MARKDOWN, unit="clause")
    assert [part.num for part in root.children] == ["I", "II"]
    part_one = root.children[0]
    # "PERMULAAN" is typeset as its own line beneath "BAHAGIAN I" (matching the real typography
    # `tests/support/pdfs.py` builds), so it lands as the part's own leading text, not an inline
    # heading on the same line as the part number.
    assert part_one.heading is None
    assert part_one.paragraphs == ["PERMULAAN"]
    assert [clause.num for clause in part_one.children] == ["1", "2"]


def test_clause_body_text_is_captured() -> None:
    root = parse_markdown_structure(BODY_MARKDOWN, unit="clause")
    clause_1 = find(root, "clause", "1")
    assert clause_1 is not None
    assert clause_1.heading == "Tajuk ringkas dan permulaan kuat kuasa"
    assert clause_1.paragraphs == ["Akta ini bolehlah dinamakan Akta Contoh 2026."]


def test_a_short_label_after_a_provision_number_is_read_as_its_marginal_note() -> None:
    """What Parliament actually prints beside a provision number: a label, not a sentence."""
    assert split_marginal_note("Tajuk ringkas") == ("Tajuk ringkas", "")
    assert split_marginal_note("Kewajipan untuk melaporkan") == ("Kewajipan untuk melaporkan", "")
    assert split_marginal_note("   Penalti   ") == ("Penalti", "")
    assert split_marginal_note("") == (None, "")


def test_a_provision_that_runs_in_after_its_number_is_body_text_and_never_a_heading() -> None:
    """The rights leak this classification exists to close.

    A Malaysian amendment bill has no marginal note: the whole provision follows the number on one
    line, and the printed line is then indistinguishable in shape from a note. `heading` is
    published in metadata-only mode and body text is withheld (ADR-027), so reading a run-in
    sentence as a heading publishes drafted legislative text while the rights review is open.
    """
    note, body = split_marginal_note(RUN_IN_PROVISION)
    assert note is None
    assert body == RUN_IN_PROVISION

    root = parse_markdown_structure(AMENDMENT_MARKDOWN, unit="clause")
    clause_2 = find(root, "clause", "2")
    assert clause_2 is not None
    assert clause_2.heading is None
    assert clause_2.paragraphs == [RUN_IN_PROVISION]

    # And it leaves the rendered document through `<content>`, which redaction empties, rather than
    # through `<heading>`, which redaction keeps.
    rendered = render(AMENDMENT_MARKDOWN)
    clause_element = next(iter(rendered)).findall(f"{{{AKN_NS}}}body/{{{AKN_NS}}}clause")[1]
    assert clause_element.find(f"{{{AKN_NS}}}heading") is None
    assert clause_element.find(f"{{{AKN_NS}}}content/{{{AKN_NS}}}p").text == RUN_IN_PROVISION


def test_a_label_longer_than_a_marginal_note_can_be_is_body_text_too() -> None:
    """80 characters is the same bound `legislation.layout` uses to tell a marginal note from an
    indented block when it has the page geometry to look at, so a label over it is not one."""
    assert MAX_MARGINAL_NOTE_CHARS == 80
    longest = "Kewajipan untuk melaporkan transaksi yang boleh disyaki kepada Pesuruhjaya Kuari"
    assert len(longest) == MAX_MARGINAL_NOTE_CHARS
    assert split_marginal_note(longest) == (longest, "")
    assert split_marginal_note(longest + " dan") == (None, longest + " dan")

    for punctuated in ("Tafsiran.", "Tafsiran;", "Tafsiran:", "Tafsiran!", "Tafsiran?"):
        assert split_marginal_note(punctuated) == (None, punctuated)


def test_a_provision_opening_a_subsection_inline_has_no_heading_and_keeps_its_list_open() -> None:
    """`1. (1) Akta ini ...` is a provision with no note of its own, and the subsection it opens
    has to stay the open one so a following `(2)` continues the same list."""
    markdown = """\
1. (1) Akta ini bolehlah dinamakan Akta Contoh 2026.

(2) Akta ini mula berkuat kuasa pada tarikh yang ditetapkan oleh Menteri.
"""
    root = parse_markdown_structure(markdown, unit="clause")
    clause_1 = find(root, "clause", "1")
    assert clause_1 is not None
    assert clause_1.heading is None
    assert clause_1.paragraphs == []
    assert [child.num for child in clause_1.children] == ["1", "2"]
    assert clause_1.children[0].paragraphs == ["Akta ini bolehlah dinamakan Akta Contoh 2026."]


def test_subsection_paragraph_and_subparagraph_nest_correctly() -> None:
    root = parse_markdown_structure(BODY_MARKDOWN, unit="clause")
    clause_3 = find(root, "clause", "3")
    assert clause_3 is not None
    subsection_1 = clause_3.children[0]
    assert subsection_1.node_type == "subsection" and subsection_1.num == "1"
    assert subsection_1.paragraphs == ["Seseorang hendaklah melaporkan kepada Pesuruhjaya"]

    paragraph_a = subsection_1.children[0]
    assert paragraph_a.node_type == "paragraph" and paragraph_a.num == "a"
    subparagraph_i = paragraph_a.children[0]
    assert subparagraph_i.node_type == "subparagraph" and subparagraph_i.num == "i"
    subparagraph_ii = paragraph_a.children[1]
    assert subparagraph_ii.node_type == "subparagraph" and subparagraph_ii.num == "ii"

    # (b) must be a sibling of (a) under the subsection, not nested under the subparagraph list.
    paragraph_b = subsection_1.children[1]
    assert paragraph_b.node_type == "paragraph" and paragraph_b.num == "b"


def test_a_schedule_restarts_numbering_and_its_items_are_paragraphs() -> None:
    markdown = BODY_MARKDOWN + "\n## JADUAL PERTAMA\n\n1. Item pertama.\n\n2. Item kedua.\n"
    root = parse_markdown_structure(markdown, unit="clause")
    schedule = next(child for child in root.children if child.node_type == "schedule")
    assert schedule.num == "1"
    assert [item.node_type for item in schedule.children] == ["paragraph", "paragraph"]
    assert [item.num for item in schedule.children] == ["1", "2"]
    # The schedule's "1" must not collide with the real clause "1" earlier in the document.
    clause_1 = find(root, "clause", "1")
    assert clause_1 is not None
    assert clause_1 not in schedule.children


def test_arrangement_heading_is_skipped_but_its_entries_are_a_known_limitation() -> None:
    """Pinned, not silently ignored: an Arrangement's table-of-contents entries look exactly
    like real body provisions to this regex parser, which is exactly why the LLM-assisted
    extractor exists (module docstring)."""
    markdown = "# SUSUNAN SEKSYEN\n\n1. Tajuk ringkas\n\n2. Tafsiran\n\n" + BODY_MARKDOWN
    root = parse_markdown_structure(markdown, unit="clause")
    top_level_clauses = [child for child in root.children if child.node_type == "clause"]
    # The two Arrangement entries land as top-level clauses alongside the real Parts, since
    # nothing here can yet tell a table-of-contents line from a body provision.
    assert len(top_level_clauses) == 2


def test_infer_language_and_unit_reads_both_off_the_arrangement_heading() -> None:
    for heading, expected in (
        ("SUSUNAN SEKSYEN", ("ms", "section")),
        ("SUSUNAN FASAL", ("ms", "clause")),
        ("ARRANGEMENT OF SECTIONS", ("en", "section")),
        ("ARRANGEMENT OF CLAUSES", ("en", "clause")),
    ):
        assert infer_language_and_unit(f"# {heading}\n\n1. Tajuk\n") == expected


def test_a_document_with_no_arrangement_heading_declares_no_language_at_all() -> None:
    """`None`, not a default. The language becomes a permanent component of the Expression IRI, so
    the caller has to find the fact elsewhere or refuse the document — never guess it."""
    assert infer_language_and_unit(BODY_MARKDOWN) == (None, "clause")


def test_assign_eids_joins_ancestors_with_double_underscore() -> None:
    root = parse_markdown_structure(BODY_MARKDOWN, unit="clause")
    assign_eids(root)
    clause_3 = find(root, "clause", "3")
    assert clause_3 is not None
    assert clause_3.eid == "part_II__cl_3"
    subsection_1 = clause_3.children[0]
    assert subsection_1.eid == "part_II__cl_3__subsec_1"
    paragraph_a = subsection_1.children[0]
    assert paragraph_a.eid == "part_II__cl_3__subsec_1__para_a"


def test_render_akn_names_the_work_the_expression_and_the_manifestation() -> None:
    root = render()
    assert root.tag == f"{{{AKN_NS}}}akomaNtoso"
    assert root.find(f"{{{AKN_NS}}}bill") is not None

    # Every level's FRBRthis names that level; every level's FRBRuri names the Work.
    assert frbr_value(root, "FRBRWork", "FRBRthis") == "/akn/my/bill/dr/2026/15"
    assert frbr_value(root, "FRBRWork", "FRBRuri") == "/akn/my/bill/dr/2026/15"
    assert frbr_value(root, "FRBRExpression", "FRBRthis") == "/akn/my/bill/dr/2026/15/msa@"
    assert frbr_value(root, "FRBRExpression", "FRBRuri") == "/akn/my/bill/dr/2026/15"
    assert frbr_value(root, "FRBRManifestation", "FRBRthis") == "/akn/my/bill/dr/2026/15/msa@.xml"
    assert frbr_value(root, "FRBRManifestation", "FRBRuri") == "/akn/my/bill/dr/2026/15"

    assert frbr_value(root, "FRBRWork", "FRBRcountry") == "my"
    assert frbr_value(root, "FRBRWork", "FRBRsubtype") == "dr"
    assert frbr_value(root, "FRBRWork", "FRBRnumber") == "15"
    assert frbr_value(root, "FRBRExpression", "FRBRlanguage", "language") == "msa"
    assert frbr_value(root, "FRBRManifestation", "FRBRformat") == "xml"
    assert frbr_value(root, "FRBRWork", "FRBRauthor", "href") == "#dewanRakyat"


def test_the_malay_and_english_readings_of_one_bill_are_two_expressions_of_one_work() -> None:
    """The property the whole IRI scheme exists to deliver.

    A cross-language citation is only resolvable if both readings agree on what document they are
    readings *of*. The previous scheme keyed the identifier off each document's own URL hash, so the
    Malay and English PDFs of one bill were two unrelated Works with nothing linking them.
    """
    malay, english = render(language="ms"), render(language="en")

    assert (
        frbr_value(malay, "FRBRWork", "FRBRuri")
        == frbr_value(english, "FRBRWork", "FRBRuri")
        == "/akn/my/bill/dr/2026/15"
    )
    assert frbr_value(malay, "FRBRWork", "FRBRthis") == frbr_value(english, "FRBRWork", "FRBRthis")

    assert frbr_value(malay, "FRBRExpression", "FRBRthis") == "/akn/my/bill/dr/2026/15/msa@"
    assert frbr_value(english, "FRBRExpression", "FRBRthis") == "/akn/my/bill/dr/2026/15/eng@"
    assert frbr_value(malay, "FRBRExpression", "FRBRlanguage", "language") == "msa"
    assert frbr_value(english, "FRBRExpression", "FRBRlanguage", "language") == "eng"

    # And each Expression carries that language's own long title, not a single hard-coded one.
    for document, title in ((malay, "RUU Contoh 2026"), (english, "Example Bill 2026")):
        long_title = document.find(
            f"{{{AKN_NS}}}bill/{{{AKN_NS}}}preface/{{{AKN_NS}}}longTitle/{{{AKN_NS}}}p"
        )
        assert long_title is not None and long_title.text == title


def test_a_rendered_document_validates_against_the_akoma_ntoso_3_0_schema() -> None:
    """Against the vendored OASIS XSD, not against our own reading of it.

    Every earlier renderer produced XML that called itself Akoma Ntoso and no Akoma Ntoso tool could
    read — an FRBR block missing required children, `<content>` beside child elements. A document is
    only publishable if the specification agrees it is one.
    """
    markdown = BODY_MARKDOWN + "\n## JADUAL PERTAMA\n\n1. Item pertama.\n"
    for language in ("ms", "en"):
        for unit in ("clause", "section"):
            root = parse_markdown_structure(markdown, unit=unit)
            assign_eids(root)
            identity = identity_from_bill(BILL, doc_type="act" if unit == "section" else "bill")
            xml_bytes = render_akn(root, identity=identity, language=language, bill=BILL)
            assert validate_akn(xml_bytes) == [], f"{language}/{unit}"


def test_text_belonging_to_a_node_with_children_introduces_them_rather_than_claiming_content() -> (
    None
):
    """AKN's hierarchy model lets a container introduce its children or carry content, never both.
    Emitting `<content>` alongside child elements is what used to fail the schema."""
    root = render()
    part_one = next(iter(root)).find(f"{{{AKN_NS}}}body/{{{AKN_NS}}}part")
    assert part_one is not None
    assert part_one.find(f"{{{AKN_NS}}}intro/{{{AKN_NS}}}p").text == "PERMULAAN"
    assert part_one.find(f"{{{AKN_NS}}}content") is None

    clause_one = part_one.find(f"{{{AKN_NS}}}clause")
    assert clause_one is not None
    assert clause_one.get("eId") == "part_I__cl_1"
    assert clause_one.find(f"{{{AKN_NS}}}num").text == "1"
    assert clause_one.find(f"{{{AKN_NS}}}content/{{{AKN_NS}}}p") is not None
    assert clause_one.find(f"{{{AKN_NS}}}intro") is None


def test_a_heading_only_provision_keeps_an_empty_content_block_rather_than_being_dropped() -> None:
    root = render("1. Tajuk sahaja\n")
    clause = next(iter(root)).find(f"{{{AKN_NS}}}body/{{{AKN_NS}}}clause")
    assert clause is not None and clause.get("eId") == "cl_1"
    assert clause.find(f"{{{AKN_NS}}}heading").text == "Tajuk sahaja"
    paragraph = clause.find(f"{{{AKN_NS}}}content/{{{AKN_NS}}}p")
    assert paragraph is not None and not paragraph.text


def test_a_preamble_is_emitted_before_the_body_rather_than_inside_it() -> None:
    """AKN puts a preamble before the body, and appending it into `<body>` was schema-invalid.

    The extractor's own prompt offers `preamble` as a node type, so a *correct* reading can contain
    one — which meant this bug counted correct readings as failed renders.
    """
    tree = Node(node_type="body", num=None, heading=None, eid="")
    tree.children.append(
        Node("preamble", None, None, "", ["BAHAWASANYA Akta ini dibuat untuk melindungi saksi."])
    )
    tree.children.append(
        Node("clause", "1", "Tajuk ringkas", "cl_1", ["Akta ini bolehlah dinamakan Akta Contoh."])
    )
    identity = identity_from_bill(BILL, doc_type="bill")
    xml_bytes = render_akn(tree, identity=identity, language="ms", bill=BILL)
    assert validate_akn(xml_bytes) == []

    document = next(iter(ET.fromstring(xml_bytes)))
    assert [child.tag.rpartition("}")[2] for child in document] == [
        "meta",
        "preface",
        "preamble",
        "body",
    ]
    preamble = document.find(f"{{{AKN_NS}}}preamble/{{{AKN_NS}}}p")
    assert preamble.text == "BAHAWASANYA Akta ini dibuat untuk melindungi saksi."
    body = document.find(f"{{{AKN_NS}}}body")
    assert body.find(f"{{{AKN_NS}}}preamble") is None
    assert [child.tag.rpartition("}")[2] for child in body] == ["clause"]


def test_render_akn_uses_an_act_root_for_a_section_numbered_document() -> None:
    root = render(unit="section")
    assert root.find(f"{{{AKN_NS}}}act") is not None
    assert root.find(f"{{{AKN_NS}}}bill") is None
    assert frbr_value(root, "FRBRWork", "FRBRuri") == "/akn/my/act/dr/2026/15"


def test_no_iri_is_minted_for_a_bill_that_does_not_identify_itself() -> None:
    """A citable identifier with a guessed component is worse than no output at all, so the four
    facts a Work IRI needs are demanded rather than defaulted — the renderer is never reached."""
    for identifier in (
        {},
        {"year": 2026, "number": 15},  # no originating chamber
        {"originating_chamber": "dewan_rakyat", "number": 15},  # no year
        {"originating_chamber": "dewan_rakyat", "year": 2026},  # no number
        {"originating_chamber": "senate", "year": 2026, "number": 15},  # not a chamber we publish
        {"originating_chamber": "dewan_rakyat", "year": "2026", "number": 15},  # year as a string
    ):
        with pytest.raises(FrbrIdentityError):
            identity_from_bill({"identifier": identifier}, doc_type="bill")


def test_a_language_we_do_not_publish_cannot_become_an_expression_iri() -> None:
    identity = identity_from_bill(BILL, doc_type="bill")
    root = parse_markdown_structure(BODY_MARKDOWN, unit="clause")
    assign_eids(root)
    with pytest.raises(FrbrIdentityError):
        render_akn(root, identity=identity, language="ta", bill=BILL)


def test_frbr_date_prefers_a_recorded_event_date_and_labels_the_year_only_fallback() -> None:
    """The label is what makes the imprecision machine-detectable: `2026-01-01` on its own reads as
    a real date, and for most archived bills the printed year is genuinely all we know."""
    assert frbr_date({}, year=2026) == ("2026-01-01", "yearOnly")
    dated = {
        "chambers": {
            "dewan_rakyat": {
                "dates": {"first_read": [{"start": "2026-03-10"}, {"start": "2026-05-02"}]}
            }
        }
    }
    assert frbr_date(dated, year=2026) == ("2026-03-10", "earliestRecorded")


def test_the_regex_extractor_satisfies_the_widened_extractor_protocol() -> None:
    """The identity attributes are part of the contract: a prompt improvement or a model swap has
    to make every artifact built by the previous producer read as stale."""
    extractor = RegexMarkdownStructureExtractor()
    assert extractor.name == "regex"
    assert extractor.model_id is None
    assert extractor.prompt_sha256 is None
    tree = extractor.extract(BODY_MARKDOWN, unit="clause")
    assert [part.num for part in tree.children] == ["I", "II"]


def test_the_parser_stops_at_the_back_matter_and_never_reads_its_numbers_as_clauses() -> None:
    """The HURAIAN narrates the clauses in prose and numbers its own paragraphs from the bill's
    low numbers over again; reading on appended a second clause 2 to the tree, which the gate
    then rightly rejected as a duplicate eId."""
    markdown = "\n".join(
        [
            "1. Akta ini bolehlah dinamakan Akta Contoh 2024.",
            "2. Akta Contoh 1990 dipinda dalam seksyen 2.",
            "## HURAIAN",
            "Rang Undang-Undang ini bertujuan untuk meminda Akta Contoh 1990.",
            "2. Fasal 1 mengandungi tajuk ringkas.",
            "3. Fasal 2 bertujuan untuk meminda seksyen 2.",
        ]
    )
    tree = parse_markdown_structure(markdown, unit="clause")
    assert [node.num for node in tree.children] == ["1", "2"]


def test_a_back_matter_heading_before_any_provision_does_not_end_the_document() -> None:
    """A committee-stage amendment paper opens with a short HURAIAN of its own and reprints the
    whole bill after it — back matter only ends a body that has begun."""
    markdown = "\n".join(
        [
            "## HURAIAN",
            "Pindaan yang dicadangkan.",
            "1. Akta ini bolehlah dinamakan Akta Contoh 2024.",
        ]
    )
    tree = parse_markdown_structure(markdown, unit="clause")
    assert [node.num for node in tree.children] == ["1"]
