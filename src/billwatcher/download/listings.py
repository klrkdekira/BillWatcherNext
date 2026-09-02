"""Steps 1 and 2 of the file-first pipeline: fetch Parliament's listing pages, then parse
whatever landed in the store into per-bill records.

Step 1 (`fetch_listings`) is the only network-touching half; step 2 (`parse_listings`) is fully
offline, reading nothing but what step 1 already wrote through `PipelineStore` — the same
fetch/parse separation HANDOFF 11.1 requires of the database-backed scraper, kept here for the
same reason: a parser fix must be replayable from stored bytes without re-crawling Parliament.

Both steps name what they could not do. A listing has no bill and no document version to be named
by, so its failures are `ListingFailure`s — a key and the URL an operator would retry by hand —
and a cold archive crawl reports each page as it lands, because seventy-odd requests at the crawl
policy's two-second spacing is minutes of otherwise silent work.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from billwatcher.download.bills import merge_listing_into_bill
from billwatcher.download.fetch import Fetcher, FetchResult
from billwatcher.download.parse_archive import (
    ArchiveParseError,
    is_archive_index_url,
    is_archive_year_url,
    parse_archive_index,
    parse_archive_year,
)
from billwatcher.download.parse_listing import ListingParseError, parse_listing
from billwatcher.download.targets import TARGETS, archive_year_url
from billwatcher.reporting import (
    ListingFailure,
    Progress,
    StepResult,
    announce,
    describe_error,
)
from billwatcher.store import PipelineStore

ROBOTS_URL = "https://www.parlimen.gov.my/robots.txt"


def fetch_listings(
    fetcher: Fetcher,
    store: PipelineStore,
    *,
    archive_year_limit: int | None = None,
    skip_existing: bool = True,
    current_year: int | None = None,
    progress: Progress = None,
) -> StepResult:
    """Live. Fetches robots.txt, then every target in `TARGETS` — both chambers' current listings
    and archive indices, in **both published languages** — and every year each index offers (or only
    the newest `archive_year_limit` years, oldest cheaply skipped).

    With `skip_existing` (the default) a full crawl is resumable: an archived year already stored
    successfully is not fetched again. **Only closed archive years are skippable**, and the choice
    of what is *not* skippable is the load-bearing part:

    * `robots.txt`, both current listings and both archive indices are **always** re-fetched. They
      are how a new bill, and a new archive year, are discovered at all — skipping them because a
      copy exists locally would turn "resume the crawl" into "never see anything new", which is a
      silent coverage hole rather than a saved request.
    * The **current** calendar year's archive is always re-fetched too, because Parliament is still
      adding rows to it. Only years strictly before it are treated as closed.

    A non-200 that is stored still counts as fetched, not failed: it is a real observation of what
    Parliament served, `has_listing` refuses to treat it as a usable snapshot, and the next run
    retries it. The status code rides along in the progress line so it is visible while it happens.
    """
    counts = {"fetched": 0, "skipped": 0, "failed": 0}
    failures: list[ListingFailure] = []
    year_now = current_year if current_year is not None else datetime.now(UTC).year

    try:
        robots_result = fetcher.get(ROBOTS_URL)
    except Exception as error:
        counts["failed"] += 1
        failures.append(ListingFailure("robots-txt", ROBOTS_URL, describe_error(error)))
    else:
        _store_response(store, key="robots-txt", url=ROBOTS_URL, result=robots_result)
        counts["fetched"] += 1
        announce(progress, f"fetched robots-txt (HTTP {robots_result.status_code})")

    for target in TARGETS:
        key = f"{target.chamber}-{target.listing_kind}-{target.language}"
        try:
            result = fetcher.get(target.url)
        except Exception as error:
            counts["failed"] += 1
            failures.append(ListingFailure(key, target.url, describe_error(error)))
            continue
        _store_response(
            store,
            key=key,
            url=target.url,
            result=result,
            chamber=target.chamber,
            listing_kind=target.listing_kind,
            language=target.language,
        )
        counts["fetched"] += 1
        announce(progress, f"fetched {key} (HTTP {result.status_code})")
        if target.listing_kind != "archive_index" or result.status_code != 200:
            continue
        try:
            index = parse_archive_index(result.body.decode("utf-8"), source_url=result.final_url)
        except (UnicodeDecodeError, ArchiveParseError) as error:
            counts["failed"] += 1
            failures.append(ListingFailure(key, result.final_url, describe_error(error)))
            continue
        years = index.years[:archive_year_limit] if archive_year_limit else index.years
        announce(progress, f"{key} offers {len(years)} archive year(s)")
        for year in years:
            year_key = f"{target.chamber}-archive-{year}-{target.language}"
            # A closed year's archive cannot gain rows, so a stored copy is the whole answer.
            if skip_existing and year < year_now and store.has_listing(key=year_key):
                counts["skipped"] += 1
                continue
            year_url = archive_year_url(target.url, year)
            try:
                year_result = fetcher.get(year_url)
            except Exception as error:
                counts["failed"] += 1
                failures.append(ListingFailure(year_key, year_url, describe_error(error)))
                continue
            _store_response(
                store,
                key=year_key,
                url=year_url,
                result=year_result,
                chamber=target.chamber,
                listing_kind="archive_year",
                language=target.language,
                scope=str(year),
            )
            counts["fetched"] += 1
            announce(progress, f"fetched {year_key} (HTTP {year_result.status_code})")
    return StepResult(counts=counts, failures=tuple(failures))


def _store_response(
    store: PipelineStore, *, key: str, url: str, result: FetchResult, **extra: Any
) -> None:
    extension = "txt" if key == "robots-txt" else "xml" if "arkib=yes" in url else "html"
    metadata = {
        "url": url,
        "final_url": result.final_url,
        "requested_at": result.requested_at.isoformat(),
        "status_code": result.status_code,
        "sha256": hashlib.sha256(result.body).hexdigest(),
        "byte_size": len(result.body),
        **extra,
    }
    store.save_listing(key=key, extension=extension, body=result.body, metadata=metadata)


def parse_listings(store: PipelineStore, *, progress: Progress = None) -> StepResult:
    """Offline. Re-parses every stored listing snapshot and upserts `bills/<slug>/bill.json`.

    Idempotent: parsing the same stored bytes twice merges the same fields with the same
    `observed_at`, so `FileStore`'s write-only-if-changed sidecar serialisation writes nothing
    new on a repeat run.

    A snapshot whose own labels are in a different language than the request that fetched it is
    **refused rather than merged**, and reported as `listings_wrong_language`. Parliament's language
    follows the session that serves the request, not only the `lang=` parameter
    (`documentation/upstream.md`), so an English request can be answered with a Malay page that
    parses perfectly. Merging it would file a Malay title under `titles.raw_en` and record English
    as the language of Malay documents — a wrong permanent Expression IRI (ADR-024, ADR-040) rather
    than a missing one. It is not counted as a parse failure because it is not one: the bytes
    parsed, and it is the fetch that has to be repeated.
    """
    counts = {
        "listings_parsed": 0,
        "listings_failed": 0,
        "listings_wrong_language": 0,
        "bills_touched": 0,
    }
    failures: list[ListingFailure] = []
    touched: set[str] = set()
    for stored in store.iter_listings():
        url = stored.metadata.get("url", "")
        if not url or stored.metadata.get("status_code") != 200:
            continue
        if is_archive_index_url(url):
            continue  # the index carries no bill rows, only the year list `fetch_listings` used
        try:
            body_text = stored.body.decode("utf-8")
            source_url = stored.metadata.get("final_url") or url
            parsed = (
                parse_archive_year(body_text, source_url=source_url)
                if is_archive_year_url(url)
                else parse_listing(body_text, source_url=source_url)
            )
        except (UnicodeDecodeError, ListingParseError) as error:
            counts["listings_failed"] += 1
            failures.append(ListingFailure(stored.key, url, describe_error(error)))
            continue
        chamber = stored.metadata.get("chamber", "")
        language = stored.metadata.get("language", "ms")
        observed_at = stored.metadata.get("requested_at") or datetime.now(UTC).isoformat()
        if parsed.observed_language is not None and parsed.observed_language != language:
            counts["listings_wrong_language"] += 1
            failures.append(
                ListingFailure(
                    stored.key,
                    url,
                    f"requested {language!r} and was served a page whose labels are "
                    f"{parsed.observed_language!r}; not merged. Re-fetch this target.",
                )
            )
            announce(progress, f"REFUSED {stored.key}: served {parsed.observed_language!r}")
            continue
        counts["listings_parsed"] += 1
        for record in parsed.records:
            slug = record.identifier.slug
            existing = store.load_bill(slug)
            merged = merge_listing_into_bill(
                existing,
                record,
                chamber=chamber,
                language=language,
                source_url=url,
                observed_at=observed_at,
            )
            store.save_bill(slug, merged)
            touched.add(slug)
        announce(progress, f"parsed {stored.key}: {len(parsed.records)} bill row(s)")
    counts["bills_touched"] = len(touched)
    return StepResult(counts=counts, failures=tuple(failures))
