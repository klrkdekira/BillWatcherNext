"""Steps 1 and 2 of the file-first pipeline, against real fixture bytes with a mocked transport.

No database, no object store: `FileStore` is the only thing state lands in.
"""

from pathlib import Path

import httpx

from billwatcher.pipeline.listings import fetch_listings, parse_listings
from billwatcher.pipeline.store import FileStore
from billwatcher.pipeline.targets import TARGETS
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.policy import CrawlPolicy

FIXTURES = Path("tests/fixtures/parliament")
POLICY = CrawlPolicy("BillWatcherNext-pipeline-test/0.1 (+https://example.org/about)")

_DN_ARCHIVE_INDEX = (
    b"<?xml version='1.0'?><tree id='0'>"
    b"<item child='1' id='0_2011' text='2011'><userdata name='myurl'>#</userdata></item>"
    b"</tree>"
)

_ROUTES = {
    "https://www.parlimen.gov.my/robots.txt": (404, b"not found", "text/plain"),
    TARGETS[0].url: (200, (FIXTURES / "current_dr_bm.html").read_bytes(), "text/html"),
    TARGETS[1].url: (200, (FIXTURES / "current_dn_bm.html").read_bytes(), "text/html"),
    TARGETS[2].url: (200, (FIXTURES / "archive_index_dr.xml").read_bytes(), "text/xml"),
    TARGETS[3].url: (200, _DN_ARCHIVE_INDEX, "text/xml"),
    TARGETS[2].url.replace("ajx=0", "ajx=1") + "&id=0_2024": (
        200,
        (FIXTURES / "archive_year_dr_2024.xml").read_bytes(),
        "text/xml",
    ),
    TARGETS[3].url.replace("ajx=0", "ajx=1") + "&id=0_2011": (
        200,
        (FIXTURES / "archive_year_dn_2011.xml").read_bytes(),
        "text/xml",
    ),
}


def _fetcher() -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body, content_type = _ROUTES[str(request.url)]
        return httpx.Response(
            status, content=body, headers={"Content-Type": content_type}, request=request
        )

    return Fetcher(POLICY, transport=httpx.MockTransport(handler), sleep=lambda _delay: None)


def test_fetch_then_parse_produces_bill_records_from_both_current_and_archive(tmp_path) -> None:
    store = FileStore(tmp_path)
    with _fetcher() as fetcher:
        fetch_counts = fetch_listings(fetcher, store, archive_year_limit=1)

    # robots + 2 current + 2 archive indices + 2 archive years = 7 fetches, nothing failed.
    assert fetch_counts == {"fetched": 7, "failed": 0}

    stored_keys = {listing.key for listing in store.iter_listings()}
    assert stored_keys == {
        "robots-txt",
        "dewan_rakyat-current-ms",
        "dewan_negara-current-ms",
        "dewan_rakyat-archive_index-ms",
        "dewan_negara-archive_index-ms",
        "dewan_rakyat-archive-2024-ms",
        "dewan_negara-archive-2011-ms",
    }

    parse_counts = parse_listings(store)
    # The two archive *indices* are stored but carry no bill rows; four listings parse into bills.
    assert parse_counts["listings_parsed"] == 4
    assert parse_counts["listings_failed"] == 0

    slugs = set(store.iter_bill_slugs())
    assert "dr-15-2026" in slugs  # from current_dr_bm.html
    assert "dr-17-2024" in slugs  # from archive_year_dr_2024.xml

    bill = store.load_bill("dr-15-2026")
    assert bill is not None
    assert bill["chambers"]["dewan_rakyat"]["status_normalized"] == "passed"
    assert bill["documents"][0]["url"] == "https://www.parlimen.gov.my/pdf/dr15.pdf"


def test_re_parsing_the_same_stored_listings_converges_to_the_same_content(tmp_path) -> None:
    """`parse_listings` alone, not `fetch_listings`, is what must settle to the same content on
    a repeat run: re-fetching live pages legitimately advances `requested_at` (and so
    `last_seen_at`), which is a real fact worth recording, not something to suppress.

    D.R.15/2026 is touched by *two* listings (both chambers reference it, per A4), so it is
    written more than once within a single `parse_listings` call — a bill's file naturally gets
    an intermediate write before settling, every run, since listings are re-merged from scratch
    each time rather than diffed. What must hold is the *final* content, not the file's mtime.
    """
    store = FileStore(tmp_path)
    with _fetcher() as fetcher:
        fetch_listings(fetcher, store, archive_year_limit=1)
    parse_listings(store)
    bill_path = tmp_path / "bills" / "dr-15-2026" / "bill.json"
    first_content = bill_path.read_bytes()

    parse_listings(store)

    assert bill_path.read_bytes() == first_content
