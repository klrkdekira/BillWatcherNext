import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.domain.vocabulary import EVENT_TYPE_TO_CHAMBER_FIELD
from billwatcher.models import (
    Bill,
    BillDocument,
    BillEvent,
    Blob,
    ChamberRecord,
    Document,
    FetchQueueItem,
    SourceSnapshot,
)
from billwatcher.operations import record_anomaly
from billwatcher.scraper.changes import update_tracked_field
from billwatcher.scraper.normalize import canonicalize_url, normalize_text, same_title
from billwatcher.scraper.parse_archive import parse_stored_listing
from billwatcher.scraper.parse_listing import (
    ParsedDateCell,
    ParsedListing,
)
from billwatcher.search.indexer import rebuild_bill_metadata_unit
from billwatcher.storage.blobs import BlobStore
from billwatcher.version import PARSER_VERSION

# Anomaly detail is bounded (HANDOFF 8); a broken page must not write an unbounded blob.
MAX_ISSUE_ROWS = 20
MAX_ISSUE_VALUES = 12


@dataclass(frozen=True, slots=True)
class IngestCounts:
    bills_inserted: int = 0
    bills_updated: int = 0
    chamber_records_inserted: int = 0
    changes: int = 0
    events_inserted: int = 0
    documents_queued: int = 0


