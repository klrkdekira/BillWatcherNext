from datetime import date

from billwatcher.download.bills import merge_listing_into_bill
from billwatcher.download.normalize import DateRange, normalize_identifier
from billwatcher.download.parse_listing import ParsedDateCell, ParsedListingBill


def record(
    *,
    identifier: str = "D.R.15/2026",
    title: str = "RUU Contoh 2026",
    status_raw: str = "Bacaan Kali Pertama",
    status_normalized: str = "first_read",
    presenter: str | None = "Menteri",
    document_urls: tuple[str, ...] = (),
    dates: tuple[ParsedDateCell, ...] = (),
) -> ParsedListingBill:
    return ParsedListingBill(
        identifier=normalize_identifier(identifier),
        title=title,
        status_raw=status_raw,
        status_normalized=status_normalized,
        year=2026,
        presenter=presenter,
        document_urls=document_urls,
        dates=dates,
    )


def first_reading(day: int) -> tuple[ParsedDateCell, ...]:
    return (
        ParsedDateCell(
            event_type="first_reading",
            label="Bacaan Pertama Pada",
            raw=f"{day:02d}/07/2026",
            ranges=(DateRange(date(2026, 7, day)),),
        ),
    )


def test_a_new_bill_is_created_with_the_first_seen_timestamp() -> None:
    merged = merge_listing_into_bill(
        None,
        record(),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/listing",
        observed_at="2026-08-21T00:00:00Z",
    )
    assert merged["identifier"]["slug"] == "dr-15-2026"
    assert merged["identifier"]["normalized"] == "DR-15-2026"
    assert merged["first_seen_at"] == "2026-08-21T00:00:00Z"
    assert merged["last_seen_at"] == "2026-08-21T00:00:00Z"
    assert merged["titles"]["raw_ms"] == "RUU Contoh 2026"
    assert merged["chambers"]["dewan_rakyat"]["status_normalized"] == "first_read"


def test_a_second_observation_updates_last_seen_but_keeps_first_seen() -> None:
    first = merge_listing_into_bill(
        None,
        record(),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/listing",
        observed_at="2026-08-01T00:00:00Z",
    )
    second = merge_listing_into_bill(
        first,
        record(status_raw="Bacaan Kali Kedua", status_normalized="second_read"),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/listing",
        observed_at="2026-08-21T00:00:00Z",
    )
    assert second["first_seen_at"] == "2026-08-01T00:00:00Z"
    assert second["last_seen_at"] == "2026-08-21T00:00:00Z"
    assert second["chambers"]["dewan_rakyat"]["status_normalized"] == "second_read"


def test_last_seen_at_is_monotonic_regardless_of_processing_order() -> None:
    """`FileStore.iter_listings` sorts by storage key, not by fetch time, so a bill referenced by
    two chambers can have the more-recently-fetched listing merged in first. `last_seen_at` must
    never move backwards just because of that processing order — found by an integration test
    where D.R.15/2026 (present in both current listings, per A4) settled to a `last_seen_at`
    earlier than its own `first_seen_at`."""
    first = merge_listing_into_bill(
        None,
        record(),
        chamber="dewan_negara",
        language="ms",
        source_url="https://example.org/dn",
        observed_at="2026-08-21T10:00:05Z",
    )
    second = merge_listing_into_bill(
        first,
        record(),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/dr",
        observed_at="2026-08-21T10:00:01Z",
    )
    assert second["last_seen_at"] == "2026-08-21T10:00:05Z"


def test_two_chambers_are_kept_separate() -> None:
    merged = merge_listing_into_bill(
        None,
        record(),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/dr",
        observed_at="2026-08-01T00:00:00Z",
    )
    merged = merge_listing_into_bill(
        merged,
        record(status_raw="Diluluskan", status_normalized="passed"),
        chamber="dewan_negara",
        language="ms",
        source_url="https://example.org/dn",
        observed_at="2026-08-05T00:00:00Z",
    )
    assert merged["chambers"]["dewan_rakyat"]["status_normalized"] == "first_read"
    assert merged["chambers"]["dewan_negara"]["status_normalized"] == "passed"


