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

# BASE turns the release 3 features on as well; the publication gates below want a bare
# production configuration and nothing else, so that what a test enables is the only thing enabled.
PRODUCTION = dict(
    environment="production",
    site_host="bills.example.my",
    public_base_url="https://bills.example.my",
    contact_email="ops@example.my",
    database_url="postgresql+psycopg://u:p@db/bills",
)


def test_every_setting_is_isolated_from_the_developers_environment() -> None:
    """`_LEAKY_SETTINGS` is hand-maintained; nothing else makes it complete.

    A field missing from it inherits whatever the developer exported, which is how a suite passes
    on one machine and fails on another — the failure mode the autouse fixture exists to prevent.
    Adding a `Settings` field means adding its variable name there, in the same position.
    """
    from tests.conftest import _LEAKY_SETTINGS

    expected = [name.upper() for name in Settings.model_fields]
    assert list(_LEAKY_SETTINGS) == expected


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


def test_serving_the_legislation_corpus_in_production_requires_the_rights_review() -> None:
    """ADR-018 asks for the same hard control the lower-risk archived bytes already have.

    The corpus is a reading of the law rather than a copy of a document, which TODO 1.7 records as
    a higher bar than A14 — so a flag flip must not be enough to publish it.
    """
    with pytest.raises(ValueError, match="LEGISLATION_CORPUS_RIGHTS_CONFIRMED"):
        Settings(**PRODUCTION, serve_legislation_corpus=True)

    allowed = Settings(
        **PRODUCTION, serve_legislation_corpus=True, legislation_corpus_rights_confirmed=True
    )
    assert allowed.serve_legislation_corpus
    # Confirming the rights review does not also opt into republishing the text.
    assert allowed.legislation_publication_mode == "metadata"

    # Development is ungated, for the same reason ADR-013 leaves the archive ungated locally:
    # serving the corpus locally is how the serving path gets validated at all.
    local = Settings(**{**PRODUCTION, "environment": "development"}, serve_legislation_corpus=True)
    assert local.serve_legislation_corpus
    assert local.legislation_corpus_rights_confirmed is False


def test_publishing_provision_text_in_production_needs_the_a14_confirmation_as_well() -> None:
    """`full` republishes the source document's own words, which is the A14 question."""
    with pytest.raises(ValueError, match="ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED"):
        Settings(
            **PRODUCTION,
            serve_legislation_corpus=True,
            legislation_corpus_rights_confirmed=True,
            legislation_publication_mode="full",
        )

    allowed = Settings(
        **PRODUCTION,
        serve_legislation_corpus=True,
        legislation_corpus_rights_confirmed=True,
        legislation_publication_mode="full",
        archived_document_rights_confirmed=True,
    )
    assert allowed.legislation_publication_mode == "full"

    # The A14 confirmation alone does not stand in for the corpus one: the two reviews are
    # separate questions and TODO 1.7 forbids folding one into the other.
    with pytest.raises(ValueError, match="LEGISLATION_CORPUS_RIGHTS_CONFIRMED"):
        Settings(
            **PRODUCTION,
            serve_legislation_corpus=True,
            legislation_publication_mode="full",
            archived_document_rights_confirmed=True,
        )

    local = Settings(
        **{**PRODUCTION, "environment": "development"},
        serve_legislation_corpus=True,
        legislation_publication_mode="full",
    )
    assert local.legislation_publication_mode == "full"


def test_the_publication_mode_is_inert_without_the_serve_flag() -> None:
    """Nothing is published while the corpus is not served, so `full` alone is not a rights act.

    Worth pinning because the alternative reading — refuse any `full` in production — would make
    an operator's dormant, unused setting break the boot of a deployment that publishes nothing.
    """
    settings = Settings(**PRODUCTION, legislation_publication_mode="full")
    assert settings.legislation_publication_mode == "full"
    assert settings.serve_legislation_corpus is False


