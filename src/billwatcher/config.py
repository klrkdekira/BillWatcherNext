from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal

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
    # `filesystem` writes files directly; `s3` talks to any S3-compatible service, which in this
    # deployment is VersityGW over the same archive volume (ADR-013).
    blob_storage_backend: Literal["filesystem", "s3"] = "filesystem"
    s3_endpoint_url: str = ""
    s3_bucket: str = "billwatcher-blobs"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "us-east-1"
    # Serving our archived copy of an official document is gated on the rights review in
    # assumption A14 and ADR-004. Off until that review concludes and is recorded.
    serve_archived_documents: bool = False
    # ADR-013 says enabling public serving is the A14 rights decision, "not a configuration
    # change" — but a single flag was exactly a configuration change, so the document and the code
    # disagreed. In production, serving now also requires an operator to assert that the rights
    # review has concluded. Development is untouched: proving the serving path locally is how
    # ADR-013 was validated in the first place.
    archived_document_rights_confirmed: bool = False
    # HSTS, in seconds; 0 disables it. Off by default on purpose: TLS is terminated by a proxy
    # outside this stack (ADR-015), so the application cannot verify that HTTPS works, and a
    # year-long promise made before it does takes the domain down for every browser that saw it.
    # HANDOFF 17 says to add it only once HTTPS and the domain are known good. 31536000 is a year.
    hsts_max_age_seconds: int = Field(default=0, ge=0)
    scrape_enabled: bool = False
    scrape_interval_hours: int = Field(default=12, ge=1)
    scrape_delay_seconds: float = Field(default=2.0, ge=2.0)
    scrape_concurrency: int = Field(default=1, ge=1)
    scrape_max_requests_per_run: int = 2000
    scrape_max_bytes_per_run: int = 1_073_741_824
    scrape_max_duration_seconds: int = 3600
    scrape_max_new_documents: int = Field(default=500, ge=0)
    # HANDOFF 11.7 makes a full archive crawl a separate, explicitly triggered mode with its own,
    # larger budget, and the archive needs one: it reads one document per archived year per
    # chamber — 67 of them — and introduces the entire back catalogue of about 2,000 bill PDFs on
    # its first run. Under the incremental budget the run would end `partial` on the document
    # limit and withhold every archived year it had just read.
    archive_max_requests_per_run: int = 400
    archive_max_bytes_per_run: int = 2_147_483_648
    archive_max_duration_seconds: int = 7200
    archive_max_new_documents: int = Field(default=5000, ge=0)
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
    # `/ask` tells the reader their question is not stored. That is only true if the provider does
    # not store it either, and with Anthropic that means a zero-data-retention arrangement, which is
    # negotiated per organization and cannot be detected from inside the process (ADR-009). An
    # operator asserts it here; until then RAG refuses to start in production rather than making a
    # promise it cannot keep. The models that require 30-day retention are refused outright.
    rag_zero_retention_confirmed: bool = False

    # Claude Fable 5 and Claude Mythos 5 require 30-day data retention and are not available under
    # zero data retention (verified 2026-08-18, see ADR-009).
    RETENTION_REQUIRING_MODELS: ClassVar[frozenset[str]] = frozenset(
        {"claude-fable-5", "claude-mythos-5", "claude-mythos-preview"}
    )

    @model_validator(mode="after")
    def reject_production_placeholders(self) -> "Settings":
        if self.environment == "production":
            values = (self.site_host, self.public_base_url, self.contact_email, self.database_url)
            if any("example.org" in value or "CHANGE_ME" in value for value in values):
                raise ValueError("production configuration contains placeholder values")
        return self

    @model_validator(mode="after")
    def require_the_rights_review_before_publishing_stored_documents(self) -> "Settings":
        if (
            self.serve_archived_documents
            and self.environment == "production"
            and not self.archived_document_rights_confirmed
        ):
            raise ValueError(
                "SERVE_ARCHIVED_DOCUMENTS=true in production requires "
                "ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true, asserting that the A14 rights review has "
                "concluded and been recorded in the manual gate log; see ADR-013 and ADR-004"
            )
        return self

    @model_validator(mode="after")
    def require_s3_configuration(self) -> "Settings":
        if self.blob_storage_backend == "s3" and not (
            self.s3_endpoint_url and self.s3_access_key_id and self.s3_secret_access_key
        ):
            raise ValueError(
                "BLOB_STORAGE_BACKEND=s3 requires S3_ENDPOINT_URL, S3_ACCESS_KEY_ID "
                "and S3_SECRET_ACCESS_KEY"
            )
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
        if self.rag_enabled and self.rag_model_id in self.RETENTION_REQUIRING_MODELS:
            raise ValueError(
                f"{self.rag_model_id} requires 30-day data retention and cannot be used under a "
                "zero-data-retention arrangement; /ask promises questions are not stored (ADR-009)"
            )
        if (
            self.rag_enabled
            and self.environment == "production"
            and not self.rag_zero_retention_confirmed
        ):
            raise ValueError(
                "RAG_ENABLED in production requires RAG_ZERO_RETENTION_CONFIRMED=true, asserting "
                "that the answer provider has a zero-data-retention arrangement for this "
                "organization; see ADR-009"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
