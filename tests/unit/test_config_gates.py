"""The retention promise on /ask is enforced by configuration, not only documented (ADR-009)."""

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
    rag_provider="anthropic",
)


def test_production_rag_requires_the_retention_arrangement_to_be_asserted() -> None:
    with pytest.raises(ValueError, match="RAG_ZERO_RETENTION_CONFIRMED"):
        Settings(**BASE, rag_model_id="claude-opus-5")

    ok = Settings(**BASE, rag_model_id="claude-opus-5", rag_zero_retention_confirmed=True)
    assert ok.rag_enabled


@pytest.mark.parametrize("model", ["claude-fable-5", "claude-mythos-5"])
def test_a_model_that_requires_retention_is_refused_outright(model: str) -> None:
    """Not even an operator assertion may enable it: the model itself forbids zero retention."""
    with pytest.raises(ValueError, match="30-day data retention"):
        Settings(**BASE, rag_model_id=model, rag_zero_retention_confirmed=True)


def test_development_does_not_need_the_assertion() -> None:
    settings = Settings(
        **{**BASE, "environment": "development"},
        rag_model_id="claude-opus-5",
    )
    assert settings.rag_enabled
    assert settings.rag_zero_retention_confirmed is False


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
