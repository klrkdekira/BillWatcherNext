import json

import pytest
from rdflib import Dataset, Graph, Literal, URIRef
from rdflib.namespace import RDF

from billwatcher.frbr import WorkIdentity, identity_from_bill
from billwatcher.graph.render import AKN_NS, render_akn
from billwatcher.graph.semantic import (
    AKN,
    ELI,
    SCHEMA,
    SemanticConversionError,
    build_graph,
    parse_akn,
    render_jsonld,
    render_nquads,
)
from billwatcher.graph.structure import assign_eids, parse_markdown_structure
from billwatcher.graph.tree import Node

# Marginal notes carry no final stop and body sentences do, which is how Parliament typesets a
# provision and how `split_marginal_note` tells the two apart.
MARKDOWN = """\
## BAHAGIAN I

### PERMULAAN

1. Tajuk ringkas dan permulaan kuat kuasa

Akta ini bolehlah dinamakan Akta Contoh 2026.

2. Tafsiran

Dalam Akta ini, melainkan jika konteksnya menghendaki makna yang lain -
"""

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

BASE_IRI = "https://bills.example"
IDENTITY = WorkIdentity(doc_type="bill", chamber_code="dr", year=2026, number=15)
DOCUMENT_IRI = URIRef(f"{BASE_IRI}/akn/my/bill/dr/2026/15/msa@")


def built_xml(*, language: str = "ms", markdown: str = MARKDOWN) -> bytes:
    tree = parse_markdown_structure(markdown, unit="clause")
    assign_eids(tree)
    identity = identity_from_bill(BILL, doc_type="bill")
    return render_akn(tree, identity=identity, language=language, bill=BILL)


def graph_of(xml_bytes: bytes) -> tuple[Dataset, URIRef]:
    """The dataset step 5 would build from a stored document, and the document's own IRI."""
    tree, expression_uri, doc_type, language = parse_akn(xml_bytes)
    return build_graph(
        tree,
        base_iri=BASE_IRI,
        expression_uri=expression_uri,
        doc_type=doc_type,
        language=language,
        bill=BILL,
        identity=IDENTITY,
    )


def test_parse_akn_round_trips_the_tree_and_the_expression_identity_render_akn_wrote() -> None:
    tree, expression_uri, doc_type, language = parse_akn(built_xml())

    assert expression_uri == "/akn/my/bill/dr/2026/15/msa@"
    assert doc_type == "bill"
    # BCP 47 on the way back out, whatever ISO 639-3 code the AKN name carried.
    assert language == "ms"

    part = tree.children[0]
    assert part.node_type == "part" and part.num == "I" and part.eid == "part_I"
    clause_1 = part.children[0]
    assert clause_1.node_type == "clause" and clause_1.num == "1"
    assert clause_1.heading == "Tajuk ringkas dan permulaan kuat kuasa"
    assert clause_1.paragraphs == ["Akta ini bolehlah dinamakan Akta Contoh 2026."]
    assert clause_1.eid == "part_I__cl_1"


def test_an_english_reading_comes_back_tagged_en_not_the_iso_639_3_code() -> None:
    _, expression_uri, _, language = parse_akn(built_xml(language="en"))
    assert expression_uri == "/akn/my/bill/dr/2026/15/eng@"
    assert language == "en"


def test_xml_declaring_a_doctype_is_refused_rather_than_handed_to_the_parser() -> None:
    """The corpus is served publicly and markdown/AKN can be imported, so a document declaring an
    entity is refused outright rather than parsed and trusted."""
    hostile = (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE akomaNtoso [<!ENTITY secret SYSTEM "file:///etc/passwd">]>\n'
        b"<akomaNtoso/>"
    )
    with pytest.raises(SemanticConversionError):
        parse_akn(hostile)


def test_a_document_with_no_expression_identity_is_refused() -> None:
    unidentified = f'<akomaNtoso xmlns="{AKN_NS}"><bill name="bill"/></akomaNtoso>'.encode()
    with pytest.raises(SemanticConversionError):
        parse_akn(unidentified)


def test_the_graph_links_the_document_and_its_provisions_by_has_part_and_is_part_of() -> None:
    """A flat graph of edges, not a nested tree: N-Quads has no nesting, and one graph shape for one
    set of facts is the point of deriving both files from a single dataset."""
    dataset, document_iri = graph_of(built_xml())
    graph = dataset.graph(document_iri)

    assert document_iri == DOCUMENT_IRI
    assert (document_iri, RDF.type, AKN["bill"]) in graph
    assert (document_iri, ELI.number, Literal("DR-15-2026")) in graph
    assert (document_iri, ELI.is_realized_by, URIRef(f"{BASE_IRI}/akn/my/bill/dr/2026/15")) in graph

    part_iri = URIRef(f"{document_iri}/~part_I")
    clause_iri = URIRef(f"{document_iri}/~part_I__cl_1")
    assert (document_iri, ELI.has_part, part_iri) in graph
    assert (part_iri, ELI.is_part_of, document_iri) in graph
    assert (part_iri, ELI.has_part, clause_iri) in graph
    assert (clause_iri, ELI.is_part_of, part_iri) in graph
    assert (clause_iri, RDF.type, AKN["clause"]) in graph
    assert (clause_iri, ELI.number, Literal("1")) in graph

    # The document is not its own part, and the clause is not a part of the document directly:
    # containment is one edge per real parent, so a citation resolves to one place in the tree.
    assert (document_iri, ELI.has_part, clause_iri) not in graph