def test_document_urls_accumulate_without_duplication() -> None:
    merged = merge_listing_into_bill(
        None,
        record(document_urls=("https://example.org/a.pdf",)),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/listing",
        observed_at="2026-08-01T00:00:00Z",
    )
    merged = merge_listing_into_bill(
        merged,
        record(document_urls=("https://example.org/a.pdf", "https://example.org/b.pdf")),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/listing",
        observed_at="2026-08-02T00:00:00Z",
    )
    urls = [doc["url"] for doc in merged["documents"]]
    assert urls == ["https://example.org/a.pdf", "https://example.org/b.pdf"]


def test_re_merging_the_same_observation_is_idempotent() -> None:
    first = merge_listing_into_bill(
        None,
        record(document_urls=("https://example.org/a.pdf",)),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/listing",
        observed_at="2026-08-01T00:00:00Z",
    )
    second = merge_listing_into_bill(
        first,
        record(document_urls=("https://example.org/a.pdf",)),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/listing",
        observed_at="2026-08-01T00:00:00Z",
    )
    assert first == second


def test_an_english_title_lands_in_its_own_key_alongside_the_malay_one() -> None:
    merged = merge_listing_into_bill(
        None,
        record(title="RUU Contoh 2026"),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/dr-bm",
        observed_at="2026-08-01T00:00:00Z",
    )
    merged = merge_listing_into_bill(
        merged,
        record(title="Example Bill 2026"),
        chamber="dewan_rakyat",
        language="en",
        source_url="https://example.org/dr-en",
        observed_at="2026-08-01T00:00:00Z",
    )
    assert merged["titles"]["raw_ms"] == "RUU Contoh 2026"
    assert merged["titles"]["raw_en"] == "Example Bill 2026"


def test_the_existing_record_passed_in_is_not_mutated_in_place() -> None:
    """`load_bill` hands back one dict; a second merge call must not corrupt it through
    aliasing, since nothing here guarantees the caller re-reads before reusing it."""
    import copy

    first = merge_listing_into_bill(
        None,
        record(document_urls=("https://example.org/a.pdf",)),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/listing",
        observed_at="2026-08-01T00:00:00Z",
    )
    frozen_snapshot = copy.deepcopy(first)

    merge_listing_into_bill(
        first,
        record(document_urls=("https://example.org/a.pdf", "https://example.org/b.pdf")),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/listing",
        observed_at="2026-08-02T00:00:00Z",
    )
    assert first == frozen_snapshot


def test_a_raw_status_and_a_listing_url_are_kept_per_language() -> None:
    """`Lulus` and `Passed` are one outcome published twice, and both are what a source says. The
    normalized value is a single fact about the bill, so it does not need a language."""
    merged = merge_listing_into_bill(
        None,
        record(status_raw="Lulus", status_normalized="passed"),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/dr-bm",
        observed_at="2026-08-01T00:00:00Z",
    )
    merged = merge_listing_into_bill(
        merged,
        record(status_raw="Passed", status_normalized="passed"),
        chamber="dewan_rakyat",
        language="en",
        source_url="https://example.org/dr-en",
        observed_at="2026-08-01T00:00:00Z",
    )
    chamber = merged["chambers"]["dewan_rakyat"]
    assert chamber["statuses_raw"] == {"ms": "Lulus", "en": "Passed"}
    assert chamber["source_urls"] == {
        "ms": "https://example.org/dr-bm",
        "en": "https://example.org/dr-en",
    }
    assert chamber["status_normalized"] == "passed"


def test_a_phrase_one_language_does_not_publish_does_not_erase_the_other() -> None:
    """An unmapped phrase normalizes to `unknown`. Upstream may add a phrase in one language
    before the vocabulary has it, and that is no reason to forget what the other one established."""
    merged = merge_listing_into_bill(
        None,
        record(status_raw="Lulus", status_normalized="passed"),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/dr-bm",
        observed_at="2026-08-01T00:00:00Z",
    )
    merged = merge_listing_into_bill(
        merged,
        record(status_raw="Carried over to the next session", status_normalized="unknown"),
        chamber="dewan_rakyat",
        language="en",
        source_url="https://example.org/dr-en",
        observed_at="2026-08-01T00:00:00Z",
    )
    chamber = merged["chambers"]["dewan_rakyat"]
    assert chamber["status_normalized"] == "passed"
    assert chamber["statuses_raw"]["en"] == "Carried over to the next session"


