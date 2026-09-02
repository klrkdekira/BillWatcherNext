"""PostgreSQL-only proof of the pgvector retrieval path and its index."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from billwatcher.models import EMBEDDING_DIMENSION, Bill, ChunkEmbedding
from billwatcher.search.embeddings import DeterministicEmbeddingProvider, QueryEmbeddingCache
from billwatcher.search.semantic import hybrid_search, retrieve_chunks
from tests.integration.test_semantic import MODEL, prepared, settings


@pytest.fixture
def session(postgres_engine: Engine) -> Iterator[Session]:
    with Session(postgres_engine) as database:
        database.execute(
            text(
                "TRUNCATE TABLE chunk_embeddings, document_chunks, document_extractions,"
                " search_units, bill_events, bill_documents, document_versions, documents,"
                " chamber_records, record_changes, bills CASCADE"
            )
        )
        database.commit()
        yield database
        database.rollback()


def test_embeddings_land_in_a_real_vector_column(session: Session) -> None:
    prepared(session)
    session.flush()
    column_type = session.execute(
        text(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'chunk_embeddings'::regclass AND attname = 'embedding'"
        )
    ).scalar_one()
    assert column_type == f"vector({EMBEDDING_DIMENSION})"
    stored = session.scalars(select(ChunkEmbedding)).first()
    assert stored is not None
    assert len(stored.embedding) == EMBEDDING_DIMENSION


def test_cosine_distance_retrieval_ranks_the_right_bill(session: Session) -> None:
    witness, _roads, provider = prepared(session)
    session.flush()
    chunks = retrieve_chunks(
        session,
        query="perlindungan saksi dalam prosiding jenayah",
        provider=provider,
        cache=QueryEmbeddingCache(8),
        limit=5,
    )
    assert chunks
    assert chunks[0].bill_id == witness.id
    assert 0.0 <= chunks[0].similarity <= 1.0


def test_hybrid_fusion_and_exact_code_priority_on_postgres(session: Session) -> None:
    _witness, roads, provider = prepared(session)
    session.flush()
    results = hybrid_search(
        session,
        query="D.R.16/2026",
        settings=settings(),
        provider=provider,
        cache=QueryEmbeddingCache(8),
    )
    assert results[0].bill.id == roads.id
    assert results[0].exact_identifier

    semantic = hybrid_search(
        session,
        query="kenderaan bermotor dan lesen memandu",
        settings=settings(),
        provider=provider,
        cache=QueryEmbeddingCache(8),
    )
    assert semantic
    assert semantic[0].bill.id == roads.id
    assert semantic[0].chunks


def test_the_hnsw_index_can_be_built_and_is_used(session: Session) -> None:
    prepared(session)
    session.commit()
    session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_hnsw ON chunk_embeddings "
            "USING hnsw (embedding vector_cosine_ops)"
        )
    )
    session.commit()
    indexes = set(
        session.scalars(
            text("SELECT indexname FROM pg_indexes WHERE tablename = 'chunk_embeddings'")
        )
    )
    assert "ix_chunk_embeddings_hnsw" in indexes
    probe = DeterministicEmbeddingProvider(MODEL).embed_query("saksi")
    literal = "[" + ",".join(f"{value:.7g}" for value in probe) + "]"
    nearest = session.execute(
        text(
            "SELECT chunk_id FROM chunk_embeddings "
            "ORDER BY embedding <=> CAST(:probe AS vector) LIMIT 1"
        ).bindparams(probe=literal)
    ).scalar_one()
    assert nearest
    session.execute(text("DROP INDEX ix_chunk_embeddings_hnsw"))
    session.commit()
    assert session.scalars(select(Bill)).all()
