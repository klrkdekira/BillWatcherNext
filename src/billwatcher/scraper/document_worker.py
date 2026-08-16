import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import (
    Anomaly,
    Document,
    DocumentVersion,
    FetchAttempt,
    PresenceObservation,
)
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.queue import fail_item, finish_item, lease_next
from billwatcher.scraper.service import (
    persist_current_extraction,
    persist_document_observation,
)
from billwatcher.scraper.versioning import DownloadObservation, VersionAction
from billwatcher.storage.blobs import BlobStore


def process_one_document(
    session: Session,
    *,
    fetcher: Fetcher,
    blob_store: BlobStore,
    run_id: str,
    owner: str,
    now: datetime | None = None,
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
        if decision.action in {VersionAction.CREATED, VersionAction.ROLLBACK}:
            current = session.get(DocumentVersion, document.current_version_id)
            if current is None:
                raise RuntimeError("accepted version was not promoted")
            persist_current_extraction(session, version=current, blob_store=blob_store)
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
