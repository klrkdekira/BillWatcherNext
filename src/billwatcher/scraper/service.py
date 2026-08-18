from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import (
    Anomaly,
    Blob,
    Document,
    DocumentExtraction,
    DocumentRelation,
    DocumentVersion,
)
from billwatcher.scraper.versioning import (
    DownloadObservation,
    KnownVersion,
    VersionAction,
    VersionDecision,
    decide_document_version,
)
from billwatcher.storage.blobs import BlobStore


def persist_document_observation(
    session: Session,
    *,
    document: Document,
    observation: DownloadObservation,
    blob_store: BlobStore,
    run_id: str,
    fetch_attempt_id: str,
    final_url: str,
    etag: str | None = None,
    last_modified: str | None = None,
) -> VersionDecision:
    """Apply the HANDOFF 9.3 state machine inside the caller's transaction."""
    rows = session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version_no)
    ).all()
    known = [KnownVersion(row.version_no, row.content_sha256, row.is_current) for row in rows]
    decision = decide_document_version(observation, known)
    current = next((row for row in rows if row.is_current), None)
    document.last_checked_at = observation.checked_at

    if decision.action == VersionAction.NOT_MODIFIED:
        if current is not None:
            current.last_verified_at = observation.checked_at
        return decision
    if decision.action == VersionAction.VERIFIED:
        if current is None:
            raise RuntimeError("verified bytes require a current version")
        current.last_verified_at = observation.checked_at
        current.etag = etag or current.etag
        current.last_modified = last_modified or current.last_modified
        return decision
    if observation.body is None or decision.content_sha256 is None:
        raise RuntimeError("new version decision requires response bytes")

    stored = blob_store.put(observation.body, compress=False)
    blob = session.get(Blob, stored.sha256)
    if blob is None:
        blob = Blob(
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            media_type=observation.media_type_declared or "application/octet-stream",
            storage_path=str(stored.path),
            compression=stored.compression,
            ref_count=0,
        )
        session.add(blob)
    blob.ref_count += 1

    accepted = decision.action in {VersionAction.CREATED, VersionAction.ROLLBACK}
    if accepted and current is not None:
        current.is_current = False
        current.superseded_at = observation.checked_at

    version = DocumentVersion(
        document_id=document.id,
        version_no=decision.next_version_no or 1,
        content_sha256=decision.content_sha256,
        blob_sha256=stored.sha256,
        byte_size=stored.byte_size,
        media_type_declared=observation.media_type_declared,
        media_type_detected="application/pdf" if observation.body.startswith(b"%PDF-") else None,
        etag=etag,
        last_modified=last_modified,
        http_status=observation.status_code,
        final_url=final_url,
        retrieved_at=observation.checked_at,
        last_verified_at=observation.checked_at,
        run_id=run_id,
        fetch_attempt_id=fetch_attempt_id,
        supersedes_version_id=current.id if accepted and current is not None else None,
        is_current=accepted,
        change_kind="initial" if current is None and accepted else "content_changed",
        validation_status="accepted" if accepted else "quarantined",
        validation_error=decision.validation_error,
    )
    session.add(version)
    session.flush()
    if accepted:
        document.current_version_id = version.id
        document.last_changed_at = observation.checked_at

    if accepted:
        _propose_reissue_relations(session, document=document, blob_sha256=stored.sha256)

    if decision.action == VersionAction.ROLLBACK:
        _add_anomaly(
            session,
            kind="document_rollback",
            severity="warn",
            document=document,
            now=observation.checked_at,
            detail={
                "new_version": version.version_no,
                "matches_version": decision.matched_version_no,
            },
        )
    elif decision.action == VersionAction.QUARANTINED:
        _add_anomaly(
            session,
            kind="document_quarantined",
            severity="critical",
            document=document,
            now=observation.checked_at,
            detail={"version": version.version_no, "error": decision.validation_error},
        )
    return decision


