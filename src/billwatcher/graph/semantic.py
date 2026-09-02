"""Step 5 of the file-first pipeline: ELI-style semantic files (JSON-LD + RDF N-Quads).

Reads only `document.akn.xml` (step 4's output) — never markdown or the PDF again, so this step is
decoupled from re-running structure extraction and needs no LLM. AKN carries structure and text;
this is the metadata graph HANDOFF 26.5 calls the other half of Stage L5 ("AKN carries structure
and text; ELI carries the metadata graph. Publish both.").

Both files come from one `rdflib.Dataset`. ADR-023's guarantee — that the JSON-LD and the N-Quads
can never disagree, because there is one graph construction rather than two renderers that could
drift — is preserved, but the mechanism changed: it used to be a hand-rolled serialiser flattening
the JSON-LD dict, and it is now two serialisations of one in-memory graph. That swap is what buys
correct N-Quads escaping (the previous `_escape_literal` handled `"`, `\\` and `\n` but not `\r` or
`\t`, so a carriage return in bill text produced a malformed quad) and language-tagged literals,
which for a bilingual Malay/English corpus is not a nicety: an untagged literal cannot tell a
consumer whether it is reading Malay or English.

Two details that look like style and are not:

- N-Quads is serialised from the `Dataset` and JSON-LD from the named `Graph` inside it. rdflib's
  N-Quads serialiser requires a context-aware store, which a plain `Graph` is not; and serialising
  the whole Dataset to JSON-LD would nest everything under a named-graph wrapper, silently changing
  the flat top-level `@graph` shape ADR-023 committed to.
- Both outputs are sorted before they are written. rdflib does not promise stable serialisation
  order, and `_write_if_changed` compares bytes — so unstable ordering would turn every re-run into
  a rewrite and quietly destroy the idempotence the whole pipeline is built on.

Language tags are BCP 47 (`ms`, `en`) here, not the ISO 639-3 codes (`msa`, `eng`) that appear in
the AKN IRI. RDF requires well-formed BCP 47 and HANDOFF 15 mandates it for structured output;
`frbr.AKN_LANGUAGES` is the single place the two spellings are mapped.

Known limitation, stated rather than assumed away: the predicates are not yet SHACL-validated
against the published ELI ontology (Gate L5, HANDOFF 26.6). pySHACL is the intended implementation
and is deliberately not added yet — the shapes Gate L5 specifies check `amends` targets and
`validFrom` intervals, which Stages L3 and L4 would have to produce first, so it would validate
almost nothing today. Building the graph in rdflib is what makes those shapes drop in later
without a rewrite.
"""

import json
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree as ET

from rdflib import Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from billwatcher.files import sidecar_bytes
from billwatcher.frbr import (
    AKN_LANGUAGES,
    FrbrIdentityError,
    WorkIdentity,
    identity_from_bill,
)
from billwatcher.graph.render import AKN_NS
from billwatcher.graph.tree import Node
from billwatcher.graph.vocabulary import AKN_ELEMENTS
from billwatcher.provenance import build_record, needs_rebuild
from billwatcher.reporting import StepFailure, StepResult, describe_error
from billwatcher.store import PipelineStore, StoredDocumentRef, keys_for, sha256_of
from billwatcher.version import SEMANTIC_VERSION

ELI = Namespace("http://data.europa.eu/eli/ontology#")
SCHEMA = Namespace("https://schema.org/")
AKN = Namespace(f"{AKN_NS}#")

_JSONLD_CONTEXT = {
    "eli": str(ELI),
    "akn": str(AKN),
    "schema": str(SCHEMA),
    "hasPart": {"@id": "eli:has_part", "@type": "@id"},
    "isPartOf": {"@id": "eli:is_part_of", "@type": "@id"},
}

_TAG_TO_NODE_TYPE = {value: key for key, value in AKN_ELEMENTS.items()}


def jsonld_context_definition() -> dict[str, Any]:
    """The standalone context published beside the graphs in the static cache.

    `render_jsonld` and the exported definition deliberately share this object. A copied second
    context would eventually describe compact terms differently from the files that use them.
    Returning a fresh outer mapping keeps callers from mutating the renderer's module constant.
    """
    return {"@context": dict(_JSONLD_CONTEXT)}


class SemanticConversionError(RuntimeError):
    """The stored Akoma Ntoso document could not be read back."""


