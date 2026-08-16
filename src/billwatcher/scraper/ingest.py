import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import (
    Anomaly,
    Bill,
    BillDocument,
    BillEvent,
    Blob,
    ChamberRecord,
    Document,
    FetchQueueItem,
    SourceSnapshot,
)
from billwatcher.scraper.changes import update_tracked_field
from billwatcher.scraper.normalize import canonicalize_url, normalize_text
from billwatcher.scraper.parse_listing import ParsedListing, parse_listing
from billwatcher.search.indexer import rebuild_bill_metadata_unit
from billwatcher.storage.blobs import BlobStore
from billwatcher.version import PARSER_VERSION


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
            )
            if changed:
                bill.last_changed_at = checked_at
                updated += 1
                changes += 1

        chamber_record = session.scalar(
            select(ChamberRecord).where(
                ChamberRecord.bill_id == bill.id,
                ChamberRecord.chamber == chamber,
            )
        )
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
        else:
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
    listing = parse_listing(body.decode("utf-8"), source_url=snapshot.final_url)
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
    stable = "|".join(
        (
            bill.id,
            chamber,
            "status_observed",
            "",
            "",
            "0",
            normalize_text("status").casefold(),
            normalize_text(status_raw).casefold(),
        )
    )
    fingerprint = hashlib.sha256(stable.encode()).hexdigest()
    if session.scalar(select(BillEvent.id).where(BillEvent.fingerprint == fingerprint)):
        return False
    session.add(
        BillEvent(
            bill_id=bill.id,
            chamber=chamber,
            event_type="status_observed",
            sequence=0,
            source_label="Status",
            source_value=status_raw,
            source_url=source_url,
            snapshot_id=snapshot_id,
            run_id=run_id,
            parser_version=PARSER_VERSION,
            observed_at=observed_at,
            fingerprint=fingerprint,
        )
    )
    return True


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
    anomaly = session.scalar(
        select(Anomaly).where(
            Anomaly.kind == kind,
            Anomaly.entity_type == entity_type,
            Anomaly.entity_id == entity_id,
            Anomaly.resolved_at.is_(None),
        )
    )
    if anomaly:
        anomaly.last_seen_at = now
        anomaly.occurrence_count += 1
        anomaly.detail_json = detail
    else:
        session.add(
            Anomaly(
                kind=kind,
                severity=severity,
                entity_type=entity_type,
                entity_id=entity_id,
                url=url,
                detail_json=detail,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