def test_every_quad_lands_in_the_expressions_own_named_graph() -> None:
    """One named graph per Expression, so a triple store holding the whole corpus can still say
    which document a statement came from — and drop one document without touching the rest."""
    dataset, document_iri = graph_of(built_xml())
    assert {quad[3] for quad in dataset.quads((None, None, None, None))} == {document_iri}


def test_every_human_readable_literal_carries_its_bcp_47_language_tag() -> None:
    """An untagged literal cannot tell a consumer whether it is reading Malay or English, which for
    a bilingual corpus published as one graph is not a nicety."""
    for language, title in (("ms", "RUU Contoh 2026"), ("en", "Example Bill 2026")):
        dataset, document_iri = graph_of(built_xml(language=language))
        graph = dataset.graph(document_iri)
        clause_iri = URIRef(f"{document_iri}/~part_I__cl_1")

        assert (document_iri, SCHEMA.name, Literal(title, lang=language)) in graph
        heading = graph.value(clause_iri, SCHEMA.name)
        text = graph.value(clause_iri, SCHEMA.text)
        assert isinstance(heading, Literal) and heading.language == language
        assert isinstance(text, Literal) and text.language == language

        # A language *code* is data, not prose: it stays an untagged literal.
        assert (document_iri, ELI.language, Literal(language)) in graph


def test_serialising_the_same_graph_twice_yields_identical_bytes() -> None:
    """rdflib promises no serialisation order, and the store compares bytes — so unstable ordering
    would turn every re-run into a rewrite and quietly destroy the pipeline's idempotence."""
    dataset, document_iri = graph_of(built_xml())
    assert render_nquads(dataset) == render_nquads(dataset)
    assert render_jsonld(dataset, document_iri) == render_jsonld(dataset, document_iri)

    # And two datasets built independently from the same document agree byte for byte.
    rebuilt, rebuilt_iri = graph_of(built_xml())
    assert render_nquads(rebuilt) == render_nquads(dataset)
    assert render_jsonld(rebuilt, rebuilt_iri) == render_jsonld(dataset, document_iri)


def test_the_json_ld_and_the_n_quads_state_exactly_the_same_triples() -> None:
    """ADR-023's guarantee, checked as triples rather than as text: the two files are two
    serialisations of one dataset, so neither can carry a fact the other lacks."""
    dataset, document_iri = graph_of(built_xml())

    from_jsonld = Graph()
    from_jsonld.parse(data=render_jsonld(dataset, document_iri).decode("utf-8"), format="json-ld")
    from_nquads = Dataset()
    from_nquads.parse(data=render_nquads(dataset).decode("utf-8"), format="nquads")

    assert set(from_jsonld) == set(dataset.graph(document_iri))
    assert {quad[:3] for quad in from_nquads.quads((None, None, None, None))} == set(from_jsonld)


def test_the_json_ld_declares_the_prefixes_its_compact_terms_depend_on() -> None:
    dataset, document_iri = graph_of(built_xml())
    document = json.loads(render_jsonld(dataset, document_iri))

    context = document["@context"]
    assert context["eli"] == str(ELI)
    assert context["schema"] == str(SCHEMA)
    assert context["akn"] == str(AKN)
    assert context["hasPart"] == {"@id": "eli:has_part", "@type": "@id"}

    # A flat top-level @graph, sorted by @id — not a named-graph wrapper (ADR-023).
    ids = [entry["@id"] for entry in document["@graph"]]
    assert ids == sorted(ids)
    assert str(document_iri) in ids


def test_n_quads_escapes_quotes_backslashes_and_line_breaks_inside_a_literal() -> None:
    """Byte level on purpose: this is the one property a triple comparison cannot see.

    `render_nquads` sorts *lines*, so a raw newline inside a literal does not merely produce an
    ugly file — it splits one statement into two unparseable ones. The previous hand-rolled
    serialiser escaped `"`, `\\` and `\\n` but not `\\r`, so a carriage return in bill text
    silently emitted a malformed quad.
    """
    root = Node(node_type="body", num=None, heading=None, eid="")
    clause = Node(node_type="clause", num="1", heading='Judul "istimewa"', eid="cl_1")
    clause.paragraphs.append('Teks "dipetik", satu garis miring \\ dan\r\nsatu baris baru.')
    root.children.append(clause)

    dataset, _ = build_graph(
        root,
        base_iri=BASE_IRI,
        expression_uri=IDENTITY.expression_uri("ms"),
        doc_type="bill",
        language="ms",
        bill=BILL,
        identity=IDENTITY,
    )
    nquads = render_nquads(dataset).decode("utf-8")

    assert '\\"istimewa\\"' in nquads
    assert '"Teks \\"dipetik\\", satu garis miring \\\\ dan\\r\\nsatu baris baru."@ms' in nquads
    # One line per statement: nothing in the text opened a new one.
    assert len(nquads.splitlines()) == len(list(dataset.quads((None, None, None, None))))
    assert all(line.endswith(" .") for line in nquads.splitlines())