def parse_akn(xml_bytes: bytes) -> tuple[Node, str, str, str]:
    """Reconstruct `(tree, expression_uri, document_type, language)` from stored Akoma Ntoso.

    Reads step 4's file rather than step 4's in-memory tree, which is what lets the two steps run
    any time apart and lets step 5 be re-run without re-invoking the extractor (ADR-023).
    """
    if b"<!DOCTYPE" in xml_bytes[:2048] or b"<!ENTITY" in xml_bytes[:2048]:
        # The same refusal `scraper.parse_archive` already makes. These bytes are normally ours,
        # but markdown and AKN can now be imported and the corpus is served publicly, so a document
        # declaring a doctype is refused rather than handed to an entity-expanding parser.
        raise SemanticConversionError("XML declaring a doctype or entity is refused")
    try:
        root_el = ET.fromstring(xml_bytes)
        doc_el = next(iter(root_el))
    except (ET.ParseError, StopIteration) as error:
        raise SemanticConversionError(f"not a well-formed Akoma Ntoso document: {error}") from error
    doc_name = doc_el.tag.rsplit("}", 1)[-1]
    expression = _meta_value(doc_el, "FRBRExpression", "FRBRthis")
    iso_language = _meta_value(doc_el, "FRBRExpression", "FRBRlanguage", attribute="language")
    language = next((tag for tag, code in AKN_LANGUAGES.items() if code == iso_language), "")
    if not expression or not language:
        raise SemanticConversionError(
            f"document carries no usable Expression identity: uri={expression!r} "
            f"language={iso_language!r}"
        )
    root = Node(node_type="body", num=None, heading=None, eid="")
    body_el = doc_el.find(f"{{{AKN_NS}}}body")
    if body_el is not None:
        for child in body_el:
            root.children.append(_node_from_element(child))
    return root, expression, doc_name, language


def _meta_value(doc_el: ET.Element, level: str, element: str, *, attribute: str = "value") -> str:
    path = f"{{{AKN_NS}}}meta/{{{AKN_NS}}}identification/{{{AKN_NS}}}{level}/{{{AKN_NS}}}{element}"
    found = doc_el.find(path)
    return (found.get(attribute) if found is not None else None) or ""


def _node_from_element(element: ET.Element) -> Node:
    tag = element.tag.rsplit("}", 1)[-1]
    num_el = element.find(f"{{{AKN_NS}}}num")
    heading_el = element.find(f"{{{AKN_NS}}}heading")
    node = Node(
        node_type=_TAG_TO_NODE_TYPE.get(tag, tag),
        num=num_el.text if num_el is not None else None,
        heading=heading_el.text if heading_el is not None else None,
        eid=element.get("eId", ""),
    )
    for wrapper in ("content", "intro", "wrapUp"):
        container = element.find(f"{{{AKN_NS}}}{wrapper}")
        if container is not None:
            node.paragraphs.extend(p.text for p in container.findall(f"{{{AKN_NS}}}p") if p.text)
    for child in element:
        if child.tag.rsplit("}", 1)[-1] in _TAG_TO_NODE_TYPE:
            node.children.append(_node_from_element(child))
    return node


def build_graph(
    root: Node,
    *,
    base_iri: str,
    expression_uri: str,
    doc_type: str,
    language: str,
    bill: dict[str, Any],
    identity: WorkIdentity,
) -> tuple[Dataset, URIRef]:
    """One RDF dataset: the document, every provision, and the edges between them.

    A flat graph, not a nested one: `hasPart`/`isPartOf` edges rather than containment, because
    N-Quads has no nesting and one graph shape for one set of facts is the point.
    """
    document_iri = URIRef(f"{base_iri}{expression_uri}")
    dataset = Dataset()
    graph = dataset.graph(document_iri)

    graph.add((document_iri, RDF.type, AKN[doc_type]))
    graph.add(
        (
            document_iri,
            ELI.jurisdiction,
            URIRef("http://publications.europa.eu/resource/authority/country/MYS"),
        )
    )
    graph.add((document_iri, ELI.is_realized_by, URIRef(f"{base_iri}{identity.work_uri}")))
    graph.add((document_iri, ELI.language, Literal(language)))
    identifier = bill.get("identifier") or {}
    if identifier.get("normalized"):
        graph.add((document_iri, ELI.number, Literal(str(identifier["normalized"]))))
    title = (bill.get("titles") or {}).get(f"raw_{language}") or (bill.get("titles") or {}).get(
        "raw_ms"
    )
    if title:
        graph.add((document_iri, SCHEMA.name, Literal(title, lang=language)))

    for child in root.children:
        _collect(
            child,
            graph=graph,
            parent_iri=document_iri,
            document_iri=document_iri,
            language=language,
        )
    return dataset, document_iri


