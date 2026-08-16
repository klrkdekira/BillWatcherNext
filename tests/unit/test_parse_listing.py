from pathlib import Path

import pytest

from billwatcher.scraper.parse_listing import ListingParseError, parse_listing

FIXTURES = Path("tests/fixtures/parliament")
SOURCE = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr"


@pytest.mark.parametrize(
    "fixture",
    [
        "current_dr_bm.html",
        "current_dn_bm.html",
        "archive_dr_bm.html",
        "archive_dn_bm.html",
        "current_dr_en.html",
    ],
)
def test_required_listing_fixtures_parse(fixture: str) -> None:
    result = parse_listing((FIXTURES / fixture).read_text(), source_url=SOURCE)
    assert len(result.records) == 1
    assert len(result.structure_fingerprint) == 64


def test_exact_current_record_output_and_document_link() -> None:
    result = parse_listing((FIXTURES / "current_dr_bm.html").read_text(), source_url=SOURCE)
    record = result.records[0]
    assert record.identifier.normalized == "DR-15-2026"
    assert record.status_normalized == "passed"
    assert record.presenter == "Menteri di Jabatan Perdana Menteri"
    assert record.document_urls == ("https://www.parlimen.gov.my/pdf/dr15.pdf",)


def test_malformed_identifier_fails_loudly() -> None:
    with pytest.raises(ListingParseError, match="unparseable bill identifier"):
        parse_listing((FIXTURES / "malformed.html").read_text(), source_url=SOURCE)


def test_zero_rows_is_not_treated_as_an_empty_parliament() -> None:
    html = "<table><tr><th>Kod</th><th>Tajuk</th><th>Status</th></tr></table>"
    with pytest.raises(ListingParseError, match="zero records"):
        parse_listing(html, source_url=SOURCE)


def test_changed_or_missing_semantic_headers_fail() -> None:
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr></table>"
    with pytest.raises(ListingParseError, match="semantic columns"):
        parse_listing(html, source_url=SOURCE)
