"""Pure merge logic for one bill's file-first record.

No I/O here — `billwatcher.download.listings.parse_listings` owns reading the previous record
through `PipelineStore` and writing the merged one back. Keeping the merge itself pure is what
makes it directly unit-testable without a filesystem, a fetch, or a fixture file.
"""

from typing import Any

from billwatcher.download.parse_listing import ParsedListingBill


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

    One bill is merged from up to **four** listings: two chambers × two languages (ADR-040). Which
    fields that affects is the whole of the language handling here. A title, a raw status phrase and
    a listing URL are written in one language and are kept per language, so the English crawl adds
    to the record rather than overwriting the Malay one. A date, a presenter's name and a normalized
    status are the same fact whichever page published it, and stay single-valued.
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
    base["chambers"][chamber] = _merge_chamber(
        base["chambers"].get(chamber),
        record,
        language=language,
        source_url=source_url,
        observed_at=observed_at,
    )
    _merge_documents(
        base["documents"], record, chamber=chamber, language=language, observed_at=observed_at
    )
    return base


def _merge_chamber(
    previous: dict[str, Any] | None,
    record: ParsedListingBill,
    *,
    language: str,
    source_url: str,
    observed_at: str,
) -> dict[str, Any]:
    """One chamber's current record, folding in what this language's listing published."""
    prior: dict[str, Any] = previous or {}
    dates: dict[str, list[dict[str, str | None]]] = {}
    for cell in record.dates:
        if cell.error:
            continue
        for span in cell.ranges:
            dates.setdefault(cell.event_type, []).append(
                {"start": span.start.isoformat(), "end": span.end.isoformat() if span.end else None}
            )
    statuses_raw = dict(prior.get("statuses_raw") or {})
    statuses_raw[language] = record.status_raw
    source_urls = dict(prior.get("source_urls") or {})
    source_urls[language] = source_url
    return {
        # The phrase, per language: `Lulus` and `Passed` are one outcome published twice, and the
        # raw phrase is retained for both because it is what the source actually says (A9).
        "statuses_raw": statuses_raw,
        # `unknown` is what an unmapped phrase normalizes to. One language naming a phrase the
        # vocabulary does not have must not erase what the other language already established.
        "status_normalized": (
            prior.get("status_normalized", "unknown")
            if record.status_normalized == "unknown"
            else record.status_normalized
        ),
        "presenter": record.presenter or prior.get("presenter"),
        # Both languages publish the same dates, but only where both pages carry the detail rows.
        # A page that yielded none says nothing about the bill; it must not empty what we have.
        "dates": dates or prior.get("dates") or {},
        "source_urls": source_urls,
        "last_seen_at": max(prior.get("last_seen_at", observed_at), observed_at),
    }


def _merge_documents(
    documents: list[dict[str, Any]],
    record: ParsedListingBill,
    *,
    chamber: str,
    language: str,
    observed_at: str,
) -> None:
    """Queue this row's document URLs, recording which languages' listings named each one.

    `languages` accumulates rather than overwrites, and that is the point: the language of a
    document decides the language of its reading, and so a permanent component of its Expression
    IRI (ADR-024). One entry is the answer. Two means Parliament publishes the same file on pages
    of both languages, which is not evidence for either — so the record says so instead of letting
    whichever listing was parsed last decide.
    """
    by_url = {doc["url"]: doc for doc in documents if doc.get("url")}
    for url in record.document_urls:
        entry = by_url.get(url)
        if entry is None:
            entry = {
                "url": url,
                "chamber": chamber,
                "languages": [language],
                "first_seen_at": observed_at,
            }
            documents.append(entry)
            by_url[url] = entry
            continue
        languages = [value for value in entry.get("languages") or [] if isinstance(value, str)]
        if language not in languages:
            languages.append(language)
        entry["languages"] = sorted(languages)


def _copy(record: dict[str, Any]) -> dict[str, Any]:
    """A defensive deep-enough copy: nested dicts/lists are mutated, the caller's is not."""
    return {
        "identifier": dict(record["identifier"]),
        "titles": dict(record.get("titles", {})),
        "chambers": {
            chamber: _copy_chamber(value)
            for chamber, value in (record.get("chambers") or {}).items()
        },
        "documents": [_copy_document(doc) for doc in record.get("documents", [])],
        "first_seen_at": record.get("first_seen_at"),
        "last_seen_at": record.get("last_seen_at"),
    }


def _copy_chamber(record: dict[str, Any]) -> dict[str, Any]:
    copied = dict(record)
    for key in ("statuses_raw", "source_urls"):
        if isinstance(copied.get(key), dict):
            copied[key] = dict(copied[key])
    if isinstance(copied.get("dates"), dict):
        copied["dates"] = {
            event: [dict(span) for span in spans] for event, spans in copied["dates"].items()
        }
    return copied


def _copy_document(document: dict[str, Any]) -> dict[str, Any]:
    copied = dict(document)
    if isinstance(copied.get("languages"), list):
        copied["languages"] = list(copied["languages"])
    return copied
