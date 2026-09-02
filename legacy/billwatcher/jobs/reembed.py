"""Backfill embeddings for a named model (HANDOFF 9.6, 12.3).

A model change backfills alongside the previous model's vectors. Nothing is deleted here; the
old model's rows are dropped only by a separate, explicit job once the replacement is validated.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import (
    BackfillJob,
    ChunkEmbedding,
    DocumentChunk,
)
from billwatcher.search.embeddings import EmbeddingProvider
from billwatcher.version import CHUNKER_VERSION

EMBEDDING_PIPELINE_VERSION = "1.0.0"
BATCH_SIZE = 32


def run_reembed(
    session: Session,
    *,
    provider: EmbeddingProvider,
    dry_run: bool = True,
    limit: int = 200,
) -> BackfillJob:
    job = BackfillJob(
        kind="reembed",
        to_version=provider.model_id[:32],
        filter_json={
            "limit": limit,
            "model_id": provider.model_id,
            "dimension": provider.dimension,
            "chunker_version": CHUNKER_VERSION,
        },
        dry_run=dry_run,
        state="running",
        started_at=datetime.now(UTC),
    )
    session.add(job)
    session.flush()

    embedded = select(ChunkEmbedding.chunk_id).where(
        ChunkEmbedding.embedding_model_id == provider.model_id
    )
    chunks = session.scalars(
        select(DocumentChunk)
        .where(
            DocumentChunk.is_current.is_(True),
            DocumentChunk.chunker_version == CHUNKER_VERSION,
            DocumentChunk.id.not_in(embedded),
        )
        .order_by(DocumentChunk.created_at, DocumentChunk.chunk_index)
        .limit(limit)
    ).all()

    written = failed = 0
    if not dry_run:
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            try:
                vectors = provider.embed_documents([chunk.content for chunk in batch])
            except Exception:
                failed += len(batch)
                continue
            for chunk, vector in zip(batch, vectors, strict=True):
                session.add(
                    ChunkEmbedding(
                        chunk_id=chunk.id,
                        embedding_model_id=provider.model_id,
                        model_dimension=provider.dimension,
                        embedding=vector,
                        embedding_pipeline_version=EMBEDDING_PIPELINE_VERSION,
                    )
                )
                written += 1
        session.flush()

    job.counts = {"eligible": len(chunks), "embedded": written, "failed": failed}
    job.state = "succeeded" if failed == 0 else "failed"
    job.finished_at = datetime.now(UTC)
    return job


def drop_superseded_model(session: Session, *, model_id: str, dry_run: bool = True) -> int:
    """Explicitly remove one model's vectors after its replacement has been validated."""
    rows = session.scalars(
        select(ChunkEmbedding).where(ChunkEmbedding.embedding_model_id == model_id)
    ).all()
    if not dry_run:
        for row in rows:
            session.delete(row)
    return len(rows)
