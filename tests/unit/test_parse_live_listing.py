"""The parser against real Parliament markup, saved 2026-08-18 (docs/upstream.md).

Every other listing fixture in this suite was hand-written. This one is reduced from bytes the
crawler actually stored, and it is the only fixture that proves the parser survives the real
page: nested detail tables, script-carried document links, and the published status vocabulary.
"""

from datetime import date
from pathlib import Path

from billwatcher.scraper.parse_listing import parse_listing

FIXTURE = Path("tests/fixtures/parliament/live_current_dr_bm.html")
SOURCE = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr"


def parsed():
    return parse_listing(FIXTURE.read_text(), source_url=SOURCE)


def test_the_real_page_parses_without_issues() -> None:
    result = parsed()
    assert len(result.records) == 4
    assert result.issues == ()
    assert result.headers == ("Kod", "Tahun", "Tajuk", "Status")


def test_the_nested_detail_table_does_not_corrupt_the_listing_rows() -> None:
    """Each status cell contains a detail table; unnested, every row looks malformed."""
    result = parsed()
    codes = [record.identifier.normalized for record in result.records]
    assert codes == ["DR-22-2026", "DR-20-2026", "DR-16-2026", "DR-4-2026"]
    assert all(record.year == 2026 for record in result.records)


def test_hidden_popup_text_is_not_part_of_the_status() -> None:
    """The status cell also holds a hidden box containing the code and a close link."""
    statuses = {record.status_raw for record in parsed().records}
    assert statuses == {
        "Lulus",
        "Dirujuk ke JKPK",
        "Bacaan Kali Pertama",
        "Tidak Mendapat Undi 2/3 Peringkat Bacaan Ke-2",
    }
    assert not any("Tutup" in status for status in statuses)
    assert not any("D.R." in status for status in statuses)


def test_the_published_status_vocabulary_maps_without_guessing() -> None:
    mapped = {record.status_raw: record.status_normalized for record in parsed().records}
    assert mapped == {
        "Lulus": "passed",
        "Dirujuk ke JKPK": "referred",
        "Bacaan Kali Pertama": "first_read",
        "Tidak Mendapat Undi 2/3 Peringkat Bacaan Ke-2": "defeated",
    }


def test_dates_and_presenter_come_from_the_expanded_detail() -> None:
    passed_bill = next(r for r in parsed().records if r.identifier.normalized == "DR-22-2026")
    cells = {cell.event_type: cell for cell in passed_bill.dates}
    assert set(cells) == {"first_reading", "second_reading", "passed"}
    assert cells["first_reading"].ranges[0].start == date(2026, 7, 14)
    assert cells["second_reading"].ranges[0].start == date(2026, 7, 16)
    assert cells["passed"].ranges[0].start == date(2026, 7, 16)
    assert all(cell.error is None for cell in passed_bill.dates)
    # The presenter is a detail row, not a column of the main table.
    assert passed_bill.presenter == "YB Tuan Liew Chin Tong, Timbalan Menteri Kewangan"


def test_a_committee_referral_is_read_from_its_own_detail_row() -> None:
    referred = next(r for r in parsed().records if r.identifier.normalized == "DR-20-2026")
    cells = {cell.event_type: cell for cell in referred.dates}
    assert cells["committee_referral"].ranges[0].start == date(2026, 7, 14)
    assert cells["committee_referral"].label == "Dirujuk JKPK Pada"


def test_document_links_carried_by_a_script_call_are_found_and_encoded() -> None:
    """The page has no href PDFs at all; every document is behind onclick="loadResult(...)"."""
    record = next(r for r in parsed().records if r.identifier.normalized == "DR-22-2026")
    assert len(record.document_urls) == 1
    url = record.document_urls[0]
    assert url.startswith("https://www.parlimen.gov.my/files/billindex/pdf/2026/DR/")
    assert url.endswith(".pdf")
    # Real document paths contain spaces, which must be encoded to stay a usable URL.
    assert " " not in url
    assert "%20" in url


def test_every_record_carries_a_document_and_a_first_reading() -> None:
    for record in parsed().records:
        assert record.document_urls, record.identifier.normalized
        assert any(cell.event_type == "first_reading" for cell in record.dates)
