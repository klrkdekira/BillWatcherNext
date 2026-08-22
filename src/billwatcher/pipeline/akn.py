"""Step 4 of the file-first pipeline: convert markdown to Akoma Ntoso (OASIS LegalDocML) XML.

Markdown is produced elsewhere — the operator's own vLLM endpoint reads the PDF — and lands at
`documents/<bill-slug>/<doc-key>/v<NNN>/document.md` (`PipelineStore.save_markdown`). This step
never touches a PDF or a page image; it only ever reads that markdown text and writes
`document.akn.xml` beside it.

Reading the document's *structure* out of that markdown is also LLM-assisted, at the operator's
direction: `pipeline.akn_llm.VllmMarkdownStructureExtractor` sends the markdown to the same class
of vLLM OpenAI-compatible endpoint used elsewhere in this project and asks for the provision
hierarchy back as JSON. That is the right tool for the hardest part of this problem — telling a
document's Arrangement of Sections (table of contents) apart from its body, when a
table-of-contents entry is textually identical to the body provision it lists
(`5. Kewajipan untuk melaporkan` appears twice) — because it needs contextual understanding a
regex cannot have without a page/geometry signal, which markdown does not carry.

What stays deterministic, and always will: `Node`, `render_akn`, and `assign_eids`. An extractor
(regex or LLM) only ever decides *what* provisions exist and their printed numbers/text; this
module decides eId assignment and AKN serialisation from that, the same separation of concerns
`billwatcher.mineru` uses between a model's content blocks and this project's own markdown
assembly. `RegexMarkdownStructureExtractor` (deterministic, offline) also satisfies the same
`MarkdownStructureExtractor` protocol, for tests and for use with no LLM configured — it reuses
`billwatcher.legislation.vocabulary` (Bahagian/Part, Seksyen/Section, Fasal/Clause, eId prefixes,
roman numeral and paragraph-letter resolution), which is pure text classification with no
dependency on a database or on PDF layout geometry, so it applies to markdown lines exactly as it
already applies to the Postgres-backed Stage L1 reading (HANDOFF 26.2). It does not attempt the
Arrangement/body split described above, which is exactly why the LLM-assisted path is preferred.
"""

from typing import Any, Protocol
from xml.etree import ElementTree as ET

from billwatcher.legislation.vocabulary import (
    AKN_ELEMENTS,
    EID_PREFIXES,
    arrangement_heading,
    container_heading,
    parenthesised,
    provision_number,
    resolve_letter,
    schedule_heading,
)
from billwatcher.pipeline import fidelity
from billwatcher.pipeline.akn_schema import validate_akn
from billwatcher.pipeline.frbr import (
    AKN_LANGUAGES,
    COUNTRY,
    FrbrIdentityError,
    WorkIdentity,
    identity_from_bill,
)
from billwatcher.pipeline.provenance import build_record, needs_rebuild
from billwatcher.pipeline.reporting import StepFailure, StepResult, describe_error
from billwatcher.pipeline.store import (
    DocumentKeys,
    PipelineStore,
    StoredDocumentRef,
    keys_for,
    sha256_of,
)
from billwatcher.pipeline.tree import Node, strip_markdown_line
from billwatcher.storage.audit_tree import sidecar_bytes
from billwatcher.version import AKN_FIDELITY_GATE_VERSION, AKN_VERSION

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"


class AknSchemaError(RuntimeError):
    """A rendered document is not valid Akoma Ntoso 3.0 — our renderer's fault, not the source's."""


__all__ = [
    "AKN_NS",
    "AknSchemaError",
    "MarkdownStructureExtractor",
    "Node",
    "RegexMarkdownStructureExtractor",
    "assign_eids",
    "convert_to_akn",
    "infer_language_and_unit",
    "parse_markdown_structure",
    "render_akn",
    "resolve_language",
    "strip_markdown_line",
]


# A marginal note is a short label, not a sentence: `Tajuk ringkas`, `Kewajipan untuk melaporkan`,
# `Penalti`. 80 characters is not a fresh guess — it is the same bound
# `legislation.layout._MARGIN_MAX_CHARS` already uses to tell a marginal note from an indented block
# when it has the page geometry to look at. The number is duplicated rather than imported because
# that module pulls in pdfminer and this pipeline is deliberately PDF-free (ADR-021).
MAX_MARGINAL_NOTE_CHARS = 80

_SENTENCE_ENDINGS = (".", ";", ":", "!", "?")


