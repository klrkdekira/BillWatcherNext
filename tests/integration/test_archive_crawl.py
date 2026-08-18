"""The archive crawl end to end: index, per-year fan-out, coverage, and degradation (ADR-014).

Release 1 requires the archive as well as the current listings. The archive is a tree fetched as
XML — an index of years, then one document per year — so the crawl reads many more targets than
the two current listings, and each has to be visible on its own coverage row.
"""

from pathlib import Path

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import (
    Anomaly,
    Bill,
    BillEvent,
    ChamberRecord,
    CoverageTarget,
    FetchQueueItem,
    RecordChange,
    SourceSnapshot,
)
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.policy import CrawlPolicy
from billwatcher.scraper.queue import CrawlBudget
from billwatcher.scraper.worker import ScrapeOrchestrator, archive_year_url
from billwatcher.storage.blobs import FilesystemBlobStore
from tests.integration.test_worker import upstream_document

FIXTURES = Path("tests/fixtures/parliament")
POLICY = CrawlPolicy("BillWatcherNext/0.1 (+https://example.org/about)")


def transport(
    override: dict[str, httpx.Response] | None = None,
    edge_case_year: str | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                content=b"User-agent: *\nAllow: /\n",
                headers={"Content-Type": "text/plain"},
                request=request,
            )
        year = (request.url.params.get("id") or "").removeprefix("0_")
        if override and year in override:
            response = override[year]
            return httpx.Response(response.status_code, content=response.content, request=request)
        if edge_case_year and year == edge_case_year:
            return httpx.Response(
                200,
                content=(FIXTURES / "archive_year_edge_cases.xml").read_bytes(),
                headers={"Content-Type": "text/xml"},
                request=request,
            )
        return upstream_document(request)

    return httpx.MockTransport(handler)


def crawl(
    database: Session,
    tmp_path: Path,
    upstream: httpx.MockTransport,
    *,
    mode: str = "archive",
    archive_year_limit: int | None = None,
):
    fetcher = Fetcher(POLICY, transport=upstream, sleep=lambda _delay: None)
    return ScrapeOrchestrator(
        session=database,
        fetcher=fetcher,
        blob_store=FilesystemBlobStore(tmp_path),
        budget=CrawlBudget(40, 5_000_000, 60, 40),
        archive_year_limit=archive_year_limit,
    ).run(mode=mode)


def database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_archive_mode_reads_every_year_and_leaves_the_current_listings_alone(tmp_path) -> None:
    with database() as session:
        run = crawl(session, tmp_path, transport())
        session.flush()
        assert run.state == "succeeded"
        assert run.publish_decision == "published"
        # robots.txt, one index per chamber, and the two years each index offers.
        assert run.fetched == 7

        coverage = {
            (row.chamber, row.listing_kind, row.scope_key): row
            for row in session.scalars(select(CoverageTarget))
        }
        assert set(coverage) == {
            ("dewan_rakyat", "archive", ""),
            ("dewan_rakyat", "archive", "2024"),
            ("dewan_rakyat", "archive", "2011"),
            ("dewan_negara", "archive", ""),
            ("dewan_negara", "archive", "2024"),
            ("dewan_negara", "archive", "2011"),
        }
        assert all(row.state == "healthy" for row in coverage.values())
        # The index's record count is the years it offered, not bills.
        assert coverage[("dewan_rakyat", "archive", "")].last_record_count == 2
        assert coverage[("dewan_rakyat", "archive", "2024")].last_record_count == 4
        # The newest archived year can still gain bills, so it has a freshness expectation. 2011
        # has closed and cannot change, so it has none: an interval of zero means staleness does
        # not apply, which keeps 66 immutable years off the alert list.
        assert coverage[("dewan_rakyat", "archive", "2024")].expected_interval_hours == 720
        assert coverage[("dewan_rakyat", "archive", "2011")].expected_interval_hours == 0
        assert coverage[("dewan_rakyat", "archive", "")].expected_interval_hours == 168

        # Archived bills are published with their readings and their documents queued.
        bills = session.scalars(select(Bill)).all()
        assert {bill.identifier_normalized for bill in bills} == {
            "DR-17-2024",
            "DR-18-2024",
            "DR-20-2024",
            "DR-21-2024",
            "DR-15-2011",
            "DR-32-2011",
            "DR-1-2011",
            "DR-2-2011",
        }
        assert session.scalar(select(func.count()).select_from(BillEvent)) > 0
        assert session.scalar(select(func.count()).select_from(FetchQueueItem)) > 0
        assert session.scalar(select(func.count()).select_from(Anomaly)) == 0

        # Each archived bill's provenance is the year document it came from, not the index.
        record = session.scalars(
            select(ChamberRecord).join(Bill).where(Bill.identifier_normalized == "DR-17-2024")
        ).first()
        assert record is not None
        assert record.source_url.endswith("ajx=1&id=0_2024")


