"""Provider wiring, resolved once per application.

HANDOFF 12.3 requires that provider calls never live in route handlers. A provider that cannot
be built leaves its feature switched off rather than raising at request time.
"""

from dataclasses import dataclass

from billwatcher.config import Settings
from billwatcher.search.embeddings import (
    EmbeddingProvider,
    EmbeddingProviderUnavailable,
    QueryEmbeddingCache,
    build_provider,
)
from billwatcher.search.rag import (
    AnswerProvider,
    AnswerProviderUnavailable,
    build_answer_provider,
)
from billwatcher.storage import build_blob_store
from billwatcher.storage.blobs import BlobStore


@dataclass(frozen=True, slots=True)
class Retrieval:
    """Provider handles resolved once per application, never inside a route handler."""

    embedding_provider: EmbeddingProvider | None
    answer_provider: AnswerProvider | None
    cache: QueryEmbeddingCache
    blob_store: BlobStore


def build_retrieval(settings: Settings) -> Retrieval:
    embedding_provider: EmbeddingProvider | None = None
    answer_provider: AnswerProvider | None = None
    if settings.semantic_search_enabled:
        try:
            embedding_provider = build_provider(settings)
        except EmbeddingProviderUnavailable:
            embedding_provider = None
    if settings.rag_enabled and embedding_provider is not None:
        try:
            answer_provider = build_answer_provider(settings)
        except AnswerProviderUnavailable:
            answer_provider = None
    return Retrieval(
        blob_store=build_blob_store(settings),
        embedding_provider=embedding_provider,
        answer_provider=answer_provider,
        cache=QueryEmbeddingCache(settings.query_embedding_cache_size),
    )
