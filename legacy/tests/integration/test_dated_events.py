"""Dated listing columns become events and chamber-record projections (HANDOFF 8, 11.5)."""

from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import Anomaly, BillEvent, ChamberRecord, RecordChange
from billwatcher.scraper.ingest import ingest_listing
from billwatcher.scraper.parse_listing import parse_listing

FIXTURES = Path("tests/fixtures/parliament")
NOW = datetime(2026, 8, 17, tzinfo=UTC)
DR_URL = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr"
DN_URL = "https://www.parlimen.gov.my/bills-dewan-negara.html?lang=bm&uweb=dn"


def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def ingest(database: Session, fixture: str, *, chamber: str, url: str, run: str = "run") -> None:
    ingest_listing(
        database,
        parse_listing((FIXTURES / fixture).read_text(), source_url=url),
        chamber=chamber,
        language="ms",
        source_url=url,
        snapshot_id=f"snapshot-{chamber}",
        run_id=run,
        checked_at=NOW,
    )
    database.flush()


def test_reading_dates_reach_the_chamber_record_projection() -> None:
    with session() as database:
        ingest(database, "current_dr_bm_dated.html", chamber="dewan_rakyat", url=DR_URL)
        record = database.scalars(select(ChamberRecord)).one()
        assert record.first_read_on == date(2026, 7, 13)
        assert record.second_read_on == date(2026, 7, 13)
        assert record.third_read_on == date(2026, 7, 16)
        assert record.referred_on == date(2026, 7, 15)
        assert record.passed_on == date(2026, 7, 17)


def test_a_range_in_one_cell_keeps_both_ends() -> None:
    with session() as database:
        ingest(database, "current_dr_bm_dated.html", chamber="dewan_rakyat", url=DR_URL)
        second = database.scalars(
            select(BillEvent).where(BillEvent.event_type == "second_reading")
        ).one()
        assert second.event_on == date(2026, 7, 13)
        assert second.event_on_end == date(2026, 7, 14)
        assert second.source_value == "13–14 Julai 2026"


def test_several_dates_in_one_cell_become_sequenced_events() -> None:
    with session() as database:
        ingest(database, "current_dr_bm_dated.html", chamber="dewan_rakyat", url=DR_URL)
        third = database.scalars(
            select(BillEvent)
            .where(BillEvent.event_type == "third_reading")
            .order_by(BillEvent.sequence)
        ).all()
        assert [event.sequence for event in third] == [0, 1]
        assert [event.event_on for event in third] == [date(2026, 7, 16), date(2026, 7, 17)]
        assert all(event.event_on_end is None for event in third)


def test_every_dated_column_records_its_source_label_and_value() -> None:
    with session() as database:
        ingest(database, "current_dr_bm_dated.html", chamber="dewan_rakyat", url=DR_URL)
        events = database.scalars(
            select(BillEvent).where(BillEvent.event_type != "status_observed")
        ).all()
        assert {event.event_type for event in events} == {
            "first_reading",
            "second_reading",
            "third_reading",
            "committee_referral",
            "passed",
        }
        assert all(event.source_label and event.source_value for event in events)
        assert all(event.parser_version for event in events)


def test_a_second_identical_run_adds_no_duplicate_events_or_changes() -> None:
    with session() as database:
        ingest(database, "current_dr_bm_dated.html", chamber="dewan_rakyat", url=DR_URL)
        before = database.scalar(select(func.count()).select_from(BillEvent))
        database.query(RecordChange).delete()
        database.flush()

        ingest(database, "current_dr_bm_dated.html", chamber="dewan_rakyat", url=DR_URL, run="two")
        assert database.scalar(select(func.count()).select_from(BillEvent)) == before
        assert database.scalar(select(func.count()).select_from(RecordChange)) == 0


def test_the_same_bill_keeps_conflicting_chamber_dates_apart() -> None:
    """The same code in both chambers is one bill with two independent timelines."""
    with session() as database:
        ingest(database, "current_dr_bm_dated.html", chamber="dewan_rakyat", url=DR_URL)
        ingest(database, "current_dn_bm_dated.html", chamber="dewan_negara", url=DN_URL)

        records = {
            record.chamber: record for record in database.scalars(select(ChamberRecord)).all()
        }
        assert len(records) == 2
        assert len({record.bill_id for record in records.values()}) == 1
        assert records["dewan_rakyat"].first_read_on == date(2026, 7, 13)
        assert records["dewan_negara"].first_read_on == date(2026, 7, 20)

        negara_second = database.scalars(
            select(BillEvent).where(
                BillEvent.chamber == "dewan_negara", BillEvent.event_type == "second_reading"
            )
        ).one()
        assert negara_second.event_on == date(2026, 7, 21)
        assert negara_second.event_on_end == date(2026, 7, 22)
        # Neither chamber overwrote the other's reading dates.
        rakyat_second = database.scalars(
            select(BillEvent).where(
                BillEvent.chamber == "dewan_rakyat", BillEvent.event_type == "second_reading"
            )
        ).one()
        assert rakyat_second.event_on_end == date(2026, 7, 14)


def test_an_unparseable_date_raises_an_anomaly_and_leaves_the_column_null() -> None:
    with session() as database:
        ingest(database, "unparseable_date.html", chamber="dewan_rakyat", url=DR_URL)
        record = database.scalars(select(ChamberRecord)).one()
        assert record.first_read_on is None

        anomaly = database.scalars(select(Anomaly).where(Anomaly.kind == "unparseable_date")).one()
        assert anomaly.severity == "warn"
        assert anomaly.detail_json["raw"] == "13/25/2026"
        assert anomaly.detail_json["label"] == "Bacaan Kali Pertama"
        # No reading event was invented for a date we could not read.
        assert not database.scalars(
            select(BillEvent).where(BillEvent.event_type == "first_reading")
        ).all()


def test_retained_bad_rows_become_anomalies_rather_than_vanishing() -> None:
    with session() as database:
        ingest(database, "mixed_rows.html", chamber="dewan_rakyat", url=DR_URL)
        kinds = {anomaly.kind: anomaly for anomaly in database.scalars(select(Anomaly)).all()}
        assert kinds["unparseable_identifier"].severity == "warn"
        assert kinds["duplicate_identifier_conflict"].severity == "critical"

        rows = kinds["unparseable_identifier"].detail_json["rows"]
        assert any(row["raw_identifier"] == "bukan kod" for row in rows)
        assert kinds["duplicate_identifier_conflict"].detail_json["count"] == 1
        # The one good row still landed.
        assert database.scalars(select(ChamberRecord)).one().status_normalized == "passed"