def test_re_reading_the_archive_changes_nothing(tmp_path) -> None:
    with database() as session:
        crawl(session, tmp_path, transport())
        session.flush()
        bills = session.scalar(select(func.count()).select_from(Bill))
        events = session.scalar(select(func.count()).select_from(BillEvent))

        second = crawl(session, tmp_path, transport())
        session.flush()
        assert second.state == "succeeded"
        assert session.scalar(select(func.count()).select_from(Bill)) == bills
        assert session.scalar(select(func.count()).select_from(BillEvent)) == events
        assert session.scalar(select(func.count()).select_from(RecordChange)) == 0


def test_one_unreadable_year_degrades_only_that_year(tmp_path) -> None:
    broken = {"2011": httpx.Response(200, content=b"<html><body>Service unavailable</body></html>")}
    with database() as session:
        run = crawl(session, tmp_path, transport(override=broken))
        session.flush()
        # The rest of the archive publishes; the run says it is incomplete.
        assert run.state == "partial"
        assert run.publish_decision == "published"
        assert "2011" in (run.publish_reason or "") or "archive" in (run.publish_reason or "")
        assert {bill.identifier_normalized for bill in session.scalars(select(Bill))} == {
            "DR-17-2024",
            "DR-18-2024",
            "DR-20-2024",
            "DR-21-2024",
        }
        states = {
            (row.chamber, row.scope_key): row.state
            for row in session.scalars(select(CoverageTarget))
        }
        assert states[("dewan_rakyat", "2011")] == "failing"
        assert states[("dewan_rakyat", "2024")] == "healthy"
        assert states[("dewan_rakyat", "")] == "healthy"
        anomaly = session.scalar(select(Anomaly).where(Anomaly.kind == "listing_unavailable"))
        assert anomaly is not None
        assert anomaly.detail_json["scope"] == "2011"


