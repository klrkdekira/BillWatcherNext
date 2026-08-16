from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import BackfillJob, DocumentExtraction, DocumentVersion
from billwatcher.scraper.service import persist_current_extraction
from billwatcher.storage.blobs import BlobStore
from billwatcher.version import EXTRACTOR_VERSION


def run_reextract(
    session: Session,
    *,
    blob_store: BlobStore,
    dry_run: bool = True,
    limit: int = 100,
) -> BackfillJob:
    job = BackfillJob(
        kind="reextract",
        to_version=EXTRACTOR_VERSION,
        filter_json={"limit": limit, "current_versions_only": True},
        dry_run=dry_run,
        state="running",
        started_at=datetime.now(UTC),
    )
    session.add(job)
    session.flush()
    current_ids = select(DocumentExtraction.document_version_id).where(
        DocumentExtraction.extractor_name == "pypdf",
        DocumentExtraction.extractor_version == EXTRACTOR_VERSION,
        DocumentExtraction.mode == "native",
    )
    versions = session.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.is_current.is_(True),
            DocumentVersion.validation_status == "accepted",
            DocumentVersion.id.not_in(current_ids),
        )
        .order_by(DocumentVersion.retrieved_at)
        .limit(limit)
    ).all()
    failed = 0
    if not dry_run:
        for version in versions:
            try:
                persist_current_extraction(session, version=version, blob_store=blob_store)
            except Exception:
                failed += 1
    job.counts = {
        "eligible": len(versions),
        "processed": 0 if dry_run else len(versions) - failed,
        "failed": failed,
    }
    job.state = "succeeded" if failed == 0 else "failed"
    job.finished_at = datetime.now(UTC)
    return job
