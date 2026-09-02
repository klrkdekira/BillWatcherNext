"""Every published IRI, pinned by literal string.

These strings are permanent: once a citation, a mirror, or an `owl:sameAs` points at
`/akn/my/bill/dr/2026/15`, that path has to keep meaning the same document. So the tests spell the
expected IRI out in full rather than rebuilding it from the same constants the module uses — a test
that composes its expectation the way the code does cannot notice the scheme changing.

The other half is refusal. A Work IRI with a guessed component is worse than no output at all,
because it publishes a citable identifier for a document nobody can identify; every missing or
malformed component therefore has a test of its own.
"""

import pytest

from billwatcher.download.normalize import normalize_identifier
from billwatcher.frbr import (
    AKN_LANGUAGES,
    CHAMBER_CODES,
    COUNTRY,
    DOC_TYPES,
    LANGUAGES,
    MANIFESTATION_TYPES,
    FrbrIdentityError,
    WorkIdentity,
    identity_from_bill,
    parse_expression_segment,
    parse_work_path,
    slug_for,
    valid_eid,
    valid_slug,
)

BILL = {
    "identifier": {
        "raw": "D.R. 15/2026",
        "normalized": "DR-15-2026",
        "slug": "dr-15-2026",
        "originating_chamber": "dewan_rakyat",
        "year": 2026,
        "number": 15,
    }
}

DEWAN_RAKYAT_BILL = WorkIdentity(doc_type="bill", chamber_code="dr", year=2026, number=15)
DEWAN_NEGARA_ACT = WorkIdentity(doc_type="act", chamber_code="dn", year=2017, number=3)


def bill_with(**identifier: object) -> dict[str, object]:
    """The sample bill record with its `identifier` block overridden."""
    merged = dict(BILL["identifier"]) | identifier
    return {"identifier": {key: value for key, value in merged.items() if value is not ...}}


def test_the_work_iri_names_country_type_chamber_year_and_number() -> None:
    assert DEWAN_RAKYAT_BILL.work_uri == "/akn/my/bill/dr/2026/15"
    assert DEWAN_NEGARA_ACT.work_uri == "/akn/my/act/dn/2017/3"


def test_an_expression_iri_ends_in_a_bare_at_sign_in_both_languages() -> None:
    """A bare `@` means "the only version we have", which is the honest statement for a bill.

    `retrieved_at` is a fact about us, not about the document; putting it here would mint a new
    permanent identifier every time we re-fetched the same bytes.
    """
    assert DEWAN_RAKYAT_BILL.expression_uri("ms") == "/akn/my/bill/dr/2026/15/msa@"
    assert DEWAN_RAKYAT_BILL.expression_uri("en") == "/akn/my/bill/dr/2026/15/eng@"
    assert DEWAN_NEGARA_ACT.expression_uri("ms") == "/akn/my/act/dn/2017/3/msa@"
    assert DEWAN_NEGARA_ACT.expression_uri("en") == "/akn/my/act/dn/2017/3/eng@"


def test_a_manifestation_iri_appends_the_extension_for_each_published_format() -> None:
    assert DEWAN_RAKYAT_BILL.manifestation_uri("ms", "xml") == "/akn/my/bill/dr/2026/15/msa@.xml"
    assert (
        DEWAN_RAKYAT_BILL.manifestation_uri("ms", "jsonld") == "/akn/my/bill/dr/2026/15/msa@.jsonld"
    )
    assert DEWAN_RAKYAT_BILL.manifestation_uri("ms", "nq") == "/akn/my/bill/dr/2026/15/msa@.nq"
    assert DEWAN_RAKYAT_BILL.manifestation_uri("en", "html") == "/akn/my/bill/dr/2026/15/eng@.html"
    assert DEWAN_NEGARA_ACT.manifestation_uri("en", "xml") == "/akn/my/act/dn/2017/3/eng@.xml"


def test_a_provision_iri_hangs_off_the_expression_under_a_tilde() -> None:
    assert (
        DEWAN_RAKYAT_BILL.provision_uri("ms", "cl_5__subsec_1")
        == "/akn/my/bill/dr/2026/15/msa@/~cl_5__subsec_1"
    )
    assert (
        DEWAN_NEGARA_ACT.provision_uri("en", "part_II__sec_3")
        == "/akn/my/act/dn/2017/3/eng@/~part_II__sec_3"
    )


def test_the_iso_639_3_and_bcp_47_spellings_are_mapped_in_exactly_one_place() -> None:
    """`msa`/`eng` in the AKN name, `ms`/`en` on RDF literals and HTML `lang` attributes.

    Both spellings are required by different specifications, so the risk is not that either is
    wrong but that they drift apart. This pins the mapping and pins that nothing else is published.
    """
    assert AKN_LANGUAGES == {"ms": "msa", "en": "eng"}
    assert sorted(LANGUAGES) == ["en", "ms"]
    assert COUNTRY == "my"
    assert sorted(DOC_TYPES) == ["act", "bill"]
    assert CHAMBER_CODES == {"dewan_rakyat": "dr", "dewan_negara": "dn"}
    assert set(MANIFESTATION_TYPES) == {"md", "xml", "jsonld", "nq", "html"}
    assert MANIFESTATION_TYPES["md"] == "text/markdown"
    assert MANIFESTATION_TYPES["xml"] == "application/akn+xml"
    assert MANIFESTATION_TYPES["jsonld"] == "application/ld+json"
    assert MANIFESTATION_TYPES["nq"] == "application/n-quads"
    assert MANIFESTATION_TYPES["html"] == "text/html"


