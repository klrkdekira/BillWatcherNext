"""A second, independently versioned markdown reading of stored PDFs via MinerU (HANDOFF 27.7).

Never contacts Parliament — it re-reads blobs the crawler already stored — but it does call the
configured MinerU endpoint over the network for each eligible document. Additive and file-based
only: nothing here writes to `document_extractions`, sidestepping the single-writer landmine
TODO 2.4 already documents (`persist_current_extraction` demotes every row for a version
regardless of extractor name), the same way Stage L1's structural reading avoids it (ADR-020).
Eligibility is decided by what is already on disk, not a database row, since the whole point of
this reading is to live as a local file artifact.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.mineru.client import PageBlockExtractor
from billwatcher.mineru.service import extract_document_markdown
from billwatcher.models import BackfillJob, Bill, BillDocument, Blob, Document, DocumentVersion
from billwatcher.storage.audit_tree import AuditTree
from billwatcher.storage.blobs import BlobStore
from billwatcher.version import MINERU_EXTRACTOR_VERSION

STEP = "mineru-extract"
EXTRACTOR_NAME = "mineru"
RAW_FILE = "document.md"


def _bill_links(session: Session, document_id: str) -> dict[str, tuple[Bill, set[str]]]:
    """Every bill a document is linked from, with the set of chambers it was found under."""
    result: dict[str, tuple[Bill, set[str]]] = {}
    for chamber, bill in session.execute(
        select(BillDocument.chamber, Bill)
        .join(Bill, Bill.id == BillDocument.bill_id)
        .where(BillDocument.document_id == document_id)
    ).all():
        entry_bill, chambers = result.get(bill.slug, (bill, set()))
        if chamber:
            chambers.add(chamber)
        result[bill.slug] = (entry_bill, chambers)
    return result


def _already_extracted(
    audit_tree: AuditTree, *, bill_slug: str, document_id: str, version_no: int
) -> bool:
    directory = audit_tree.extraction_dir(
        bill_slug=bill_slug,
        document_id=document_id,
        version_no=version_no,
        extractor_name=EXTRACTOR_NAME,
        extractor_version=MINERU_EXTRACTOR_VERSION,
    )
    return (directory / RAW_FILE).exists() and (directory / "metadata.json").exists()


def run_mineru_extract(
    session: Session,
    *,
    blob_store: BlobStore,
    audit_tree: AuditTree,
    extractor: PageBlockExtractor,
    render_dpi: int,
    mineru_base_url: str,
    dry_run: bool = True,
    limit: int = 50,
) -> BackfillJob:
    job = BackfillJob(
        kind="mineru_extract",
        to_version=MINERU_EXTRACTOR_VERSION,
        filter_json={"limit": limit, "current_versions_only": True, "render_dpi": render_dpi},
        dry_run=dry_run,
        state="running",
        started_at=datetime.now(UTC),
    )
    session.add(job)
    session.flush()

    eligible: list[tuple[DocumentVersion, dict[str, tuple[Bill, set[str]]]]] = []
    for version in session.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.is_current.is_(True),
            DocumentVersion.validation_status == "accepted",
        )
        .order_by(DocumentVersion.retrieved_at)
    ):
        links = _bill_links(session, version.document_id)
        if not links:
            continue
        first_slug = min(links)
        if _already_extracted(
            audit_tree,
            bill_slug=first_slug,
            document_id=version.document_id,
            version_no=version.version_no,
        ):
            continue
        eligible.append((version, links))
        if len(eligible) >= limit:
            break

    counts = {"eligible": len(eligible), "processed": 0, "empty": 0, "failed": 0}
    if not dry_run:
        for version, links in eligible:
            document = session.get(Document, version.document_id)
            blob = session.get(Blob, version.blob_sha256)
            if document is None or blob is None:
                counts["failed"] += 1
                continue
            content = blob_store.get(blob.sha256, compression=blob.compression)
            result = extract_document_markdown(content, extractor=extractor, dpi=render_dpi)
            if result.status == "failed":
                counts["failed"] += 1
                continue
            for slug, (bill, chambers) in links.items():
                sidecar = {
                    "extractor_name": result.extractor_name,
                    "extractor_version": result.extractor_version,
                    "mode": result.mode,
                    "status": result.status,
                    "error": result.error,
                    "model_name": result.model_name,
                    "mineru_base_url": mineru_base_url,
                    "render_dpi": render_dpi,
                    "page_count": result.page_count,
                    "char_count": result.char_count,
                    "content_sha256": result.markdown_sha256,
                    "duration_ms": result.duration_ms,
                    "bill": {
                        "identifier_raw": bill.identifier_raw,
                        "identifier_normalized": bill.identifier_normalized,
                        "slug": bill.slug,
                    },
                    "chambers": sorted(chambers),
                    "version_no": version.version_no,
                    "is_current": version.is_current,
                    "produced_by": {"step": STEP, "run_id": job.id},
                    "database": {
                        "document_id": document.id,
                        "document_version_id": version.id,
                    },
                }
                audit_tree.write_extraction(
                    bill_slug=slug,
                    document_id=document.id,
                    version_no=version.version_no,
                    extractor_name=EXTRACTOR_NAME,
                    extractor_version=MINERU_EXTRACTOR_VERSION,
                    raw_file=RAW_FILE,
                    content_bytes=result.markdown.encode("utf-8"),
                    sidecar=sidecar,
                )
            counts["processed" if result.status == "succeeded" else "empty"] += 1

    job.counts = counts
    job.state = "succeeded" if counts["failed"] == 0 else "failed"
    job.finished_at = datetime.now(UTC)
    session.flush()
    audit_tree.write_manifest(
        step=STEP,
        run_id=job.id,
        payload={**counts, "dry_run": dry_run, "render_dpi": render_dpi},
    )
    return job
