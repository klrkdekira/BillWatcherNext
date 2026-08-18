"""The archive crawl against real PostgreSQL, because SQLite does not enforce column widths.

The archive was published to PostgreSQL and then a later change keyed parse-issue anomalies on the
listing URL, in a `varchar(36)` column meant for our own primary keys. Every SQLite test passed;
the live run failed with `value too long for type character varying(36)`. These tests exercise the
paths where the archive writes wide, real-world values, on a database that checks.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from billwatcher.models import (
    Anomaly,
    Bill,
    BillEvent,
    ChamberRecord,
    RecordChange,
    ScrapeRun,
    SourceSnapshot,
)
from billwatcher.scraper.ingest import ingest_listing
from billwatcher.scraper.parse_archive import parse_archive_year

FIXTURES = Path("tests/fixtures/parliament")
NOW = datetime(2026, 8, 18, tzinfo=UTC)
# The real archive URLs, which are long, and the real snapshot/run identity that goes with them.
YEAR_URL = (
    "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr&arkib=yes&ajx=1&id=0_2017"
)

pytestmark = pytest.mark.usefixtures("postgres_engine")


@pytest.fixture
def session(postgres_engine: Engine) -> Iterator[Session]:
    with Session(postgres_engine) as database:
        database.execute(
            text(
                "TRUNCATE TABLE search_units, bill_events, bill_documents, document_extractions,"
                " document_versions, documents, chamber_records, record_changes,"
                " presence_observations, anomalies, fetch_attempts, source_snapshots,"
                " scrape_runs, blobs, bills, fetch_queue CASCADE"
            )
        )
        database.commit()
        yield database
        database.rollback()


def provenance(session: Session) -> tuple[str, str]:
    """Every domain row must be attributable to a run and a stored snapshot."""
    run = ScrapeRun(mode="archive", trigger="manual", started_at=NOW, state="running")
    session.add(run)
    session.flush()
    snapshot = SourceSnapshot(
        run_id=run.id,
        url=YEAR_URL,
        final_url=YEAR_URL,
        requested_at=NOW,
        status_code=200,
        parser_version="1.0.0",
        parse_status="succeeded",
    )
    session.add(snapshot)
    session.flush()
    return run.id, snapshot.id


def ingest(
    session: Session,
    fixture: str,
    *,
    chamber: str = "dewan_rakyat",
    body: str | None = None,
) -> None:
    run_id, snapshot_id = provenance(session)
    listing = parse_archive_year(
        body if body is not None else (FIXTURES / fixture).read_text(), source_url=YEAR_URL
    )
    ingest_listing(
        session,
        listing,
        chamber=chamber,
        language="ms",
        source_url=YEAR_URL,
        snapshot_id=snapshot_id,
        run_id=run_id,
        checked_at=NOW,
    )
    session.flush()


def test_an_archive_year_with_bad_rows_persists_on_postgresql(session: Session) -> None:
    ingest(session, "archive_year_edge_cases.xml")

    assert session.scalar(select(func.count()).select_from(Bill)) == 5
    assert session.scalar(select(func.count()).select_from(BillEvent)) > 0

    # The retained bad row becomes an anomaly keyed on the document's URL, which is far longer
    # than the 36-character column the entity key uses.
    anomaly = session.scalar(select(Anomaly).where(Anomaly.kind == "unparseable_identifier"))
    assert anomaly is not None
    assert anomaly.url == YEAR_URL
    assert anomaly.entity_id is None
    assert anomaly.detail_json["rows"][0]["raw_identifier"] == "D.R.40/2017 ARKIB"

    # The zero date is retained raw and reported, with the date left NULL.
    dated = session.scalar(select(Anomaly).where(Anomaly.kind == "unparseable_date"))
    assert dated is not None
    assert dated.detail_json["raw"] == "30/11/-0001"


def test_re_ingesting_the_same_archive_year_writes_no_changes(session: Session) -> None:
    ingest(session, "archive_year_dr_2024.xml")
    bills = session.scalar(select(func.count()).select_from(Bill))
    events = session.scalar(select(func.count()).select_from(BillEvent))

    ingest(session, "archive_year_dr_2024.xml")
    assert session.scalar(select(func.count()).select_from(Bill)) == bills
    assert session.scalar(select(func.count()).select_from(BillEvent)) == events
    assert session.scalar(select(func.count()).select_from(RecordChange)) == 0


def test_a_title_disagreement_across_chambers_settles_on_postgresql(session: Session) -> None:
    """The live corpus has three of these; they must not rewrite the title on every run."""
    ingest(session, "archive_year_dr_2024.xml")
    renamed = (
        (FIXTURES / "archive_year_dr_2024.xml")
        .read_text()
        .replace(
            "RUU Penagih Dadah (Rawatan dan Pemulihan) (Pindaan) 2024",
            "RUU Bekalan (Pindaan) 2024",
            1,
        )
    )
    for _ in range(2):
        ingest(session, "archive_year_dr_2024.xml", chamber="dewan_negara", body=renamed)
        ingest(session, "archive_year_dr_2024.xml")

    # One change, then a conflict rather than an endless pair of edits.
    assert session.scalar(select(func.count()).select_from(RecordChange)) == 1
    conflict = session.scalar(
        select(Anomaly).where(Anomaly.kind == "duplicate_identifier_conflict")
    )
    assert conflict is not None
    assert conflict.detail_json["field_path"] == "title_bm"
    assert session.scalar(select(func.count()).select_from(ChamberRecord)) == 8