def test_an_unreadable_index_fails_the_run_because_the_archive_state_is_unknown(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nAllow: /\n", request=request)
        if request.url.params.get("ajx") == "0":
            return httpx.Response(503, request=request)
        return upstream_document(request)

    with database() as session:
        run = crawl(session, tmp_path, httpx.MockTransport(handler))
        session.flush()
        assert run.state == "failed"
        assert run.publish_decision == "withheld"
        assert session.scalar(select(func.count()).select_from(Bill)) == 0
        # The failed fetch is still recorded, so the failure is auditable.
        assert session.scalar(select(func.count()).select_from(SourceSnapshot)) == 2


def test_a_year_limit_reads_only_the_newest_years(tmp_path) -> None:
    with database() as session:
        run = crawl(session, tmp_path, transport(), archive_year_limit=1)
        session.flush()
        assert run.state == "succeeded"
        # robots.txt, two indexes, and one year per chamber.
        assert run.fetched == 5
        scopes = {row.scope_key for row in session.scalars(select(CoverageTarget))}
        assert scopes == {"", "2024"}


def test_incremental_mode_never_touches_the_archive(tmp_path) -> None:
    with database() as session:
        run = crawl(session, tmp_path, transport(), mode="incremental")
        session.flush()
        assert run.state == "succeeded"
        # robots.txt and the two current listings only.
        assert run.fetched == 3
        assert {row.listing_kind for row in session.scalars(select(CoverageTarget))} == {"current"}


def test_malformed_archive_rows_raise_warnings_and_still_publish(tmp_path) -> None:
    with database() as session:
        run = crawl(session, tmp_path, transport(edge_case_year="2011"))
        session.flush()
        assert run.state == "succeeded"
        kinds = {anomaly.kind: anomaly.severity for anomaly in session.scalars(select(Anomaly))}
        assert kinds == {"unparseable_identifier": "warn", "unparseable_date": "warn"}
        # The rows that did parse are published, including the bill whose second reading was
        # dated 30/11/-0001: the reading is missing, the bill is not.
        bill = session.scalar(select(Bill).where(Bill.identifier_normalized == "DR-2-2015"))
        assert bill is not None
        readings = session.scalars(select(BillEvent).where(BillEvent.bill_id == bill.id)).all()
        assert {event.event_type for event in readings} == {
            "first_reading",
            "passed",
            "status_observed",
        }


def test_the_year_request_is_derived_from_the_index_request() -> None:
    index = "https://www.parlimen.gov.my/bills-dewan-negara.html?lang=bm&uweb=dn&arkib=yes&ajx=0"
    assert archive_year_url(index, 1997) == (
        "https://www.parlimen.gov.my/bills-dewan-negara.html"
        "?lang=bm&uweb=dn&arkib=yes&ajx=1&id=0_1997"
    )


def test_a_year_whose_connection_drops_degrades_only_that_year(tmp_path) -> None:
    """A long crawl loses a connection sooner or later; it must not lose the run."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nAllow: /\n", request=request)
        if (request.url.params.get("id") or "") == "0_2011":
            raise httpx.RemoteProtocolError(
                "Server disconnected without sending a response.", request=request
            )
        return upstream_document(request)

    with database() as session:
        run = crawl(session, tmp_path, httpx.MockTransport(handler))
        session.flush()
        assert run.state == "partial"
        assert run.publish_decision == "published"
        # The years that read are published.
        assert {bill.identifier_normalized for bill in session.scalars(select(Bill))} == {
            "DR-17-2024",
            "DR-18-2024",
            "DR-20-2024",
            "DR-21-2024",
        }
        states = {
            (row.chamber, row.scope_key): row.state
            for row in session.scalars(select(CoverageTarget))
        }
        assert states[("dewan_rakyat", "2011")] == "failing"
        assert states[("dewan_rakyat", "2024")] == "healthy"
        anomaly = session.scalar(select(Anomaly).where(Anomaly.kind == "listing_unavailable"))
        assert anomaly is not None
        assert "disconnected" in anomaly.detail_json["reason"]


def test_two_chambers_disagreeing_about_a_title_is_a_conflict_not_an_edit_history(
    tmp_path,
) -> None:
    """Three archived bills carry a different title in each chamber's tree.

    Without this rule the title is rewritten twice per crawl for ever, so `record_changes` grows
    on every run and the second identical run no longer writes zero rows (HANDOFF 22).
    """
    disagreeing = (
        (FIXTURES / "archive_year_dr_2024.xml")
        .read_text()
        .replace(
            "RUU Penagih Dadah (Rawatan dan Pemulihan) (Pindaan) 2024",
            "RUU Bekalan (Pindaan) 2024",
            1,
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nAllow: /\n", request=request)
        if request.url.params.get("uweb") == "dn" and request.url.params.get("id") == "0_2024":
            return httpx.Response(200, content=disagreeing.encode(), request=request)
        return upstream_document(request)

    with database() as session:
        crawl(session, tmp_path, httpx.MockTransport(handler))
        session.flush()
        # The first run sees both titles and records the second as a change, which is right: it
        # had no reason yet to think the two were not a genuine edit.
        first_changes = session.scalar(select(func.count()).select_from(RecordChange))
        assert first_changes == 1
        held = session.scalar(select(Bill).where(Bill.identifier_normalized == "DR-17-2024"))
        assert held is not None
        settled = held.title_bm

        crawl(session, tmp_path, httpx.MockTransport(handler))
        session.flush()
        # The second run writes nothing further, and says why.
        assert session.scalar(select(func.count()).select_from(RecordChange)) == first_changes
        session.refresh(held)
        assert held.title_bm == settled
        conflict = session.scalar(
            select(Anomaly).where(Anomaly.kind == "duplicate_identifier_conflict")
        )
        assert conflict is not None
        assert conflict.detail_json["field_path"] == "title_bm"
        assert {conflict.detail_json["held"], conflict.detail_json["offered"]} == {
            "RUU Penagih Dadah (Rawatan dan Pemulihan) (Pindaan) 2024",
            "RUU Bekalan (Pindaan) 2024",
        }


def test_a_permanent_upstream_defect_stays_one_anomaly_across_runs(tmp_path) -> None:
    """Keyed on the snapshot, a defect that never gets fixed added a row on every crawl."""
    with database() as session:
        crawl(session, tmp_path, transport(edge_case_year="2011"))
        session.flush()
        first = session.scalars(
            select(Anomaly).where(Anomaly.kind == "unparseable_identifier")
        ).all()
        # One per upstream document — the malformed year is served for both chambers here — keyed
        # on the document's URL rather than on the snapshot of it.
        assert len(first) == 2
        assert {anomaly.entity_type for anomaly in first} == {None}
        assert all(anomaly.url for anomaly in first)
        counts = {anomaly.url: anomaly.occurrence_count for anomaly in first}

        crawl(session, tmp_path, transport(edge_case_year="2011"))
        session.flush()
        again = session.scalars(
            select(Anomaly).where(Anomaly.kind == "unparseable_identifier")
        ).all()
        assert len(again) == 2
        assert all(anomaly.occurrence_count > counts[anomaly.url] for anomaly in again)
        assert again[0].detail_json["rows"][0]["raw_identifier"] == "D.R.40/2017 ARKIB"


def test_a_row_that_is_not_a_row_and_a_label_we_do_not_know_are_reported_as_themselves(
    tmp_path,
) -> None:
    """Reporting either as an identifier problem sends an operator to the wrong place."""
    broken = (
        (FIXTURES / "archive_year_dr_2024.xml")
        .read_text()
        .replace("Bacaan Pertama Pada:", "Bacaan Sulung Pada:", 1)
        .replace("text='D.R.18/2024 - RUU Pentadbiran", "text='not a bill node at all", 1)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nAllow: /\n", request=request)
        if request.url.params.get("id") == "0_2011":
            return httpx.Response(200, content=broken.encode(), request=request)
        return upstream_document(request)

    with database() as session:
        run = crawl(session, tmp_path, httpx.MockTransport(handler))
        session.flush()
        assert run.state == "succeeded"
        raised = {anomaly.kind: anomaly.severity for anomaly in session.scalars(select(Anomaly))}
        assert raised == {"unmapped_detail_label": "warn", "malformed_row": "warn"}
        label = session.scalar(select(Anomaly).where(Anomaly.kind == "unmapped_detail_label"))
        assert label is not None
        assert "Bacaan Sulung Pada" in label.detail_json["rows"][0]["reason"]


def test_a_closed_archived_year_never_goes_stale(tmp_path) -> None:
    """66 immutable years reporting staleness once a month is 66 warnings that mean nothing."""
    from datetime import UTC, datetime, timedelta

    from billwatcher.operations import evaluate_coverage

    with database() as session:
        crawl(session, tmp_path, transport())
        session.flush()
        # Two months later, with no archive crawl in between.
        later = datetime.now(UTC) + timedelta(days=60)
        states = {
            (row.chamber, row.scope_key): row.state for row in evaluate_coverage(session, now=later)
        }
        session.flush()
        assert states[("dewan_rakyat", "2011")] == "healthy"
        assert states[("dewan_rakyat", "2024")] == "stale"
        # Exactly one alert per chamber, for the year that can actually change.
        stale = session.scalars(select(Anomaly).where(Anomaly.kind == "target_stale")).all()
        assert {anomaly.detail_json["expected_interval_hours"] for anomaly in stale} == {720, 168}


def test_an_unknown_mode_is_refused_rather_than_crawling_nothing(tmp_path) -> None:
    """Target selection is by mode, so a typo would report a clean run that read nothing."""
    import pytest

    with database() as session, pytest.raises(ValueError, match="unknown crawl mode"):
        crawl(session, tmp_path, transport(), mode="archives")
