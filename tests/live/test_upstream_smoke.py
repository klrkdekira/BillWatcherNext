"""Opt-in upstream smoke checks (HANDOFF 18 "Optional live tests").

These never run as part of `make test`. They require BILLWATCHER_LIVE_TEST=1, obey the crawl
delay, fetch two documents at most, verify TLS strictly, and skip with a clear message when
robots policy, TLS, or upstream availability prevents them. They never disable verification and
never write to the database.
"""

import os
import time

import httpx
import pytest

from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.parse_listing import ListingParseError, parse_listing
from billwatcher.scraper.policy import CrawlPolicy
from billwatcher.scraper.robots import parse_robots

pytestmark = pytest.mark.live

ROBOTS_URL = "https://www.parlimen.gov.my/robots.txt"
LISTING_URL = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr"
USER_AGENT = "BillWatcherNext/0.1 (+https://example.org/about; contact: operator@example.org)"


@pytest.fixture(scope="module")
def fetcher() -> Fetcher:
    if os.environ.get("BILLWATCHER_LIVE_TEST") != "1":
        pytest.skip("set BILLWATCHER_LIVE_TEST=1 to run the opt-in upstream smoke test")
    policy = CrawlPolicy(user_agent=USER_AGENT, delay_seconds=2.0, concurrency=1)
    with Fetcher(policy) as client:
        yield client


def _get(fetcher: Fetcher, url: str) -> object:
    try:
        return fetcher.get(url)
    except httpx.ConnectError as error:  # includes TLS trust failures
        pytest.skip(f"upstream unreachable or TLS verification failed: {error}")
    except httpx.HTTPError as error:
        pytest.skip(f"upstream transport failure: {error}")


def test_robots_is_readable_and_records_a_hash(fetcher: Fetcher) -> None:
    response = _get(fetcher, ROBOTS_URL)
    if response.status_code != 200:
        pytest.skip(f"robots.txt returned {response.status_code}; no crawl may proceed")
    policy = parse_robots(response.body, fetched_url=response.final_url)
    assert len(policy.sha256) == 64
    if not policy.permits(USER_AGENT, LISTING_URL):
        pytest.skip("robots.txt disallows the listing path for our user agent")


def test_one_listing_page_parses(fetcher: Fetcher) -> None:
    robots = _get(fetcher, ROBOTS_URL)
    if robots.status_code != 200:
        pytest.skip("robots.txt is unavailable; the crawl policy is unknown")
    policy = parse_robots(robots.body, fetched_url=robots.final_url)
    if not policy.permits(USER_AGENT, LISTING_URL):
        pytest.skip("robots.txt disallows the listing path for our user agent")

    time.sleep(max(fetcher.policy.delay_seconds, policy.crawl_delay(USER_AGENT) or 0.0))
    response = _get(fetcher, LISTING_URL)
    if response.status_code != 200:
        pytest.skip(f"listing returned {response.status_code}")
    try:
        listing = parse_listing(
            response.body.decode("utf-8", errors="replace"), source_url=LISTING_URL
        )
    except ListingParseError as error:
        pytest.fail(
            "the live listing no longer matches the committed fixtures; save a new fixture "
            f"and update docs/upstream.md before changing the parser: {error}"
        )
    assert listing.records, "a current listing must never parse to zero bills"
    assert listing.structure_fingerprint
