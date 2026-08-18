from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from billwatcher.db import Base
from billwatcher.models import Bill, BillSlugAlias
from billwatcher.scraper.ingest import ingest_listing
from billwatcher.scraper.parse_listing import parse_listing
from billwatcher.web.app import create_app

FIXTURE = Path("tests/fixtures/parliament/current_dr_bm.html")
URL = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr"
NOW = datetime(2026, 8, 17, tzinfo=UTC)


def client(*, malicious: bool = False, **settings: object) -> TestClient:
    """A seeded app. Keyword settings override configuration for the app under test."""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        ingest_listing(
            session,
            parse_listing(FIXTURE.read_text(), source_url=URL),
            chamber="dewan_rakyat",
            language="ms",
            source_url=URL,
            snapshot_id="snapshot",
            run_id="run",
            checked_at=NOW,
        )
        bill = session.scalar(select(Bill))
        assert bill is not None
        if malicious:
            bill.title_bm = "</script><script>alert(1)</script>"
        session.add(BillSlugAlias(slug="old-dr-15-2026", bill_id=bill.id, reason="test alias"))
        session.commit()
    from billwatcher.config import Settings

    return TestClient(create_app(factory, Settings(**settings) if settings else None))


def test_public_pages_are_server_rendered_and_no_javascript_required() -> None:
    with client() as browser:
        home = browser.get("/")
        assert home.status_code == 200
        assert "<h1>Search Malaysian Parliament bills</h1>" in home.text
        assert 'method="get"' in home.text
        assert "<script src=" not in home.text

        index = browser.get("/bills")
        assert index.status_code == 200
        assert "D.R.15/2026" in index.text
        assert '<label for="chamber">Chamber</label>' in index.text

        search = browser.get("/search", params={"q": "Perlindungan"})
        assert search.status_code == 200
        assert "1 result" in search.text


def test_detail_provenance_json_ld_and_alias_redirect() -> None:
    with client() as browser:
        detail = browser.get("/bills/dr-15-2026")
        assert detail.status_code == 200
        assert detail.text.count("<h1") == 1
        assert "Official listing" in detail.text
        assert "Last checked" in detail.text
        assert "Parliamentary observations" in detail.text
        assert '"@type": "Legislation"' in detail.text
        assert '"legislationLegalForce"' not in detail.text

        alias = browser.get("/bills/old-dr-15-2026", follow_redirects=False)
        assert alias.status_code == 308
        assert alias.headers["location"] == "/bills/dr-15-2026"


def test_invalid_filters_are_helpful_400_responses() -> None:
    with client() as browser:
        response = browser.get("/bills", params={"chamber": "commons"})
        assert response.status_code == 400
        assert "Unknown chamber filter" in response.text
        assert "Request ID" in response.text


def test_health_status_api_and_cache_validator() -> None:
    with client() as browser:
        assert browser.get("/health/live").json() == {"status": "ok"}
        assert browser.get("/health/ready").json() == {"status": "ready"}
        status = browser.get("/status")
        assert status.status_code == 200
        assert "Pipeline versions" in status.text
        assert "postgresql" not in status.text.casefold()

        listing = browser.get("/api/v1/bills")
        assert listing.status_code == 200
        assert listing.json()["pagination"]["total"] == 1
        detail = browser.get("/api/v1/bills/DR-15-2026")
        assert detail.status_code == 200
        etag = detail.headers["etag"]
        unchanged = browser.get("/api/v1/bills/DR-15-2026", headers={"If-None-Match": etag})
        assert unchanged.status_code == 304


def test_json_ld_escapes_script_breaking_title() -> None:
    with client(malicious=True) as browser:
        detail = browser.get("/bills/dr-15-2026")
        assert detail.status_code == 200
        assert "</script><script>alert(1)" not in detail.text
        assert "\\u003c/script\\u003e\\u003cscript\\u003ealert(1)" in detail.text


def test_changes_feed_separates_parliament_from_our_own_corrections() -> None:
    with client() as browser:
        page = browser.get("/changes")
        assert page.status_code == 200
        assert "does not mean Parliament changed its position" in page.text
        assert '<label for="kind">Change type</label>' in page.text
        assert '<label for="chamber">Chamber</label>' in page.text

        assert browser.get("/changes", params={"kind": "record"}).status_code == 200
        assert browser.get("/changes", params={"kind": "document_version"}).status_code == 200

        bad_kind = browser.get("/changes", params={"kind": "everything"})
        assert bad_kind.status_code == 400
        assert "Unknown change type" in bad_kind.text
        bad_chamber = browser.get("/changes", params={"chamber": "senate"})
        assert bad_chamber.status_code == 400


def test_search_results_carry_a_bounded_highlighted_passage() -> None:
    with client() as browser:
        results = browser.get("/search", params={"q": "Perlindungan"})
        assert results.status_code == 200
        assert "<mark>Perlindungan</mark>" in results.text
        assert "From this bill’s listing metadata." in results.text


def test_language_filter_is_applied_not_merely_validated() -> None:
    with client() as browser:
        malay = browser.get("/bills", params={"lang": "bm"})
        assert malay.status_code == 200
        assert "D.R.15/2026" in malay.text
        english = browser.get("/bills", params={"lang": "en"})
        assert english.status_code == 200
        assert "D.R.15/2026" not in english.text
        assert "No bills match these filters" in english.text
