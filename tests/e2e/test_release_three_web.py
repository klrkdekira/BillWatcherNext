"""Release 3 routes stay invisible until configured, and degrade cleanly (HANDOFF 12.3, 13)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from billwatcher.config import Settings
from billwatcher.db import Base
from billwatcher.jobs.rechunk import run_rechunk
from billwatcher.jobs.reembed import run_reembed
from billwatcher.search.embeddings import DeterministicEmbeddingProvider
from billwatcher.web.app import create_app
from tests.integration.test_semantic import MODEL, ROADS, WITNESS, seed_document

ENABLED = Settings(
    semantic_search_enabled=True,
    embedding_provider="deterministic",
    embedding_model_id=MODEL,
    rag_enabled=True,
    rag_provider="echo",
    rag_model_id="echo",
)


def build(settings: Settings) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        seed_document(session, code="DR-15-2026", number=15, text=WITNESS)
        seed_document(session, code="DR-16-2026", number=16, text=ROADS)
        run_rechunk(session, dry_run=False, limit=50)
        run_reembed(session, provider=DeterministicEmbeddingProvider(MODEL), dry_run=False)
        session.commit()
    with TestClient(create_app(factory, settings=settings)) as client:
        yield client


@pytest.fixture
def enabled() -> Iterator[TestClient]:
    yield from build(ENABLED)


@pytest.fixture
def disabled() -> Iterator[TestClient]:
    yield from build(Settings())


def test_release_three_routes_are_absent_when_the_flags_are_off(disabled: TestClient) -> None:
    assert disabled.get("/semantic-search").status_code == 404
    assert disabled.get("/ask").status_code == 404
    assert disabled.post("/ask", data={"question": "apa itu"}).status_code == 404
    assert disabled.post("/api/v1/ask", json={"question": "apa itu"}).status_code == 404
    # The ordinary site is unaffected by the kill switches.
    assert disabled.get("/bills").status_code == 200
    assert disabled.get("/search", params={"q": "perlindungan"}).status_code == 200


def test_semantic_search_renders_version_pinned_passages(enabled: TestClient) -> None:
    page = enabled.get("/semantic-search", params={"q": "perlindungan saksi"})
    assert page.status_code == 200
    assert "D.R.15/2026" in page.text
    assert "our copy retrieved" in page.text
    assert "Official document" in page.text
    assert "Keyword search remains available" in page.text


def test_semantic_search_rejects_an_unknown_filter(enabled: TestClient) -> None:
    bad = enabled.get("/semantic-search", params={"q": "saksi", "chamber": "senate"})
    assert bad.status_code == 400


def test_ask_returns_a_cited_answer_over_html_and_json(enabled: TestClient) -> None:
    form = enabled.get("/ask")
    assert form.status_code == 200
    assert "not legal advice" in form.text

    html = enabled.post("/ask", data={"question": "Apakah perlindungan saksi?"})
    assert html.status_code == 200
    assert "Sources" in html.text
    assert "our copy retrieved" in html.text.lower() or "retrieved" in html.text

    payload = enabled.post("/api/v1/ask", json={"question": "Apakah perlindungan saksi?"}).json()
    assert payload["schema_version"] == "v1"
    assert payload["status"] == "answered"
    assert payload["citations"]
    citation = payload["citations"][0]
    assert citation["document_version"] == 1
    assert citation["our_copy_retrieved_at"].startswith("2026-08-17")
    assert citation["official_document_url"].startswith("https://www.parlimen.gov.my/")
    assert citation["current_version"] is True
    assert "not legal advice" in payload["disclaimer"]


def test_ask_is_rate_limited_while_browsing_is_not(enabled: TestClient) -> None:
    statuses = [
        enabled.post("/api/v1/ask", json={"question": f"Soalan {index}"}).status_code
        for index in range(8)
    ]
    assert 429 in statuses
    assert enabled.get("/bills").status_code == 200
    assert enabled.get("/search", params={"q": "perlindungan"}).status_code == 200


def test_an_overlong_question_is_a_helpful_400(enabled: TestClient) -> None:
    response = enabled.post("/api/v1/ask", json={"question": "a" * 5_000})
    assert response.status_code == 400
    assert "must not exceed" in response.json()["error"]
