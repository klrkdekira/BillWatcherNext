"""Steps 1 and 2 of the file-first pipeline, against real fixture bytes with a mocked transport.

No database, no object store: `FileStore` is the only thing state lands in.
"""

import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from billwatcher.cli import app
from billwatcher.config import get_settings
from billwatcher.download.documents import language_of
from billwatcher.download.fetch import Fetcher
from billwatcher.download.listings import fetch_listings, parse_listings
from billwatcher.download.policy import CrawlPolicy
from billwatcher.download.targets import TARGETS, archive_year_url
from billwatcher.reporting import ListingFailure, StepResult
from billwatcher.store import FileStore

FIXTURES = Path("tests/fixtures/parliament")
POLICY = CrawlPolicy("BillWatcherNext-pipeline-test/0.1 (+https://example.org/about)")

_DN_ARCHIVE_INDEX = (
    b"<?xml version='1.0'?><tree id='0'>"
    b"<item child='1' id='0_2011' text='2011'><userdata name='myurl'>#</userdata></item>"
    b"</tree>"
)

# One fixture per (chamber, kind, language), because the crawl reads every listing in both
# published languages (ADR-040) and a route table written by index says nothing about which page
# each entry stands for.
# The two archive indices are language-neutral by nature — they carry years, not words — so the
# English index request is answered with the same bytes the live site answers it with.
_LISTING_FIXTURES = {
    ("dewan_rakyat", "current", "ms"): (FIXTURES / "current_dr_bm.html").read_bytes(),
    ("dewan_negara", "current", "ms"): (FIXTURES / "current_dn_bm.html").read_bytes(),
    ("dewan_rakyat", "current", "en"): (FIXTURES / "current_dr_en.html").read_bytes(),
    ("dewan_negara", "current", "en"): (FIXTURES / "current_dn_en.html").read_bytes(),
    ("dewan_rakyat", "archive_index", "ms"): (FIXTURES / "archive_index_dr.xml").read_bytes(),
    ("dewan_rakyat", "archive_index", "en"): (FIXTURES / "archive_index_dr.xml").read_bytes(),
    ("dewan_negara", "archive_index", "ms"): _DN_ARCHIVE_INDEX,
    ("dewan_negara", "archive_index", "en"): _DN_ARCHIVE_INDEX,
}
_YEAR_FIXTURES = {
    ("dewan_rakyat", 2024, "ms"): (FIXTURES / "archive_year_dr_2024.xml").read_bytes(),
    ("dewan_rakyat", 2024, "en"): (FIXTURES / "archive_year_dr_en_2024.xml").read_bytes(),
    ("dewan_negara", 2011, "ms"): (FIXTURES / "archive_year_dn_2011.xml").read_bytes(),
    ("dewan_negara", 2011, "en"): (FIXTURES / "archive_year_dn_en_2011.xml").read_bytes(),
}


def _target(chamber: str, listing_kind: str, language: str):
    (found,) = [
        target
        for target in TARGETS
        if (target.chamber, target.listing_kind, target.language)
        == (chamber, listing_kind, language)
    ]
    return found


def _year_url(chamber: str, year: int, language: str) -> str:
    return archive_year_url(_target(chamber, "archive_index", language).url, year)


def _build_routes() -> dict[str, tuple[int, bytes, str]]:
    routes: dict[str, tuple[int, bytes, str]] = {
        "https://www.parlimen.gov.my/robots.txt": (404, b"not found", "text/plain")
    }
    for (chamber, listing_kind, language), body in _LISTING_FIXTURES.items():
        target = _target(chamber, listing_kind, language)
        content_type = "text/xml" if listing_kind == "archive_index" else "text/html"
        routes[target.url] = (200, body, content_type)
    for (chamber, year, language), body in _YEAR_FIXTURES.items():
        routes[_year_url(chamber, year, language)] = (200, body, "text/xml")
    return routes


_ROUTES = _build_routes()