def test_a_language_we_do_not_publish_is_refused_rather_than_passed_through() -> None:
    with pytest.raises(FrbrIdentityError, match="no ISO 639-3 code"):
        DEWAN_RAKYAT_BILL.expression_uri("fr")
    with pytest.raises(FrbrIdentityError, match="no ISO 639-3 code"):
        DEWAN_RAKYAT_BILL.manifestation_uri("msa", "xml")  # the ISO code, not the BCP 47 tag


def test_an_unpublished_manifestation_extension_is_refused() -> None:
    with pytest.raises(FrbrIdentityError, match="unknown manifestation extension"):
        DEWAN_RAKYAT_BILL.manifestation_uri("ms", "pdf")


def test_a_malformed_eid_never_reaches_a_provision_iri() -> None:
    """An eId becomes a path segment, so a separator in one would silently change the IRI."""
    for eid in ("cl_5/subsec_1", "../cl_5", "cl 5", "cl_5#frag", "", "cl_5?x=1"):
        with pytest.raises(FrbrIdentityError, match="not a well-formed eId"):
            DEWAN_RAKYAT_BILL.provision_uri("ms", eid)


def test_identity_from_bill_reads_the_four_facts_off_a_stored_record() -> None:
    assert identity_from_bill(BILL, doc_type="bill") == DEWAN_RAKYAT_BILL
    assert identity_from_bill(BILL, doc_type="act") == WorkIdentity(
        doc_type="act", chamber_code="dr", year=2026, number=15
    )


def test_identity_from_bill_refuses_an_unknown_document_type() -> None:
    with pytest.raises(FrbrIdentityError, match="unknown document type"):
        identity_from_bill(BILL, doc_type="motion")


def test_identity_from_bill_refuses_a_record_with_no_originating_chamber() -> None:
    """ADR-002: a D.R. bill keeps `dr` even when the Dewan Negara lists it.

    The chamber is therefore a recorded fact and not something the serving side can infer, so a
    record without one has no Work IRI at all.
    """
    with pytest.raises(FrbrIdentityError, match="no originating chamber"):
        identity_from_bill(bill_with(originating_chamber=...), doc_type="bill")
    with pytest.raises(FrbrIdentityError, match="no originating chamber"):
        identity_from_bill(bill_with(originating_chamber=None), doc_type="bill")
    with pytest.raises(FrbrIdentityError, match="no originating chamber"):
        identity_from_bill(bill_with(originating_chamber="senate"), doc_type="bill")
    with pytest.raises(FrbrIdentityError, match="no originating chamber"):
        identity_from_bill({}, doc_type="bill")
    with pytest.raises(FrbrIdentityError, match="no originating chamber"):
        identity_from_bill({"identifier": None}, doc_type="bill")


def test_identity_from_bill_refuses_a_year_or_number_that_is_not_an_integer() -> None:
    """The previous scheme happily minted an `unknown` year from a missing bill record."""
    with pytest.raises(FrbrIdentityError, match="no usable year/number"):
        identity_from_bill(bill_with(year=...), doc_type="bill")
    with pytest.raises(FrbrIdentityError, match="no usable year/number"):
        identity_from_bill(bill_with(number=...), doc_type="bill")
    with pytest.raises(FrbrIdentityError, match="no usable year/number"):
        identity_from_bill(bill_with(year="2026"), doc_type="bill")
    with pytest.raises(FrbrIdentityError, match="no usable year/number"):
        identity_from_bill(bill_with(number="15"), doc_type="bill")
    with pytest.raises(FrbrIdentityError, match="no usable year/number"):
        identity_from_bill(bill_with(year=None, number=None), doc_type="bill")


def test_slug_for_reproduces_the_slug_the_scraper_itself_minted() -> None:
    """The bridge from a served path back to the store, which is how a request is resolved.

    `slug_for` has to agree with `normalize_identifier` exactly, or a resolvable IRI would point at
    a directory that does not exist — and it must agree without ever joining a request string onto
    a filesystem path (HANDOFF 17).
    """
    rakyat = normalize_identifier("D.R. 15/2026")
    assert rakyat.slug == "dr-15-2026"
    assert slug_for(DEWAN_RAKYAT_BILL) == rakyat.slug

    negara = normalize_identifier("D.N. 3/2017")
    assert negara.slug == "dn-3-2017"
    assert slug_for(DEWAN_NEGARA_ACT) == negara.slug

    # Two Works of one bill — the bill and the Act it becomes — share the store's slug, because the
    # slug names the upstream identifier and the doc type is not part of it.
    enacted = WorkIdentity(doc_type="act", chamber_code="dr", year=2026, number=15)
    assert slug_for(enacted) == slug_for(DEWAN_RAKYAT_BILL)


