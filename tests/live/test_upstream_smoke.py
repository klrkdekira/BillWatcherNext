"""Opt-in upstream smoke checks (HANDOFF 18 "Optional live tests").

These never run as part of `make test`. They require BILLWATCHER_LIVE_TEST=1, obey the crawl
delay, fetch two documents at most, verify TLS strictly, and skip with a clear message when
robots policy, TLS, or upstream availability prevents them. They never disable verification and
never write to the database.
"""

import os
import time
from pathlib import Path

import httpx
import pytest

from billwatcher.download.fetch import Fetcher
from billwatcher.download.parse_listing import ListingParseError, parse_listing
from billwatcher.download.policy import CrawlPolicy
from billwatcher.download.robots import parse_robots

pytestmark = pytest.mark.live

ROBOTS_URL = "https://www.parlimen.gov.my/robots.txt"
LISTING_URL = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr"
ENGLISH_LISTING_URL = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=en&uweb=dr"
USER_AGENT = "BillWatcherNext/0.1 (+https://example.org/about; contact: operator@example.org)"


@pytest.fixture(scope="module")
def fetcher() -> Fetcher:
    if os.environ.get("BILLWATCHER_LIVE_TEST") != "1":
        pytest.skip("set BILLWATCHER_LIVE_TEST=1 to run the opt-in upstream smoke test")
    # Upstream serves an incomplete certificate chain (`documentation/upstream.md`, 2026-08-18), so
    # without the intermediate every check here skips on TLS and the English guard below silently
    # never runs. Read the same bundle the crawl uses; `make ca-bundle` builds it.
    bundle_path = os.environ.get("UPSTREAM_CA_BUNDLE", "").strip()
    ca_bundle = Path(bundle_path) if bundle_path else None
    if ca_bundle is not None and not ca_bundle.is_file():
        pytest.skip(f"UPSTREAM_CA_BUNDLE does not name a file: {ca_bundle}")
    policy = CrawlPolicy(
        user_agent=USER_AGENT, delay_seconds=2.0, concurrency=1, ca_bundle=ca_bundle
    )
    with Fetcher(policy) as client:
        yield client


def _get(fetcher: Fetcher, url: str) -> object:
    try:
        return fetcher.get(url)
    except httpx.ConnectError as error:  # includes TLS trust failures
        pytest.skip(f"upstream unreachable or TLS verification failed: {error}")
    except httpx.HTTPError as error:
        pytest.skip(f"upstream transport failure: {error}")


def _robots_gate(fetcher: Fetcher, url: str) -> float:
    """The crawl delay to honour before fetching `url`, skipping if robots forbids it.

    Upstream has answered `/robots.txt` with a 404 since at least 2026-08-22 (the snapshot stored
    under `corpus/listings/robots-txt/`), and the crawl proceeds on that: RFC 9309 reads an absent
    robots.txt as "no restrictions", and `fetch_listings` records the 404 and carries on. Skipping
    these checks on it instead would have left the English guard below permanently dormant, which
    is the one thing ADR-040 relies on it not to be.
    """
    robots = _get(fetcher, ROBOTS_URL)
    if robots.status_code == 200:
        policy = parse_robots(robots.body, fetched_url=robots.final_url)
        if not policy.permits(USER_AGENT, url):
            pytest.skip("robots.txt disallows the listing path for our user agent")
        return max(fetcher.policy.delay_seconds, policy.crawl_delay(USER_AGENT) or 0.0)
    if robots.status_code < 400 or robots.status_code >= 500:
        # A 5xx or a redirect is an unknown policy rather than an absent one; do not assume.
        pytest.skip(f"robots.txt returned {robots.status_code}; the crawl policy is unknown")
    return fetcher.policy.delay_seconds


def test_robots_is_readable_and_records_a_hash(fetcher: Fetcher) -> None:
    response = _get(fetcher, ROBOTS_URL)
    if response.status_code != 200:
        pytest.skip(f"robots.txt returned {response.status_code}; no crawl may proceed")
    policy = parse_robots(response.body, fetched_url=response.final_url)
    assert len(policy.sha256) == 64
    if not policy.permits(USER_AGENT, LISTING_URL):
        pytest.skip("robots.txt disallows the listing path for our user agent")


def test_one_listing_page_parses(fetcher: Fetcher) -> None:
    time.sleep(_robots_gate(fetcher, LISTING_URL))
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


def test_the_english_listing_is_served_in_english(fetcher: Fetcher) -> None:
    """The one upstream behaviour a fixture cannot pin: whether `lang=en` is honoured.

    The site's language follows the session that serves the request — a cookieless request to the
    archive search is answered with a redirect to the *current Malay* listing, and the language
    cookie is set on first visit (documentation/upstream.md). `parse_listings` refuses a page whose
    labels are in the language it did not ask for, so if this ever stops holding, the English half
    of the corpus stops updating loudly rather than filling up with mislabelled Malay bills.
    """
    time.sleep(_robots_gate(fetcher, ENGLISH_LISTING_URL))
    response = _get(fetcher, ENGLISH_LISTING_URL)
    if response.status_code != 200:
        pytest.skip(f"listing returned {response.status_code}")
    listing = parse_listing(
        response.body.decode("utf-8", errors="replace"), source_url=ENGLISH_LISTING_URL
    )
    assert listing.records, "a current listing must never parse to zero bills"
    assert listing.observed_language == "en", (
        "upstream answered a lang=en request with a page whose labels are "
        f"{listing.observed_language!r}; the English crawl depends on this"
    )