def split_marginal_note(rest: str) -> tuple[str | None, str]:
    """Split the text after a provision number into `(marginal note, body text)`.

    Malaysian bills print a provision two ways. Usually the marginal note is on its own line and
    the body follows: `5. Kewajipan untuk melaporkan` then the prose. But an amendment bill
    typically has no note at all and runs the whole provision in after the number —
    `2. Kanun Keseksaan [Akta 574] dipinda dalam seksyen 375 dengan menggantikan ...` — and the
    printed line is then indistinguishable in shape from the first case.

    Getting this wrong is not cosmetic. `heading` and body text are published under *different*
    rights rules: headings are published in metadata-only mode and body text is withheld
    (ADR-027). Treating a run-in sentence as a heading therefore publishes drafted legislative text
    while the rights review is open. So the test is deliberately conservative — a note has to be
    short and has to not read as a sentence — and anything else is returned as body text, which is
    the safe classification. `pipeline.redact` enforces the same bound independently, because this
    parser is not the only producer of a tree.
    """
    text = rest.strip()
    if not text:
        return None, ""
    if parenthesised(text) is not None:
        # `1. (1) Akta ini ...` — the text opens a subsection, so the provision has no note of its
        # own. The same rule `legislation.structure` applies for the Postgres-backed reading.
        return None, text
    if len(text) > MAX_MARGINAL_NOTE_CHARS or text.endswith(_SENTENCE_ENDINGS):
        return None, text
    return text, ""


def parse_markdown_structure(markdown_text: str, *, unit: str = "clause") -> Node:
    """Build the provision tree from markdown text.

    `unit` is `"clause"` for a bill or `"section"` for an Act (HANDOFF 26.2) — every document in
    this pipeline is a Parliament bill PDF, so the default is `"clause"`; `infer_unit` overrides
    it when the markdown's own Arrangement heading says otherwise.
    """
    root = Node(node_type="body", num=None, heading=None, eid="")
    containers: list[Node] = []  # open part/chapter/schedule ancestors, root-most first
    provision: Node | None = None
    open_subsection: Node | None = None
    open_paragraph: Node | None = None
    last_letter: tuple[str, str] | None = None
    in_schedule = False

    def eid_of(parent: Node, node_type: str, token: str) -> str:
        piece = f"{EID_PREFIXES[node_type]}_{token}"
        return f"{parent.eid}__{piece}" if parent.eid else piece

    def reset_provision_state() -> None:
        nonlocal provision, open_subsection, open_paragraph, last_letter
        provision, open_subsection, open_paragraph, last_letter = None, None, None, None

    def innermost_open() -> Node:
        if open_paragraph is not None:
            return open_paragraph
        if open_subsection is not None:
            return open_subsection
        if provision is not None:
            return provision
        if containers:
            return containers[-1]
        return root

    for raw_line in markdown_text.splitlines():
        text = strip_markdown_line(raw_line)
        if not text:
            continue
        if arrangement_heading(text) is not None:
            # The heading line itself; entries beneath it are a known limitation (module docstring).
            continue

        container = container_heading(text)
        if container is not None:
            node_type, num, heading = container
            if node_type == "part":
                parent, containers = root, []
            elif containers and containers[0].node_type == "part":
                parent, containers = containers[0], containers[:1]
            else:
                parent, containers = root, []
            node = Node(node_type, num, heading or None, eid_of(parent, node_type, num))
            parent.children.append(node)
            containers.append(node)
            reset_provision_state()
            in_schedule = False
            continue

        schedule_num = schedule_heading(text)
        if schedule_num is not None:
            node = Node("schedule", schedule_num, None, eid_of(root, "schedule", schedule_num))
            root.children.append(node)
            containers = [node]
            reset_provision_state()
            in_schedule = True
            continue

        provision_match = provision_number(text)
        if provision_match is not None:
            num, rest = provision_match
            node_type = "paragraph" if in_schedule else unit
            parent = containers[-1] if containers else root
            note, leading = split_marginal_note(rest)
            node = Node(node_type, num, note, eid_of(parent, node_type, num))
            parent.children.append(node)
            provision, open_subsection, open_paragraph, last_letter = node, None, None, None
            if leading:
                # Body text that ran in after the provision number. It is the provision's own
                # prose, so it belongs in its paragraphs — never in `heading`, which is published
                # under a different rights rule (ADR-027). When it opens a subsection, that
                # subsection becomes the open one so a following `(2)` continues the same list
                # rather than attaching to the provision.
                inline = parenthesised(leading)
                if inline is not None and inline[0] == "subsection":
                    _, token, remainder = inline
                    child = Node("subsection", token, None, eid_of(node, "subsection", token))
                    if remainder:
                        child.paragraphs.append(remainder)
                    node.children.append(child)
                    open_subsection = child
                else:
                    node.paragraphs.append(leading)
            continue

        parenthesised_match = parenthesised(text) if provision is not None else None
        if parenthesised_match is not None:
            assert provision is not None  # guarded above; narrows for the parent lookups below
            kind, token, rest = parenthesised_match
            if kind == "subsection":
                node = Node("subsection", token, None, eid_of(provision, "subsection", token))
                provision.children.append(node)
                open_subsection, open_paragraph, last_letter = node, None, None
            else:
                resolved = resolve_letter(
                    token,
                    previous=last_letter[0] if last_letter else None,
                    previous_type=last_letter[1] if last_letter else None,
                )
                if resolved == "paragraph":
                    parent = open_subsection or provision
                    node = Node("paragraph", token, None, eid_of(parent, "paragraph", token))
                    parent.children.append(node)
                    open_paragraph = node
                else:
                    parent = open_paragraph or open_subsection or provision
                    node = Node("subparagraph", token, None, eid_of(parent, "subparagraph", token))
                    parent.children.append(node)
                last_letter = (token, resolved)
            if rest:
                node.paragraphs.append(rest)
            continue

        innermost_open().paragraphs.append(text)

    return root