def test_the_legislation_corpus_ships_off_and_metadata_only() -> None:
    """The defaults are the decision. A mirrored corpus cannot be withdrawn (ADR-018).

    An operator who deploys without reading a line of documentation must end up publishing
    nothing, and — if they enable it — publishing structure rather than the document's text.
    """
    settings = Settings()
    assert settings.serve_legislation_corpus is False
    assert settings.legislation_publication_mode == "metadata"
    assert settings.legislation_corpus_rights_confirmed is False


def test_a_trailing_slash_on_the_public_base_is_normalised_away() -> None:
    assert Settings(public_base_url="https://bills.example.my/").public_base_url == (
        "https://bills.example.my"
    )
    assert Settings(public_base_url="https://bills.example.my///").public_base_url == (
        "https://bills.example.my"
    )
    # A base with no trailing slash, and a path-carrying base, are both left alone.
    assert Settings(public_base_url="https://bills.example.my").public_base_url == (
        "https://bills.example.my"
    )
    assert Settings(public_base_url="https://example.my/bills").public_base_url == (
        "https://example.my/bills"
    )


def test_a_trailing_slash_no_longer_mints_an_undereferenceable_iri() -> None:
    """`PUBLIC_BASE_URL=https://host/` used to produce `https://host//akn/...`.

    Every published FRBR IRI is this setting concatenated with a path from `pipeline.frbr`
    (ADR-018, ADR-023), and a doubled separator names a URL the application does not serve.
    Unlike a broken page, an N-Quads file that is already mirrored cannot be corrected.
    """
    from billwatcher.pipeline.frbr import WorkIdentity

    identity = WorkIdentity(doc_type="bill", chamber_code="dr", year=2026, number=15)
    base = Settings(public_base_url="https://bills.example.my/").public_base_url

    assert base + identity.work_uri == "https://bills.example.my/akn/my/bill/dr/2026/15"
    assert (
        base + identity.expression_uri("ms")
        == "https://bills.example.my/akn/my/bill/dr/2026/15/msa@"
    )
    assert "//akn/" not in base + identity.work_uri


def test_an_empty_ca_bundle_variable_means_unset(monkeypatch) -> None:
    """`make env` ships `UPSTREAM_CA_BUNDLE=` empty; that must load, not refuse to.

    Reading it as `Path("")` made every command fail on a `.env` the project's own `make env`
    had just written, which broke `make quickstart` from a fresh clone.
    """
    from billwatcher.config import Settings

    monkeypatch.setenv("UPSTREAM_CA_BUNDLE", "")
    assert Settings().upstream_ca_bundle is None
    monkeypatch.setenv("UPSTREAM_CA_BUNDLE", "   ")
    assert Settings().upstream_ca_bundle is None


def test_a_ca_bundle_that_names_no_file_is_still_refused(monkeypatch) -> None:
    import pytest

    from billwatcher.config import Settings

    monkeypatch.setenv("UPSTREAM_CA_BUNDLE", "/nonexistent/bundle.pem")
    with pytest.raises(ValueError, match="does not name a file"):
        Settings()


def test_mineru_enabled_requires_a_base_url() -> None:
    with pytest.raises(ValueError, match="MINERU_BASE_URL"):
        Settings(mineru_enabled=True)

    settings = Settings(mineru_enabled=True, mineru_base_url="http://mineru.loqasi.io")
    assert settings.mineru_enabled
    assert settings.mineru_base_url == "http://mineru.loqasi.io"


def test_akn_llm_enabled_requires_a_base_url_and_model_id() -> None:
    with pytest.raises(ValueError, match="AKN_LLM_BASE_URL"):
        Settings(akn_llm_enabled=True)
    with pytest.raises(ValueError, match="AKN_LLM_BASE_URL"):
        Settings(akn_llm_enabled=True, akn_llm_base_url="https://llm.loqasi.io/v1")

    settings = Settings(
        akn_llm_enabled=True,
        akn_llm_base_url="https://llm.loqasi.io/v1",
        akn_llm_model_id="some-model",
    )
    assert settings.akn_llm_enabled
    assert settings.akn_llm_model_id == "some-model"
