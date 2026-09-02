"""Metadata-only publication: the rights boundary, tested from the outside.

ADR-004's policy is that this project publishes metadata and links to Parliament's official
document rather than republishing its text, until the rights review (A14) concludes. The corpus is
nonetheless stored in full, privately, and redacted at the serving boundary — so these redactors
are the control that keeps the policy true, and a bug in one of them leaks the thing it exists to
withhold.

The tests therefore build a real document end to end (markdown -> Akoma Ntoso -> RDF) rather than
hand-writing a convenient fragment, and then look for a sentence they know is in the source. A
fragment written for the test could omit the very wrapper the redactor misses.
"""

import pytest

from billwatcher.frbr import identity_from_bill
from billwatcher.graph.akn_schema import validate_akn
from billwatcher.graph.render import render_akn
from billwatcher.graph.semantic import (
    SemanticConversionError,
    build_graph,
    parse_akn,
    render_jsonld,
    render_nquads,
)
from billwatcher.graph.structure import assign_eids, parse_markdown_structure
from billwatcher.graph.tree import Node
from billwatcher.publish.redact import (
    KEEP_HEADINGS,
    MAX_HEADING_CHARS,
    contains_provision_text,
    contains_unbounded_heading,
    publishable_heading,
    redact_akn,
    redact_semantic,
)

BASE_IRI = "https://bills.example"

# Deliberately exercises both text wrappers `render_akn` can emit: clause 1 carries text with no
# children (`<content>`), and the subsection under clause 3 carries text *and* children (`<intro>`).
# A redactor that only looked inside `<content>` would pass a test built from clause 1 alone.
#
# Typeset as Parliament typesets it: the marginal notes carry no final stop and the body sentences
# do, which is the distinction `split_marginal_note` and `publishable_heading` both classify on.
MARKDOWN = """\
1. Tajuk ringkas dan permulaan kuat kuasa

Akta ini bolehlah dinamakan Akta Pelaporan Kuari 2026.

2. Tafsiran

Dalam Akta ini, melainkan jika konteksnya menghendaki makna yang lain -

3. Kewajipan untuk melaporkan

(1) Seseorang hendaklah melaporkan kepada Pesuruhjaya dalam tempoh empat belas hari.

(a) melalui portal rasmi yang ditetapkan oleh Pesuruhjaya; atau

(b) secara bertulis kepada pejabat daerah yang berkenaan.

4. Penalti

Seseorang yang melanggar fasal 3 boleh dikenakan denda tidak melebihi lima puluh ribu ringgit.
"""

# An amendment bill: no marginal note anywhere, the whole provision running in after the number.
# This is the shape the corpus is mostly made of, and the shape that used to put a drafted
# provision in `heading` and publish it verbatim.
AMENDMENT_MARKDOWN = """\
1. Tajuk ringkas

Akta ini bolehlah dinamakan Akta Pelaporan Kuari (Pindaan) 2026.

2. Akta Pelaporan Kuari 2026 dipinda dalam fasal 3 dengan memasukkan selepas perenggan (b) suatu \
perenggan baharu yang menetapkan tempoh tiga puluh hari.
"""

RUN_IN_PROVISION = (
    "Akta Pelaporan Kuari 2026 dipinda dalam fasal 3 dengan memasukkan selepas perenggan (b) "
    "suatu perenggan baharu yang menetapkan tempoh tiga puluh hari."
)

# Sentences from the body, chosen so none of their distinctive words appear in the bill's title —
# the title is published on every bill page already and is not redacted.
CONTENT_SENTENCE = "Akta ini bolehlah dinamakan Akta Pelaporan Kuari 2026."
INTRO_SENTENCE = "Seseorang hendaklah melaporkan kepada Pesuruhjaya dalam tempoh empat belas hari."
PENALTY_SENTENCE = (
    "Seseorang yang melanggar fasal 3 boleh dikenakan denda tidak melebihi lima puluh ribu ringgit."
)

