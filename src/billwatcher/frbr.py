"""FRBR Work/Expression/Manifestation identifiers for the published corpus.

One module owns every published IRI, because these strings are permanent. Once a citation, a
mirror, or an `owl:sameAs` points at `/akn/my/bill/dr/2026/15`, that path has to keep meaning the
same document; a scheme scattered across a renderer, a graph builder, and a router would drift.

The scheme follows the Akoma Ntoso naming convention's
`/akn/<country>/<doctype>/<subtype>/<date>/<number>`, with the originating chamber in the subtype
slot:

    Work            /akn/my/bill/dr/2026/15
    Expression      /akn/my/bill/dr/2026/15/msa@
    Manifestation   /akn/my/bill/dr/2026/15/msa@.xml
    Provision       /akn/my/bill/dr/2026/15/msa@/~cl_5__subsec_1

Every component is a fact the upstream document published, taken from `bill.json`'s `identifier`
block: the country is fixed, the document type comes from the document's own Arrangement heading,
the chamber is the *originating* chamber (ADR-002 — a D.R. bill keeps `dr` even when the Dewan
Negara lists it), and the year and number are as printed. Nothing here is derived from a URL, a
byte hash, or a retrieval time: all three change when we re-fetch, and a permanent identifier must
not. That is what the previous `doc-<sha256(url)[:8]>` scheme got wrong.

The Malay and English readings of one bill are two Expressions of one Work, which is what makes a
cross-language citation resolvable. Language appears in two spellings on purpose: ISO 639-3
(`msa`/`eng`) in the AKN name, per the AKN convention, and BCP 47 (`ms`/`en`) on RDF literals and
HTML `lang` attributes, per HANDOFF 15. `AKN_LANGUAGES` is the only place they are mapped.
"""

import re
from dataclasses import dataclass
from typing import Any, Literal

COUNTRY = "my"
DOC_TYPES = frozenset({"bill", "act"})

# BCP 47 (RDF literals, HTML lang) -> ISO 639-3 (the AKN name). Both spellings are required by
# different specifications; keeping the mapping in one constant is what stops them drifting.
AKN_LANGUAGES = {"ms": "msa", "en": "eng"}
LANGUAGES = frozenset(AKN_LANGUAGES)

CHAMBER_CODES = {"dewan_rakyat": "dr", "dewan_negara": "dn"}

# Media types for each published manifestation, and the extension that selects it.
MANIFESTATION_TYPES = {
    # The markdown reading (ADR-035/036). A Manifestation of the same Expression as the XML and the
    # graph, on the same identifier and differing only in extension — which is what lets the text
    # milestone publish before the semantic one without minting a second identity for one document.
    "md": "text/markdown",
    "xml": "application/akn+xml",
    "jsonld": "application/ld+json",
    "nq": "application/n-quads",
    "html": "text/html",
}

_SLUG_RE = re.compile(r"\A[a-z0-9-]{1,80}\Z")
_EID_RE = re.compile(r"\A[A-Za-z0-9_]{1,200}\Z")
_YEAR_RE = re.compile(r"\A[0-9]{4}\Z")
# ASCII digits only, no leading zero, and bounded. `str.isdigit()` was none of those three: it is
# true for every Unicode digit character, so `٢` and `２` aliased the same Work at 200 while `²`
# passed the check and then raised out of `int()` as an unauthenticated 500; and an unbounded digit
# run reached CPython's integer-parse limit the same way. A permanent identifier gets exactly one
# spelling.
_NUMBER_RE = re.compile(r"\A[1-9][0-9]{0,4}\Z")


class FrbrIdentityError(ValueError):
    """A document does not carry the facts a permanent identifier requires.

    Raised rather than defaulted. A Work IRI with a placeholder component — the `unknown` year the
    previous renderer would happily mint from a missing bill record — is worse than no output,
    because it publishes a citable identifier for a document nobody can identify.
    """


