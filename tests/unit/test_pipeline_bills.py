from billwatcher.pipeline.bills import merge_listing_into_bill
from billwatcher.scraper.normalize import normalize_identifier
from billwatcher.scraper.parse_listing import ParsedListingBill


def record(
    *,
    identifier: str = "D.R.15/2026",
    title: str = "RUU Contoh 2026",
    status_raw: str = "Bacaan Kali Pertama",
    status_normalized: str = "first_read",
    presenter: str | None = "Menteri",
    document_urls: tuple[str, ...] = (),
) -> ParsedListingBill:
    return ParsedListingBill(
        identifier=normalize_identifier(identifier),
        title=title,
        status_raw=status_raw,
        status_normalized=status_normalized,
        year=2026,
        presenter=presenter,
        document_urls=document_urls,
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