def ingest_listing(
    session: Session,
    listing: ParsedListing,
    *,
    chamber: str,
    language: str,
    source_url: str,
    snapshot_id: str,
    run_id: str,
    checked_at: datetime,
    change_source: str = "scrape",
) -> IngestCounts:
    inserted = updated = chamber_inserted = changes = events = queued = 0
    _record_parse_issues(
        session,
        listing,
        source_url=source_url,
        snapshot_id=snapshot_id,
        observed_at=checked_at,
    )
    for parsed in listing.records:
        bill = session.scalar(
            select(Bill).where(Bill.identifier_normalized == parsed.identifier.normalized)
        )
        if bill is None:
            bill = Bill(
                identifier_raw=parsed.identifier.raw,
                identifier_normalized=parsed.identifier.normalized,
                number=parsed.identifier.number,
                year=parsed.identifier.year,
                originating_chamber=parsed.identifier.originating_chamber,
                slug=parsed.identifier.slug,
                title_bm=parsed.title if language == "ms" else None,
                title_en=parsed.title if language == "en" else None,
                identifier_scheme_version=1,
                first_seen_at=checked_at,
                last_seen_at=checked_at,
                last_checked_at=checked_at,
                last_changed_at=checked_at,
            )
            session.add(bill)
            session.flush()
            inserted += 1
        else:
            bill.last_seen_at = checked_at
            bill.last_checked_at = checked_at
            title_field = "title_bm" if language == "ms" else "title_en"
            changed = update_tracked_field(
                session,
                entity=bill,
                entity_type="bill",
                field_path=title_field,
                incoming=parsed.title,
                changed_at=checked_at,
                change_source=change_source,
                run_id=run_id,
                snapshot_id=snapshot_id,
                source_url=source_url,
                # One bill's title is published in several forms across the site, so a rewrite
                # is only a change when it is a different title (HANDOFF 10.1). And a title that
                # keeps changing back is two chambers disagreeing, not an edit history.
                equivalent=same_title,
                oscillation_is_conflict=True,
            )
            if changed:
                bill.last_changed_at = checked_at
                updated += 1
                changes += 1

        # HANDOFF 11.3 step 8: an English listing reconciles the title by normalized
        # identifier and nothing else. Its status and presenter are the same facts rendered in
        # another language, and letting them through would overwrite the published Malay text.
        authoritative = language == "ms"

        chamber_record = session.scalar(
            select(ChamberRecord).where(
                ChamberRecord.bill_id == bill.id,
                ChamberRecord.chamber == chamber,
            )
        )
        if chamber_record is None and not authoritative:
            rebuild_bill_metadata_unit(session, bill)
            continue
        if chamber_record is None:
            chamber_record = ChamberRecord(
                bill_id=bill.id,
                chamber=chamber,
                status_raw=parsed.status_raw,
                status_normalized=parsed.status_normalized,
                presenter_raw=parsed.presenter,
                source_url=source_url,
                source_snapshot_id=snapshot_id,
                first_seen_at=checked_at,
                last_seen_at=checked_at,
                last_checked_at=checked_at,
                last_changed_at=checked_at,
            )
            session.add(chamber_record)
            session.flush()
            chamber_inserted += 1
            newly_inserted = True
        elif not authoritative:
            newly_inserted = False
            chamber_record.last_seen_at = checked_at
            chamber_record.last_checked_at = checked_at
        else:
            newly_inserted = False
            chamber_record.last_seen_at = checked_at
            chamber_record.last_checked_at = checked_at
            chamber_record.source_snapshot_id = snapshot_id
            for field, incoming in (
                ("status_raw", parsed.status_raw),
                ("status_normalized", parsed.status_normalized),
                ("presenter_raw", parsed.presenter),
            ):
                if update_tracked_field(
                    session,
                    entity=chamber_record,
                    entity_type="chamber_record",
                    field_path=field,
                    incoming=incoming,
                    changed_at=checked_at,
                    change_source=change_source,
                    run_id=run_id,
                    snapshot_id=snapshot_id,
                    source_url=source_url,
                ):
                    chamber_record.last_changed_at = checked_at
                    changes += 1

        if not authoritative:
            rebuild_bill_metadata_unit(session, bill)
            for raw_url in parsed.document_urls:
                if _link_and_queue_document(
                    session,
                    bill=bill,
                    chamber=chamber,
                    raw_url=raw_url,
                    listing_url=source_url,
                    observed_at=checked_at,
                ):
                    queued += 1
            continue

        if parsed.status_normalized == "unknown":
            _upsert_anomaly(
                session,
                "unmapped_status",
                "warn",
                "chamber_record",
                chamber_record.id,
                source_url,
                checked_at,
                {"status_raw": parsed.status_raw},
            )
        if _insert_status_event(
            session,
            bill=bill,
            chamber=chamber,
            status_raw=parsed.status_raw,
            source_url=source_url,
            snapshot_id=snapshot_id,
            run_id=run_id,
            observed_at=checked_at,
        ):
            events += 1
        dated_changes, dated_events = _apply_dated_columns(
            session,
            bill=bill,
            chamber_record=chamber_record,
            chamber=chamber,
            cells=parsed.dates,
            source_url=source_url,
            snapshot_id=snapshot_id,
            run_id=run_id,
            checked_at=checked_at,
            change_source=change_source,
            newly_inserted=newly_inserted,
        )
        changes += dated_changes
        events += dated_events
        rebuild_bill_metadata_unit(session, bill)
        for raw_url in parsed.document_urls:
            if _link_and_queue_document(
                session,
                bill=bill,
                chamber=chamber,
                raw_url=raw_url,
                listing_url=source_url,
                observed_at=checked_at,
            ):
                queued += 1
    return IngestCounts(inserted, updated, chamber_inserted, changes, events, queued)


def replay_snapshot(
    session: Session,
    snapshot: SourceSnapshot,
    *,
    blob_store: BlobStore,
    chamber: str,
    language: str,
    run_id: str,
) -> IngestCounts:
    if snapshot.blob_sha256 is None:
        raise ValueError("snapshot has no stored response body")
    blob = session.get(Blob, snapshot.blob_sha256)
    if blob is None:
        raise ValueError("snapshot blob row is missing")
    body = blob_store.get(blob.sha256, compression=blob.compression)
    listing = parse_stored_listing(
        body.decode("utf-8"), url=snapshot.url, source_url=snapshot.final_url
    )
    return ingest_listing(
        session,
        listing,
        chamber=chamber,
        language=language,
        source_url=snapshot.final_url,
        snapshot_id=snapshot.id,
        run_id=run_id,
        checked_at=snapshot.requested_at,
        change_source="replay",
    )


