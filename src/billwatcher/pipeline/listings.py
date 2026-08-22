"""Steps 1 and 2 of the file-first pipeline: fetch Parliament's listing pages, then parse
whatever landed in the store into per-bill records.

Step 1 (`fetch_listings`) is the only network-touching half; step 2 (`parse_listings`) is fully
offline, reading nothing but what step 1 already wrote through `PipelineStore` — the same
fetch/parse separation HANDOFF 11.1 requires of the database-backed scraper, kept here for the
same reason: a parser fix must be replayable from stored bytes without re-crawling Parliament.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from billwatcher.pipeline.bills import merge_listing_into_bill
from billwatcher.pipeline.store import PipelineStore
from billwatcher.pipeline.targets import TARGETS, archive_year_url
from billwatcher.scraper.fetch import Fetcher, FetchResult
from billwatcher.scraper.parse_archive import (
    ArchiveParseError,
    is_archive_index_url,
    is_archive_year_url,
    parse_archive_index,
    parse_archive_year,
)
from billwatcher.scraper.parse_listing import ListingParseError, parse_listing

ROBOTS_URL = "https://www.parlimen.gov.my/robots.txt"


def fetch_listings(
    fetcher: Fetcher,
    store: PipelineStore,
    *,
    archive_year_limit: int | None = None,
) -> dict[str, int]:
    """Live. Fetches robots.txt, both current listings, both archive indices, and every year
    each index offers (or only the newest `archive_year_limit` years, oldest cheaply skipped).
    """
    counts = {"fetched": 0, "failed": 0}

    try:
        robots_result = fetcher.get(ROBOTS_URL)
        _store_response(store, key="robots-txt", url=ROBOTS_URL, result=robots_result)
        counts["fetched"] += 1
    except Exception:
        counts["failed"] += 1

    for target in TARGETS:
        try:
            result = fetcher.get(target.url)
        except Exception:
            counts["failed"] += 1
            continue
        key = f"{target.chamber}-{target.listing_kind}-{target.language}"
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
        if target.listing_kind != "archive_index" or result.status_code != 200:
            continue
        try:
            index = parse_archive_index(result.body.decode("utf-8"), source_url=result.final_url)
        except (UnicodeDecodeError, ArchiveParseError):
            counts["failed"] += 1
            continue
        years = index.years[:archive_year_limit] if archive_year_limit else index.years
        for year in years:
            year_url = archive_year_url(target.url, year)
            try:
                year_result = fetcher.get(year_url)
            except Exception:
                counts["failed"] += 1
                continue
            year_key = f"{target.chamber}-archive-{year}-{target.language}"
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
    return counts


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


def parse_listings(store: PipelineStore) -> dict[str, int]:
    """Offline. Re-parses every stored listing snapshot and upserts `bills/<slug>/bill.json`.

    Idempotent: parsing the same stored bytes twice merges the same fields with the same
    `observed_at`, so `FileStore`'s write-only-if-changed sidecar serialisation writes nothing
    new on a repeat run.
    """
    counts = {"listings_parsed": 0, "listings_failed": 0, "bills_touched": 0}
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
        except (UnicodeDecodeError, ListingParseError):
            counts["listings_failed"] += 1
            continue
        counts["listings_parsed"] += 1
        chamber = stored.metadata.get("chamber", "")
        language = stored.metadata.get("language", "ms")
        observed_at = stored.metadata.get("requested_at") or datetime.now(UTC).isoformat()
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
    counts["bills_touched"] = len(touched)
    return counts