def _add_anomaly(
    session: Session,
    *,
    kind: str,
    severity: str,
    document: Document,
    now: datetime,
    detail: dict[str, object],
) -> None:
    existing = session.scalar(
        select(Anomaly).where(
            Anomaly.kind == kind,
            Anomaly.entity_type == "document",
            Anomaly.entity_id == document.id,
            Anomaly.resolved_at.is_(None),
        )
    )
    if existing is not None:
        existing.last_seen_at = now
        existing.occurrence_count += 1
        existing.detail_json = detail
        return
    session.add(
        Anomaly(
            kind=kind,
            severity=severity,
            entity_type="document",
            entity_id=document.id,
            url=document.canonical_source_url,
            detail_json=detail,
            first_seen_at=now.astimezone(UTC),
            last_seen_at=now.astimezone(UTC),
        )
    )


def blob_path_is_inside_root(path: str, root: Path) -> bool:
    """Used by storage verification before reading a path recorded in the database."""
    try:
        Path(path).resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def persist_current_extraction(
    session: Session,
    *,
    version: DocumentVersion,
    blob_store: BlobStore,
) -> "DocumentExtraction":
    """Create an additive extraction row and rebuild page-level search projections."""
    from billwatcher.scraper.parse_document import extract_pdf
    from billwatcher.search.indexer import index_document_extraction
    from billwatcher.version import EXTRACTOR_VERSION

    existing = session.scalar(
        select(DocumentExtraction).where(
            DocumentExtraction.document_version_id == version.id,
            DocumentExtraction.extractor_name == "pypdf",
            DocumentExtraction.extractor_version == EXTRACTOR_VERSION,
            DocumentExtraction.mode == "native",
        )
    )
    if existing is not None:
        return existing
    blob = session.get(Blob, version.blob_sha256)
    if blob is None:
        raise ValueError("document version blob row is missing")
    content = blob_store.get(blob.sha256, compression=blob.compression)
    result = extract_pdf(content)
    for older in session.scalars(
        select(DocumentExtraction).where(
            DocumentExtraction.document_version_id == version.id,
            DocumentExtraction.is_current.is_(True),
        )
    ):
        older.is_current = False
    extraction = DocumentExtraction(
        document_version_id=version.id,
        extractor_name=result.extractor_name,
        extractor_version=result.extractor_version,
        pipeline_version=result.extractor_version,
        mode=result.mode,
        status=result.status,
        error=result.error,
        extracted_text=result.text,
        text_sha256=result.text_sha256,
        page_count=result.page_count,
        char_count=result.char_count,
        is_current=True,
        duration_ms=result.duration_ms,
    )
    session.add(extraction)
    version.page_count = result.page_count
    session.flush()
    if result.status == "succeeded":
        index_document_extraction(session, document_version_id=version.id, pages=result.pages)
    return extraction


def _propose_reissue_relations(session: Session, *, document: Document, blob_sha256: str) -> None:
    """Handle the one unambiguous HANDOFF 9.2 case: identical bytes served at a new URL.

    Documents are never auto-merged. A relation is *proposed* and an anomaly asks a human to
    confirm it; broader revision heuristics wait on assumption A11 (HANDOFF 25.3).
    """
    siblings = session.scalars(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentVersion.blob_sha256 == blob_sha256,
            DocumentVersion.document_id != document.id,
            DocumentVersion.validation_status == "accepted",
        )
    ).all()
    for sibling in siblings:
        existing = session.scalar(
            select(DocumentRelation).where(
                DocumentRelation.from_document_id == document.id,
                DocumentRelation.to_document_id == sibling.document_id,
                DocumentRelation.relation == "reissue_of",
            )
        )
        if existing is not None:
            continue
        session.add(
            DocumentRelation(
                from_document_id=document.id,
                to_document_id=sibling.document_id,
                relation="reissue_of",
                confidence=0.5,
                decided_by="heuristic",
                created_at=document.last_checked_at,
                note="Identical stored bytes were already served at another canonical URL.",
            )
        )
        _add_anomaly(
            session,
            kind="document_relation_proposed",
            severity="warn",
            document=document,
            now=document.last_checked_at,
            detail={
                "relation": "reissue_of",
                "to_document_id": sibling.document_id,
                "shared_blob": blob_sha256,
            },
        )