def test_a_listing_that_published_no_dates_does_not_empty_the_ones_we_have() -> None:
    """Both languages publish the same dates, but a page whose detail box is missing — or whose
    labels the parser does not yet know — yields none, and silence is not a correction."""
    merged = merge_listing_into_bill(
        None,
        record(dates=first_reading(2)),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/dr-bm",
        observed_at="2026-08-01T00:00:00Z",
    )
    merged = merge_listing_into_bill(
        merged,
        record(dates=()),
        chamber="dewan_rakyat",
        language="en",
        source_url="https://example.org/dr-en",
        observed_at="2026-08-01T00:00:00Z",
    )
    assert merged["chambers"]["dewan_rakyat"]["dates"]["first_reading"] == [
        {"start": "2026-07-02", "end": None}
    ]


def test_a_document_records_which_languages_listings_named_it() -> None:
    """The archive publishes `DR 17 BM.pdf` on its Malay pages and `DR 17 BI.pdf` on its English
    ones: two files, one language each, and that language becomes part of the Expression IRI."""
    merged = merge_listing_into_bill(
        None,
        record(document_urls=("https://example.org/DR 17 BM.pdf",)),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/dr-bm",
        observed_at="2026-08-01T00:00:00Z",
    )
    merged = merge_listing_into_bill(
        merged,
        record(document_urls=("https://example.org/DR 17 BI.pdf",)),
        chamber="dewan_rakyat",
        language="en",
        source_url="https://example.org/dr-en",
        observed_at="2026-08-01T00:00:00Z",
    )
    assert [(doc["url"], doc["languages"]) for doc in merged["documents"]] == [
        ("https://example.org/DR 17 BM.pdf", ["ms"]),
        ("https://example.org/DR 17 BI.pdf", ["en"]),
    ]


def test_one_file_named_by_both_languages_keeps_both_sightings() -> None:
    """The archive's older paths carry no language marker, so both trees can name the same file.
    Recording both is what lets a later step see that the language is unsettled instead of
    inheriting whichever listing happened to be parsed last."""
    merged = merge_listing_into_bill(
        None,
        record(document_urls=("https://example.org/DR012011.pdf",)),
        chamber="dewan_negara",
        language="en",
        source_url="https://example.org/dn-en",
        observed_at="2026-08-01T00:00:00Z",
    )
    merged = merge_listing_into_bill(
        merged,
        record(document_urls=("https://example.org/DR012011.pdf",)),
        chamber="dewan_negara",
        language="ms",
        source_url="https://example.org/dn-bm",
        observed_at="2026-08-01T00:00:00Z",
    )
    (document,) = merged["documents"]
    assert document["languages"] == ["en", "ms"]


def test_a_document_stored_before_languages_were_tracked_gains_one_on_the_next_parse() -> None:
    """The corpus already holds ~1,204 documents recorded without a language. `parse_listings`
    replays every stored listing on each run, so the field arrives without re-crawling anything."""
    legacy = {
        "identifier": {"slug": "dr-15-2026", "normalized": "DR-15-2026"},
        "titles": {"raw_ms": "RUU Contoh 2026"},
        "chambers": {},
        "documents": [
            {
                "url": "https://example.org/a.pdf",
                "chamber": "dewan_rakyat",
                "first_seen_at": "2026-08-01T00:00:00Z",
            }
        ],
        "first_seen_at": "2026-08-01T00:00:00Z",
        "last_seen_at": "2026-08-01T00:00:00Z",
    }
    merged = merge_listing_into_bill(
        legacy,
        record(document_urls=("https://example.org/a.pdf",)),
        chamber="dewan_rakyat",
        language="ms",
        source_url="https://example.org/dr-bm",
        observed_at="2026-08-22T00:00:00Z",
    )
    (document,) = merged["documents"]
    assert document["languages"] == ["ms"]
    assert document["first_seen_at"] == "2026-08-01T00:00:00Z"
