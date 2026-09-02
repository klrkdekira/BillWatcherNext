"""The provision tree serialised as Akoma Ntoso (OASIS LegalDocML) XML.

`akn` is the right name for exactly this file and its schema validator, and for nothing else in
the pipeline: Akoma Ntoso is what the standard calls itself, `.akn` is its conventional extension,
`akn` is its namespace prefix and `<akomaNtoso>` its root element. A reader who sees
`document.akn.xml` knows what is in it, and the vendored OASIS schema this is validated against
uses those names too.

What it is *not* is the domain. A Malaysian bill's Bahagian and Fasal exist whether or not anyone
renders them as XML; that structure lives in `graph.structure`, and this module turns it into one
serialisation at the end of the pipeline. ADR-030 makes the same split at the step level
(`render-akn` is the cheap deterministic half, downstream of the expensive read), so a renderer fix
regenerates the corpus in seconds without re-reading a single document.
"""

import re
from typing import Any
from xml.etree import ElementTree as ET

from billwatcher.frbr import AKN_LANGUAGES, COUNTRY, WorkIdentity
from billwatcher.graph.tree import Node
from billwatcher.graph.vocabulary import AKN_ELEMENTS, HCONTAINER_TYPES

# The standard's own namespace, quoted from the OASIS schema this output is validated against.
AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"

__all__ = ["AKN_NS", "AknSchemaError", "frbr_date", "render_akn", "xml_text"]