def assign_eids(root: Node) -> None:
    """Assign every descendant's `eId` from its parent's, in place.

    The one piece of bookkeeping never delegated to an extractor, LLM or regex alike: an eId is
    an identifier, and guessing one from a model's output would repeat exactly the mistake
    HANDOFF 26.2 warns against for `wId` — a node's numbering must come from what it printed, not
    from anything invented on top of it. A node with no `num` (should not happen for a
    well-formed tree) falls back to its parent's eId rather than breaking the walk.
    """

    def walk(node: Node, parent_eid: str) -> None:
        for child in node.children:
            if child.num:
                piece = f"{EID_PREFIXES[child.node_type]}_{child.num}"
                child.eid = f"{parent_eid}__{piece}" if parent_eid else piece
            else:
                child.eid = parent_eid
            walk(child, child.eid)

    walk(root, "")


class MarkdownStructureExtractor(Protocol):
    """What `convert_to_akn` needs from whatever reads a document's provision hierarchy.

    The identity attributes are part of the contract because the step has to record *what* read a
    document's structure, not merely that something did. Without them a prompt improvement or a
    model swap leaves every existing artifact looking current, and the corpus silently mixes
    readings from different producers with no way to tell which is which.
    """

    name: str
    model_id: str | None
    prompt_sha256: str | None

    def extract(self, markdown_text: str, *, unit: str) -> Node: ...


class RegexMarkdownStructureExtractor:
    """Deterministic, offline, no LLM: wraps `parse_markdown_structure`.

    Does not attempt the Arrangement/body split (module docstring); useful for tests and for
    running this step with no LLM endpoint configured, not the default for production use. Its
    distinct `name` is what makes a regex-built artifact correctly read as stale once an LLM
    extractor is configured, rather than being mistaken for an equivalent reading.
    """

    name = "regex"
    model_id: str | None = None
    prompt_sha256: str | None = None

    def extract(self, markdown_text: str, *, unit: str) -> Node:
        return parse_markdown_structure(markdown_text, unit=unit)


def infer_language_and_unit(markdown_text: str) -> tuple[str | None, str]:
    """`(language, unit)` from the markdown's own Arrangement heading.

    The unit decides whether this is a `<bill>` of clauses or an `<act>` of sections (HANDOFF
    26.2); everything in this pipeline is a Parliament bill, so `clause` is the right default even
    with no Arrangement heading at all.

    The language is returned separately, and as `None` when the document declares nothing, because
    it is not a thing to default. It becomes a permanent component of the Expression IRI, so
    guessing it — the previous renderer hard-coded `msa` for every document — mints a permanent
    identifier asserting a fact nobody established. HANDOFF 26.7 blesses the Arrangement heading as
    the source for it and warns specifically against sniffing the language out of the document's
    URL or filename, which upstream spells inconsistently.
    """
    for raw_line in markdown_text.splitlines():
        text = strip_markdown_line(raw_line)
        if not text:
            continue
        classified = arrangement_heading(text)
        if classified is not None:
            return classified[0], classified[1]
    return None, "clause"


