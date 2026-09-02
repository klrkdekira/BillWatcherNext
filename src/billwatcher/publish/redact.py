"""Metadata-only publication: structure and identifiers, none of the source document's words.

The rights review (assumption A14) has not concluded, and until it does this project's standing
policy is to publish metadata and link to Parliament's official document rather than republish its
text (ADR-004). A structural reading is genuinely useful under that policy — a citable IRI per
provision, the numbering, the shape of the document, the graph of what contains what — and none of
it requires reproducing a single sentence of drafted text.

So the corpus is stored in full, privately, exactly as the source PDFs already are, and redacted at
the serving boundary. That is the same posture ADR-004 already established for document bytes, and
it means the rights decision is a configuration change rather than a corpus regeneration: flipping
`PUBLICATION_MODE` to `full` publishes text that was already on disk, and flipping it
back stops publishing it.

Provision headings are kept. They are the drafter's words, so this is a judgement rather than an
obvious call: they are the same class of short published fragment as the bill title, which this site
already publishes on every bill page, and ADR-004 permits bounded excerpts. `KEEP_HEADINGS` exists
so narrowing that boundary after an adverse review is a one-line change rather than a redesign.

Both redactors work on parsed structures, never on the serialised bytes. A regular expression over
XML or N-Quads would be a text-processing bug away from leaking the thing it exists to withhold.
"""

from xml.etree import ElementTree as ET

from rdflib import Dataset, URIRef

from billwatcher.graph.render import AKN_NS
from billwatcher.graph.semantic import SCHEMA, SemanticConversionError, render_jsonld

# Provision headings survive redaction. See the module docstring: a deliberate, recorded judgement,
# isolated here so it can be reversed without touching anything else.
KEEP_HEADINGS = True

# ...but only where the heading really is a *bounded* fragment, which is the whole basis on which
# ADR-027 permits publishing it at all. Nothing upstream guarantees that: a Malaysian amendment bill
# typically has no marginal note and runs the entire provision in after its number, and an LLM
# extractor can put whatever it likes in the field. `pipeline.akn.split_marginal_note` classifies it
# at parse time, and this repeats the test at the serving boundary rather than trusting it, because
# the parser is not the only producer of a tree and this is where the rights rule is enforced.
#
# Deliberately the same rule as the parser's, and deliberately duplicated rather than imported as
# one constant: if the two ever disagree, the safe outcome is that the *boundary* wins.
#
# Both halves are evidenced rather than guessed. 80 characters is the bound
# `legislation.layout._MARGIN_MAX_CHARS` already uses for "a marginal note is short". The
# terminal-punctuation test is what separates the two shapes in the real fixtures captured from
# Parliament PDFs: marginal notes and Arrangement entries are printed without a final stop
# (`Tajuk ringkas`, `1. Tajuk ringkas dan permulaan kuat kuasa`) and body sentences with one
# (`Seseorang yang melanggar seksyen 3 melakukan suatu kesalahan.`).
MAX_HEADING_CHARS = 80
_SENTENCE_ENDINGS = (".", ";", ":", "!", "?")

# The AKN wrappers that hold drafted prose. `preamble` is here too, found live in the first real
# corpus run: `render_akn` puts a bill's enacting formula ("Suatu Akta untuk meminda... DIPERBUAT
# oleh Parlimen Malaysia...") in a `<p>` directly under `<preamble>`, never inside a
# content/intro/wrapUp wrapper, so the redactor's own iteration missed it entirely — and so did
# `contains_provision_text`'s belt-and-braces self-check below, which walks this same tuple. The
# self-check stayed silent through exactly the leak it exists to catch, the same shape as the
# heading leak ADR-027's review already found once.
_TEXT_WRAPPERS = ("content", "intro", "wrapUp", "preamble")


def publishable_heading(heading: str | None) -> str | None:
    """The heading if it is a bounded label, else None.

    A heading that is long, or that reads as a sentence, is prose that reached the field by
    mis-parsing or by a model's choice. Withholding it costs a label on a page; publishing it
    republishes drafted legislative text while the rights review is open.
    """
    if not KEEP_HEADINGS or heading is None:
        return None
    text = heading.strip()
    if not text or len(text) > MAX_HEADING_CHARS or text.endswith(_SENTENCE_ENDINGS):
        return None
    return text


