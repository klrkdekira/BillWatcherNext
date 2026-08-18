from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    site_host: str = "localhost"
    public_base_url: str = "http://localhost:8000"
    contact_email: str = "operator@example.org"
    database_url: str = "postgresql+psycopg://billwatcher:billwatcher@localhost/billwatcher"
    blob_storage_root: Path = Path("var/blobs")
    scrape_enabled: bool = False
    scrape_interval_hours: int = Field(default=12, ge=1)
    scrape_delay_seconds: float = Field(default=2.0, ge=2.0)
    scrape_concurrency: int = Field(default=1, ge=1)
    scrape_max_requests_per_run: int = 2000
    scrape_max_bytes_per_run: int = 1_073_741_824
    scrape_max_duration_seconds: int = 3600
    scrape_max_new_documents: int = Field(default=500, ge=0)
    document_max_bytes: int = 104_857_600
    # An explicit trust store for upstream requests. Use it when the site serves an incomplete
    # certificate chain: put the missing intermediate in a bundle and point this at it. There is
    # deliberately no setting that disables verification (HANDOFF 5).
    upstream_ca_bundle: Path | None = None
    # What to do when the site publishes no robots.txt. RFC 9309 treats a 404 as unrestricted;
    # assumption A13 requires a recorded decision instead, so the default refuses to crawl.
    robots_missing_policy: Literal["refuse", "allow"] = "refuse"
    absence_streak_alert: int = 3
    count_drop_abort_fraction: float = 0.30
    fetch_attempt_retention_days: int = 180
    semantic_search_enabled: bool = False
    # No embedding model is chosen for this project yet (HANDOFF 21). Semantic search cannot be
    # enabled until an operator names a provider and model whose dimension matches the schema.
    embedding_provider: str = ""
    embedding_model_id: str = ""
    semantic_candidates: int = Field(default=50, ge=1, le=500)
    hybrid_rrf_k: int = Field(default=60, ge=1)
    query_embedding_cache_size: int = Field(default=256, ge=0)
    rag_enabled: bool = False
    rag_provider: str = ""
    rag_model_id: str = ""
    rag_max_context_chunks: int = Field(default=8, ge=1, le=32)
    rag_max_question_chars: int = Field(default=500, ge=1)
    rag_min_retrieval_score: float = Field(default=0.05, ge=0.0)
    rag_timeout_seconds: float = Field(default=30.0, gt=0)

    @model_validator(mode="after")
    def reject_production_placeholders(self) -> "Settings":
        if self.environment == "production":
            values = (self.site_host, self.public_base_url, self.contact_email, self.database_url)
            if any("example.org" in value or "CHANGE_ME" in value for value in values):
                raise ValueError("production configuration contains placeholder values")
        return self

    @model_validator(mode="after")
    def reject_unreadable_ca_bundle(self) -> "Settings":
        if self.upstream_ca_bundle is not None and not self.upstream_ca_bundle.is_file():
            raise ValueError(f"UPSTREAM_CA_BUNDLE does not name a file: {self.upstream_ca_bundle}")
        return self

    @model_validator(mode="after")
    def reject_unconfigured_release_three_features(self) -> "Settings":
        if self.semantic_search_enabled and not (
            self.embedding_provider and self.embedding_model_id
        ):
            raise ValueError(
                "SEMANTIC_SEARCH_ENABLED requires EMBEDDING_PROVIDER and EMBEDDING_MODEL_ID"
            )
        if self.rag_enabled and not self.semantic_search_enabled:
            raise ValueError("RAG_ENABLED requires SEMANTIC_SEARCH_ENABLED")
        if self.rag_enabled and not (self.rag_provider and self.rag_model_id):
            raise ValueError("RAG_ENABLED requires RAG_PROVIDER and RAG_MODEL_ID")
        if self.environment == "production" and self.embedding_provider == "deterministic":
            raise ValueError("the deterministic embedding provider is for development only")
        if self.environment == "production" and self.rag_provider == "echo":
            raise ValueError("the echo answer provider is for development only")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