def event_fingerprint(
    *,
    bill_id: str,
    chamber: str,
    event_type: str,
    event_on: date | None,
    event_on_end: date | None,
    sequence: int,
    source_label: str,
    source_value: str,
) -> str:
    """The recipe documented in docs/data-model.md.

    Run, snapshot, and observation timestamps are excluded so replaying the same bytes at the
    same parser version produces the same fingerprints and therefore no duplicate events.
    """
    stable = "|".join(
        (
            bill_id,
            chamber,
            event_type,
            event_on.isoformat() if event_on else "",
            event_on_end.isoformat() if event_on_end else "",
            str(sequence),
            normalize_text(source_label).casefold(),
            normalize_text(source_value).casefold(),
        )
    )
    return hashlib.sha256(stable.encode()).hexdigest()


def _insert_event(
    session: Session,
    *,
    bill: Bill,
    chamber: str,
    event_type: str,
    source_label: str,
    source_value: str,
    source_url: str,
    snapshot_id: str,
    run_id: str,
    observed_at: datetime,
    event_on: date | None = None,
    event_on_end: date | None = None,
    sequence: int = 0,
) -> bool:
    fingerprint = event_fingerprint(
        bill_id=bill.id,
        chamber=chamber,
        event_type=event_type,
        event_on=event_on,
        event_on_end=event_on_end,
        sequence=sequence,
        source_label=source_label,
        source_value=source_value,
    )
    if session.scalar(select(BillEvent.id).where(BillEvent.fingerprint == fingerprint)):
        return False
    session.add(
        BillEvent(
            bill_id=bill.id,
            chamber=chamber,
            event_type=event_type,
            event_on=event_on,
            event_on_end=event_on_end,
            sequence=sequence,
            source_label=source_label,
            source_value=source_value,
            source_url=source_url,
            snapshot_id=snapshot_id,
            run_id=run_id,
            parser_version=PARSER_VERSION,
            observed_at=observed_at,
            fingerprint=fingerprint,
        )
    )
    return True


def _insert_status_event(
    session: Session,
    *,
    bill: Bill,
    chamber: str,
    status_raw: str,
    source_url: str,
    snapshot_id: str,
    run_id: str,
    observed_at: datetime,
) -> bool:
    return _insert_event(
        session,
        bill=bill,
        chamber=chamber,
        event_type="status_observed",
        source_label="Status",
        source_value=status_raw,
        source_url=source_url,
        snapshot_id=snapshot_id,
        run_id=run_id,
        observed_at=observed_at,
    )


def _apply_dated_columns(
    session: Session,
    *,
    bill: Bill,
    chamber_record: ChamberRecord,
    chamber: str,
    cells: Sequence[ParsedDateCell],
    source_url: str,
    snapshot_id: str,
    run_id: str,
    checked_at: datetime,
    change_source: str,
    newly_inserted: bool = False,
) -> tuple[int, int]:
    """Project dated listing columns onto events and the chamber-record shortcut columns.

    Events are the authoritative history: a cell holding a range keeps both ends, and a cell
    holding several dates produces several events with an incrementing sequence (HANDOFF 11.5).
    """
    changes = events = 0
    for cell in cells:
        if cell.error is not None:
            _upsert_anomaly(
                session,
                "unparseable_date",
                "warn",
                "chamber_record",
                chamber_record.id,
                source_url,
                checked_at,
                {"label": cell.label, "raw": cell.raw, "error": cell.error},
            )
            continue
        for sequence, span in enumerate(cell.ranges):
            if _insert_event(
                session,
                bill=bill,
                chamber=chamber,
                event_type=cell.event_type,
                source_label=cell.label,
                source_value=cell.raw,
                source_url=source_url,
                snapshot_id=snapshot_id,
                run_id=run_id,
                observed_at=checked_at,
                event_on=span.start,
                event_on_end=span.end,
                sequence=sequence,
            ):
                events += 1
        field = EVENT_TYPE_TO_CHAMBER_FIELD.get(cell.event_type)
        if field is None or not cell.ranges:
            continue
        if newly_inserted:
            # First observation of this chamber record: the dates are part of the insert, not a
            # change to something we previously held.
            setattr(chamber_record, field, cell.ranges[0].start)
            continue
        if update_tracked_field(
            session,
            entity=chamber_record,
            entity_type="chamber_record",
            field_path=field,
            incoming=cell.ranges[0].start,
            changed_at=checked_at,
            change_source=change_source,
            run_id=run_id,
            snapshot_id=snapshot_id,
            source_url=source_url,
        ):
            chamber_record.last_changed_at = checked_at
            changes += 1
    return changes, events


