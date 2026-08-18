"""Hybrid lexical + vector retrieval (HANDOFF 12.3).

Metadata filters and the current-version restriction are applied inside the retrieval query,
not after limiting results, so a filtered search cannot silently lose relevant chunks.
"""

import time
from dataclasses import dataclass

import structlog
from sqlalchemy import Select, select, text
from sqlalchemy.orm import Session

from billwatcher.config import Settings
from billwatcher.models import (
    Bill,
    BillDocument,
    ChamberRecord,
    ChunkEmbedding,
    Document,
    DocumentChunk,
    DocumentExtraction,
    DocumentVersion,
)
from billwatcher.scraper.normalize import parse_identifier_query
from billwatcher.search.embeddings import (
    EmbeddingProvider,
    QueryEmbeddingCache,
    cosine_similarity,
)
from billwatcher.search.lexical import query_fingerprint, search_bills
from billwatcher.version import CHUNKER_VERSION

_log = structlog.get_logger("billwatcher.semantic")


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A retrieval result pinned to the exact bytes and page range it came from."""

    chunk_id: str
    content: str
    heading: str | None
    page_start: int | None
    page_end: int | None
    similarity: float
    bill_id: str
    bill_slug: str
    bill_identifier: str
    document_id: str
    document_source_url: str
    document_version_id: str
    document_version_no: int
    document_retrieved_at: str
    is_current_version: bool

    @property
    def anchor(self) -> str:
        """A deterministic citation anchor: document version plus chunk."""
        return f"{self.document_version_id}#chunk-{self.chunk_id}"


@dataclass(frozen=True, slots=True)
class HybridResult:
    bill: Bill
    score: float
    exact_identifier: bool
    chunks: tuple[RetrievedChunk, ...]


class SemanticSearchDisabled(RuntimeError):
    pass


def _chunk_query(
    *,
    chamber: str | None,
    status: str | None,
    year: int | None,
    include_superseded: bool,
) -> Select[tuple[DocumentChunk, ChunkEmbedding, Bill, Document, DocumentVersion]]:
    statement = (
        select(DocumentChunk, ChunkEmbedding, Bill, Document, DocumentVersion)
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
        .join(DocumentExtraction, DocumentExtraction.id == DocumentChunk.extraction_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentExtraction.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(BillDocument, BillDocument.document_id == Document.id)
        .join(Bill, Bill.id == BillDocument.bill_id)
        .where(
            DocumentChunk.is_current.is_(True),
            DocumentChunk.chunker_version == CHUNKER_VERSION,
            Bill.tombstoned_at.is_(None),
        )
    )
    if not include_superseded:
        statement = statement.where(DocumentVersion.is_current.is_(True))
    if chamber or status:
        statement = statement.join(ChamberRecord, ChamberRecord.bill_id == Bill.id)
    if chamber:
        statement = statement.where(ChamberRecord.chamber == chamber)
    if status:
        statement = statement.where(ChamberRecord.status_normalized == status)
    if year:
        statement = statement.where(Bill.year == year)
    return statement


def retrieve_chunks(
    session: Session,
    *,
    query: str,
    provider: EmbeddingProvider,
    cache: QueryEmbeddingCache,
    chamber: str | None = None,
    status: str | None = None,
    year: int | None = None,
    include_superseded: bool = False,
    limit: int = 50,
) -> list[RetrievedChunk]:
    """Vector retrieval with the filters applied during, not after, candidate selection."""
    vector = cache.embed(provider, query)
    statement = _chunk_query(
        chamber=chamber, status=status, year=year, include_superseded=include_superseded
    ).where(ChunkEmbedding.embedding_model_id == provider.model_id)

    if session.get_bind().dialect.name == "postgresql":
        literal_vector = "[" + ",".join(f"{component:.7g}" for component in vector) + "]"
        distance = text(
            "chunk_embeddings.embedding <=> CAST(:probe AS vector) AS distance"
        ).bindparams(probe=literal_vector)
        rows = session.execute(
            statement.add_columns(distance).order_by(text("distance")).limit(limit)
        ).all()
        scored = [(1.0 - float(row[-1]), row) for row in rows]
    else:
        rows = session.execute(statement).all()
        scored = sorted(
            ((cosine_similarity(vector, row[1].embedding), row) for row in rows),
            key=lambda pair: pair[0],
            reverse=True,
        )[:limit]

    results: list[RetrievedChunk] = []
    for similarity, row in scored:
        chunk, _embedding, bill, document, version = row[0], row[1], row[2], row[3], row[4]
        results.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                content=chunk.content,
                heading=chunk.heading,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                similarity=similarity,
                bill_id=bill.id,
                bill_slug=bill.slug,
                bill_identifier=bill.identifier_raw,
                document_id=document.id,
                document_source_url=document.canonical_source_url,
                document_version_id=version.id,
                document_version_no=version.version_no,
                document_retrieved_at=version.retrieved_at.isoformat(),
                is_current_version=version.is_current,
            )
        )
    return results


def hybrid_search(
    session: Session,
    *,
    query: str,
    settings: Settings,
    provider: EmbeddingProvider,
    cache: QueryEmbeddingCache,
    chamber: str | None = None,
    status: str | None = None,
    year: int | None = None,
    lang: str | None = None,
    include_superseded: bool = False,
    page_size: int = 20,
) -> list[HybridResult]:
    """Fuse lexical and vector candidates with reciprocal rank fusion; exact codes stay first."""
    if not settings.semantic_search_enabled:
        raise SemanticSearchDisabled("semantic search is disabled")
    started = time.monotonic()

    lexical = search_bills(
        session,
        query=query,
        chamber=chamber,
        status=status,
        year=year,
        lang=lang,
        page=1,
        page_size=min(settings.semantic_candidates, 100),
        include_superseded=include_superseded,
    )
    chunks = retrieve_chunks(
        session,
        query=query,
        provider=provider,
        cache=cache,
        chamber=chamber,
        status=status,
        year=year,
        include_superseded=include_superseded,
        limit=settings.semantic_candidates,
    )

    k = settings.hybrid_rrf_k
    scores: dict[str, float] = {}
    for rank, bill in enumerate(lexical.items, start=1):
        scores[bill.id] = scores.get(bill.id, 0.0) + 1.0 / (k + rank)
    chunk_rank: dict[str, int] = {}
    for rank, chunk in enumerate(chunks, start=1):
        chunk_rank.setdefault(chunk.bill_id, rank)
    for bill_id, rank in chunk_rank.items():
        scores[bill_id] = scores.get(bill_id, 0.0) + 1.0 / (k + rank)

    identifiers = parse_identifier_query(query)
    bills = {
        bill.id: bill
        for bill in session.scalars(select(Bill).where(Bill.id.in_(list(scores)))).all()
    }
    by_bill: dict[str, list[RetrievedChunk]] = {}
    for chunk in chunks:
        by_bill.setdefault(chunk.bill_id, []).append(chunk)

    results = [
        HybridResult(
            bill=bills[bill_id],
            score=score,
            exact_identifier=bool(
                identifiers.exact and bills[bill_id].identifier_normalized == identifiers.exact
            ),
            chunks=tuple(by_bill.get(bill_id, ())[:3]),
        )
        for bill_id, score in scores.items()
        if bill_id in bills
    ]
    # An exact bill-code match always wins, whatever the fused score says.
    results.sort(
        key=lambda item: (
            0 if item.exact_identifier else 1,
            -item.score,
            item.bill.identifier_normalized,
        )
    )
    _log.info(
        "semantic.query",
        fingerprint=query_fingerprint(query),
        lexical_candidates=len(lexical.items),
        vector_candidates=len(chunks),
        returned=min(len(results), page_size),
        model=provider.model_id,
        latency_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return results[:page_size]