BILL = {
    "identifier": {
        "slug": "dr-15-2026",
        "normalized": "DR-15-2026",
        "originating_chamber": "dewan_rakyat",
        "year": 2026,
        "number": 15,
    },
    "titles": {"raw_ms": "Rang Undang-Undang Pelaporan Kuari 2026"},
    "chambers": {"dewan_rakyat": {"dates": {"first_reading": [{"start": "2026-03-10"}]}}},
}

IDENTITY = identity_from_bill(BILL, doc_type="bill")


def built_akn(markdown: str = MARKDOWN) -> bytes:
    tree = parse_markdown_structure(markdown, unit="clause")
    assign_eids(tree)
    return render_akn(tree, identity=IDENTITY, language="ms", bill=BILL)


FULL_AKN = built_akn()


def built_semantic(xml_bytes: bytes = FULL_AKN) -> tuple[bytes, bytes]:
    tree, expression_uri, doc_type, language = parse_akn(xml_bytes)
    dataset, document_iri = build_graph(
        tree,
        base_iri=BASE_IRI,
        expression_uri=expression_uri,
        doc_type=doc_type,
        language=language,
        bill=BILL,
        identity=IDENTITY,
    )
    return render_nquads(dataset), render_jsonld(dataset, document_iri)


FULL_NQUADS, FULL_JSONLD = built_semantic()


def built_akn_with_heading(heading: str) -> bytes:
    """A document whose second clause carries `heading` — whatever a producer decided to put there.

    Built from a tree rather than from markdown on purpose: an LLM extractor fills `heading`
    directly, so the boundary has to be tested against a heading no parser would have produced.
    """
    tree = Node(node_type="body", num=None, heading=None, eid="")
    tree.children.append(
        Node("clause", "1", "Tajuk ringkas", "cl_1", ["Akta ini bolehlah dinamakan Akta Contoh."])
    )
    tree.children.append(Node("clause", "2", heading, "cl_2", ["Teks fasal kedua."]))
    return render_akn(tree, identity=IDENTITY, language="ms", bill=BILL)


def test_the_source_document_really_does_carry_the_sentences_these_tests_hunt_for() -> None:
    """The control for every test below: absence only means something if presence was real."""
    for sentence in (CONTENT_SENTENCE, INTRO_SENTENCE, PENALTY_SENTENCE):
        assert sentence in MARKDOWN
        assert sentence.encode("utf-8") in FULL_AKN
        assert sentence.encode("utf-8") in FULL_NQUADS
        assert sentence.encode("utf-8") in FULL_JSONLD
    # Both wrappers are present, so the redactor is being asked to empty both.
    assert b"<intro>" in FULL_AKN
    assert b"<content>" in FULL_AKN


def test_no_body_sentence_survives_redact_akn() -> None:
    redacted = redact_akn(FULL_AKN)
    for sentence in (CONTENT_SENTENCE, INTRO_SENTENCE, PENALTY_SENTENCE):
        assert sentence.encode("utf-8") not in redacted
    # Not a word of it, not merely not the whole sentence.
    for word in (b"Pesuruhjaya", b"denda", b"portal", b"bertulis"):
        assert word not in redacted


def test_a_preamble_carries_no_sentence_through_redaction() -> None:
    """Found live on the first real corpus run: `render_akn` puts a bill's enacting formula in a
    `<p>` directly under `<preamble>`, never inside a content/intro/wrapUp wrapper. The redactor's
    own belt-and-braces self-check (`contains_provision_text`) walks the same wrapper list, so
    without `preamble` in it the check stays silent through exactly the leak it exists to catch —
    the same shape as the heading leak ADR-027's review already found once.
    """
    formula = "Suatu Akta untuk meminda Akta Pelaporan Kuari 2026 dan bagi perkara berkaitan."
    tree = Node(node_type="body", num=None, heading=None, eid="")
    tree.children.append(Node("preamble", None, None, "", paragraphs=[formula]))
    tree.children.append(
        Node("clause", "1", "Tajuk ringkas", "cl_1", ["Akta ini bolehlah dinamakan Akta Contoh."])
    )
    akn = render_akn(tree, identity=IDENTITY, language="ms", bill=BILL)

    assert b"<preamble>" in akn
    assert formula.encode("utf-8") in akn  # the control: it really is there before redaction
    assert contains_provision_text(akn) is True

    redacted = redact_akn(akn)
    assert formula.encode("utf-8") not in redacted
    assert b"meminda" not in redacted  # not a word of it, not merely not the whole sentence
    assert validate_akn(redacted) == []
    assert contains_provision_text(redacted) is False