# The organisations an FRBR block may point at. AKN requires every `FRBRauthor` to reference a
# declared TLCOrganization, so the `references` block and these hrefs are one fact in two places.
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
        ET.SubElement(block, f"{{{AKN_NS}}}p").text = title

    # AKN puts a preamble before the body, not inside it — the extractor's own prompt offers
    # `preamble` as a node type, so a correct reading can contain one, and appending it into
    # `<body>` made the document schema-invalid and counted that correct reading as failed.
    preamble_nodes = [child for child in root.children if child.node_type == "preamble"]
    if preamble_nodes:
        preamble = ET.SubElement(doc_el, f"{{{AKN_NS}}}preamble")
        for node in preamble_nodes:
            container = ET.SubElement(preamble, f"{{{AKN_NS}}}p")
            container.text = " ".join(part for part in [node.heading, *node.paragraphs] if part)

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
    if node.node_type == "schedule":
        attrs["name"] = "schedule"
    element = ET.Element(f"{{{AKN_NS}}}{AKN_ELEMENTS[node.node_type]}", attrs)
    if node.num:
        ET.SubElement(element, f"{{{AKN_NS}}}num").text = node.num
    if node.heading:
        ET.SubElement(element, f"{{{AKN_NS}}}heading").text = node.heading
    if node.paragraphs:
        wrapper = "intro" if node.children else "content"
        container = ET.SubElement(element, f"{{{AKN_NS}}}{wrapper}")
        for text in node.paragraphs:
            ET.SubElement(container, f"{{{AKN_NS}}}p").text = text
    for child in node.children:
        element.append(_render_node(child))
    if not node.paragraphs and not node.children:
        # A hierarchy element must carry something. An empty provision is a real reading of a
        # heading-only clause, so give it an empty content block rather than dropping it.
        content = ET.SubElement(element, f"{{{AKN_NS}}}content")
        ET.SubElement(content, f"{{{AKN_NS}}}p")
    return element


def resolve_language(
    store: PipelineStore, ref: StoredDocumentRef, markdown_text: str
) -> tuple[str, str | None]:
    """`(language, disagreement)` for one document, refusing to invent either.

    The language is a permanent component of the Expression IRI, so it comes from a recorded fact:
    what the operator declared when importing the markdown (they know which PDF they extracted),
    cross-checked against the document's own Arrangement heading. When both are present and
    disagree, the declared value wins and the disagreement is returned for the gate verdict to
    record — a silent overrule is how a wrong Expression IRI becomes permanent.

    Raises when neither source has an answer. Failing one document loudly is much cheaper than
    publishing a citable identifier that asserts a language nobody established.
    """
    detected, _ = infer_language_and_unit(markdown_text)
    record = store.load_provenance(
        bill_slug=ref.bill_slug, doc_key=ref.doc_key, version=ref.version, artifact="markdown"
    )
    declared = ((record or {}).get("inputs") or {}).get("language")
    if declared is not None and declared not in AKN_LANGUAGES:
        raise FrbrIdentityError(f"declared language is not one we publish: {declared!r}")
    if declared is None and detected is None:
        raise FrbrIdentityError(
            "no language on the record: the markdown declares no Arrangement heading and none was "
            "given at import; re-import it with --language"
        )
    if declared is None:
        return str(detected), None
    if detected is not None and detected != declared:
        return declared, f"declared {declared!r}, document reads {detected!r}"
    return declared, None


