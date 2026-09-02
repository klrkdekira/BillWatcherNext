"""Embedding provider interface (HANDOFF 12.3).

Provider calls never appear in route handlers. No production embedding model has been selected
for this project (HANDOFF 21 lists it as a decision still to record), so there is no default:
an operator must name a provider and model, and the model's dimension must match the schema.
"""

import hashlib
import math
from collections import OrderedDict
from collections.abc import Sequence
from typing import Protocol

from billwatcher.config import Settings
from billwatcher.models import EMBEDDING_DIMENSION


class EmbeddingProvider(Protocol):
    model_id: str
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class EmbeddingProviderUnavailable(RuntimeError):
    """Raised when the configured provider cannot serve a request."""


class DeterministicEmbeddingProvider:
    """A reproducible local stand-in for development and tests only.

    It is a hashed bag-of-words projection: similar wording produces similar vectors, which is
    enough to exercise chunking, storage, indexing, and fusion. It has no semantic understanding
    and is rejected in production configuration.
    """

    def __init__(self, model_id: str, dimension: int = EMBEDDING_DIMENSION) -> None:
        self.model_id = model_id
        self.dimension = dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _tokenize(text):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return _normalize(vector)


def _tokenize(text: str) -> list[str]:
    return [
        token
        for token in "".join(
            character if character.isalnum() else " " for character in text.casefold()
        ).split()
        if token
    ]


def _normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(component * component for component in vector))
    if magnitude == 0:
        return vector
    return [component / magnitude for component in vector]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("cannot compare embeddings of different dimensions")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_magnitude = math.sqrt(sum(a * a for a in left))
    right_magnitude = math.sqrt(sum(b * b for b in right))
    if left_magnitude == 0 or right_magnitude == 0:
        return 0.0
    return dot / (left_magnitude * right_magnitude)


_PROVIDERS = {"deterministic": DeterministicEmbeddingProvider}


def build_provider(settings: Settings) -> EmbeddingProvider:
    """Resolve the configured provider, refusing to invent a model choice."""
    if not settings.embedding_provider or not settings.embedding_model_id:
        raise EmbeddingProviderUnavailable(
            "no embedding model is configured; set EMBEDDING_PROVIDER and EMBEDDING_MODEL_ID"
        )
    factory = _PROVIDERS.get(settings.embedding_provider)
    if factory is None:
        raise EmbeddingProviderUnavailable(
            f"unknown embedding provider {settings.embedding_provider!r}; "
            f"known providers: {', '.join(sorted(_PROVIDERS))}"
        )
    provider = factory(settings.embedding_model_id)
    if provider.dimension != EMBEDDING_DIMENSION:
        raise EmbeddingProviderUnavailable(
            f"model {provider.model_id!r} produces {provider.dimension} dimensions but the "
            f"schema stores {EMBEDDING_DIMENSION}; a different width needs its own migration"
        )
    return provider


class QueryEmbeddingCache:
    """Bounded cache keyed by model and normalized query (HANDOFF 12.3)."""

    def __init__(self, max_entries: int) -> None:
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[str, str], list[float]] = OrderedDict()

    def embed(self, provider: EmbeddingProvider, query: str) -> list[float]:
        key = (provider.model_id, " ".join(query.casefold().split()))
        if self.max_entries <= 0:
            return provider.embed_query(query)
        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
            return cached
        vector = provider.embed_query(query)
        self._entries[key] = vector
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return vector