# What XML 1.0 refuses inside text: the C0 controls other than tab, newline and return, the
# surrogates, and the two noncharacters. A PDF's text layer can carry them — found live: a font
# that produced U+0018 wherever the digit 1 was printed, 171 times in one reading — and
# `ElementTree` writes them out unescaped, producing a document that calls itself XML and no parser
# will open, so a tree that passed the gate recorded a failed render. Each is replaced with U+FFFD
# rather than deleted: the reading had a character there, and the replacement says so where a
# deletion would quietly turn `1967` into `967`.
_XML_FORBIDDEN_RE = re.compile("[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def xml_text(value: str) -> str:
    """`value` with each character XML cannot carry replaced by U+FFFD; otherwise untouched."""
    return _XML_FORBIDDEN_RE.sub("\ufffd", value)


class AknSchemaError(RuntimeError):
    """Rendered XML that the vendored OASIS schema refuses.

    Not a bad reading — a broken renderer. Raised rather than reported so a defect in this module
    can never publish XML that calls itself Akoma Ntoso and cannot be read by Akoma Ntoso tooling.
    """


_ORGANISATIONS = {
    "dr": ("dewanRakyat", "/akn/ontology/organization/my/dewanRakyat", "Dewan Rakyat"),
    "dn": ("dewanNegara", "/akn/ontology/organization/my/dewanNegara", "Dewan Negara"),
}
_PUBLISHER = ("billwatcher", "/akn/ontology/organization/billwatcher", "BillWatcher")


def render_akn(root: Node, *, identity: WorkIdentity, language: str, bill: dict[str, Any]) -> bytes:
    """Serialise a provision tree as a schema-valid Akoma Ntoso document.

    `<bill>` for a clause-numbered document, `<act>` for a section-numbered one (HANDOFF 26.2).
    Identification is a real FRBR triple rather than the three near-identical blocks this used to
    emit: the Work is the bill, the Expression is that bill in one language, and the Manifestation
    is this XML file — and each level's `FRBRthis` names that level, while every `FRBRuri` names the
    Work, as the AKN naming convention requires.

    `FRBRdate` carries the identifier's year and nothing more precise. We know the bill's year
    because it is printed in its own number; we do not know the day it was introduced, and AKN
    accepts a year-precision date, so inventing `2026-01-01` to fill the attribute would put a
    fabricated fact on the public record.
    """
    ET.register_namespace("", AKN_NS)
    akoma = ET.Element(f"{{{AKN_NS}}}akomaNtoso")
    doc_el = ET.SubElement(akoma, f"{{{AKN_NS}}}{identity.doc_type}", {"name": identity.doc_type})

    org_eid, org_href, org_label = _ORGANISATIONS[identity.chamber_code]
    date = frbr_date(bill, year=identity.year)
    meta = ET.SubElement(doc_el, f"{{{AKN_NS}}}meta")
    identification = ET.SubElement(meta, f"{{{AKN_NS}}}identification", {"source": "#billwatcher"})

    work = ET.SubElement(identification, f"{{{AKN_NS}}}FRBRWork")
    _frbr_common(work, this=identity.work_uri, uri=identity.work_uri, date=date, author=org_eid)
    ET.SubElement(work, f"{{{AKN_NS}}}FRBRcountry", {"value": COUNTRY})
    ET.SubElement(work, f"{{{AKN_NS}}}FRBRsubtype", {"value": identity.chamber_code})
    ET.SubElement(work, f"{{{AKN_NS}}}FRBRnumber", {"value": str(identity.number)})

    expression_uri = identity.expression_uri(language)
    expression = ET.SubElement(identification, f"{{{AKN_NS}}}FRBRExpression")
    _frbr_common(expression, this=expression_uri, uri=identity.work_uri, date=date, author=org_eid)
    ET.SubElement(expression, f"{{{AKN_NS}}}FRBRlanguage", {"language": AKN_LANGUAGES[language]})

    manifestation = ET.SubElement(identification, f"{{{AKN_NS}}}FRBRManifestation")
    _frbr_common(
        manifestation,
        this=identity.manifestation_uri(language, "xml"),
        uri=identity.work_uri,
        date=date,
        author=_PUBLISHER[0],
    )
    ET.SubElement(manifestation, f"{{{AKN_NS}}}FRBRformat", {"value": "xml"})

    references = ET.SubElement(meta, f"{{{AKN_NS}}}references", {"source": "#billwatcher"})
    for eid, href, label in (_PUBLISHER, (org_eid, org_href, org_label)):
        ET.SubElement(
            references,
            f"{{{AKN_NS}}}TLCOrganization",
            {"eId": eid, "href": href, "showAs": label},
        )

    title = (bill.get("titles") or {}).get(f"raw_{language}")
    if title:
        preface = ET.SubElement(doc_el, f"{{{AKN_NS}}}preface")
        block = ET.SubElement(preface, f"{{{AKN_NS}}}longTitle", {"eId": "longTitle"})
        ET.SubElement(block, f"{{{AKN_NS}}}p").text = xml_text(title)

    # AKN puts a preamble before the body, not inside it — the extractor's own prompt offers
    # `preamble` as a node type, so a correct reading can contain one, and appending it into
    # `<body>` made the document schema-invalid and counted that correct reading as failed.
    preamble_nodes = [child for child in root.children if child.node_type == "preamble"]
    if preamble_nodes:
        preamble = ET.SubElement(doc_el, f"{{{AKN_NS}}}preamble")
        for node in preamble_nodes:
            container = ET.SubElement(preamble, f"{{{AKN_NS}}}p")
            container.text = xml_text(
                " ".join(part for part in [node.heading, *node.paragraphs] if part)
            )

    body = ET.SubElement(doc_el, f"{{{AKN_NS}}}body")
    for child in root.children:
        if child.node_type == "preamble":
            continue
        body.append(_render_node(child))
    xml_bytes: bytes = ET.tostring(akoma, xml_declaration=True, encoding="utf-8")
    return xml_bytes


def _frbr_common(
    block: ET.Element, *, this: str, uri: str, date: tuple[str, str], author: str
) -> None:
    """The four children AKN requires at every FRBR level, in schema order."""
    ET.SubElement(block, f"{{{AKN_NS}}}FRBRthis", {"value": this})
    ET.SubElement(block, f"{{{AKN_NS}}}FRBRuri", {"value": uri})
    ET.SubElement(block, f"{{{AKN_NS}}}FRBRdate", {"date": date[0], "name": date[1]})
    ET.SubElement(block, f"{{{AKN_NS}}}FRBRauthor", {"href": f"#{author}"})


def frbr_date(bill: dict[str, Any], *, year: int) -> tuple[str, str]:
    """`(date, name)` for an FRBR block: a real published date where one exists.

    AKN's `date` attribute is an `xs:date`, so year precision cannot be expressed in the value
    itself — which is a problem, because for many archived bills the year printed in the
    identifier is genuinely all we know. Rather than fabricate 1 January and let it read as a
    real date, this prefers the earliest event date the bill's own listing published, and when
    there is none it falls back to `YYYY-01-01` under the name `yearOnly`. The label is what
    makes the imprecision machine-detectable instead of a silent invention.
    """
    starts = [
        span["start"]
        for chamber in (bill.get("chambers") or {}).values()
        for spans in (chamber.get("dates") or {}).values()
        for span in spans
        if isinstance(span.get("start"), str)
    ]
    if starts:
        return min(starts), "earliestRecorded"
    return f"{year:04d}-01-01", "yearOnly"


def _render_node(node: Node) -> ET.Element:
    """One hierarchy element.

    Text that belongs to a node with children becomes `<intro>` rather than `<content>`: AKN's
    hierarchy model allows a container to introduce its children or to carry content, not both, and
    the old renderer emitted `<content>` alongside child elements — which is how a document that
    looked fine locally failed the schema.
    """
    attrs = {"eId": node.eid}
    if node.node_type in HCONTAINER_TYPES:
        attrs["name"] = node.node_type
    element = ET.Element(f"{{{AKN_NS}}}{AKN_ELEMENTS[node.node_type]}", attrs)
    if node.num:
        ET.SubElement(element, f"{{{AKN_NS}}}num").text = xml_text(node.num)
    if node.heading:
        ET.SubElement(element, f"{{{AKN_NS}}}heading").text = xml_text(node.heading)
    if node.paragraphs:
        wrapper = "intro" if node.children else "content"
        container = ET.SubElement(element, f"{{{AKN_NS}}}{wrapper}")
        for text in node.paragraphs:
            ET.SubElement(container, f"{{{AKN_NS}}}p").text = xml_text(text)
    for child in node.children:
        element.append(_render_node(child))
    if not node.paragraphs and not node.children:
        # A hierarchy element must carry something. An empty provision is a real reading of a
        # heading-only clause, so give it an empty content block rather than dropping it.
        content = ET.SubElement(element, f"{{{AKN_NS}}}content")
        ET.SubElement(content, f"{{{AKN_NS}}}p")
    return element
