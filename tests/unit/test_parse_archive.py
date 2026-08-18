"""Golden tests for the archive tree parser (ADR-014).

Every fixture here was reduced from bytes the site really served on 2026-08-18, so these assert
exact structured output rather than "it parsed" (HANDOFF 11.6).
"""

from datetime import date
from pathlib import Path

import pytest

from billwatcher.scraper.normalize import DateRange
from billwatcher.scraper.parse_archive import (
    ArchiveParseError,
    parse_archive_index,
    parse_archive_year,
    parse_stored_listing,
)

FIXTURES = Path("tests/fixtures/parliament")
INDEX_URL = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr&arkib=yes&ajx=0"
YEAR_URL = (
    "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr&arkib=yes&ajx=1&id=0_2024"
)


def year(fixture: str, url: str = YEAR_URL):
    return parse_archive_year((FIXTURES / fixture).read_text(), source_url=url)


def test_index_yields_years_newest_first() -> None:
    parsed = parse_archive_index(
        (FIXTURES / "archive_index_dr.xml").read_text(), source_url=INDEX_URL
    )
    assert parsed.years == (2024, 2011)
    assert len(parsed.structure_fingerprint) == 64


def test_exact_archived_bill_output() -> None:
    record = year("archive_year_dr_2024.xml").records[0]
    assert record.identifier.normalized == "DR-17-2024"
    assert record.title == "RUU Penagih Dadah (Rawatan dan Pemulihan) (Pindaan) 2024"
    assert record.status_raw == "Lulus"
    assert record.status_normalized == "passed"
    assert record.year == 2024
    assert record.presenter == (
        "YB Datuk Seri Dr. Shamsul Anuar bin Haji Nasarah - Timbalan Menteri Dalam Negeri"
    )
    # The path really does contain spaces, and it is reached through a script call rather than an
    # href, so a parser that collects hrefs finds nothing at all.
    assert record.document_urls == (
        "https://www.parlimen.gov.my/files/billindex/pdf/2024/DR%2017%20BM.pdf",
    )
    assert [(cell.event_type, cell.ranges) for cell in record.dates] == [
        ("first_reading", (DateRange(date(2024, 7, 2), None),)),
        ("second_reading", (DateRange(date(2024, 7, 3), None),)),
        ("passed", (DateRange(date(2024, 7, 18), None),)),
    ]


def test_a_bill_that_never_passed_carries_no_detail_at_all() -> None:
    """63 archived bills have no children: no dates, no presenter, no document."""
    parsed = year("archive_year_dn_2011.xml")
    unpassed = [record for record in parsed.records if record.status_raw != "Lulus"]
    assert [record.identifier.normalized for record in unpassed] == ["DR-15-2011", "DR-32-2011"]
    for record in unpassed:
        # The Dewan Negara takes both readings in one sitting and publishes them as one status.
        assert record.status_raw == "Bacaan Kali Kedua dan Ketiga"
        assert record.status_normalized == "third_read"
        assert record.dates == ()
        assert record.document_urls == ()
        assert record.presenter is None
    assert not parsed.issues


def test_the_english_tree_labels_its_dates_differently() -> None:
    """Regression: the English labels are not the Malay ones, and missing them lost every date."""
    record = year("archive_year_dr_en_2024.xml").records[0]
    assert record.status_normalized == "passed"
    assert [(cell.label, cell.event_type) for cell in record.dates] == [
        ("First reading", "first_reading"),
        ("The second reading", "second_reading"),
        ("Passed At", "passed"),
    ]
    assert record.presenter is not None


def test_malformed_identifiers_are_reported_and_never_dropped() -> None:
    parsed = year("archive_year_edge_cases.xml")
    # A stray token is not punctuation, so it is reported rather than guessed at. The doubled
    # slash in `D.R.16//2017` is punctuation, and it normalizes: it is the only spelling under
    # which that bill is ever published.
    assert [(issue.raw_identifier, issue.row_number) for issue in parsed.issues] == [
        ("D.R.40/2017 ARKIB", 2),
    ]
    assert all("unparseable bill identifier" in issue.reason for issue in parsed.issues)
    assert "DR-16-2017" in {record.identifier.normalized for record in parsed.records}
    # The rest of the year still publishes.
    assert len(parsed.records) == 5


