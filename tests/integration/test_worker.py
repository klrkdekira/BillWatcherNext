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
from billwatcher.operations import evaluate_coverage
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.policy import CrawlPolicy
from billwatcher.scraper.queue import CrawlBudget
from billwatcher.scraper.worker import ScrapeOrchestrator
from billwatcher.storage.blobs import FilesystemBlobStore

FIXTURES = Path("tests/fixtures/parliament")
POLICY = CrawlPolicy("BillWatcherNext/0.1 (+https://example.org/about)")


# The archive is a tree fetched as XML: an index of years, then one document per year
# (ADR-014). The reduced index offers 2024 and 2011, so a full run reads four archived years —
# two chambers times two years — on top of the two current listings.
ARCHIVE_YEARS = {"2024": "archive_year_dr_2024.xml", "2011": "archive_year_dn_2011.xml"}


def upstream_document(request: httpx.Request) -> httpx.Response:
    """Answer a listing request with the committed fixture for that exact upstream document."""
    params = request.url.params
    chamber = "dn" if params.get("uweb") == "dn" else "dr"
    if params.get("arkib") == "yes":
        if params.get("ajx") == "0":
            name = "archive_index_dr.xml"
        else:
            year = (params.get("id") or "").removeprefix("0_")
            name = ARCHIVE_YEARS[year]
        media_type = "text/xml"
    else:
        name = f"current_{chamber}_bm.html"
        media_type = "text/html"
    return httpx.Response(
        200,
        content=(FIXTURES / name).read_bytes(),
        headers={"Content-Type": f"{media_type}; charset=utf-8"},
        request=request,
    )


def transport(robots: bytes = b"User-agent: *\nAllow: /\n") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                content=robots,
                headers={"Content-Type": "text/plain"},
                request=request,
            )
        return upstream_document(request)

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
        return upstream_document(request)

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
        blob_store=FilesystemBlobStore(tmp_path),
        budget=CrawlBudget(20, 1_000_000, 60, 20),
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
        # One robots.txt, two current listings, two archive indexes, and the two archived years
        # each index offers.
        assert first.fetched == 9
        assert first.parsed == 18
        assert database.scalar(select(func.count()).select_from(Bill)) == 9
        # Two current listings, two archive indexes, and one row per archived year per chamber,
        # so a single unreadable year is visible on `/status` instead of hiding in an average.
        assert database.scalar(select(func.count()).select_from(CoverageTarget)) == 8
        assert database.scalar(select(func.count()).select_from(FetchAttempt)) == 9
        assert database.scalar(select(func.count()).select_from(SourceSnapshot)) == 9
        assert database.scalar(select(func.count()).select_from(PresenceObservation)) == 9
        assert database.scalar(select(func.count()).select_from(Anomaly)) == 0

        second = orchestrator(database, tmp_path, transport()).run(mode="full")
        database.flush()
        assert second.state == "succeeded"
        assert database.scalar(select(func.count()).select_from(Bill)) == 9
        # The whole point: re-reading every current listing and every archived year changes
        # nothing (HANDOFF 22, change tracking).
        assert database.scalar(select(func.count()).select_from(RecordChange)) == 0
        assert database.scalar(select(func.count()).select_from(ScrapeRun)) == 2
        # Presence is one observation per bill per published full run, so a second run adds a
        # second round of observations rather than overwriting the first.
        assert database.scalar(select(func.count()).select_from(PresenceObservation)) == 18


