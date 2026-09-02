import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import (
    Anomaly,
    Bill,
    BillDocument,
    Blob,
    Document,
    DocumentVersion,
    FetchAttempt,
    PresenceObservation,
    ScrapeRun,
)
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.queue import fail_item, finish_item, lease_next
from billwatcher.scraper.service import (
    evaluate_extraction_health,
    persist_current_extraction,
    persist_document_observation,
)
from billwatcher.scraper.versioning import DownloadObservation, VersionAction
from billwatcher.storage.audit_tree import AuditTree
from billwatcher.storage.blobs import BlobStore
from billwatcher.version import EXTRACTOR_VERSION


def build_document_sidecar(
    *,
    document: Document,
    version: DocumentVersion,
    bill: Bill,
    chambers: list[str],
    listing_url: str | None,
    step: str,
    run_id: str,
) -> dict[str, Any]:
    """The HANDOFF 27.3 sidecar contract for one document version, one bill link at a time.

    A document linked from two bills gets one sidecar per bill directory (legibility over
    dedup, HANDOFF 27.2); the `database.blob_sha256` field is what lets an auditor see two such
    sidecars are the same bytes without needing the database.
    """
    parsed = urlparse(document.canonical_source_url)
    upstream_filename = parsed.path.rsplit("/", 1)[-1] or None
    return {
        "sha256": version.content_sha256,
        "byte_size": version.byte_size,
        "media_type_declared": version.media_type_declared,
        "media_type_detected": version.media_type_detected,
        "source": {
            "publisher": "Parlimen Malaysia",
            "host": parsed.netloc,
            "url": document.source_url_raw,
            "final_url": version.final_url,
            "upstream_filename": upstream_filename,
            "listing_url": listing_url,
        },
        "http": {
            "status": version.http_status,
            "etag": version.etag,
            "last_modified": version.last_modified,
        },
        "retrieved_at": version.retrieved_at.isoformat(),
        # Known dead fields today (TODO 2.4, HANDOFF 26.7): stated as the record states them,
        # never guessed. A rebuild backfills every sidecar once the classification sweep lands.
        "language": document.language,
        "document_kind": document.document_kind,
        "bill": {
            "identifier_raw": bill.identifier_raw,
            "identifier_normalized": bill.identifier_normalized,
            "slug": bill.slug,
        },
        "chambers": chambers,
        "version_no": version.version_no,
        "is_current": version.is_current,
        "validation_status": version.validation_status,
        "validation_error": version.validation_error,
        "produced_by": {"step": step, "run_id": run_id},
        "database": {
            "document_id": document.id,
            "document_version_id": version.id,
            "blob_sha256": version.blob_sha256,
        },
    }


def write_version_to_audit_tree(
    session: Session,
    *,
    audit_tree: AuditTree,
    document: Document,
    version: DocumentVersion,
    blob_store: BlobStore,
    step: str,
) -> list[Path]:
    """Materialise one document version into the tree, once per bill it is linked from.

    A document with no bill link yet is skipped rather than failed: that is only possible
    before ingestion has run at all, since HANDOFF 8's `bill_documents` link is written before a
    document is ever queued.
    """
    links = session.execute(
        select(BillDocument.chamber, Bill)
        .join(Bill, Bill.id == BillDocument.bill_id)
        .where(BillDocument.document_id == document.id)
    ).all()
    if not links:
        return []
    bills_by_slug: dict[str, Bill] = {}
    chambers_by_slug: dict[str, set[str]] = {}
    listing_url_by_slug: dict[str, str | None] = {}
    for chamber, bill in links:
        bills_by_slug[bill.slug] = bill
        if chamber:
            chambers_by_slug.setdefault(bill.slug, set()).add(chamber)
        listing_url_by_slug.setdefault(bill.slug, None)
    blob = session.get(Blob, version.blob_sha256)
    if blob is None:
        raise ValueError("document version blob row is missing")
    pdf_bytes = blob_store.get(blob.sha256, compression=blob.compression)
    written: list[Path] = []
    for slug, bill in bills_by_slug.items():
        sidecar = build_document_sidecar(
            document=document,
            version=version,
            bill=bill,
            chambers=sorted(chambers_by_slug.get(slug, set())),
            listing_url=listing_url_by_slug.get(slug),
            step=step,
            run_id=version.run_id,
        )
        result = audit_tree.write_document_version(
            bill_slug=slug,
            document_id=document.id,
            version_no=version.version_no,
            pdf_bytes=pdf_bytes,
            sidecar=sidecar,
        )
        written.append(result.directory)
    return written