def test_a_zero_date_is_kept_raw_and_reported() -> None:
    """Thirteen archived readings are dated `30/11/-0001`; none may become a real date."""
    record = next(r for r in year("archive_year_edge_cases.xml").records if r.year == 2015)
    second = next(cell for cell in record.dates if cell.event_type == "second_reading")
    assert second.raw == "30/11/-0001"
    assert second.ranges == ()
    assert second.error is not None
    # The readings around it still parse.
    assert [cell.event_type for cell in record.dates if cell.ranges] == ["first_reading", "passed"]


def test_one_title_in_two_spellings_is_one_bill() -> None:
    parsed = year("archive_year_edge_cases.xml")
    identifiers = [record.identifier.normalized for record in parsed.records]
    assert identifiers.count("DR-45-2017") == 1
    assert identifiers.count("DR-1-1998") == 1
    assert not any("duplicate identifier" in issue.reason for issue in parsed.issues)


def test_upstream_escaping_is_not_republished() -> None:
    parsed = year("archive_year_edge_cases.xml")
    titles = {record.identifier.normalized: record.title for record in parsed.records}
    assert titles["DR-1-2023"] == "RUU Pencetakan Teks Al-Qur'an (Pindaan) 2023"
    assert titles["DR-1-1998"].endswith("Al-Qur'an (Pindaan) 1997")
    presenter = parsed.records[0].presenter or ""
    assert "&#039;" not in presenter
    assert "Dato' Sri" in presenter


def test_an_unknown_detail_label_changes_the_fingerprint_and_is_reported() -> None:
    """The tree declares no header row, so a renamed label is what drift has to catch."""
    original = (FIXTURES / "archive_year_dr_2024.xml").read_text()
    renamed = original.replace("Bacaan Pertama Pada:", "Bacaan Sulung Pada:")
    before = parse_archive_year(original, source_url=YEAR_URL)
    after = parse_archive_year(renamed, source_url=YEAR_URL)
    assert after.structure_fingerprint != before.structure_fingerprint
    assert any("Bacaan Sulung Pada" in issue.reason for issue in after.issues)
    # And the date it used to carry is gone rather than silently mislabelled.
    assert [cell.event_type for cell in after.records[0].dates] == ["second_reading", "passed"]


def test_a_year_that_gains_a_bill_is_not_drift() -> None:
    """The newest archived year keeps changing, and that must not withhold publication."""
    from xml.etree import ElementTree

    original = (FIXTURES / "archive_year_dr_2024.xml").read_text()
    tree = ElementTree.fromstring(original)
    tree.remove(tree.findall("item")[-1])
    trimmed = ElementTree.tostring(tree, encoding="unicode")

    shorter = parse_archive_year(trimmed, source_url=YEAR_URL)
    assert len(shorter.records) == 3
    assert shorter.structure_fingerprint == (
        parse_archive_year(original, source_url=YEAR_URL).structure_fingerprint
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('<?xml version="1.0"?><html><body>Not found</body></html>', "root"),
        ('<?xml version="1.0"?><tree id="0"></tree>', "no bill nodes"),
        ("<tree", "not well formed"),
        (
            '<?xml version="1.0"?><!DOCTYPE tree [<!ENTITY a "boom">]><tree id="0">'
            "<item text='x'/></tree>",
            "doctype",
        ),
    ],
)
def test_a_response_that_is_not_the_tree_fails_loudly(body: str, message: str) -> None:
    with pytest.raises(ArchiveParseError) as raised:
        parse_archive_year(body, source_url=YEAR_URL)
    assert message in str(raised.value)


def test_stored_snapshots_are_parsed_by_the_shape_their_url_names() -> None:
    """Replay reads bytes saved months ago, so the shape comes from the request, not the body."""
    archived = parse_stored_listing(
        (FIXTURES / "archive_year_dr_2024.xml").read_text(), url=YEAR_URL, source_url=YEAR_URL
    )
    assert len(archived.records) == 4
    current_url = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr"
    current = parse_stored_listing(
        (FIXTURES / "current_dr_bm.html").read_text(), url=current_url, source_url=current_url
    )
    assert len(current.records) == 1
    with pytest.raises(ArchiveParseError):
        parse_stored_listing(
            (FIXTURES / "archive_index_dr.xml").read_text(), url=INDEX_URL, source_url=INDEX_URL
        )