def test_redacted_akoma_ntoso_is_still_valid_akoma_ntoso() -> None:
    """The `<p>` elements stay, and stay empty.

    Dropping the wrappers would leave hierarchy elements the schema requires to carry something,
    and an invalid document is not a useful thing to publish either.
    """
    redacted = redact_akn(FULL_AKN)
    assert validate_akn(FULL_AKN) == []
    assert validate_akn(redacted) == []
    assert b"<p />" in redacted or b"<p/>" in redacted


def test_provision_numbers_and_headings_survive_redaction() -> None:
    """Structure is the whole point of publishing under a metadata-only policy.

    Headings are the drafter's words, so keeping them is a judgement rather than an obvious call —
    the same class of short published fragment as the bill title. `KEEP_HEADINGS` is where that
    judgement is recorded, so narrowing it after an adverse review is a one-line change.
    """
    assert KEEP_HEADINGS is True
    redacted = redact_akn(FULL_AKN)
    assert b"<num>1</num>" in redacted
    assert b"<num>4</num>" in redacted
    assert b'eId="cl_3__subsec_1__para_a"' in redacted
    assert b"<heading>Kewajipan untuk melaporkan</heading>" in redacted
    assert b"<heading>Penalti</heading>" in redacted
    # The long title is the bill's published name, which this site already shows on every bill
    # page, so it is not provision prose and is not redacted.
    assert b"<longTitle" in redacted
    assert BILL["titles"]["raw_ms"].encode("utf-8") in redacted


def test_redacted_nquads_drop_schema_text_and_keep_every_structural_triple() -> None:
    redacted = redact_semantic(FULL_NQUADS, as_jsonld=False).decode("utf-8")
    assert "https://schema.org/text" not in redacted
    assert INTRO_SENTENCE not in redacted

    document = f"{BASE_IRI}/akn/my/bill/dr/2026/15/msa@"
    clause = f"<{document}/~cl_3>"
    assert f'{clause} <http://data.europa.eu/eli/ontology#number> "3"' in redacted
    assert f"<{document}> <http://data.europa.eu/eli/ontology#has_part> {clause}" in redacted
    assert f'{clause} <https://schema.org/name> "Kewajipan untuk melaporkan"@ms' in redacted
    # The document's own metadata is untouched.
    assert '<http://data.europa.eu/eli/ontology#number> "DR-15-2026"' in redacted
    assert "Rang Undang-Undang Pelaporan Kuari 2026" in redacted


def test_redacted_jsonld_drops_schema_text_and_keeps_every_structural_key() -> None:
    """Rebuilt from the stored N-Quads, so one redaction produces both published representations.

    Two redactors over two files could disagree; this one cannot, which is the same single-graph
    discipline step 5 itself uses.
    """
    redacted = redact_semantic(FULL_NQUADS, as_jsonld=True).decode("utf-8")
    assert '"schema:text"' not in redacted
    assert INTRO_SENTENCE not in redacted
    assert '"eli:number": "3"' in redacted
    assert '"hasPart"' in redacted
    assert '"isPartOf"' in redacted
    assert '"schema:name"' in redacted
    assert "Kewajipan untuk melaporkan" in redacted