@dataclass(frozen=True, slots=True)
class WorkIdentity:
    """The four facts that name a Work, and nothing else."""

    doc_type: Literal["bill", "act"]
    chamber_code: str
    year: int
    number: int

    @property
    def work_uri(self) -> str:
        return f"/akn/{COUNTRY}/{self.doc_type}/{self.chamber_code}/{self.year}/{self.number}"

    def expression_uri(self, language: str) -> str:
        """`…/msa@` — the version-date is deliberately empty.

        In the AKN convention a bare `@` means "the only version we have", which is the honest
        statement here: a bill has no expression date on our record. `retrieved_at` is a fact about
        us, not about the document, and putting it here would mint a new permanent identifier every
        time we re-fetched the same bytes. `@YYYY-MM-DD` is reserved for when a real document date
        — a first reading, a gazette date — is on the record.
        """
        return f"{self.work_uri}/{_akn_language(language)}@"

    def manifestation_uri(self, language: str, extension: str) -> str:
        if extension not in MANIFESTATION_TYPES:
            raise FrbrIdentityError(f"unknown manifestation extension: {extension!r}")
        return f"{self.expression_uri(language)}.{extension}"

    def provision_uri(self, language: str, eid: str) -> str:
        if not _EID_RE.match(eid):
            raise FrbrIdentityError(f"not a well-formed eId: {eid!r}")
        return f"{self.expression_uri(language)}/~{eid}"


def _akn_language(language: str) -> str:
    try:
        return AKN_LANGUAGES[language]
    except KeyError:
        raise FrbrIdentityError(
            f"no ISO 639-3 code for language {language!r}; expected one of {sorted(LANGUAGES)}"
        ) from None


def identity_from_bill(bill: dict[str, Any], *, doc_type: str) -> WorkIdentity:
    """Read a Work identity out of a stored bill record, refusing to guess any part of it."""
    if doc_type not in DOC_TYPES:
        raise FrbrIdentityError(f"unknown document type: {doc_type!r}")
    identifier = bill.get("identifier") or {}
    chamber = identifier.get("originating_chamber")
    code = CHAMBER_CODES.get(chamber or "")
    if code is None:
        raise FrbrIdentityError(f"no originating chamber on the bill record: {chamber!r}")
    year, number = identifier.get("year"), identifier.get("number")
    if not isinstance(year, int) or not isinstance(number, int):
        raise FrbrIdentityError(
            f"bill record has no usable year/number: year={year!r} number={number!r}"
        )
    return WorkIdentity(
        doc_type="act" if doc_type == "act" else "bill",
        chamber_code=code,
        year=year,
        number=number,
    )


def slug_for(identity: WorkIdentity) -> str:
    """The bill slug this Work belongs to — the store's own key, and the HTML identity.

    `normalize_identifier` builds a slug as `d<r|n>-<number>-<year>` lowercased, so a Work
    identity reproduces it exactly. This is the bridge from a served path back to the store,
    which is how a request is resolved without ever joining a request string onto a filesystem
    path (HANDOFF 17).
    """
    return f"d{identity.chamber_code[1]}-{identity.number}-{identity.year}"


def parse_work_path(
    doc_type: str, chamber_code: str, year: str, number: str
) -> WorkIdentity | None:
    """Validate the four segments of a Work path, or return None.

    Returns None rather than raising: these are untrusted request segments, and a caller turning
    them into a 404 is the correct response to every malformed one.
    """
    if doc_type not in DOC_TYPES or chamber_code not in set(CHAMBER_CODES.values()):
        return None
    if not _YEAR_RE.match(year) or not _NUMBER_RE.match(number):
        return None
    return WorkIdentity(
        doc_type="act" if doc_type == "act" else "bill",
        chamber_code=chamber_code,
        year=int(year),
        number=int(number),
    )


def parse_expression_segment(segment: str) -> tuple[str, str] | None:
    """Split `msa@.xml` into a BCP 47 language and an extension, or None.

    `msa@` alone means the Expression itself, served as HTML — the default representation.
    """
    name, separator, extension = segment.partition(".")
    if not name.endswith("@"):
        return None
    iso = name[:-1]
    language = next((tag for tag, code in AKN_LANGUAGES.items() if code == iso), None)
    if language is None:
        return None
    if not separator:
        return language, "html"
    # A separator with nothing after it (`msa@.`) is a malformed request, not the Expression. Left
    # as "no extension" it gave every Expression and provision a second URL serving identical
    # bytes, which for a permanent identifier is one spelling too many.
    if extension not in MANIFESTATION_TYPES:
        return None
    return language, extension


def valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug))


def valid_eid(eid: str) -> bool:
    return bool(_EID_RE.match(eid))