# robots + 8 targets + 4 archive years (one per chamber per language, at archive_year_limit=1).
_COLD_CRAWL_FETCHES = 13


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
        fetch_result = fetch_listings(fetcher, store, archive_year_limit=1)

    assert fetch_result.counts == {"fetched": _COLD_CRAWL_FETCHES, "skipped": 0, "failed": 0}
    assert fetch_result.failures == ()

    stored_keys = {listing.key for listing in store.iter_listings()}
    assert stored_keys == {
        "robots-txt",
        "dewan_rakyat-current-ms",
        "dewan_negara-current-ms",
        "dewan_rakyat-archive_index-ms",
        "dewan_negara-archive_index-ms",
        "dewan_rakyat-archive-2024-ms",
        "dewan_negara-archive-2011-ms",
        "dewan_rakyat-current-en",
        "dewan_negara-current-en",
        "dewan_rakyat-archive_index-en",
        "dewan_negara-archive_index-en",
        "dewan_rakyat-archive-2024-en",
        "dewan_negara-archive-2011-en",
    }

    parse_result = parse_listings(store)
    # The four archive *indices* are stored but carry no bill rows; eight listings — four Malay and
    # four English — parse into bills.
    assert parse_result.counts["listings_parsed"] == 8
    assert parse_result.counts["listings_failed"] == 0
    assert parse_result.counts["listings_wrong_language"] == 0
    assert parse_result.failures == ()

    slugs = set(store.iter_bill_slugs())
    assert "dr-15-2026" in slugs  # from current_dr_bm.html
    assert "dr-17-2024" in slugs  # from archive_year_dr_2024.xml

    bill = store.load_bill("dr-15-2026")
    assert bill is not None
    assert bill["chambers"]["dewan_rakyat"]["status_normalized"] == "passed"
    assert bill["documents"][0]["url"] == "https://www.parlimen.gov.my/pdf/dr15.pdf"


def test_both_languages_of_one_bill_land_on_one_record(tmp_path) -> None:
    """The point of crawling both: one bill, one record, two titles, and two documents.

    D.R.17/2024 is published in the archive tree twice — `DR 17 BM.pdf` under the Malay pages and
    `DR 17 BI.pdf` under the English ones. They are two Expressions of one Work (ADR-024), so they
    must arrive as two documents of one bill, each knowing which language named it, rather than as
    one document whose language depends on which listing was parsed last.
    """
    store = FileStore(tmp_path)
    with _fetcher() as fetcher:
        fetch_listings(fetcher, store, archive_year_limit=1)
    parse_listings(store)

    bill = store.load_bill("dr-17-2024")
    assert bill is not None
    assert bill["titles"]["raw_ms"] == "RUU Penagih Dadah (Rawatan dan Pemulihan) (Pindaan) 2024"
    assert (
        bill["titles"]["raw_en"]
        == "Drug Dependants (Treatment and Rehabilitation) (Amendment) Bill 2024"
    )

    languages = {
        document["url"].rsplit("/", 1)[-1]: document["languages"] for document in bill["documents"]
    }
    assert languages == {"DR%2017%20BM.pdf": ["ms"], "DR%2017%20BI.pdf": ["en"]}

    # The raw phrase is kept per language; the normalized one is a single fact about the bill.
    chamber = bill["chambers"]["dewan_rakyat"]
    assert chamber["statuses_raw"] == {"ms": "Lulus", "en": "Passed"}
    assert chamber["status_normalized"] == "passed"
    assert set(chamber["source_urls"]) == {"ms", "en"}
    # Both trees publish the same reading dates, and merging twice must not duplicate them.
    assert chamber["dates"]["first_reading"] == [{"start": "2024-07-02", "end": None}]


def test_a_document_both_languages_link_claims_neither(tmp_path) -> None:
    """The archive's older path shapes carry no `BM`/`BI` marker, so both trees can name the same
    file. One file cannot be two Expressions of one bill, so the record keeps both sightings and
    lets the reading step fall back rather than picking a language by parse order."""
    store = FileStore(tmp_path)
    with _fetcher() as fetcher:
        fetch_listings(fetcher, store, archive_year_limit=1)
    parse_listings(store)

    bill = store.load_bill("dr-1-2011")
    assert bill is not None
    (document,) = bill["documents"]
    assert document["url"].endswith("/DR012011.pdf")
    assert document["languages"] == ["en", "ms"]
    assert language_of(document) is None