def test_contains_provision_text_agrees_with_the_redactors_on_every_representation() -> None:
    """The independent second opinion: the redactors are the control, this says they worked."""
    assert contains_provision_text(FULL_AKN) is True
    assert contains_provision_text(FULL_NQUADS) is True
    assert contains_provision_text(FULL_JSONLD) is True

    assert contains_provision_text(redact_akn(FULL_AKN)) is False
    assert contains_provision_text(redact_semantic(FULL_NQUADS, as_jsonld=False)) is False
    assert contains_provision_text(redact_semantic(FULL_NQUADS, as_jsonld=True)) is False


def test_publishable_heading_keeps_a_note_and_withholds_a_sentence_or_a_long_label() -> None:
    """The bound ADR-027 permits a heading to be published under, applied at the boundary.

    Both halves are evidenced rather than guessed: 80 characters is the bound
    `legislation.layout` already uses for "a marginal note is short", and the terminal-stop test is
    what separates the two shapes in the fixtures captured from real Parliament PDFs.
    """
    assert publishable_heading("Tajuk ringkas") == "Tajuk ringkas"
    assert publishable_heading("Kewajipan untuk melaporkan") == "Kewajipan untuk melaporkan"
    assert publishable_heading("  Penalti  ") == "Penalti"

    assert publishable_heading(RUN_IN_PROVISION) is None
    assert publishable_heading("Seseorang yang melanggar fasal 3 melakukan kesalahan.") is None
    for punctuated in ("Penalti.", "Penalti;", "Penalti:", "Penalti!", "Penalti?"):
        assert publishable_heading(punctuated) is None

    longest = "Kewajipan untuk melaporkan transaksi yang boleh disyaki kepada Pesuruhjaya Kuari"
    assert len(longest) == MAX_HEADING_CHARS == 80
    assert publishable_heading(longest) == longest
    assert publishable_heading(longest + " dan") is None

    assert publishable_heading(None) is None
    assert publishable_heading("   ") is None


def test_a_provision_that_ran_in_after_its_number_reaches_no_redacted_representation() -> None:
    """The leak this whole bound exists to close, checked on every published representation.

    A Malaysian amendment bill has no marginal note: the provision runs in after the number. Read
    as a heading it was published verbatim in metadata-only mode — a drafted provision republished
    while the rights review is open — because headings are kept and body text is withheld.
    """
    full_akn = built_akn(AMENDMENT_MARKDOWN)
    full_nquads, full_jsonld = built_semantic(full_akn)

    # The control: the stored corpus really does hold it.
    assert RUN_IN_PROVISION.encode("utf-8") in full_akn
    assert RUN_IN_PROVISION in full_nquads.decode("utf-8")
    assert RUN_IN_PROVISION in full_jsonld.decode("utf-8")

    published = (
        redact_akn(full_akn),
        redact_semantic(full_nquads, as_jsonld=False),
        redact_semantic(full_nquads, as_jsonld=True),
    )
    for payload in published:
        text = payload.decode("utf-8")
        assert RUN_IN_PROVISION not in text
        # Not a word of it, not merely not the whole sentence.
        for word in ("dipinda", "memasukkan", "perenggan"):
            assert word not in text
        assert contains_provision_text(payload) is False

    # The provision is still there as structure, and the note-carrying clause keeps its heading.
    assert b'<clause eId="cl_2">' in published[0]
    assert b"<num>2</num>" in published[0]
    assert b"<heading>Tajuk ringkas</heading>" in published[0]
    assert validate_akn(published[0]) == []


