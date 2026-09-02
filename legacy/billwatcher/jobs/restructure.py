"""Build structural readings from stored bytes at the current parser versions (HANDOFF 26.3).

Offline and replayable: it re-reads blobs the crawler already stored, so a structure-parser fix
rebuilds exactly the affected rows without contacting Parliament. Additive, like every other
backfill here — an older reading is demoted, never deleted.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.legislation.layout import EXTRACTOR_NAME
from billwatcher.legislation.persistence import (
    UNPUBLISHABLE,
    evaluate_structure_health,
    persist_structure,
)
from billwatcher.models import BackfillJob, DocumentStructure, DocumentVersion
from billwatcher.storage.blobs import BlobStore
from billwatcher.version import LAYOUT_EXTRACTOR_VERSION, STRUCTURE_VERSION


def run_restructure(
    session: Session,
    *,
    blob_store: BlobStore,
    dry_run: bool = True,
    limit: int = 100,
) -> BackfillJob:
    job = BackfillJob(
        kind="restructure",
        to_version=f"{LAYOUT_EXTRACTOR_VERSION}/{STRUCTURE_VERSION}",
        filter_json={"limit": limit, "current_versions_only": True},
        dry_run=dry_run,
        state="running",
        started_at=datetime.now(UTC),
    )
    session.add(job)
    session.flush()

    already = select(DocumentStructure.document_version_id).where(
        DocumentStructure.extractor_name == EXTRACTOR_NAME,
        DocumentStructure.extractor_version == LAYOUT_EXTRACTOR_VERSION,
        DocumentStructure.structure_version == STRUCTURE_VERSION,
    )
    versions = session.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.is_current.is_(True),
            # A quarantined version is kept for the record and is never read for structure.
            DocumentVersion.validation_status == "accepted",
            DocumentVersion.id.not_in(already),
        )
        .order_by(DocumentVersion.retrieved_at)
        .limit(limit)
    ).all()

    counts = {"eligible": len(versions), "processed": 0, "failed": 0}
    by_status: dict[str, int] = {}
    if not dry_run:
        for version in versions:
            # Each document is read inside its own savepoint. Without one, a single document that
            # raises mid-write — a constraint violation, an unreadable blob — leaves the
            # transaction aborted on PostgreSQL, and every remaining document in the batch fails
            # with it. One bad document must cost one document.
            try:
                with session.begin_nested():
                    structure = persist_structure(session, version=version, blob_store=blob_store)
                    status = structure.gate_status
                by_status[status] = by_status.get(status, 0) + 1
                counts["processed"] += 1
            except Exception:
                counts["failed"] += 1
        evaluate_structure_health(session)

    counts.update({f"gate_{status}": total for status, total in sorted(by_status.items())})
    counts["gate_blocked"] = sum(
        total for status, total in by_status.items() if status in UNPUBLISHABLE
    )
    job.counts = counts
    job.state = "succeeded" if counts["failed"] == 0 else "failed"
    job.finished_at = datetime.now(UTC)
    return job