def test_a_page_served_in_the_wrong_language_is_refused_not_merged(tmp_path) -> None:
    """Parliament's language follows the session that serves the request, so an English request can
    be answered with a Malay page (documentation/upstream.md). Merging it would file a Malay title
    under `raw_en` and mint an English Expression IRI for a Malay document."""
    store = FileStore(tmp_path)
    routes = dict(_ROUTES)
    english_dr = _target("dewan_rakyat", "current", "en")
    routes[english_dr.url] = (200, (FIXTURES / "current_dr_bm.html").read_bytes(), "text/html")
    fetcher, _seen = _recording_fetcher(routes)
    with fetcher:
        fetch_listings(fetcher, store, archive_year_limit=1)

    result = parse_listings(store)

    assert result.counts["listings_wrong_language"] == 1
    assert result.counts["listings_failed"] == 0
    (failure,) = [item for item in result.failures if item.key == "dewan_rakyat-current-en"]
    assert "requested 'en'" in failure.reason
    assert "'ms'" in failure.reason
    bill = store.load_bill("dr-15-2026")
    assert bill is not None
    assert bill["titles"]["raw_ms"] == "RUU Perlindungan Saksi"
    # The refused page contributed nothing at all: the Dewan Rakyat record knows only the Malay
    # listing that really was served in Malay. (The bill's English title here comes from the Dewan
    # Negara's English listing, which was served correctly — that page is a different observation.)
    assert set(bill["chambers"]["dewan_rakyat"]["source_urls"]) == {"ms"}
    assert set(bill["chambers"]["dewan_negara"]["source_urls"]) == {"ms", "en"}


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