def convert_to_akn(
    store: PipelineStore,
    *,
    extractor: MarkdownStructureExtractor,
    min_text_coverage: float = fidelity.MIN_TEXT_COVERAGE,
) -> StepResult:
    """Converts every document whose Akoma Ntoso is missing or no longer matches its source.

    `extractor` is injected — never constructed here — so this function never knows whether it
    is talking to a vLLM endpoint or the deterministic regex fallback; that decision belongs to
    the caller (`pipeline.akn_llm.build_structure_extractor` for the real one).

    Gate P1 decides whether the file exists. In this pipeline `has_akn` is the promotion flag every
    later step reads, so a tree that cannot account for its source must not leave one behind — but
    the verdict is written either way, and a rejected render is kept under a name nothing reads,
    because ADR-017 requires a failing artifact to be a review item rather than a discard.
    """
    counts = {"eligible": 0, "converted": 0, "rejected": 0, "failed": 0}
    failures: list[StepFailure] = []
    for ref in store.iter_documents():
        keys = keys_for(ref)
        if not store.has_markdown(**keys):
            continue
        markdown = store.load_markdown(**keys)
        if markdown is None:
            counts["failed"] += 1
            failures.append(_failure(ref, "markdown disappeared between listing and read"))
            continue
        # Every input this render reads has to be in the staleness key, or a correction to it
        # silently leaves the published artifact behind. Two are not files in this document's own
        # directory, so they are recorded as digests rather than as `source_files` — that list is
        # what `pipeline verify` re-hashes on disk, and naming a file it cannot find there would
        # make a correct store report itself as damaged.
        #
        # `bill.json`: `render_akn` takes the FRBR identity, `FRBRdate` and `<longTitle>` from it,
        # so a later crawl correcting a bill's title or first-reading date must regenerate the XML.
        # The markdown provenance: `resolve_language` reads the declared language out of it, and
        # that language is a permanent component of the Expression IRI, so a corrected language that
        # did not regenerate would leave the document published at an IRI asserting the wrong one.
        bill_record = store.load_bill(ref.bill_slug)
        markdown_provenance = store.load_provenance(**keys, artifact="markdown")
        inputs = {
            "source_files": [{"file": "document.md", "sha256": sha256_of(markdown)}],
            "bill_sha256": sha256_of(sidecar_bytes(bill_record or {})),
            "markdown_provenance_sha256": sha256_of(sidecar_bytes(markdown_provenance or {})),
            "code_version": AKN_VERSION,
            "gate_version": AKN_FIDELITY_GATE_VERSION,
            "min_text_coverage": min_text_coverage,
            "producer": extractor.name,
            "model_id": extractor.model_id,
            "prompt_sha256": extractor.prompt_sha256,
        }
        if not needs_rebuild(
            store, ref, artifact="akn", inputs=inputs, present=store.has_akn(**keys)
        ):
            continue
        counts["eligible"] += 1

        try:
            language, disagreement = resolve_language(store, ref, markdown)
            _, unit = infer_language_and_unit(markdown)
            bill = store.load_bill(ref.bill_slug)
            if bill is None:
                raise FrbrIdentityError(f"no bill record for {ref.bill_slug!r}")
            identity = identity_from_bill(bill, doc_type="act" if unit == "section" else "bill")
            tree = extractor.extract(markdown, unit=unit)
            assign_eids(tree)
            verdict = fidelity.evaluate(tree, markdown, unit=unit, min_coverage=min_text_coverage)
            xml_bytes = render_akn(tree, identity=identity, language=language, bill=bill)
            schema_errors = validate_akn(xml_bytes)
            if schema_errors:
                # Not a bad reading — a broken renderer. Fail loudly rather than publish XML that
                # calls itself Akoma Ntoso and cannot be read by Akoma Ntoso tooling.
                raise AknSchemaError("; ".join(schema_errors[:3]))
        except Exception as error:
            reason = describe_error(error)
            store.save_akn_gate(**keys, record=fidelity.failure(reason).as_detail())
            _withdraw(store, keys, present=store.has_akn(**keys))
            counts["failed"] += 1
            failures.append(_failure(ref, reason))
            continue

        record = verdict.as_detail()
        record["language"] = language
        if disagreement is not None:
            record["language_disagreement"] = disagreement
        store.save_akn_gate(**keys, record=record)
        if not verdict.passed:
            store.save_rejected_akn(**keys, content=xml_bytes)
            _withdraw(store, keys, present=store.has_akn(**keys))
            counts["rejected"] += 1
            failures.append(_failure(ref, f"gate P1 {verdict.status}: {_summarise(verdict)}"))
            continue

        store.save_akn(**keys, content=xml_bytes)
        store.save_provenance(
            **keys,
            artifact="akn",
            record=build_record(
                artifact="akn", inputs=inputs, outputs={"document.akn.xml": xml_bytes}
            ),
        )
        counts["converted"] += 1
    return StepResult(counts=counts, failures=tuple(failures))


def _withdraw(store: PipelineStore, keys: DocumentKeys, *, present: bool) -> None:
    """Unpublish an Akoma Ntoso document whose latest reading no longer passes the gate.

    Without this, a re-read that fails leaves the *previous* reading promoted while the verdict
    beside it says `mismatch` — so the served document and the confidence statement printed next to
    it describe different things, and a reader is told a reading was checked when the check it was
    shown belongs to a different render. The published Expression is withdrawn instead, which is the
    same rule as first conversion: the gate decides whether the file exists.

    The rejected render and the verdict both stay on disk, so the withdrawal is reviewable rather
    than silent (ADR-017, ADR-025).
    """
    if present:
        store.withdraw_akn(**keys)


def _failure(ref: StoredDocumentRef, reason: str) -> StepFailure:
    return StepFailure(
        bill_slug=ref.bill_slug, doc_key=ref.doc_key, version=ref.version, reason=reason
    )


def _summarise(verdict: fidelity.FidelityResult) -> str:
    kinds = sorted({item.kind for item in verdict.blocking})
    return ", ".join(kinds) if kinds else verdict.status
