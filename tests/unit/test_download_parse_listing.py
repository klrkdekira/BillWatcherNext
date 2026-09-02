from datetime import date
from pathlib import Path

import pytest

from billwatcher.download.normalize import DateRange
from billwatcher.download.parse_listing import (
    ListingParseError,
    observed_language,
    parse_listing,
)

FIXTURES = Path("tests/fixtures/parliament")
SOURCE = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr"


@pytest.mark.parametrize(
    "fixture",
    [
        "current_dr_bm.html",
        "current_dn_bm.html",
        "current_dn_bm_withdrawn.html",
        "current_dr_en.html",
        "current_dr_bm_dated.html",
        "current_dn_bm_dated.html",
        "unparseable_date.html",
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


def test_a_listing_of_only_malformed_rows_fails_loudly() -> None:
    with pytest.raises(ListingParseError, match="zero records"):
        parse_listing((FIXTURES / "malformed.html").read_text(), source_url=SOURCE)


def test_a_bad_row_is_retained_as_an_issue_and_never_drops_the_page() -> None:
    """HANDOFF 11.3 step 7: keep the raw row, report it, and keep parsing the rest."""
    result = parse_listing((FIXTURES / "mixed_rows.html").read_text(), source_url=SOURCE)
    assert [record.identifier.normalized for record in result.records] == ["DR-15-2026"]

    reasons = {issue.reason.split(":")[0] for issue in result.issues}
    assert "unparseable bill identifier" in reasons
    assert any("missing a required title" in issue.reason for issue in result.issues)
    assert any("invalid year" in issue.reason for issue in result.issues)
    assert any(issue.reason.startswith("duplicate identifier") for issue in result.issues)

    # Every rejected row keeps the text it came from.
    bad_code = next(issue for issue in result.issues if issue.raw_identifier == "bukan kod")
    assert bad_code.row_number == 3
    assert "RUU Tanpa Kod" in bad_code.raw_values


def test_an_identical_repeated_row_collapses_without_an_anomaly() -> None:
    result = parse_listing((FIXTURES / "mixed_rows.html").read_text(), source_url=SOURCE)
    duplicates = [
        issue for issue in result.issues if issue.reason.startswith("duplicate identifier")
    ]
    # Rows 5 and 6 both repeat D.R.15/2026; only the one with a conflicting title is an issue.
    assert len(duplicates) == 1
    assert "RUU Tajuk Bercanggah" in duplicates[0].reason


def test_dated_columns_are_parsed_into_ranges_and_sequences() -> None:
    result = parse_listing((FIXTURES / "current_dr_bm_dated.html").read_text(), source_url=SOURCE)
    cells = {cell.event_type: cell for cell in result.records[0].dates}
    assert set(cells) == {
        "first_reading",
        "second_reading",
        "third_reading",
        "committee_referral",
        "passed",
    }

    first = cells["first_reading"]
    assert first.ranges == (DateRange(date(2026, 7, 13), None),)

    # A range inside one cell keeps both ends.
    second = cells["second_reading"]
    assert second.ranges == (DateRange(date(2026, 7, 13), date(2026, 7, 14)),)

    # Several dates in one cell become several spans, ordered as published.
    third = cells["third_reading"]
    assert third.ranges == (
        DateRange(date(2026, 7, 16), None),
        DateRange(date(2026, 7, 17), None),
    )
    assert all(cell.error is None for cell in result.records[0].dates)


def test_an_unparseable_date_keeps_its_raw_text_instead_of_becoming_null() -> None:
    result = parse_listing((FIXTURES / "unparseable_date.html").read_text(), source_url=SOURCE)
    assert len(result.records) == 1
    cell = result.records[0].dates[0]
    assert cell.raw == "13/25/2026"
    assert cell.ranges == ()
    assert cell.error and "invalid Malaysian date" in cell.error


def test_a_soft_404_served_with_200_is_a_parse_failure() -> None:
    with pytest.raises(ListingParseError, match="no table rows found"):
        parse_listing((FIXTURES / "soft_404.html").read_text(), source_url=SOURCE)


def test_a_soft_404_carrying_a_plausible_table_is_still_refused() -> None:
    with pytest.raises(ListingParseError, match="semantic columns"):
        parse_listing((FIXTURES / "soft_404_table.html").read_text(), source_url=SOURCE)


def test_zero_rows_is_not_treated_as_an_empty_parliament() -> None:
    html = "<table><tr><th>Kod</th><th>Tajuk</th><th>Status</th></tr></table>"
    with pytest.raises(ListingParseError, match="zero records"):
        parse_listing(html, source_url=SOURCE)


def test_changed_or_missing_semantic_headers_fail() -> None:
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr></table>"
    with pytest.raises(ListingParseError, match="semantic columns"):
        parse_listing(html, source_url=SOURCE)


@pytest.mark.parametrize(
    ("fixture", "language"),
    [
        ("current_dr_bm.html", "ms"),
        ("current_dn_bm.html", "ms"),
        ("current_dr_bm_dated.html", "ms"),
        ("current_dr_en.html", "en"),
        ("current_dn_en.html", "en"),
    ],
)
def test_a_listing_reports_the_language_its_own_labels_are_written_in(
    fixture: str, language: str
) -> None:
    """The crawl cannot take `lang=en` at its word — the site's language follows the session that
    serves the request (documentation/upstream.md) — so the page has to say so itself."""
    result = parse_listing((FIXTURES / fixture).read_text(), source_url=SOURCE)
    assert result.observed_language == language


def test_labels_that_settle_nothing_report_no_language() -> None:
    """`None` is an answer, not a failure: `Status` is spelled the same in both languages, and a
    page whose labels score equally in both is evidence for neither."""
    assert observed_language([]) is None
    assert observed_language(["Status"]) is None
    assert observed_language(["Kod", "Title"]) is None
    # A trailing colon is how the detail rows carry their labels, and is not part of the label.
    assert observed_language(["Passed At:"]) == "en"
    assert observed_language(["Diluluskan Pada:"]) == "ms"