def _recording_fetcher(routes: dict[str, tuple[int, bytes, str]]) -> tuple[Fetcher, list[str]]:
    """A fetcher that records every URL it is actually asked for, so a skip is provable."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        status, body, content_type = routes[url]
        return httpx.Response(
            status, content=body, headers={"Content-Type": content_type}, request=request
        )

    fetcher = Fetcher(POLICY, transport=httpx.MockTransport(handler), sleep=lambda _delay: None)
    return fetcher, seen


def test_a_second_crawl_skips_closed_archive_years_it_already_has(tmp_path) -> None:
    """This is what makes a full-corpus crawl resumable rather than an all-or-nothing run."""
    store = FileStore(tmp_path)
    with _fetcher() as fetcher:
        fetch_listings(fetcher, store, archive_year_limit=1, current_year=2026)

    fetcher, seen = _recording_fetcher(dict(_ROUTES))
    with fetcher:
        result = fetch_listings(fetcher, store, archive_year_limit=1, current_year=2026)

    # Both closed years (2024, 2011) are already stored in both languages, so none is requested
    # again: four skips, and the nine always-refetched requests.
    assert result.counts["skipped"] == 4
    assert result.counts["fetched"] == 9
    assert result.counts["failed"] == 0
    assert not [url for url in seen if "ajx=1" in url]
    # ...but everything that could have changed *is* re-requested.
    assert "https://www.parlimen.gov.my/robots.txt" in seen
    for target in TARGETS:
        assert target.url in seen


def test_the_current_years_archive_is_refetched_even_when_already_stored(tmp_path) -> None:
    """Parliament is still adding rows to the running year, so a stored copy is not the answer."""
    store = FileStore(tmp_path)
    with _fetcher() as fetcher:
        fetch_listings(fetcher, store, archive_year_limit=1, current_year=2026)

    fetcher, seen = _recording_fetcher(dict(_ROUTES))
    with fetcher:
        # 2024 is now "this year": it must be re-read; 2011 is closed and stays skipped.
        result = fetch_listings(fetcher, store, archive_year_limit=1, current_year=2024)

    # 2011 stays skipped in both languages; 2024 is re-read in both.
    assert result.counts["skipped"] == 2
    year_requests = [url for url in seen if "ajx=1" in url]
    assert len(year_requests) == 2
    assert all("id=0_2024" in url for url in year_requests)


def test_a_new_bill_in_the_current_listing_is_still_found_on_a_resumed_crawl(tmp_path) -> None:
    """The coverage hole a naive "skip if exists" would open: never seeing anything new."""
    store = FileStore(tmp_path)
    with _fetcher() as fetcher:
        fetch_listings(fetcher, store, archive_year_limit=1, current_year=2026)
    parse_listings(store)
    assert "dr-99-2026" not in set(store.iter_bill_slugs())

    grown = (
        (FIXTURES / "current_dr_bm.html").read_bytes().replace(b"D.R.15/2026", b"D.R.99/2026", 1)
    )
    routes = dict(_ROUTES)
    routes[_target("dewan_rakyat", "current", "ms").url] = (200, grown, "text/html")
    fetcher, _seen = _recording_fetcher(routes)
    with fetcher:
        fetch_listings(fetcher, store, archive_year_limit=1, current_year=2026)
    parse_listings(store)

    assert "dr-99-2026" in set(store.iter_bill_slugs())


def test_a_stored_failure_is_retried_rather_than_cemented(tmp_path) -> None:
    """Skipping exists to avoid redundant work, not to freeze a bad response into the record."""
    store = FileStore(tmp_path)
    failing = dict(_ROUTES)
    dn_2011 = _year_url("dewan_negara", 2011, "ms")
    failing[dn_2011] = (500, b"upstream error", "text/plain")
    fetcher, _ = _recording_fetcher(failing)
    with fetcher:
        fetch_listings(fetcher, store, archive_year_limit=1, current_year=2026)
    assert store.has_listing(key="dewan_negara-archive-2011-ms") is False

    fetcher, seen = _recording_fetcher(dict(_ROUTES))
    with fetcher:
        result = fetch_listings(fetcher, store, archive_year_limit=1, current_year=2026)

    assert dn_2011 in seen
    # Every year but the one that failed stored successfully first time round.
    assert result.counts["skipped"] == 3
    assert store.has_listing(key="dewan_negara-archive-2011-ms") is True


def test_refetching_the_archive_is_available_when_the_operator_asks_for_it(tmp_path) -> None:
    store = FileStore(tmp_path)
    with _fetcher() as fetcher:
        fetch_listings(fetcher, store, archive_year_limit=1, current_year=2026)

    fetcher, seen = _recording_fetcher(dict(_ROUTES))
    with fetcher:
        result = fetch_listings(
            fetcher, store, archive_year_limit=1, skip_existing=False, current_year=2026
        )

    assert result.counts == {"fetched": _COLD_CRAWL_FETCHES, "skipped": 0, "failed": 0}
    assert len([url for url in seen if "ajx=1" in url]) == 4


def _fetcher_that_cannot_reach(broken_url: str) -> Fetcher:
    """A fetcher whose transport refuses one URL and serves the rest of the fixture routes."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == broken_url:
            raise httpx.ConnectError("connection refused", request=request)
        status, body, content_type = _ROUTES[url]
        return httpx.Response(
            status, content=body, headers={"Content-Type": content_type}, request=request
        )

    return Fetcher(POLICY, transport=httpx.MockTransport(handler), sleep=lambda _delay: None)


def test_an_archive_year_that_will_not_fetch_is_named_with_the_url_to_retry(tmp_path) -> None:
    """`{"failed": 1}` over a seventy-year archive crawl says nothing about which year is missing,
    and a listing has no bill slug or document version to be named by — only a key and a URL."""
    store = FileStore(tmp_path)
    dr_2024 = _year_url("dewan_rakyat", 2024, "ms")

    with _fetcher_that_cannot_reach(dr_2024) as fetcher:
        result = fetch_listings(fetcher, store, archive_year_limit=1, current_year=2026)

    assert result.counts == {"fetched": _COLD_CRAWL_FETCHES - 1, "skipped": 0, "failed": 1}
    (failure,) = result.failures
    assert failure.key == "dewan_rakyat-archive-2024-ms"
    assert failure.url == dr_2024
    assert "ConnectError" in failure.reason
    assert dr_2024 in failure.label
    assert store.has_listing(key="dewan_rakyat-archive-2024-ms") is False


