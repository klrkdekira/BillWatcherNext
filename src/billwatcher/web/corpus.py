"""The public, read-only serving surface for the file-first legislation corpus (ADR-018).

Every level of an FRBR path resolves to something — `/akn/my`, `/akn/my/bill`,
`/akn/my/bill/dr`, `/akn/my/bill/dr/2026`, the Work, each Expression, each Manifestation, each
provision — because a citation is only durable if truncating it lands somewhere rather than 404ing.
That is the one property the static build in HANDOFF 26 would have given for free and which this
module has to provide deliberately.

Three rules shape all of it:

- **Nothing from a request ever reaches a path.** Every segment is validated by
  `billwatcher.pipeline.frbr` first, and the store is then addressed by `frbr.slug_for(identity)` —
  an identifier this project mints from four validated facts — through `PipelineStore` methods only.
  There is no `os.path.join` here and no `:path` converter, and the extension is split off *inside*
  the handler rather than by a `{name}.{ext}` route template, so there is no route shape that could
  be pointed at a file we did not write (HANDOFF 17).
- **Publication mode is enforced at the boundary, not in the corpus.** The store holds the full
  reading; `legislation_publication_mode` decides what leaves this module. In the default
  `metadata` mode every machine representation goes through `pipeline.redact`, and the HTML pages
  never receive provision text in their template context at all — withholding by construction
  rather than by a template conditional somebody could delete.
- **Flags come off the injected `Settings`.** `get_settings()` is `lru_cache`d, so a handler that
  called it would ignore the configuration the application was actually built with. Three existing
  handlers do exactly that; none of these do.

What is deliberately *not* here: any statement about whether a bill passed or what the law is. This
is a machine reading of a document, every page says so, and the reader is told the fidelity gate's
verdict on the reading they are looking at rather than being left to assume it was checked.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response

from billwatcher.config import Settings
from billwatcher.legislation.vocabulary import NODE_LABELS
from billwatcher.pipeline import frbr, redact
from billwatcher.pipeline.frbr import WorkIdentity
from billwatcher.pipeline.semantic import SemanticConversionError, parse_akn
from billwatcher.pipeline.store import PipelineStore, StoredDocumentRef, sha256_of
from billwatcher.pipeline.tree import Node
from billwatcher.web.templating import render

# The representations of one Expression, in the order they are advertised. HTML first because it is
# what the Expression itself serves and the only one a person reads.
REPRESENTATIONS = ("html", "xml", "jsonld", "nq")

# Derived files are regenerated whenever their source markdown, the renderer, or the extraction
# prompt changes, so they are emphatically not the `immutable` the archived-PDF route serves. Five
# minutes is long enough to absorb a crawler and short enough that a corrected reading appears.
CACHE_CONTROL = "public, max-age=300"

WITHHELD = (
    "This service publishes a structural reading of Parliament's documents only where the rights "
    "review has concluded and been recorded. It has not, so the reading is not served here; "
    "Parliament's own document remains available from the bill page."
)
UNAVAILABLE = "Our reading of this document is unavailable."
REDACTION_FAILED = (
    "This representation was withheld: an automated check found that provision text survived "
    "redaction, which is a bug in this service rather than a property of the document."
)
NO_SUCH_WORK = "We hold no reading of that document."

_SLUG_RE = re.compile(r"^d([rn])-([1-9][0-9]{0,3})-([0-9]{4})$")
_YEAR_RE = re.compile(r"^[0-9]{4}$")
# A URL fit to appear in a `Link` header: no control characters, and none of the delimiters that
# would let an upstream-derived string forge a second link value or a second header. The sidecar is
# ours, but the URL inside it came from Parliament's HTML, so it is validated rather than trusted.
# `\A`/`\Z` rather than `^`/`$`: Python's `$` also matches before a trailing newline, so the
# guard whose whole job is to reject anything that could forge a header was letting a URL with
# a trailing LF through into one.
_HEADER_URL_RE = re.compile(r"\Ahttps?://[!-;=?-~]+\Z")

# The words each level of the corpus is described with. Kept together so a page's prose is
# one thing to review rather than a phrase inlined at each of seven route bodies.
_DOC_TYPE_LABELS = {"bill": "Bills", "act": "Acts"}
_DOC_TYPE_SINGULAR = {"bill": "Bill", "act": "Act"}
_DOC_TYPE_NOTES = {
    "bill": (
        "A bill is a document laid before Parliament. Publishing a reading of one here is not a "
        "statement that it is enacted or currently in force."
    ),
    "act": (
        "An Act as read from a document Parliament published. This is a reading of that document, "
        "not a consolidation and not a statement of the law."
    ),
}
_CHAMBER_LABELS = {"dr": "Dewan Rakyat", "dn": "Dewan Negara"}
_LANGUAGE_LABELS = {"ms": "Malay", "en": "English"}


@dataclass(frozen=True, slots=True)
class Alternate:
    """One sibling representation of an Expression."""

    url: str
    media_type: str


@dataclass(frozen=True, slots=True)
class Expression:
    """A stored Expression: a Work in one language, and the document our reading came from."""

    identity: WorkIdentity
    language: str
    ref: StoredDocumentRef


@dataclass(frozen=True, slots=True)
class WorkListing:
    """A Work and the languages we hold a reading in, for the year and Work listings."""

    identity: WorkIdentity
    languages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProvisionView:
    """One provision as a page renders it.

    `paragraphs` is empty in `metadata` mode because the text is never put here, not because the
    template declines to print it. Withholding by construction survives a template edit.
    """

    eid: str
    label: str
    heading: str | None
    href: str
    paragraphs: tuple[str, ...]
    children: tuple["ProvisionView", ...]


def alternates(identity: WorkIdentity, language: str, *, current: str) -> tuple[Alternate, ...]:
    """Every representation of this Expression except the one being served.

    Pure, so the `Link` header and the `<link rel="alternate">` block in the HTML head are one fact
    rendered twice rather than two lists that can drift (ADR-018).
    """
    found = []
    for extension in REPRESENTATIONS:
        if extension == current:
            continue
        url = (
            identity.expression_uri(language)
            if extension == "html"
            else identity.manifestation_uri(language, extension)
        )
        found.append(Alternate(url, frbr.MANIFESTATION_TYPES[extension]))
    return tuple(found)


def link_header(items: tuple[Alternate, ...], *, canonical: str | None) -> str:
    """One comma-joined `Link` value: the alternates, then the official document.

    The canonical target is Parliament's own document, never a page of ours. Our reading is a
    derivative; saying so in the header is the same statement the archived-bytes route makes.
    """
    parts = [f'<{item.url}>; rel="alternate"; type="{item.media_type}"' for item in items]
    if canonical:
        parts.append(f'<{canonical}>; rel="canonical"')
    return ", ".join(parts)


def canonical_url(metadata: dict[str, Any]) -> str | None:
    """The official document URL from a document sidecar, if it is safe to put in a header."""
    url = metadata.get("source_url")
    if isinstance(url, str) and _HEADER_URL_RE.match(url):
        return url
    return None


def identity_from_slug(slug: str, *, doc_type: str) -> WorkIdentity | None:
    """The Work a bill slug names, or None.

    The round-trip through `slug_for` is the check that matters: it means every identity this
    returns is one that maps back to exactly the slug we were given, so a listing page can never
    advertise a Work whose path resolves to a different directory.
    """
    match = _SLUG_RE.match(slug)
    if match is None or doc_type not in frbr.DOC_TYPES:
        return None
    identity = WorkIdentity(
        doc_type="act" if doc_type == "act" else "bill",
        chamber_code=f"d{match.group(1)}",
        year=int(match.group(3)),
        number=int(match.group(2)),
    )
    return identity if frbr.slug_for(identity) == slug else None


def register_corpus_routes(app: FastAPI, *, store: PipelineStore, config: Settings) -> None:
    """Attach the corpus serving surface. Registered whether or not it serves anything.

    The routes exist in the closed state too, and answer with the policy rather than with a bare
    404: a reader who follows a citation is owed the reason the document is not there.
    """
    metadata_only = config.legislation_publication_mode == "metadata"

    def closed(request: Request) -> Response | None:
        if config.serve_legislation_corpus:
            return None
        return render(request, "error.html", {"message": WITHHELD}, status_code=404)

    def missing(request: Request, message: str = NO_SUCH_WORK) -> Response:
        return render(request, "error.html", {"message": message}, status_code=404)

    def unavailable(request: Request) -> Response:
        """The corpus is published, but this artifact could not be read or redacted.

        A distinct status from the closed state on purpose: one is a policy, the other is our
        problem, and a mirror or a monitor has to be able to tell them apart.
        """
        return render(request, "error.html", {"message": UNAVAILABLE}, status_code=503)

    @app.get("/akn/my", response_class=HTMLResponse)
    def corpus_root(request: Request) -> Response:
        if withheld := closed(request):
            return withheld
        entries = [
            {
                "href": f"/akn/{frbr.COUNTRY}/{doc_type}",
                "label": _DOC_TYPE_LABELS[doc_type],
                "note": _DOC_TYPE_NOTES[doc_type],
            }
            for doc_type in sorted(frbr.DOC_TYPES)
        ]
        return _listing(
            request,
            title="Malaysian legislation",
            lead=(
                "Structural readings of Parliament's documents, on permanent Akoma Ntoso "
                "identifiers. Every level of a path below resolves, so a truncated citation still "
                "leads somewhere."
            ),
            entries=entries,
        )

    @app.get("/akn/my/{doc_type}", response_class=HTMLResponse)
    def corpus_doc_type(request: Request, doc_type: str) -> Response:
        if withheld := closed(request):
            return withheld
        if doc_type not in frbr.DOC_TYPES:
            return missing(request)
        entries = [
            {
                "href": f"/akn/{frbr.COUNTRY}/{doc_type}/{code}",
                "label": _CHAMBER_LABELS[code],
                "note": (
                    "The originating chamber, which never changes once a document has one "
                    "(ADR-002)."
                ),
            }
            for code in sorted(frbr.CHAMBER_CODES.values())
        ]
        return _listing(
            request,
            title=f"{_DOC_TYPE_LABELS[doc_type]} by originating chamber",
            lead=_DOC_TYPE_NOTES[doc_type],
            entries=entries,
        )

    @app.get("/akn/my/{doc_type}/{chamber}", response_class=HTMLResponse)
    def corpus_chamber(request: Request, doc_type: str, chamber: str) -> Response:
        if withheld := closed(request):
            return withheld
        if doc_type not in frbr.DOC_TYPES or chamber not in set(frbr.CHAMBER_CODES.values()):
            return missing(request)
        years: dict[int, int] = {}
        for work in _works_in(store, doc_type=doc_type, chamber_code=chamber):
            years[work.identity.year] = years.get(work.identity.year, 0) + 1
        entries = [
            {
                "href": f"/akn/{frbr.COUNTRY}/{doc_type}/{chamber}/{year}",
                "label": str(year),
                "note": f"{count} document{'' if count == 1 else 's'} read",
            }
            for year, count in sorted(years.items(), reverse=True)
        ]
        return _listing(
            request,
            title=f"{_CHAMBER_LABELS[chamber]}: {_DOC_TYPE_LABELS[doc_type].lower()} by year",
            lead=(
                "The year printed in a document's own number, which is what names it permanently "
                "— never the year we happened to read it."
            ),
            entries=entries,
        )

    @app.get("/akn/my/{doc_type}/{chamber}/{year}", response_class=HTMLResponse)
    def corpus_year(request: Request, doc_type: str, chamber: str, year: str) -> Response:
        if withheld := closed(request):
            return withheld
        if doc_type not in frbr.DOC_TYPES or chamber not in set(frbr.CHAMBER_CODES.values()):
            return missing(request)
        if not _YEAR_RE.match(year):
            return missing(request)
        works = _works_in(store, doc_type=doc_type, chamber_code=chamber, year=int(year))
        entries = [
            {
                "href": work.identity.work_uri,
                "label": f"{_DOC_TYPE_SINGULAR[doc_type]} {work.identity.number} of {year}",
                "note": ", ".join(_LANGUAGE_LABELS[code] for code in work.languages),
            }
            for work in sorted(works, key=lambda item: item.identity.number)
        ]
        return _listing(
            request,
            title=f"{_CHAMBER_LABELS[chamber]}: {year}",
            lead=(
                f"Every {_DOC_TYPE_SINGULAR[doc_type].lower()} of {year} we hold a reading of, by "
                "its printed number."
            ),
            entries=entries,
        )

    @app.get("/akn/my/{doc_type}/{chamber}/{year}/{number}", response_class=HTMLResponse)
    def corpus_work(
        request: Request, doc_type: str, chamber: str, year: str, number: str
    ) -> Response:
        if withheld := closed(request):
            return withheld
        identity = frbr.parse_work_path(doc_type, chamber, year, number)
        if identity is None:
            return missing(request)
        expressions = _stored_expressions(store, identity)
        if not expressions:
            return missing(request)
        bill = store.load_bill(frbr.slug_for(identity)) or {}
        context = {
            "identity": identity,
            "work_uri": identity.work_uri,
            "identifier": (bill.get("identifier") or {}).get("raw") or identity.work_uri,
            "expressions": [
                {
                    "language": expression.language,
                    "language_label": _LANGUAGE_LABELS[expression.language],
                    "href": identity.expression_uri(expression.language),
                    "title": _title_of(bill, expression.language),
                    "representations": [
                        {"href": item.url, "media_type": item.media_type}
                        for item in alternates(identity, expression.language, current="html")
                    ],
                    "document": _document_facts(store, expression),
                }
                for expression in expressions
            ],
            "bill_slug": frbr.slug_for(identity),
            # A Work with readings in both languages has two source documents, two gate verdicts
            # and two retrieval times. Printing the first Expression's as the Work's would
            # attribute one PDF's sha256 and confidence to a reading it did not produce, so the
            # Work-level block is omitted and each Expression carries its own instead.
            "document": _document_facts(store, expressions[0]) if len(expressions) == 1 else None,
            "metadata_only": metadata_only,
        }
        return _validated(request, render(request, "corpus_work.html", context), headers={})

    @app.get(
        "/akn/my/{doc_type}/{chamber}/{year}/{number}/{segment}",
        response_class=HTMLResponse,
    )
    def corpus_expression(
        request: Request, doc_type: str, chamber: str, year: str, number: str, segment: str
    ) -> Response:
        """The Expression as HTML, or one of its Manifestations.

        The extension is split off here rather than by the route template: a `{name}.{ext}` route
        matches a dot anywhere in the segment, which is the traversal surface this whole module is
        built to not have.
        """
        if withheld := closed(request):
            return withheld
        identity = frbr.parse_work_path(doc_type, chamber, year, number)
        parsed = frbr.parse_expression_segment(segment)
        if identity is None or parsed is None:
            return missing(request)
        language, extension = parsed
        expression = _resolve(store, identity, language)
        if expression is None:
            return missing(request)
        if extension != "html":
            return _manifestation(request, expression, extension)

        tree = _read_tree(store, expression)
        if tree is None:
            return unavailable(request)
        bill = store.load_bill(expression.ref.bill_slug) or {}
        base = identity.expression_uri(language)
        siblings = alternates(identity, language, current="html")
        provisions = _views(tree.children, language=language, base=base, text=not metadata_only)
        if metadata_only and redact.contains_unbounded_heading(headings_of(provisions)):
            # The same two-layer discipline the machine representations get: `_view` applies the
            # bound, and this is the independent second opinion that it held. The HTML path had the
            # control but not the check, and a missing second opinion is exactly what let the
            # original heading leak reach every representation unnoticed.
            return render(request, "error.html", {"message": REDACTION_FAILED}, status_code=500)
        context = {
            "identity": identity,
            "language": language,
            "language_label": _LANGUAGE_LABELS[language],
            "expression_uri": base,
            "work_uri": identity.work_uri,
            "identifier": (bill.get("identifier") or {}).get("raw") or identity.work_uri,
            "title": _title_of(bill, language),
            "provisions": provisions,
            "alternates": [{"href": item.url, "media_type": item.media_type} for item in siblings],
            "bill_slug": expression.ref.bill_slug,
            "document": _document_facts(store, expression),
            "metadata_only": metadata_only,
        }
        return _validated(
            request,
            render(request, "corpus_expression.html", context),
            headers=_headers(siblings, expression, indexable=True),
        )

    @app.get(
        "/akn/my/{doc_type}/{chamber}/{year}/{number}/{segment}/{provision}",
        response_class=HTMLResponse,
    )
    def corpus_provision(
        request: Request,
        doc_type: str,
        chamber: str,
        year: str,
        number: str,
        segment: str,
        provision: str,
    ) -> Response:
        """One provision, addressed by the `~eId` its own document printed.

        Only the Expression has provisions; `msa@.xml/~cl_1` is not a resource, because a
        Manifestation is a file and a file has no sub-resources.
        """
        if withheld := closed(request):
            return withheld
        identity = frbr.parse_work_path(doc_type, chamber, year, number)
        parsed = frbr.parse_expression_segment(segment)
        if identity is None or parsed is None or not provision.startswith("~"):
            return missing(request)
        language, extension = parsed
        eid = provision[1:]
        if extension != "html" or not frbr.valid_eid(eid):
            return missing(request)
        expression = _resolve(store, identity, language)
        if expression is None:
            return missing(request)
        tree = _read_tree(store, expression)
        if tree is None:
            return unavailable(request)
        found = _find(tree, eid)
        if found is None:
            return missing(request, "We hold no provision with that identifier.")

        base = identity.expression_uri(language)
        siblings = alternates(identity, language, current="html")
        bill = store.load_bill(expression.ref.bill_slug) or {}
        view = _view(found, language=language, base=base, text=not metadata_only)
        if metadata_only and redact.contains_unbounded_heading(headings_of((view,))):
            return render(request, "error.html", {"message": REDACTION_FAILED}, status_code=500)
        context = {
            "identity": identity,
            "language": language,
            "language_label": _LANGUAGE_LABELS[language],
            "provision": view,
            "provision_uri": identity.provision_uri(language, eid),
            "expression_uri": base,
            "identifier": (bill.get("identifier") or {}).get("raw") or identity.work_uri,
            "title": _title_of(bill, language),
            "alternates": [{"href": item.url, "media_type": item.media_type} for item in siblings],
            "bill_slug": expression.ref.bill_slug,
            "document": _document_facts(store, expression),
            "metadata_only": metadata_only,
        }
        return _validated(
            request,
            render(request, "corpus_provision.html", context),
            headers=_headers(siblings, expression, indexable=True),
        )

    def _manifestation(request: Request, expression: Expression, extension: str) -> Response:
        """One machine representation, redacted if the mode says so, as bytes.

        Never through Jinja: an XML template would escape the payload a second time and an N-Quads
        one would not escape it at all. The response is the file, or the redaction of it.
        """
        try:
            payload = _representation(store, expression, extension, metadata_only=metadata_only)
        except (SemanticConversionError, OSError):
            return unavailable(request)
        if payload is None:
            return unavailable(request)
        if metadata_only and redact.contains_provision_text(payload):
            # The redactors are the control; this is the independent second opinion. If it fires,
            # something is wrong with this service, and the answer is to serve nothing.
            return render(request, "error.html", {"message": REDACTION_FAILED}, status_code=500)
        siblings = alternates(expression.identity, expression.language, current=extension)
        headers = _headers(siblings, expression, indexable=False)
        etag = f'"{sha256_of(payload)}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag, **headers})
        return Response(
            payload,
            media_type=frbr.MANIFESTATION_TYPES[extension],
            headers={"ETag": etag, **headers},
        )

    def _headers(
        siblings: tuple[Alternate, ...], expression: Expression, *, indexable: bool
    ) -> dict[str, str]:
        headers = {
            "Cache-Control": CACHE_CONTROL,
            "Link": link_header(siblings, canonical=canonical_url(expression.ref.metadata)),
        }
        if not indexable:
            # The HTML pages are our own derived work and are the thing ADR-018 wants indexed, so
            # nothing restricts them. The XML, JSON-LD and N-Quads are byte-level derivatives of
            # the same reading: indexing them would put four near-duplicate documents in a search
            # index for every one a person can read.
            headers["X-Robots-Tag"] = "noindex"
        return headers

    def _validated(request: Request, response: Response, *, headers: dict[str, str]) -> Response:
        """An ETag over the bytes actually being returned, and a 304 when they are unchanged.

        Over the rendered body rather than over a source digest, because in `metadata` mode the
        bytes leaving here are a redaction of the stored file and an ETag naming the stored file
        would promise a reader something we are not sending.
        """
        etag = f'"{sha256_of(bytes(response.body))}"'
        merged = {"Cache-Control": CACHE_CONTROL, **headers}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag, **merged})
        response.headers["ETag"] = etag
        for header, value in merged.items():
            response.headers[header] = value
        return response

    def _listing(
        request: Request, *, title: str, lead: str, entries: list[dict[str, str]]
    ) -> Response:
        """A level that lists what is beneath it.

        `document` is None on purpose: a listing has no single source document to be honest about.
        """
        context = {
            "title": title,
            "lead": lead,
            "entries": entries,
            "metadata_only": metadata_only,
            "document": None,
        }
        return _validated(request, render(request, "corpus_listing.html", context), headers={})


def _works_in(
    store: PipelineStore,
    *,
    doc_type: str,
    chamber_code: str | None = None,
    year: int | None = None,
) -> list[WorkListing]:
    """Every Work of a kind we hold a reading of, narrowed before any document is opened.

    The slug filter is what keeps a listing affordable: a slug is one of our own identifiers, so
    chamber, number and year are readable from it without opening `bill.json`, and only the bills
    that survive the filter cost a directory walk. There is no index over the corpus — the file
    tree is the record (ADR-021) — so a listing is a walk; narrowing it first is the whole point.
    """
    found: list[WorkListing] = []
    for slug in store.iter_bill_slugs():
        identity = identity_from_slug(slug, doc_type=doc_type)
        if identity is None:
            continue
        if chamber_code is not None and identity.chamber_code != chamber_code:
            continue
        if year is not None and identity.year != year:
            continue
        languages = tuple(item.language for item in _stored_expressions(store, identity))
        if languages:
            found.append(WorkListing(identity, languages))
    return found


def _stored_expressions(store: PipelineStore, identity: WorkIdentity) -> tuple[Expression, ...]:
    """The Expressions of one Work, one per language, in language order.

    Two stored documents can claim the same Expression — two PDFs of the same bill, both read as
    Malay. That is a corpus defect, not a request to publish two documents at one identifier, so
    the first in the store's own sorted order wins and the resolution stays deterministic rather
    than depending on directory iteration order.
    """
    by_language: dict[str, Expression] = {}
    for ref in store.iter_bill_documents(frbr.slug_for(identity)):
        language, doc_type = _expression_facts(store, ref)
        if language is None or doc_type != identity.doc_type:
            continue
        by_language.setdefault(language, Expression(identity, language, ref))
    return tuple(by_language[language] for language in sorted(by_language))


def _expression_facts(
    store: PipelineStore, ref: StoredDocumentRef
) -> tuple[str | None, str | None]:
    """`(language, doc_type)` for a stored document, or `(None, None)` if it has no reading.

    Read from the gate verdict, which already records both, so resolving a request costs a small
    JSON read per candidate document instead of parsing every candidate's XML. The XML is the
    fallback for a document written before the verdict carried a language.
    """
    if not store.has_akn(bill_slug=ref.bill_slug, doc_key=ref.doc_key, version=ref.version):
        return None, None
    gate = store.load_akn_gate(bill_slug=ref.bill_slug, doc_key=ref.doc_key, version=ref.version)
    language = (gate or {}).get("language")
    unit = (gate or {}).get("unit")
    if isinstance(language, str) and isinstance(unit, str) and unit:
        return language, ("act" if unit == "section" else "bill")
    xml_bytes = store.load_akn(bill_slug=ref.bill_slug, doc_key=ref.doc_key, version=ref.version)
    if xml_bytes is None:
        return None, None
    try:
        _, _, doc_type, parsed_language = parse_akn(xml_bytes)
    except SemanticConversionError:
        return None, None
    return parsed_language, doc_type


def _resolve(store: PipelineStore, identity: WorkIdentity, language: str) -> Expression | None:
    return next(
        (
            expression
            for expression in _stored_expressions(store, identity)
            if expression.language == language
        ),
        None,
    )


def _read_tree(store: PipelineStore, expression: Expression) -> Node | None:
    ref = expression.ref
    try:
        xml_bytes = store.load_akn(
            bill_slug=ref.bill_slug, doc_key=ref.doc_key, version=ref.version
        )
        if xml_bytes is None:
            return None
        tree, _, _, _ = parse_akn(xml_bytes)
    except (SemanticConversionError, OSError):
        return None
    return tree


def _representation(
    store: PipelineStore, expression: Expression, extension: str, *, metadata_only: bool
) -> bytes | None:
    """The bytes for one Manifestation, already redacted when the mode requires it.

    Both semantic representations are redacted from the stored N-Quads rather than each from its own
    file, which is the same single-graph discipline step 5 uses: one redaction produces both, so the
    published JSON-LD and the published N-Quads cannot disagree about what was withheld. A document
    whose N-Quads are missing therefore has no publishable JSON-LD either, and says so.
    """
    slug, key, version = expression.ref.bill_slug, expression.ref.doc_key, expression.ref.version
    if extension == "xml":
        xml_bytes = store.load_akn(bill_slug=slug, doc_key=key, version=version)
        if xml_bytes is None or not metadata_only:
            return xml_bytes
        return redact.redact_akn(xml_bytes)
    if extension == "jsonld":
        if not metadata_only:
            return store.load_jsonld(bill_slug=slug, doc_key=key, version=version)
        nquads = store.load_rdf(bill_slug=slug, doc_key=key, version=version)
        return None if nquads is None else redact.redact_semantic(nquads, as_jsonld=True)
    if extension == "nq":
        nquads = store.load_rdf(bill_slug=slug, doc_key=key, version=version)
        if nquads is None or not metadata_only:
            return nquads
        return redact.redact_semantic(nquads, as_jsonld=False)
    return None


def _document_facts(store: PipelineStore, expression: Expression) -> dict[str, Any]:
    """What the disclaimer needs: where this reading came from, and how it was judged."""
    ref = expression.ref
    slug, key, version = ref.bill_slug, ref.doc_key, ref.version
    provenance = (
        store.load_provenance(bill_slug=slug, doc_key=key, version=version, artifact="akn") or {}
    )
    inputs = provenance.get("inputs") or {}
    return {
        "source_url": ref.metadata.get("source_url"),
        "source_sha256": ref.metadata.get("sha256"),
        "retrieved_at": ref.metadata.get("retrieved_at"),
        "producer": inputs.get("producer"),
        "model_id": inputs.get("model_id"),
        "code_version": inputs.get("code_version"),
        "gate": _gate_facts(store.load_akn_gate(bill_slug=slug, doc_key=key, version=version)),
    }


def _gate_facts(gate: dict[str, Any] | None) -> dict[str, Any] | None:
    """Gate P1's verdict, formatted for a reader.

    Surfaced on every page rather than kept for operators: a reader is entitled to know how
    confident the reading they are looking at is, and a coverage figure with a threshold beside it
    says that far better than a green tick would.
    """
    if not gate:
        return None
    coverage = gate.get("coverage")
    minimum = gate.get("min_coverage")
    findings = gate.get("findings") or []
    return {
        "status": gate.get("status"),
        "coverage": f"{float(coverage) * 100:.1f}%" if isinstance(coverage, int | float) else None,
        "min_coverage": (
            f"{float(minimum) * 100:.1f}%" if isinstance(minimum, int | float) else None
        ),
        "node_count": gate.get("node_count"),
        "blocking_count": gate.get("blocking_count"),
        "kinds": sorted({str(item.get("kind")) for item in findings if item.get("kind")}),
        "language_disagreement": gate.get("language_disagreement"),
    }


def _title_of(bill: dict[str, Any], language: str) -> dict[str, str] | None:
    """The bill's published title for this Expression, with the language it is actually in.

    Malay is the authoritative language for federal legislation and is very often the only title on
    the record, so an English Expression carrying a Malay title is the ordinary case rather than a
    defect — but tagging it `lang="en"` would tell a screen reader to pronounce Malay as English.
    """
    titles = bill.get("titles") or {}
    for code in (language, "ms", "en"):
        value = titles.get(f"raw_{code}")
        if value:
            return {"text": str(value), "language": code}
    return None


def _views(nodes: list[Node], *, language: str, base: str, text: bool) -> tuple[ProvisionView, ...]:
    return tuple(_view(node, language=language, base=base, text=text) for node in nodes)


def headings_of(views: tuple[ProvisionView, ...]) -> list[Any]:
    """Every heading in a provision tree, nested, for the independent post-render check."""
    return [[view.heading, headings_of(view.children)] for view in views]


def _view(node: Node, *, language: str, base: str, text: bool) -> ProvisionView:
    return ProvisionView(
        eid=node.eid,
        label=_label(node, language),
        # A heading is published only where it is the bounded label ADR-027 permits. In full-text
        # mode the bound is irrelevant, because the prose is being published anyway.
        heading=node.heading if text else redact.publishable_heading(node.heading),
        href=f"{base}/~{node.eid}" if node.eid else "",
        paragraphs=tuple(node.paragraphs) if text else (),
        children=_views(node.children, language=language, base=base, text=text),
    )


def _label(node: Node, language: str) -> str:
    """`Fasal 3` / `Clause 3`, in the Expression's own language.

    The published Malay and English words for each node kind are already a controlled vocabulary
    (`legislation.vocabulary.NODE_LABELS`); naming a provision here reuses it rather than inventing
    a second set of words for the same thing.
    """
    labels = NODE_LABELS.get(node.node_type)
    word = (labels[0] if language == "ms" else labels[1]) if labels else node.node_type
    return f"{word} {node.num}" if node.num else word


def _find(root: Node, eid: str) -> Node | None:
    for node in _walk(root):
        if node.eid == eid:
            return node
    return None


def _walk(node: Node) -> Iterator[Node]:
    for child in node.children:
        yield child
        yield from _walk(child)