def _link_and_queue_document(
    session: Session,
    *,
    bill: Bill,
    chamber: str,
    raw_url: str,
    listing_url: str,
    observed_at: datetime,
) -> bool:
    canonical = canonicalize_url(raw_url)
    document = session.scalar(select(Document).where(Document.canonical_source_url == canonical))
    if document is None:
        document = Document(
            document_kind="unknown",
            language="unknown",
            canonical_source_url=canonical,
            source_url_raw=raw_url,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            last_checked_at=observed_at,
            last_changed_at=observed_at,
        )
        session.add(document)
        session.flush()
    else:
        document.last_seen_at = observed_at
    link = session.scalar(
        select(BillDocument).where(
            BillDocument.bill_id == bill.id,
            BillDocument.chamber == chamber,
            BillDocument.document_id == document.id,
            BillDocument.role == "listing_document",
        )
    )
    if link is None:
        session.add(
            BillDocument(
                bill_id=bill.id,
                document_id=document.id,
                chamber=chamber,
                role="listing_document",
                first_seen_at=observed_at,
                last_seen_at=observed_at,
                source_url=listing_url,
            )
        )
    else:
        link.last_seen_at = observed_at
    queue = session.scalar(
        select(FetchQueueItem).where(
            FetchQueueItem.target_kind == "document",
            FetchQueueItem.url == canonical,
        )
    )
    if queue is not None:
        return False
    session.add(FetchQueueItem(target_kind="document", url=canonical, document_id=document.id))
    return True


def _upsert_anomaly(
    session: Session,
    kind: str,
    severity: str,
    entity_type: str,
    entity_id: str,
    url: str,
    now: datetime,
    detail: dict[str, object],
) -> None:
    record_anomaly(
        session,
        kind=kind,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        url=url,
        detail=detail,
        now=now,
    )


def _record_parse_issues(
    session: Session,
    listing: ParsedListing,
    *,
    source_url: str,
    snapshot_id: str,
    observed_at: datetime,
) -> None:
    """Turn retained bad rows into anomalies so nothing disappears without a trace.

    These deduplicate on the **upstream document**, identified by its URL, rather than on the
    snapshot of it. Keying on the snapshot looked right and was not: a snapshot is a new row every
    run, so a permanent upstream defect — and there are several, see `docs/upstream.md` — would add
    one anomaly per crawl for ever and turn `/status` into a log. The document is not an entity we
    store, so it has no entity id; `record_anomaly` deduplicates those on the URL.
    """
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for issue in listing.issues:
        grouped.setdefault(_classify_issue(issue.reason), []).append(
            {
                "row": issue.row_number,
                "reason": issue.reason,
                "raw_identifier": issue.raw_identifier,
                "raw_values": list(issue.raw_values)[:MAX_ISSUE_VALUES],
            }
        )
    for (kind, severity), rows in grouped.items():
        record_anomaly(
            session,
            kind=kind,
            severity=severity,
            url=source_url,
            now=observed_at,
            detail={
                "count": len(rows),
                "rows": rows[:MAX_ISSUE_ROWS],
                "latest_snapshot_id": snapshot_id,
            },
        )


# Which anomaly a retained row maps to. `unmapped_detail_label` and `malformed_row` extend the
# HANDOFF 10.5 minimum set, which the handoff states as a minimum: the archive tree can fail in
# two ways a column-shaped listing cannot — a detail label we do not understand, and a node whose
# text does not match the grammar at all — and reporting either as an identifier problem would
# send an operator looking in the wrong place.
_ISSUE_KINDS: Final = (
    ("duplicate identifier", ("duplicate_identifier_conflict", "critical")),
    ("unmapped detail label", ("unmapped_detail_label", "warn")),
    ("unparseable bill identifier", ("unparseable_identifier", "warn")),
)


def _classify_issue(reason: str) -> tuple[str, str]:
    for prefix, kind in _ISSUE_KINDS:
        if reason.startswith(prefix):
            return kind
    # A row that could not be read as a row at all: no title, no status, or text that does not
    # match the shape the parser understands.
    return ("malformed_row", "warn")