def test_a_stored_listing_that_will_not_parse_is_named_rather_than_only_counted(tmp_path) -> None:
    """A parser fix is replayed from stored bytes, so knowing *which* snapshot defeated it is the
    difference between re-reading one page and re-reading the whole store."""
    store = FileStore(tmp_path)
    url = _target("dewan_rakyat", "current", "ms").url
    store.save_listing(
        key="dewan_rakyat-current-ms",
        extension="html",
        body=b"<html><body>no table here</body></html>",
        metadata={
            "url": url,
            "final_url": url,
            "status_code": 200,
            "chamber": "dewan_rakyat",
            "language": "ms",
        },
    )

    result = parse_listings(store)

    assert result.counts["listings_parsed"] == 0
    assert result.counts["listings_failed"] == 1
    (failure,) = result.failures
    assert failure.key == "dewan_rakyat-current-ms"
    assert failure.url == url
    assert "ListingParseError" in failure.reason


def test_the_parse_step_leaves_a_manifest_behind_like_every_other_step(tmp_path, monkeypatch):
    """Steps 1-3 reported one JSON line and vanished, so a corpus download left no record of
    itself at all while the later steps each wrote one (ADR-019)."""
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "store"))
    get_settings.cache_clear()
    store = FileStore(tmp_path / "store")
    with _fetcher() as fetcher:
        fetch_listings(fetcher, store, archive_year_limit=1)

    invocation = CliRunner().invoke(app, ["parse-listings"])

    assert invocation.exit_code == 0
    manifests = list((tmp_path / "store" / "manifests" / "parse-listings").glob("*.json"))
    assert len(manifests) == 1
    payload = json.loads(manifests[0].read_text())
    assert payload["counts"]["listings_parsed"] == 8
    assert payload["failures"] == []
    assert payload["code_versions"]["billwatcher"]
    assert payload["started_at"] <= payload["finished_at"]


def _total_failure(*_args, **_kwargs):
    """A crawl that reached nothing at all — the shape an incomplete TLS chain produces."""
    return StepResult(
        counts={"fetched": 0, "skipped": 0, "failed": 2},
        failures=(
            ListingFailure("robots-txt", "https://www.parlimen.gov.my/robots.txt", "ConnectError"),
            ListingFailure(
                "dewan_rakyat-current-en",
                "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=en&uweb=dr",
                "ConnectError: certificate verify failed",
            ),
        ),
    )


def _partial_failure(*_args, **_kwargs):
    """A crawl that stored most targets and lost one — normal, and resumable."""
    return StepResult(
        counts={"fetched": 7, "skipped": 0, "failed": 1},
        failures=(
            ListingFailure(
                "dewan_negara-archive_index-en",
                "https://www.parlimen.gov.my/bills-dewan-negara.html?lang=en&uweb=dn",
                "ReadTimeout",
            ),
        ),
    )


def test_a_fetch_that_reached_nothing_exits_non_zero(tmp_path, monkeypatch) -> None:
    """`make download` runs the listings step and then the documents step. A crawl that failed
    every target used to exit 0, so a misconfigured trust store sent the second step out over the
    same broken setup and the run reported success having stored nothing."""
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "store"))
    get_settings.cache_clear()
    monkeypatch.setattr("billwatcher.cli.fetch_listings", _total_failure)

    invocation = CliRunner().invoke(app, ["fetch-listings", "--approve-live"])

    assert invocation.exit_code == 1
    assert "accomplished nothing" in invocation.output


def test_a_fetch_that_lost_only_some_targets_still_exits_zero(tmp_path, monkeypatch) -> None:
    """The guard above must not turn a resumable partial crawl into a failed build: a handful of
    unreachable targets in a 2,400-document corpus is expected, and the next run picks them up."""
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "store"))
    get_settings.cache_clear()
    monkeypatch.setattr("billwatcher.cli.fetch_listings", _partial_failure)

    invocation = CliRunner().invoke(app, ["fetch-listings", "--approve-live"])

    assert invocation.exit_code == 0
    assert "accomplished nothing" not in invocation.output
