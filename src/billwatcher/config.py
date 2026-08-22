from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    site_host: str = "localhost"
    public_base_url: str = "http://localhost:8000"
    contact_email: str = "operator@example.org"
    database_url: str = "postgresql+psycopg://billwatcher:billwatcher@localhost/billwatcher"
    blob_storage_root: Path = Path("var/blobs")
    # The human-legible audit tree (HANDOFF 27): a derived, rebuildable projection of the
    # database and blob store, never a second source of truth. Safe to delete; `audit-rebuild`
    # regenerates it. Belongs to the Postgres-backed pipeline, currently dormant.
    audit_tree_root: Path = Path("data")
    # Where the file-first pipeline (`billwatcher.pipeline`) keeps its own state: listings,
    # bills, and documents, as plain files. This *is* the record for that pipeline today, not a
    # projection of anything else — a database/object-store backend is a later, additive
    # extension behind the same `PipelineStore` interface, not a replacement for these files.
    pipeline_data_root: Path = Path("pipeline-data")
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
    # OpenAI-compatible answer servers (including vLLM) are configured explicitly. The API key is
    # optional because a self-hosted endpoint may be reachable only on a private network.
    rag_base_url: str = ""
    rag_api_key: str = ""
    rag_max_context_chunks: int = Field(default=8, ge=1, le=32)
    rag_max_question_chars: int = Field(default=500, ge=1)
    rag_min_retrieval_score: float = Field(default=0.05, ge=0.0)
    rag_timeout_seconds: float = Field(default=30.0, gt=0)
    # A second, independently versioned reading of stored PDFs via a hosted MinerU
    # vision-language model (HANDOFF 27.7, ADR-020). Off by default: sending official document
    # images to a third-party endpoint is a data-handling decision, not a default.
    mineru_enabled: bool = False
    mineru_base_url: str = ""
    # Empty defers to the server's single served model, checked once at client construction.
    mineru_model_name: str = ""
    mineru_api_key: str = ""
    mineru_render_dpi: int = Field(default=150, ge=72, le=400)
    mineru_timeout_seconds: float = Field(default=120.0, gt=0)
    # The file-first pipeline's Akoma Ntoso conversion step (HANDOFF 28) reads a document's
    # provision structure with the help of an OpenAI-compatible vLLM endpoint, at the operator's
    # direction, rather than by regex alone. A separate setting from RAG_*/MINERU_*: a different
    # endpoint, for a different pipeline that does not touch the Postgres-backed one.
    akn_llm_enabled: bool = False
    akn_llm_base_url: str = ""
    akn_llm_model_id: str = ""
    akn_llm_api_key: str = ""
    akn_llm_timeout_seconds: float = Field(default=120.0, gt=0)
    # Gate P1's one statistical threshold: the fraction of the source markdown's distinct words
    # that must appear somewhere in the provision tree read out of it. Configurable rather than
    # hard-coded because the real corpus is unmeasured (A15) — exact where exactness is defensible,
    # configurable where it is a judgement.
    akn_gate_min_text_coverage: float = Field(default=0.95, ge=0.0, le=1.0)
    # The file-first pipeline's corpus — Akoma Ntoso XML, ELI JSON-LD, N-Quads — served on
    # truncatable ELI paths by this application rather than built into a static tree (ADR-018).
    # Off by default and, in production, refused without an explicit rights confirmation: a
    # mirrored corpus cannot be withdrawn, so the control is at least as hard as the one guarding
    # the lower-risk archived bytes.
    serve_legislation_corpus: bool = False
    # `metadata` publishes structure only — FRBR IRIs, provision numbers, headings, and the
    # relationships between them — republishing none of the source document's body text, which is
    # what makes it publishable while A14 is open. `full` adds the text and is a separate,
    # separately confirmed rights decision. An enumeration rather than a boolean so the safe value
    # is the default rather than the negation of a flag.
    legislation_publication_mode: Literal["metadata", "full"] = "metadata"
    # ADR-018 asks for the same hard control SERVE_ARCHIVED_DOCUMENTS has. A separate field from
    # ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED on purpose: TODO 1.7 records that publishing a reading of
    # the law is a higher bar than republishing stored bytes and must not be folded into A14.
    legislation_corpus_rights_confirmed: bool = False

    @model_validator(mode="after")
    def require_mineru_configuration(self) -> "Settings":
        if self.mineru_enabled and not self.mineru_base_url:
            raise ValueError("MINERU_ENABLED requires MINERU_BASE_URL")
        return self

    @model_validator(mode="after")
    def require_akn_llm_configuration(self) -> "Settings":
        if self.akn_llm_enabled and not (self.akn_llm_base_url and self.akn_llm_model_id):
            raise ValueError("AKN_LLM_ENABLED requires AKN_LLM_BASE_URL and AKN_LLM_MODEL_ID")
        return self

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
    def require_the_rights_review_before_publishing_the_legislation_corpus(self) -> "Settings":
        if self.serve_legislation_corpus and self.environment == "production":
            if not self.legislation_corpus_rights_confirmed:
                raise ValueError(
                    "SERVE_LEGISLATION_CORPUS=true in production requires "
                    "LEGISLATION_CORPUS_RIGHTS_CONFIRMED=true, asserting that the rights review "
                    "has concluded and been recorded in the manual gate log; see ADR-018 and "
                    "ADR-004"
                )
            if self.legislation_publication_mode == "full" and (
                not self.archived_document_rights_confirmed
            ):
                raise ValueError(
                    "LEGISLATION_PUBLICATION_MODE=full in production requires "
                    "ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true: publishing provision text "
                    "republishes the source document's own words, which is the A14 question; "
                    "see ADR-004 and ADR-018"
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

    @field_validator("public_base_url", mode="before")
    @classmethod
    def strip_the_trailing_slash_from_the_public_base(cls, value: object) -> object:
        """`PUBLIC_BASE_URL=https://host/` must not mint `https://host//akn/...`.

        This setting is the base of every published FRBR IRI (ADR-018, ADR-023). A trailing slash
        produced an IRI with a doubled separator that does not dereference to the path the
        application actually serves — and unlike a broken page, a published N-Quads file cannot be
        recalled. Normalising here fixes it once for every consumer instead of at each call site.
        """
        if isinstance(value, str):
            return value.rstrip("/")
        return value

    @field_validator("upstream_ca_bundle", mode="before")
    @classmethod
    def treat_an_empty_variable_as_unset(cls, value: object) -> object:
        """`UPSTREAM_CA_BUNDLE=` means "no bundle", not "a bundle at the empty path".

        `.env.development` ships the variable empty, because it names a decision an operator has
        to make rather than a default. Without this, pydantic reads the empty string as `Path("")`
        — which normalises to `.` — and `reject_unreadable_ca_bundle` then refuses to load *any*
        configuration, so `make env` produced a `.env` that broke every command after it,
        `make quickstart` included.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

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
        if self.rag_enabled and self.rag_provider == "openai_compatible" and not self.rag_base_url:
            raise ValueError("RAG_PROVIDER=openai_compatible requires RAG_BASE_URL")
        if self.environment == "production" and self.embedding_provider == "deterministic":
            raise ValueError("the deterministic embedding provider is for development only")
        if self.environment == "production" and self.rag_provider == "echo":
            raise ValueError("the echo answer provider is for development only")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
