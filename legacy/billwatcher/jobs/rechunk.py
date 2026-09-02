"""Rebuild chunk sets at the current chunker version (HANDOFF 9.6).

Additive: existing chunk rows at older chunker versions are demoted, never deleted, so a
citation issued against an older chunk set still resolves.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import (
    BackfillJob,
    DocumentChunk,
    DocumentExtraction,
    DocumentVersion,
)
from billwatcher.search.chunking import chunk_extraction
from billwatcher.version import CHUNKER_VERSION


def run_rechunk(
    session: Session,
    *,
    dry_run: bool = True,
    limit: int = 100,
    current_versions_only: bool = True,
) -> BackfillJob:
    job = BackfillJob(
        kind="rechunk",
        to_version=CHUNKER_VERSION,
        filter_json={"limit": limit, "current_versions_only": current_versions_only},
        dry_run=dry_run,
        state="running",
        started_at=datetime.now(UTC),
    )
    session.add(job)
    session.flush()

    already = select(DocumentChunk.extraction_id).where(
        DocumentChunk.chunker_version == CHUNKER_VERSION
    )
    statement = (
        select(DocumentExtraction)
        .where(
            DocumentExtraction.is_current.is_(True),
            DocumentExtraction.status == "succeeded",
            DocumentExtraction.id.not_in(already),
        )
        .order_by(DocumentExtraction.created_at)
        .limit(limit)
    )
    if current_versions_only:
        current = select(DocumentVersion.id).where(DocumentVersion.is_current.is_(True))
        statement = statement.where(DocumentExtraction.document_version_id.in_(current))

    extractions = session.scalars(statement).all()
    written = failed = 0
    if not dry_run:
        for extraction in extractions:
            try:
                written += rechunk_extraction(session, extraction)
            except Exception:
                failed += 1
    job.counts = {
        "eligible": len(extractions),
        "chunks_written": written,
        "failed": failed,
    }
    job.state = "succeeded" if failed == 0 else "failed"
    job.finished_at = datetime.now(UTC)
    return job


def rechunk_extraction(session: Session, extraction: DocumentExtraction) -> int:
    """Write the current chunker's output and demote every older chunk set for this extraction."""
    if not extraction.extracted_text:
        return 0
    for older in session.scalars(
        select(DocumentChunk).where(
            DocumentChunk.extraction_id == extraction.id,
            DocumentChunk.chunker_version != CHUNKER_VERSION,
        )
    ):
        older.is_current = False

    existing = {
        chunk.chunk_index: chunk
        for chunk in session.scalars(
            select(DocumentChunk).where(
                DocumentChunk.extraction_id == extraction.id,
                DocumentChunk.chunker_version == CHUNKER_VERSION,
            )
        )
    }
    written = 0
    for chunk in chunk_extraction(extraction.extracted_text):
        row = existing.pop(chunk.chunk_index, None)
        if row is None:
            session.add(
                DocumentChunk(
                    extraction_id=extraction.id,
                    chunker_version=CHUNKER_VERSION,
                    chunk_index=chunk.chunk_index,
                    heading=chunk.heading,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    content_sha256=chunk.content_sha256,
                    is_current=True,
                )
            )
        else:
            row.content = chunk.content
            row.heading = chunk.heading
            row.page_start = chunk.page_start
            row.page_end = chunk.page_end
            row.token_count = chunk.token_count
            row.content_sha256 = chunk.content_sha256
            row.is_current = True
        written += 1
    for leftover in existing.values():
        leftover.is_current = False
    session.flush()
    return written
