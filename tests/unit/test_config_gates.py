"""Production configuration gates that protect operator decisions."""

import pytest

from billwatcher.config import Settings

BASE = dict(
    environment="production",
    site_host="bills.example.my",
    public_base_url="https://bills.example.my",
    contact_email="ops@example.my",
    database_url="postgresql+psycopg://u:p@db/bills",
    semantic_search_enabled=True,
    embedding_provider="bge",
    embedding_model_id="bge-m3",
    rag_enabled=True,
    rag_provider="openai_compatible",
)


def test_openai_compatible_rag_requires_an_endpoint() -> None:
    with pytest.raises(ValueError, match="RAG_BASE_URL"):
        Settings(**BASE, rag_model_id="local-instruct")

    settings = Settings(
        **BASE,
        rag_model_id="local-instruct",
        rag_base_url="http://vllm:8000/v1",
    )
    assert settings.rag_enabled
    assert settings.rag_base_url == "http://vllm:8000/v1"


def test_publishing_stored_documents_in_production_requires_the_rights_review() -> None:
    """ADR-013 calls this a rights decision, "not a configuration change" — so make that true."""
    base = dict(
        environment="production",
        site_host="bills.example.my",
        public_base_url="https://bills.example.my",
        contact_email="ops@example.my",
        database_url="postgresql+psycopg://u:p@db/bills",
    )
    with pytest.raises(ValueError, match="ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED"):
        Settings(**base, serve_archived_documents=True)

    allowed = Settings(
        **base, serve_archived_documents=True, archived_document_rights_confirmed=True
    )
    assert allowed.serve_archived_documents

    # Development is untouched: proving the serving path locally is how ADR-013 was validated.
    local = Settings(**{**base, "environment": "development"}, serve_archived_documents=True)
    assert local.serve_archived_documents
    assert local.archived_document_rights_confirmed is False