def redact_akn(xml_bytes: bytes) -> bytes:
    """Akoma Ntoso with every provision's body text emptied and its structure intact.

    The `<p>` elements stay, and stay empty: dropping the wrappers entirely would leave hierarchy
    elements the schema requires to carry something, so a redacted document would no longer be
    valid Akoma Ntoso — and an invalid document is not a useful thing to publish either.
    """
    if b"<!DOCTYPE" in xml_bytes[:2048] or b"<!ENTITY" in xml_bytes[:2048]:
        raise SemanticConversionError("XML declaring a doctype or entity is refused")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        raise SemanticConversionError(f"not well-formed XML: {error}") from error
    ET.register_namespace("", AKN_NS)
    for wrapper in _TEXT_WRAPPERS:
        for container in root.iter(f"{{{AKN_NS}}}{wrapper}"):
            for paragraph in container.iter(f"{{{AKN_NS}}}p"):
                paragraph.text = None
                paragraph.tail = None
                for descendant in list(paragraph):
                    paragraph.remove(descendant)
    for element in root.iter():
        for heading in element.findall(f"{{{AKN_NS}}}heading"):
            kept = publishable_heading(heading.text)
            if kept is None:
                # Removed rather than emptied. `<heading/>` would assert that the provision has a
                # heading and that it is blank, which is a different claim from the one the corpus
                # disclaimer makes — that a provision printed without its own heading is shown
                # without one.
                element.remove(heading)
            else:
                heading.text = kept
    # The long title is the bill's published name, which this site already shows on every bill
    # page, so it is not redacted here — only provision prose is.
    redacted: bytes = ET.tostring(root, xml_declaration=True, encoding="utf-8")
    return redacted


def redact_semantic(nquads_bytes: bytes, *, as_jsonld: bool) -> bytes:
    """The same graph with every `schema:text` literal removed.

    Rebuilt from the stored N-Quads rather than from the JSON-LD, so one redaction produces both
    published representations and they cannot disagree — the same single-graph discipline step 5
    itself uses.
    """
    dataset = Dataset()
    try:
        dataset.parse(data=nquads_bytes.decode("utf-8"), format="nquads")
    except Exception as error:
        # rdflib raises a variety of parse errors; none of them should reach a request handler as a
        # traceback, and all of them mean the same thing to a caller.
        raise SemanticConversionError(f"stored N-Quads could not be read: {error}") from error
    for context in list(dataset.graphs()):
        for triple in list(context.triples((None, SCHEMA.text, None))):
            context.remove(triple)
        for triple in list(context.triples((None, SCHEMA.name, None))):
            subject, predicate, value = triple
            # The document's own `schema:name` is the bill's published title, which is public
            # already; a provision's is its heading, and gets the same bound the XML does.
            if subject == context.identifier:
                continue
            if publishable_heading(str(value)) is None:
                context.remove(triple)
    if not as_jsonld:
        lines = sorted(
            line for line in dataset.serialize(format="nquads").splitlines() if line.strip()
        )
        return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
    identifiers = [
        context.identifier
        for context in dataset.graphs()
        if len(context) and isinstance(context.identifier, URIRef)
    ]
    if len(identifiers) != 1:
        raise SemanticConversionError(
            f"expected exactly one named graph in a document's N-Quads, found {len(identifiers)}"
        )
    return render_jsonld(dataset, identifiers[0])


def contains_provision_text(payload: bytes) -> bool:
    """Whether a published representation still carries provision prose.

    A cheap assertion for tests and for a belt-and-braces check at the serving boundary: the
    redactors are the control, and this is the independent second opinion that they worked. It
    therefore has to check the same two ways text can escape — a populated body wrapper, and a
    `heading` that is really a sentence. A net that only looked at `<content>` would have stayed
    silent through exactly the leak this function exists to catch.
    """
    if b"schema.org/text" in payload or b'"schema:text"' in payload:
        return True
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return False
    for wrapper in _TEXT_WRAPPERS:
        for container in root.iter(f"{{{AKN_NS}}}{wrapper}"):
            for paragraph in container.iter(f"{{{AKN_NS}}}p"):
                if (paragraph.text or "").strip():
                    return True
    for element in root.iter():
        for heading in element.findall(f"{{{AKN_NS}}}heading"):
            text = (heading.text or "").strip()
            if text and publishable_heading(text) is None:
                return True
    return False


def contains_unbounded_heading(values: object) -> bool:
    """Whether any heading in a nested structure exceeds the published bound.

    For the HTML path, which builds its own view objects rather than serialising AKN, so the
    XML-shaped net above cannot see it.
    """
    if isinstance(values, str):
        return bool(values.strip()) and publishable_heading(values) is None
    if isinstance(values, dict):
        return any(contains_unbounded_heading(item) for item in values.values())
    if isinstance(values, list | tuple):
        return any(contains_unbounded_heading(item) for item in values)
    return False
