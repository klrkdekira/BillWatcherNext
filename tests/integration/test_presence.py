from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import Anomaly, Bill, PresenceObservation
from billwatcher.scraper.presence import record_full_run_presence

NOW = datetime(2026, 8, 17, tzinfo=UTC)


def test_absence_requires_repeated_full_runs_and_never_deletes() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bill = Bill(
            identifier_raw="D.R.1/2026",
            identifier_normalized="DR-1-2026",
            number=1,
            year=2026,
            originating_chamber="dewan_rakyat",
            slug="dr-1-2026",
            title_bm="Contoh",
            identifier_scheme_version=1,
            first_seen_at=NOW,
            last_seen_at=NOW,
            last_checked_at=NOW,
            last_changed_at=NOW,
        )
        session.add(bill)
        session.flush()
        for index in range(3):
            record_full_run_presence(
                session,
                run_id=f"run-{index}",
                listing_url="https://www.parlimen.gov.my/list",
                expected_bill_ids={bill.id},
                present_bill_ids=set(),
                observed_at=NOW + timedelta(days=index),
            )
        session.flush()
        assert session.get(Bill, bill.id) is bill
        assert bill.absent_streak == 3
        assert bill.tombstoned_at is None
        assert session.scalar(select(func.count()).select_from(PresenceObservation)) == 3
        assert (
            session.scalar(select(Anomaly.kind).where(Anomaly.kind == "document_gone"))
            == "document_gone"
        )

        record_full_run_presence(
            session,
            run_id="present",
            listing_url="https://www.parlimen.gov.my/list",
            expected_bill_ids={bill.id},
            present_bill_ids={bill.id},
            observed_at=NOW + timedelta(days=4),
        )
        assert bill.absent_streak == 0
