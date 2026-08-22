"""Shared fixtures.

The offline suite runs entirely on SQLite. PostgreSQL-only behaviour (the weighted tsvector,
`websearch_to_tsquery`, `ts_headline`, and pgvector) is exercised only when a disposable test
database is supplied through BILLWATCHER_TEST_DATABASE_URL, and skips with a clear message
otherwise.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text

POSTGRES_URL_ENV = "BILLWATCHER_TEST_DATABASE_URL"

# Every `Settings` field, as the environment variable that sets it: a developer's .env or shell
# may define any of them, and any of them would then change what a test asserts. Listed rather
# than derived from `Settings.model_fields` so that the set a test runs against is readable here,
# in declaration order; `test_config_gates.py` fails when a new field is not added.
_LEAKY_SETTINGS = (
    "ENVIRONMENT",
    "SITE_HOST",
    "PUBLIC_BASE_URL",
    "CONTACT_EMAIL",
    "DATABASE_URL",
    "BLOB_STORAGE_ROOT",
    "AUDIT_TREE_ROOT",
    "PIPELINE_DATA_ROOT",
    "BLOB_STORAGE_BACKEND",
    "S3_ENDPOINT_URL",
    "S3_BUCKET",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "S3_REGION",
    "SERVE_ARCHIVED_DOCUMENTS",
    "ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED",
    "HSTS_MAX_AGE_SECONDS",
    "SCRAPE_ENABLED",
    "SCRAPE_INTERVAL_HOURS",
    "SCRAPE_DELAY_SECONDS",
    "SCRAPE_CONCURRENCY",
    "SCRAPE_MAX_REQUESTS_PER_RUN",
    "SCRAPE_MAX_BYTES_PER_RUN",
    "SCRAPE_MAX_DURATION_SECONDS",
    "SCRAPE_MAX_NEW_DOCUMENTS",
    "ARCHIVE_MAX_REQUESTS_PER_RUN",
    "ARCHIVE_MAX_BYTES_PER_RUN",
    "ARCHIVE_MAX_DURATION_SECONDS",
    "ARCHIVE_MAX_NEW_DOCUMENTS",
    "DOCUMENT_MAX_BYTES",
    "UPSTREAM_CA_BUNDLE",
    "ROBOTS_MISSING_POLICY",
    "ABSENCE_STREAK_ALERT",
    "COUNT_DROP_ABORT_FRACTION",
    "FETCH_ATTEMPT_RETENTION_DAYS",
    "SEMANTIC_SEARCH_ENABLED",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL_ID",
    "SEMANTIC_CANDIDATES",
    "HYBRID_RRF_K",
    "QUERY_EMBEDDING_CACHE_SIZE",
    "RAG_ENABLED",
    "RAG_PROVIDER",
    "RAG_MODEL_ID",
    "RAG_BASE_URL",
    "RAG_API_KEY",
    "RAG_MAX_CONTEXT_CHUNKS",
    "RAG_MAX_QUESTION_CHARS",
    "RAG_MIN_RETRIEVAL_SCORE",
    "RAG_TIMEOUT_SECONDS",
    "MINERU_ENABLED",
    "MINERU_BASE_URL",
    "MINERU_MODEL_NAME",
    "MINERU_API_KEY",
    "MINERU_RENDER_DPI",
    "MINERU_TIMEOUT_SECONDS",
    "AKN_LLM_ENABLED",
    "AKN_LLM_BASE_URL",
    "AKN_LLM_MODEL_ID",
    "AKN_LLM_API_KEY",
    "AKN_LLM_TIMEOUT_SECONDS",
    "AKN_GATE_MIN_TEXT_COVERAGE",
    "SERVE_LEGISLATION_CORPUS",
    "LEGISLATION_PUBLICATION_MODE",
    "LEGISLATION_CORPUS_RIGHTS_CONFIRMED",
)


@pytest.fixture(autouse=True)
def isolate_settings_from_the_local_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must describe their own configuration, never inherit the developer's.

    Without this a populated .env silently changes what a test asserts — a suite that passes
    on one machine and fails on another.
    """
    from billwatcher.config import Settings, get_settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in _LEAKY_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def postgres_url() -> str | None:
    return os.environ.get(POSTGRES_URL_ENV) or None


@pytest.fixture(scope="session")
def postgres_engine() -> Iterator[Engine]:
    url = postgres_url()
    if not url:
        pytest.skip(f"set {POSTGRES_URL_ENV} to a disposable database to run PostgreSQL tests")
    engine = create_engine(url, poolclass=None)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    _upgrade_to_head(url)
    yield engine
    engine.dispose()


def _upgrade_to_head(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    config.attributes["connection_url"] = url
    command.upgrade(config, "head")


S3_ENDPOINT_ENV = "BILLWATCHER_TEST_S3_ENDPOINT"


def s3_endpoint() -> str | None:
    return os.environ.get(S3_ENDPOINT_ENV) or None


@pytest.fixture
def versity_store():  # type: ignore[no-untyped-def]
    """An S3 archive backed by a real VersityGW, skipped unless one is configured.

    `make db-up` starts one on 127.0.0.1:7070; point BILLWATCHER_TEST_S3_ENDPOINT at it.
    """
    endpoint = s3_endpoint()
    if not endpoint:
        pytest.skip(f"set {S3_ENDPOINT_ENV} to run the S3 archive tests against VersityGW")
    import uuid

    from billwatcher.storage.blobs import S3BlobStore

    store = S3BlobStore(
        bucket=f"bwn-test-{uuid.uuid4().hex[:12]}",
        endpoint_url=endpoint,
        access_key_id=os.environ.get("BILLWATCHER_TEST_S3_KEY", "billwatcher"),
        secret_access_key=os.environ.get("BILLWATCHER_TEST_S3_SECRET", "billwatcher-secret"),
    )
    store.ensure_bucket()
    yield store
    for digest in store.stored_digests():
        store.delete(digest)