def test_new_document_budget_rolls_back_listing_publication(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        fetcher = Fetcher(POLICY, transport=transport(), sleep=lambda _delay: None)
        worker = ScrapeOrchestrator(
            session=database,
            fetcher=fetcher,
            blob_store=FilesystemBlobStore(tmp_path),
            budget=CrawlBudget(20, 1_000_000, 60, 0),
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
        assert database.scalar(select(func.count()).select_from(SourceSnapshot)) == 7


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
        # The decision is visible rather than silent, but it is a standing condition and must
        # not permanently fail the release gate.
        anomaly = database.scalar(select(Anomaly).where(Anomaly.kind == "robots_absent"))
        assert anomaly is not None
        assert anomaly.severity == "warn"
        assert anomaly.detail_json["status_code"] == 404
        assert not database.scalars(select(Anomaly).where(Anomaly.kind == "robots_changed")).all()


def broken_archive() -> httpx.MockTransport:
    """Current listings work; the archive answers with something that is not a listing.

    This is the real upstream shape: `?arkib=yes` returns a search form, not a table of bills.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nAllow: /\n", request=request)
        if request.url.params.get("arkib") == "yes":
            return httpx.Response(
                200,
                content=b'<html><body><form action="carian.html" method="get">'
                b'<table width="100%"><tr><th>Kembali Ke Senarai</th></tr></table>'
                b"</form></body></html>",
                headers={"Content-Type": "text/html"},
                request=request,
            )
        chamber = "dn" if request.url.params.get("uweb") == "dn" else "dr"
        return httpx.Response(
            200,
            content=(FIXTURES / f"current_{chamber}_bm.html").read_bytes(),
            headers={"Content-Type": "text/html; charset=utf-8"},
            request=request,
        )

    return httpx.MockTransport(handler)


def test_an_unreadable_archive_does_not_block_the_current_listings(tmp_path) -> None:
    """HANDOFF 10.4: per-target state exists so one broken target is visible, not blocking."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        run = orchestrator(database, tmp_path, broken_archive()).run(mode="full")
        database.flush()

        assert run.state == "partial"
        assert run.publish_decision == "published"
        assert "archive" in (run.publish_reason or "")
        assert run.failed == 2
        # The current listings published.
        assert database.scalar(select(func.count()).select_from(Bill)) > 0

        targets = {
            (target.chamber, target.listing_kind): target
            for target in database.scalars(select(CoverageTarget))
        }
        evaluate_coverage(database)
        database.flush()
        assert targets[("dewan_rakyat", "current")].state == "healthy"
        assert targets[("dewan_rakyat", "archive")].state == "failing"
        assert targets[("dewan_negara", "archive")].state == "failing"

        anomalies = database.scalars(
            select(Anomaly).where(Anomaly.kind == "listing_unavailable")
        ).all()
        assert len(anomalies) == 2
        assert all(anomaly.severity == "warn" for anomaly in anomalies)
        # Absence evidence needs a complete run, so an incomplete one records none.
        assert database.scalar(select(func.count()).select_from(PresenceObservation)) == 0


def test_a_broken_current_listing_still_fails_the_whole_run(tmp_path) -> None:
    """The current listings are the product; a parse failure there withholds everything."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nAllow: /\n", request=request)
        return httpx.Response(
            200,
            content=b"<html><body><h1>Ralat</h1></body></html>",
            headers={"Content-Type": "text/html"},
            request=request,
        )

    with Session(engine) as database:
        run = orchestrator(database, tmp_path, httpx.MockTransport(handler)).run()
        database.flush()
        assert run.state == "failed"
        assert run.publish_decision == "withheld"
        assert database.scalar(select(func.count()).select_from(Bill)) == 0


def test_an_error_status_is_never_handed_to_the_parser(tmp_path) -> None:
    """A 5xx body is not a listing; the state is unknown, so nothing publishes."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    normal = transport()

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("arkib") == "yes":
            return httpx.Response(503, content=b"<html>busy</html>", request=request)
        return normal.handle_request(request)

    with Session(engine) as database:
        run = orchestrator(database, tmp_path, httpx.MockTransport(flaky)).run(mode="full")
        database.flush()
        assert run.state == "failed"
        assert "returned 503" in (run.publish_reason or "")
        assert database.scalar(select(func.count()).select_from(Bill)) == 0