def test_a_sentence_a_producer_put_in_the_heading_field_is_withheld_and_reported() -> None:
    """The parser is not the only producer of a tree, which is why the bound is repeated here.

    An LLM extractor fills `heading` too, and nothing upstream constrains what it puts there. The
    boundary therefore re-tests every heading it is handed rather than trusting the parse, and the
    safety net has to look at headings as well as body wrappers — a net that only checked
    `<content>` would have stayed silent through exactly this leak.
    """
    invented = built_akn_with_heading(RUN_IN_PROVISION)

    assert contains_provision_text(invented) is True
    redacted = redact_akn(invented)
    assert RUN_IN_PROVISION.encode("utf-8") not in redacted
    assert contains_provision_text(redacted) is False
    # Withholding a heading must not cost schema validity either.
    assert validate_akn(invented) == []
    assert validate_akn(redacted) == []
    # The clause that does carry a real marginal note is untouched.
    assert b"<heading>Tajuk ringkas</heading>" in redacted


def test_redact_semantic_drops_a_provision_name_that_is_not_a_bounded_label() -> None:
    """A provision's `schema:name` is its heading, so it gets the same bound the XML does.

    The *document's* own `schema:name` is the bill's published title, which this site already shows
    on every bill page, so it is kept whatever its shape — a title is not a provision.
    """
    nquads, jsonld = built_semantic(built_akn_with_heading(RUN_IN_PROVISION))
    for as_jsonld in (False, True):
        published = redact_semantic(nquads, as_jsonld=as_jsonld).decode("utf-8")
        assert RUN_IN_PROVISION not in published
        assert "Tajuk ringkas" in published
        assert BILL["titles"]["raw_ms"] in published


def test_contains_unbounded_heading_sees_a_sentence_anywhere_in_a_nested_view_structure() -> None:
    """For the HTML path, which builds view objects rather than serialising AKN, so the XML-shaped
    net cannot see it."""
    views = {
        "label": "Fasal 2",
        "children": [{"label": "Subseksyen 1", "heading": "Tajuk ringkas", "paragraphs": []}],
    }
    assert contains_unbounded_heading(views) is False

    leaking = {"label": "Fasal 2", "children": [{"heading": RUN_IN_PROVISION}]}
    assert contains_unbounded_heading(leaking) is True
    assert contains_unbounded_heading((None, 3, "", "   ")) is False


def test_redaction_is_byte_stable_across_runs() -> None:
    """A redacted representation may be cached or mirrored, so it has to be one fixed answer."""
    assert redact_akn(FULL_AKN) == redact_akn(FULL_AKN)
    assert redact_semantic(FULL_NQUADS, as_jsonld=False) == redact_semantic(
        FULL_NQUADS, as_jsonld=False
    )
    assert redact_semantic(FULL_NQUADS, as_jsonld=True) == redact_semantic(
        FULL_NQUADS, as_jsonld=True
    )
    # Redacting a redacted document is a no-op, so re-serving it cannot drift either.
    assert redact_akn(redact_akn(FULL_AKN)) == redact_akn(FULL_AKN)


def test_redact_akn_refuses_xml_declaring_a_doctype_or_an_entity() -> None:
    """These bytes are normally ours, but AKN can be imported and this output is served publicly.

    An entity-expanding parser on the serving path is a file-disclosure bug, so the document is
    refused before it reaches one rather than sanitised afterwards.
    """
    doctype = (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE akomaNtoso [<!ENTITY leak SYSTEM "file:///etc/passwd">]>\n'
        b'<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0"/>'
    )
    with pytest.raises(SemanticConversionError, match="doctype or entity is refused"):
        redact_akn(doctype)

    entity_only = (
        b'<?xml version="1.0"?>\n<!ENTITY leak SYSTEM "file:///etc/passwd">\n<akomaNtoso/>'
    )
    with pytest.raises(SemanticConversionError, match="doctype or entity is refused"):
        redact_akn(entity_only)


def test_redact_akn_reports_malformed_xml_rather_than_raising_a_parser_error() -> None:
    with pytest.raises(SemanticConversionError, match="not well-formed XML"):
        redact_akn(b"<akomaNtoso><bill>")


def test_redact_semantic_reports_unreadable_nquads_rather_than_serving_them() -> None:
    with pytest.raises(SemanticConversionError, match="could not be read"):
        redact_semantic(b"this is not n-quads at all\n", as_jsonld=False)