def process_one_document(
    session: Session,
    *,
    fetcher: Fetcher,
    blob_store: BlobStore,
    run_id: str,
    owner: str,
    now: datetime | None = None,
    audit_tree: AuditTree | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    item = lease_next(session, owner=owner, now=now)
    if item is None:
        return False
    if item.target_kind != "document" or item.document_id is None:
        fail_item(session, item, owner=owner, now=now, error="invalid document queue item")
        return True
    document = session.get(Document, item.document_id)
    if document is None:
        fail_item(session, item, owner=owner, now=now, error="document row is missing")
        return True
    try:
        result = fetcher.get(item.url, etag=item.etag, last_modified=item.last_modified)
        attempt = FetchAttempt(
            run_id=run_id,
            target_kind="document",
            url=item.url,
            method="GET",
            attempted_at=result.requested_at,
            duration_ms=result.duration_ms,
            status_code=result.status_code,
            bytes_received=len(result.body),
            conditional=bool(item.etag or item.last_modified),
            not_modified=result.not_modified,
        )
        session.add(attempt)
        session.flush()
        if result.status_code in {404, 410}:
            _record_document_absence(session, document, run_id, result.requested_at)
            finish_item(item, owner=owner)
            return True
        if result.status_code in {408, 429} or result.status_code >= 500:
            fail_item(
                session,
                item,
                owner=owner,
                now=result.requested_at,
                error=f"HTTP {result.status_code}",
            )
            return True
        if result.status_code not in {200, 304}:
            finish_item(item, owner=owner)
            return True

        media_type = result.headers.get("content-type")
        body = None if result.status_code == 304 else result.body
        decision = persist_document_observation(
            session,
            document=document,
            observation=DownloadObservation(
                result.status_code, result.requested_at, body, media_type
            ),
            blob_store=blob_store,
            run_id=run_id,
            fetch_attempt_id=attempt.id,
            final_url=result.final_url,
            etag=result.headers.get("etag"),
            last_modified=result.headers.get("last-modified"),
        )
        if result.body:
            attempt.blob_sha256 = hashlib.sha256(result.body).hexdigest()
        item.etag = result.headers.get("etag") or item.etag
        item.last_modified = result.headers.get("last-modified") or item.last_modified
        if audit_tree is not None and decision.next_version_no is not None:
            # Covers CREATED, ROLLBACK, and QUARANTINED alike: a quarantined download is still a
            # raw bytes-on-the-wire fact worth an auditable record, tagged by its
            # `validation_status` in the sidecar rather than silently absent from the tree.
            downloaded_version = session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.version_no == decision.next_version_no,
                )
            )
            if downloaded_version is not None:
                write_version_to_audit_tree(
                    session,
                    audit_tree=audit_tree,
                    document=document,
                    version=downloaded_version,
                    blob_store=blob_store,
                    step="fetch-documents",
                )
        if decision.action in {VersionAction.CREATED, VersionAction.ROLLBACK}:
            current = session.get(DocumentVersion, document.current_version_id)
            if current is None:
                raise RuntimeError("accepted version was not promoted")
            persist_current_extraction(session, version=current, blob_store=blob_store)
            evaluate_extraction_health(session, now=now)
        document.absent_streak = 0
        finish_item(item, owner=owner)
    except Exception as error:
        fail_item(session, item, owner=owner, now=now, error=str(error))
    return True


def _record_document_absence(
    session: Session, document: Document, run_id: str, observed_at: datetime
) -> None:
    document.absent_streak += 1
    document.last_absent_at = observed_at
    session.add(
        PresenceObservation(
            run_id=run_id,
            entity_type="document",
            entity_id=document.id,
            listing_url=document.canonical_source_url,
            present=False,
            observed_at=observed_at,
        )
    )
    if document.absent_streak < 3:
        return
    existing = session.scalar(
        select(Anomaly).where(
            Anomaly.kind == "document_gone",
            Anomaly.entity_type == "document",
            Anomaly.entity_id == document.id,
            Anomaly.resolved_at.is_(None),
        )
    )
    if existing:
        existing.last_seen_at = observed_at
        existing.occurrence_count += 1
        existing.detail_json = {"absent_streak": document.absent_streak}
    else:
        session.add(
            Anomaly(
                kind="document_gone",
                severity="warn",
                entity_type="document",
                entity_id=document.id,
                url=document.canonical_source_url,
                detail_json={"absent_streak": document.absent_streak},
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            )
        )


def open_document_run(session: Session, *, trigger: str = "schedule") -> ScrapeRun:
    """Start a run row for a document-download pass.

    `fetch_attempts.run_id` is a foreign key, so document downloads need a real run to be
    attributable to, exactly like a listing crawl (HANDOFF 8).
    """
    run = ScrapeRun(
        mode="incremental",
        trigger=trigger,
        started_at=datetime.now(UTC),
        state="running",
        policy_snapshot={"stage": "documents", "extractor_version": EXTRACTOR_VERSION},
        publish_decision="published",
        publish_reason="document downloads publish per version, not per run",
    )
    session.add(run)
    session.flush()
    return run


def close_document_run(session: Session, run: ScrapeRun, *, processed: int) -> ScrapeRun:
    run.fetched = processed
    run.state = "succeeded"
    run.ended_at = datetime.now(UTC)
    session.flush()
    return run


def run_fetch_documents_step(
    session: Session,
    *,
    fetcher: Fetcher,
    blob_store: BlobStore,
    audit_tree: AuditTree,
    trigger: str = "manual",
    limit: int = 5000,
) -> dict[str, Any]:
    """Step S3 (HANDOFF 27.1): drain the document fetch queue.

    Each accepted or quarantined download is written to the audit tree as it happens
    (`process_one_document`'s `audit_tree` argument); this wrapper is what makes the whole drain
    one Make target with one manifest, rather than an open-ended loop the operator has to size
    by hand. `limit` is a backstop against an unexpectedly large queue in one process, not a
    live-crawl budget — the queue drain stops on its own once nothing is left to lease, and the
    per-request politeness delay already lives in the fetcher (HANDOFF 25.6 finding 11).
    """
    run = open_document_run(session, trigger=trigger)
    session.commit()
    processed = 0
    for _ in range(max(1, limit)):
        owner = f"fetch-documents-{datetime.now(UTC).timestamp()}"
        if not process_one_document(
            session,
            fetcher=fetcher,
            blob_store=blob_store,
            run_id=run.id,
            owner=owner,
            audit_tree=audit_tree,
        ):
            break
        processed += 1
        session.commit()
    close_document_run(session, run, processed=processed)
    session.commit()
    manifest = {
        "run_id": run.id,
        "trigger": trigger,
        "considered": processed,
        "queue_drained": processed < limit,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    audit_tree.write_manifest(step="fetch-documents", run_id=run.id, payload=manifest)
    return manifest