def test_parse_work_path_accepts_the_four_segments_of_a_real_work() -> None:
    assert parse_work_path("bill", "dr", "2026", "15") == DEWAN_RAKYAT_BILL
    assert parse_work_path("act", "dn", "2017", "3") == DEWAN_NEGARA_ACT


def test_parse_work_path_returns_none_for_every_malformed_segment() -> None:
    """None, not an exception: these are untrusted request segments and a 404 is the right answer.

    The zero-padded and non-numeric cases matter beyond tidiness — `015` and `15` would otherwise
    be two paths for one document, and a non-numeric segment must never reach `int()`.
    """
    assert parse_work_path("motion", "dr", "2026", "15") is None  # a doc type we do not publish
    assert parse_work_path("bill", "senate", "2026", "15") is None  # not a chamber code
    assert parse_work_path("bill", "dewan_rakyat", "2026", "15") is None  # the name, not the code
    assert parse_work_path("bill", "dr", "26", "15") is None  # a two-digit year
    assert parse_work_path("bill", "dr", "20260", "15") is None  # a five-digit year
    assert parse_work_path("bill", "dr", "2026", "015") is None  # zero-padded
    assert parse_work_path("bill", "dr", "2026", "01") is None  # zero-padded, two digits
    assert parse_work_path("bill", "dr", "2026", "0") is None  # there is no bill number zero
    assert parse_work_path("bill", "dr", "2026", "fifteen") is None
    assert parse_work_path("bill", "dr", "2026", "15/../3") is None
    assert parse_work_path("bill", "dr", "2026", "") is None
    assert parse_work_path("BILL", "DR", "2026", "15") is None  # the scheme is lower case


def test_a_number_that_is_not_ascii_digits_is_neither_an_alias_nor_a_500() -> None:
    """`str.isdigit()` was three wrong things at once, and two of them were reachable by request.

    It is true for every Unicode digit character, so `٢` and `２` aliased the Work at 200 — one
    document with several permanent identifiers — while `²` passed the check and then raised out of
    `int()` as an unauthenticated 500. It is also unbounded, so a long digit run reached CPython's
    integer-parse limit the same way. A permanent identifier gets exactly one spelling.
    """
    for number in ("²", "٢", "０", "２", "١٥", "1٢", "9" * 40, "1_5", " 15", "15 ", "+15", "-15"):
        assert parse_work_path("bill", "dr", "2026", number) is None, number
    # The bound is five digits, which is more bills than Parliament has ever numbered in a year.
    assert parse_work_path("bill", "dr", "2026", "99999") is not None
    assert parse_work_path("bill", "dr", "2026", "100000") is None


def test_parse_expression_segment_reads_the_language_and_the_representation() -> None:
    assert parse_expression_segment("msa@") == ("ms", "html")
    assert parse_expression_segment("eng@") == ("en", "html")
    assert parse_expression_segment("eng@.xml") == ("en", "xml")
    assert parse_expression_segment("msa@.nq") == ("ms", "nq")
    assert parse_expression_segment("msa@.jsonld") == ("ms", "jsonld")
    assert parse_expression_segment("msa@.html") == ("ms", "html")


def test_parse_expression_segment_returns_none_for_anything_it_does_not_serve() -> None:
    assert parse_expression_segment("msa") is None  # no `@`, so not an Expression segment
    assert parse_expression_segment("fra@") is None  # a language we do not publish
    assert parse_expression_segment("ms@") is None  # the BCP 47 tag, not the ISO 639-3 code
    assert parse_expression_segment("msa@.exe") is None
    assert parse_expression_segment("msa@.xml.gz") is None
    assert parse_expression_segment("@") is None
    assert parse_expression_segment("") is None


def test_a_separator_with_no_extension_after_it_is_not_a_second_url_for_the_expression() -> None:
    """`msa@.` read as "no extension" gave every Expression and every provision beneath it a second
    URL serving identical bytes, which for a permanent identifier is one spelling too many."""
    assert parse_expression_segment("msa@") == ("ms", "html")
    assert parse_expression_segment("msa@.") is None
    assert parse_expression_segment("eng@.") is None
    assert parse_expression_segment("msa@..") is None


def test_valid_slug_and_valid_eid_reject_anything_that_could_traverse_a_path() -> None:
    assert valid_slug("dr-15-2026") is True
    assert valid_slug("DR-15-2026") is False  # the store's slugs are lower case
    assert valid_slug("../etc/passwd") is False
    assert valid_slug("dr_15_2026") is False
    assert valid_slug("") is False
    assert valid_slug("d" * 81) is False

    assert valid_eid("part_II__cl_3__subsec_1") is True
    assert valid_eid("cl_3/../secret") is False
    assert valid_eid("cl 3") is False
    assert valid_eid("") is False
    assert valid_eid("c" * 201) is False
