from pathlib import Path

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import (
    Anomaly,
    Bill,
    CoverageTarget,
    FetchAttempt,
    PresenceObservation,
    RecordChange,
    ScrapeRun,
    SourceSnapshot,
)
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.policy import CrawlPolicy
from billwatcher.scraper.queue import CrawlBudget
from billwatcher.scraper.worker import ScrapeOrchestrator
from billwatcher.storage.blobs import BlobStore

FIXTURES = Path("tests/fixtures/parliament")
POLICY = CrawlPolicy("BillWatcherNext/0.1 (+https://example.org/about)")


def transport(robots: bytes = b"User-agent: *\nAllow: /\n") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                content=robots,
                headers={"Content-Type": "text/plain"},
                request=request,
            )
        chamber = "dn" if request.url.params.get("uweb") == "dn" else "dr"
        archived = request.url.params.get("arkib") == "yes"
        name = f"{'archive' if archived else 'current'}_{chamber}_bm.html"
        return httpx.Response(
            200,
            content=(FIXTURES / name).read_bytes(),
            headers={"Content-Type": "text/html; charset=utf-8"},
            request=request,
        )

    return httpx.MockTransport(handler)


def missing_robots(status_code: int = 404) -> httpx.MockTransport:
    """A site that publishes no robots.txt, answering with an HTML error page."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                status_code,
                content=b"<html><head><title>404 Not Found</title></head><body>"
                b"<h1>Not Found</h1></body></html>",
                headers={"Content-Type": "text/html"},
                request=request,
            )
        chamber = "dn" if request.url.params.get("uweb") == "dn" else "dr"
        archived = request.url.params.get("arkib") == "yes"
        name = f"{'archive' if archived else 'current'}_{chamber}_bm.html"
        return httpx.Response(
            200,
            content=(FIXTURES / name).read_bytes(),
            headers={"Content-Type": "text/html; charset=utf-8"},
            request=request,
        )

    return httpx.MockTransport(handler)


def orchestrator(
    database: Session,
    tmp_path: Path,
    upstream: httpx.MockTransport,
    *,
    allow_missing_robots: bool = False,
) -> ScrapeOrchestrator:
    fetcher = Fetcher(POLICY, transport=upstream, sleep=lambda _delay: None)
    return ScrapeOrchestrator(
        session=database,
        fetcher=fetcher,
        blob_store=BlobStore(tmp_path),
        budget=CrawlBudget(20, 1_000_000, 60, 20),
        sleep=lambda _delay: None,
        allow_missing_robots=allow_missing_robots,
    )


def test_full_orchestration_is_auditable_and_idempotent(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        first = orchestrator(database, tmp_path, transport()).run(mode="full")
        database.flush()
        assert first.state == "succeeded"
        assert first.publish_decision == "published"
        assert first.fetched == 5
        assert first.parsed == 4
        assert database.scalar(select(func.count()).select_from(Bill)) == 3
        assert database.scalar(select(func.count()).select_from(CoverageTarget)) == 4
        assert database.scalar(select(func.count()).select_from(FetchAttempt)) == 5
        assert database.scalar(select(func.count()).select_from(SourceSnapshot)) == 5
        assert database.scalar(select(func.count()).select_from(PresenceObservation)) == 3

        second = orchestrator(database, tmp_path, transport()).run()
        database.flush()
        assert second.state == "succeeded"
        assert database.scalar(select(func.count()).select_from(Bill)) == 3
        assert database.scalar(select(func.count()).select_from(RecordChange)) == 0
        assert database.scalar(select(func.count()).select_from(ScrapeRun)) == 2
        assert database.scalar(select(func.count()).select_from(PresenceObservation)) == 3


def test_new_document_budget_rolls_back_listing_publication(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        fetcher = Fetcher(POLICY, transport=transport(), sleep=lambda _delay: None)
        worker = ScrapeOrchestrator(
            session=database,
            fetcher=fetcher,
            blob_store=BlobStore(tmp_path),
            budget=CrawlBudget(20, 1_000_000, 60, 0),
            sleep=lambda _delay: None,
        )
        run = worker.run()
        database.flush()
        assert run.state == "partial"
        assert run.publish_decision == "withheld"
        assert database.scalar(select(func.count()).select_from(Bill)) == 0


def test_late_target_failure_withholds_all_domain_publication(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    normal = transport()

    def fail_last(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("uweb") == "dn" and request.url.params.get("arkib") == "yes":
            return httpx.Response(503, request=request)
        return normal.handle_request(request)

    with Session(engine) as database:
        run = orchestrator(database, tmp_path, httpx.MockTransport(fail_last)).run(mode="full")
        database.flush()
        assert run.state == "failed"
        assert run.publish_decision == "withheld"
        assert database.scalar(select(func.count()).select_from(Bill)) == 0
        assert database.scalar(select(func.count()).select_from(PresenceObservation)) == 0
        assert database.scalar(select(func.count()).select_from(SourceSnapshot)) == 5


def test_changed_robots_stops_before_listings_and_raises_critical(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        assert orchestrator(database, tmp_path, transport()).run().state == "succeeded"
        changed = b"User-agent: *\nDisallow: /private\n"
        second = orchestrator(database, tmp_path, transport(changed)).run()
        database.flush()
        assert second.state == "failed"
        assert second.publish_decision == "withheld"
        assert second.fetched == 1
        anomaly = database.scalar(select(Anomaly).where(Anomaly.kind == "robots_changed"))
        assert anomaly is not None
        assert anomaly.severity == "critical"


def test_robots_denial_stops_without_publishing(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        denied = b"User-agent: *\nDisallow: /\n"
        run = orchestrator(database, tmp_path, transport(denied)).run()
        assert run.state == "failed"
        assert run.publish_decision == "withheld"
        assert database.scalar(select(func.count()).select_from(Bill)) == 0


def test_an_error_page_is_never_mistaken_for_permission_to_crawl(tmp_path) -> None:
    """A 404 body parses to an empty ruleset, which would read as "crawl anything"."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        run = orchestrator(database, tmp_path, missing_robots()).run()
        assert run.state == "failed"
        assert run.publish_decision == "withheld"
        assert "robots.txt returned 404" in (run.publish_reason or "")
        # Nothing was published from the listings behind that missing policy.
        assert database.scalar(select(func.count()).select_from(Bill)) == 0


def test_a_gateway_error_on_robots_also_stops_the_run(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        run = orchestrator(database, tmp_path, missing_robots(503)).run()
        assert run.state == "failed"
        assert "robots.txt returned 503" in (run.publish_reason or "")
        assert database.scalar(select(func.count()).select_from(Bill)) == 0


def test_a_gateway_error_is_not_excused_by_the_missing_robots_decision(tmp_path) -> None:
    """Allowing an absent policy must not also excuse a server that is simply broken."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        run = orchestrator(database, tmp_path, missing_robots(503), allow_missing_robots=True).run()
        assert run.state == "failed"
        assert "robots.txt returned 503" in (run.publish_reason or "")


def test_a_recorded_decision_permits_crawling_a_site_with_no_robots(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        run = orchestrator(database, tmp_path, missing_robots(), allow_missing_robots=True).run()
        assert run.state == "succeeded"
        assert database.scalar(select(func.count()).select_from(Bill)) > 0
        # The decision is visible rather than silent.
        anomaly = database.scalar(select(Anomaly).where(Anomaly.kind == "robots_changed"))
        assert anomaly is not None
        assert anomaly.severity == "critical"
        assert anomaly.detail_json["status_code"] == 404