def _collect(
    node: Node,
    *,
    graph: Graph,
    parent_iri: URIRef,
    document_iri: URIRef,
    language: str,
) -> None:
    if not node.eid:
        return
    node_iri = URIRef(f"{document_iri}/~{node.eid}")
    graph.add((node_iri, RDF.type, AKN[node.node_type]))
    graph.add((node_iri, ELI.is_part_of, parent_iri))
    graph.add((parent_iri, ELI.has_part, node_iri))
    if node.num:
        graph.add((node_iri, ELI.number, Literal(node.num)))
    if node.heading:
        graph.add((node_iri, SCHEMA.name, Literal(node.heading, lang=language)))
    if node.paragraphs:
        graph.add((node_iri, SCHEMA.text, Literal(" ".join(node.paragraphs), lang=language)))
    for child in node.children:
        _collect(
            child,
            graph=graph,
            parent_iri=node_iri,
            document_iri=document_iri,
            language=language,
        )


def render_jsonld(dataset: Dataset, document_iri: URIRef) -> bytes:
    """The flat `@graph` shape, serialised deterministically.

    Round-tripped through `json.dumps` with sorted keys rather than trusting rdflib's own key
    order, so the bytes are stable run to run and `_write_if_changed` stays a real no-op.
    """
    graph = dataset.graph(document_iri)
    raw = graph.serialize(format="json-ld", context=_JSONLD_CONTEXT, auto_compact=True)
    document = json.loads(raw)
    if "@graph" in document:
        document["@graph"] = sorted(document["@graph"], key=lambda entry: str(entry.get("@id", "")))
    text = json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def render_nquads(dataset: Dataset) -> bytes:
    """N-Quads from the same dataset, line-sorted so the bytes are reproducible."""
    raw = dataset.serialize(format="nquads")
    lines = sorted(line for line in raw.splitlines() if line.strip())
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


def generate_semantic_files(store: PipelineStore, *, base_iri: str) -> StepResult:
    """Offline. Converts every document whose semantic files are missing or out of date."""
    counts = {"eligible": 0, "converted": 0, "failed": 0}
    failures: list[StepFailure] = []
    for ref in store.iter_documents():
        keys = keys_for(ref)
        if not store.has_akn(**keys):
            continue
        xml_bytes = store.load_akn(**keys)
        if xml_bytes is None:
            counts["failed"] += 1
            failures.append(_failure(ref, "Akoma Ntoso disappeared between listing and read"))
            continue
        # `build_graph` reads the bill record for `eli:number` and the document's `schema:name`, so
        # it is an input to this artifact exactly as the Akoma Ntoso is, and a corrected bill title
        # has to regenerate the graph. Recorded as a digest rather than in `source_files` because it
        # does not live in this document's directory, and `source_files` is the list
        # `pipeline verify` re-hashes there.
        bill_record = store.load_bill(ref.bill_slug)
        inputs = {
            "source_files": [{"file": "document.akn.xml", "sha256": sha256_of(xml_bytes)}],
            "bill_sha256": sha256_of(sidecar_bytes(bill_record or {})),
            "code_version": SEMANTIC_VERSION,
            "producer": "rdflib",
            "base_iri": base_iri,
        }
        if not needs_rebuild(
            store, ref, artifact="semantic", inputs=inputs, present=store.has_semantic(**keys)
        ):
            continue
        counts["eligible"] += 1
        try:
            tree, expression_uri, doc_type, language = parse_akn(xml_bytes)
            bill = store.load_bill(ref.bill_slug)
            if bill is None:
                raise FrbrIdentityError(f"no bill record for {ref.bill_slug!r}")
            identity = identity_from_bill(bill, doc_type=doc_type)
            dataset, document_iri = build_graph(
                tree,
                base_iri=base_iri,
                expression_uri=expression_uri,
                doc_type=doc_type,
                language=language,
                bill=bill,
                identity=identity,
            )
            jsonld_bytes = render_jsonld(dataset, document_iri)
            nquads_bytes = render_nquads(dataset)
        except Exception as error:
            counts["failed"] += 1
            failures.append(_failure(ref, describe_error(error)))
            continue
        store.save_jsonld(**keys, content=jsonld_bytes)
        store.save_rdf(**keys, content=nquads_bytes)
        store.save_provenance(
            **keys,
            artifact="semantic",
            record=build_record(
                artifact="semantic",
                inputs=inputs,
                outputs={"document.jsonld": jsonld_bytes, "document.nq": nquads_bytes},
            ),
        )
        counts["converted"] += 1
    return StepResult(counts=counts, failures=tuple(failures))


def _failure(ref: StoredDocumentRef, reason: str) -> StepFailure:
    return StepFailure(
        bill_slug=ref.bill_slug, doc_key=ref.doc_key, version=ref.version, reason=reason
    )


def utc_now() -> datetime:
    """Indirection so a step's manifest timestamp is stubbable in a test."""
    return datetime.now(UTC)
