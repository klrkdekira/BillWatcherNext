"""Pure merge logic for one bill's file-first record.

No I/O here — `billwatcher.pipeline.listings.parse_listings` owns reading the previous record
through `PipelineStore` and writing the merged one back. Keeping the merge itself pure is what
makes it directly unit-testable without a filesystem, a fetch, or a fixture file.
"""

from typing import Any

from billwatcher.scraper.parse_listing import ParsedListingBill


def merge_listing_into_bill(
    existing: dict[str, Any] | None,
    record: ParsedListingBill,
    *,
    chamber: str,
    language: str,
    source_url: str,
    observed_at: str,
) -> dict[str, Any]:
    """Fold one parsed listing row into a bill's accumulated record.

    Deliberately simple for this file-first pass: one current record per chamber, no field-level
    change history and no event fingerprints — the richer HANDOFF data model
    (`record_changes`, `bill_events`, `chamber_records`) is a database concern, and the database
    is explicitly out of scope for now. Re-running this against the same listing is idempotent:
    the same inputs produce the same merged dict, so a repeated parse writes nothing new through
    `FileStore`'s deterministic sidecar serialisation.
    """
    identifier = record.identifier
    base: dict[str, Any] = (
        _copy(existing)
        if existing is not None
        else {
            "identifier": {
                "raw": identifier.raw,
                "normalized": identifier.normalized,
                "number": identifier.number,
                "year": identifier.year,
                "originating_chamber": identifier.originating_chamber,
                "slug": identifier.slug,
            },
            "titles": {},
            "chambers": {},
            "documents": [],
            "first_seen_at": observed_at,
        }
    )
    # Listings are parsed in an arbitrary order (`FileStore.iter_listings` sorts by storage key,
    # not by fetch time), so a bill seen in two listings can be merged with the more-recently
    # fetched one processed first. Taking the max keeps `last_seen_at` monotonic regardless of
    # processing order; a blind overwrite could otherwise move it backwards.
    base["last_seen_at"] = max(base.get("last_seen_at", observed_at), observed_at)
    base["titles"][f"raw_{language}"] = record.title

    dates: dict[str, list[dict[str, str | None]]] = {}
    for cell in record.dates:
        if cell.error:
            continue
        for span in cell.ranges:
            dates.setdefault(cell.event_type, []).append(
                {"start": span.start.isoformat(), "end": span.end.isoformat() if span.end else None}
            )
    base["chambers"][chamber] = {
        "status_raw": record.status_raw,
        "status_normalized": record.status_normalized,
        "presenter": record.presenter,
        "dates": dates,
        "source_url": source_url,
        "last_seen_at": observed_at,
    }

    existing_urls = {doc["url"] for doc in base["documents"]}
    for url in record.document_urls:
        if url in existing_urls:
            continue
        base["documents"].append({"url": url, "chamber": chamber, "first_seen_at": observed_at})
        existing_urls.add(url)
    return base


def _copy(record: dict[str, Any]) -> dict[str, Any]:
    """A defensive deep-enough copy: nested dicts/lists are mutated, the caller's is not."""
    return {
        "identifier": dict(record["identifier"]),
        "titles": dict(record.get("titles", {})),
        "chambers": {k: dict(v) for k, v in record.get("chambers", {}).items()},
        "documents": [dict(doc) for doc in record.get("documents", [])],
        "first_seen_at": record.get("first_seen_at"),
        "last_seen_at": record.get("last_seen_at"),
    }
