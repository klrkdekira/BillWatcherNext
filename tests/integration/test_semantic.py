"""Package G: chunk, embed, and retrieve with the feature flag on (HANDOFF 12.3)."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from billwatcher.config import Settings
from billwatcher.db import Base
from billwatcher.jobs.rechunk import run_rechunk
from billwatcher.jobs.reembed import drop_superseded_model, run_reembed
from billwatcher.models import (
    EMBEDDING_DIMENSION,
    Bill,
    BillDocument,
    Blob,
    ChunkEmbedding,
    Document,
    DocumentChunk,
    DocumentExtraction,
    DocumentVersion,
    FetchAttempt,
    ScrapeRun,
)
from billwatcher.search.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingProviderUnavailable,
    QueryEmbeddingCache,
    build_provider,
)
from billwatcher.search.semantic import SemanticSearchDisabled, hybrid_search, retrieve_chunks

NOW = datetime(2026, 8, 17, tzinfo=UTC)
MODEL = "deterministic-dev-1024"

WITNESS = (
    "--- Page 1 ---\n"
    "RUU PERLINDUNGAN SAKSI\n"
    "1. Akta ini memperuntukkan perlindungan bagi saksi dalam prosiding jenayah.\n"
    "2. Menteri boleh menetapkan program perlindungan saksi.\n"
)
ROADS = (
    "--- Page 1 ---\n"
    "RUU PENGANGKUTAN JALAN\n"
    "1. Akta ini mengawal selia kenderaan bermotor dan lesen memandu.\n"
    "2. Pihak berkuasa boleh mengenakan kompaun lalu lintas.\n"
)


def settings(**overrides: object) -> Settings:
    base = {
        "semantic_search_enabled": True,
        "embedding_provider": "deterministic",
        "embedding_model_id": MODEL,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


def provenance(session: Session) -> tuple[str, str]:
    """Real run and attempt rows so the same seed works under enforced foreign keys."""
    run = ScrapeRun(mode="fixture", trigger="manual", started_at=NOW, state="succeeded")
    session.add(run)
    session.flush()
    attempt = FetchAttempt(
        run_id=run.id,
        target_kind="document",
        url="https://www.parlimen.gov.my/doc.pdf",
        method="GET",
        attempted_at=NOW,
        duration_ms=1,
        status_code=200,
    )
    session.add(attempt)
    session.flush()
    return run.id, attempt.id


def seed_document(session: Session, *, code: str, number: int, text: str) -> Bill:
    run_id, attempt_id = provenance(session)
    digest = code.lower().ljust(64, "0")
    if session.get(Blob, digest) is None:
        session.add(
            Blob(
                sha256=digest,
                byte_size=len(text),
                media_type="application/pdf",
                storage_path=f"var/blobs/{digest}",
                compression="none",
                ref_count=1,
            )
        )
        session.flush()
    bill = Bill(
        identifier_raw=f"D.R.{number}/2026",
        identifier_normalized=code,
        number=number,
        year=2026,
        slug=code.lower(),
        title_bm=text.splitlines()[1],
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )
    document = Document(
        document_kind="bill_as_introduced",
        language="ms",
        canonical_source_url=f"https://www.parlimen.gov.my/{code.lower()}.pdf",
        source_url_raw=f"https://www.parlimen.gov.my/{code.lower()}.pdf",
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )
    session.add_all([bill, document])
    session.flush()
    session.add(
        BillDocument(
            bill_id=bill.id,
            document_id=document.id,
            chamber="dewan_rakyat",
            role="listing_document",
            first_seen_at=NOW,
            last_seen_at=NOW,
            source_url="https://www.parlimen.gov.my/list",
        )
    )
    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        content_sha256=digest,
        blob_sha256=digest,
        byte_size=len(text),
        http_status=200,
        final_url=document.canonical_source_url,
        retrieved_at=NOW,
        last_verified_at=NOW,
        run_id=run_id,
        fetch_attempt_id=attempt_id,
        is_current=True,
        change_kind="initial",
        validation_status="accepted",
    )
    session.add(version)
    session.flush()
    document.current_version_id = version.id
    session.add(
        DocumentExtraction(
            document_version_id=version.id,
            extractor_name="pypdf",
            extractor_version="1.0.0",
            pipeline_version="1.0.0",
            mode="native",
            status="succeeded",
            extracted_text=text,
            text_sha256="a" * 64,
            page_count=1,
            char_count=len(text),
            is_current=True,
            duration_ms=1,
        )
    )
    session.flush()
    return bill


def prepared(session: Session) -> tuple[Bill, Bill, DeterministicEmbeddingProvider]:
    witness = seed_document(session, code="DR-15-2026", number=15, text=WITNESS)
    roads = seed_document(session, code="DR-16-2026", number=16, text=ROADS)
    run_rechunk(session, dry_run=False, limit=50)
    provider = DeterministicEmbeddingProvider(MODEL)
    run_reembed(session, provider=provider, dry_run=False, limit=200)
    session.flush()
    return witness, roads, provider


def test_no_model_configured_means_no_semantic_search() -> None:
    with pytest.raises(EmbeddingProviderUnavailable, match="no embedding model is configured"):
        build_provider(Settings())
    with pytest.raises(EmbeddingProviderUnavailable, match="unknown embedding provider"):
        build_provider(settings(embedding_provider="magic"))


def test_deterministic_provider_matches_the_schema_width() -> None:
    provider = build_provider(settings())
    assert provider.dimension == EMBEDDING_DIMENSION
    assert provider.model_id == MODEL
    first = provider.embed_query("perlindungan saksi")
    assert first == provider.embed_query("perlindungan saksi")
    assert len(first) == EMBEDDING_DIMENSION


def test_rechunk_is_additive_and_dry_run_writes_nothing(session: Session) -> None:
    seed_document(session, code="DR-15-2026", number=15, text=WITNESS)
    dry = run_rechunk(session, dry_run=True, limit=10)
    session.flush()
    assert dry.counts["eligible"] == 1
    assert dry.counts["chunks_written"] == 0
    assert session.scalars(select(DocumentChunk)).all() == []

    applied = run_rechunk(session, dry_run=False, limit=10)
    session.flush()
    assert applied.counts["chunks_written"] >= 1
    chunks = session.scalars(select(DocumentChunk)).all()
    assert chunks and all(chunk.is_current for chunk in chunks)
    assert {chunk.chunker_version for chunk in chunks} == {"1.0.0"}

    # Running again finds nothing new to do.
    assert run_rechunk(session, dry_run=False, limit=10).counts["eligible"] == 0


def test_reembed_is_dry_run_by_default_and_models_coexist(session: Session) -> None:
    seed_document(session, code="DR-15-2026", number=15, text=WITNESS)
    run_rechunk(session, dry_run=False, limit=10)
    first = DeterministicEmbeddingProvider(MODEL)
    dry = run_reembed(session, provider=first, dry_run=True)
    session.flush()
    assert dry.counts["embedded"] == 0
    assert session.scalars(select(ChunkEmbedding)).all() == []

    run_reembed(session, provider=first, dry_run=False)
    session.flush()
    original = session.scalars(select(ChunkEmbedding)).all()
    assert original and {row.embedding_model_id for row in original} == {MODEL}
    assert all(row.model_dimension == EMBEDDING_DIMENSION for row in original)

    replacement = DeterministicEmbeddingProvider("deterministic-dev-next")
    run_reembed(session, provider=replacement, dry_run=False)
    session.flush()
    # The replacement backfills alongside the previous model rather than mutating it.
    both = session.scalars(select(ChunkEmbedding)).all()
    assert {row.embedding_model_id for row in both} == {MODEL, "deterministic-dev-next"}

    assert drop_superseded_model(session, model_id=MODEL, dry_run=True) == len(original)
    assert session.scalars(select(ChunkEmbedding)).all() == both
    drop_superseded_model(session, model_id=MODEL, dry_run=False)
    session.flush()
    assert {row.embedding_model_id for row in session.scalars(select(ChunkEmbedding))} == {
        "deterministic-dev-next"
    }


def test_vector_retrieval_finds_the_right_bill_and_pins_the_version(session: Session) -> None:
    witness, _roads, provider = prepared(session)
    chunks = retrieve_chunks(
        session,
        query="perlindungan saksi dalam prosiding jenayah",
        provider=provider,
        cache=QueryEmbeddingCache(8),
        limit=5,
    )
    assert chunks
    assert chunks[0].bill_id == witness.id
    assert chunks[0].document_version_no == 1
    assert chunks[0].is_current_version
    assert chunks[0].anchor.endswith(f"#chunk-{chunks[0].chunk_id}")
    assert chunks[0].document_retrieved_at.startswith("2026-08-17")


def test_filters_are_applied_during_retrieval_not_afterwards(session: Session) -> None:
    prepared(session)
    cache = QueryEmbeddingCache(8)
    unfiltered = retrieve_chunks(
        session,
        query="kenderaan bermotor",
        provider=DeterministicEmbeddingProvider(MODEL),
        cache=cache,
        limit=10,
    )
    assert unfiltered
    filtered = retrieve_chunks(
        session,
        query="kenderaan bermotor",
        provider=DeterministicEmbeddingProvider(MODEL),
        cache=cache,
        year=1999,
        limit=10,
    )
    assert filtered == []


def test_superseded_versions_are_excluded_by_default(session: Session) -> None:
    witness, _roads, provider = prepared(session)
    version = session.scalars(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.canonical_source_url.contains("15"))
    ).one()
    version.is_current = False
    session.flush()
    cache = QueryEmbeddingCache(8)
    assert not any(
        chunk.bill_id == witness.id
        for chunk in retrieve_chunks(
            session, query="perlindungan saksi", provider=provider, cache=cache, limit=10
        )
    )
    assert any(
        chunk.bill_id == witness.id
        for chunk in retrieve_chunks(
            session,
            query="perlindungan saksi",
            provider=provider,
            cache=cache,
            include_superseded=True,
            limit=10,
        )
    )


def test_hybrid_search_puts_an_exact_bill_code_first(session: Session) -> None:
    _witness, roads, provider = prepared(session)
    results = hybrid_search(
        session,
        query="D.R.16/2026",
        settings=settings(),
        provider=provider,
        cache=QueryEmbeddingCache(8),
    )
    assert results
    assert results[0].bill.id == roads.id
    assert results[0].exact_identifier


def test_hybrid_search_refuses_when_the_flag_is_off(session: Session) -> None:
    _witness, _roads, provider = prepared(session)
    with pytest.raises(SemanticSearchDisabled):
        hybrid_search(
            session,
            query="saksi",
            settings=Settings(),
            provider=provider,
            cache=QueryEmbeddingCache(8),
        )


def test_query_embedding_cache_reuses_one_vector_per_model(session: Session) -> None:
    calls: list[str] = []

    class Counting(DeterministicEmbeddingProvider):
        def embed_query(self, text: str) -> list[float]:
            calls.append(text)
            return super().embed_query(text)

    provider = Counting(MODEL)
    cache = QueryEmbeddingCache(4)
    cache.embed(provider, "Perlindungan  Saksi")
    cache.embed(provider, "perlindungan saksi")
    assert len(calls) == 1
