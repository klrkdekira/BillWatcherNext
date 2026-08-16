from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import Anomaly, CoverageTarget
from billwatcher.operations import evaluate_coverage

NOW = datetime(2026, 8, 17, tzinfo=UTC)


def test_stale_target_creates_deduplicated_anomaly_and_recovers() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        target = CoverageTarget(
            chamber="dewan_rakyat",
            listing_kind="current",
            language="ms",
            scope_key="",
            expected_interval_hours=12,
            last_success_at=NOW - timedelta(hours=13),
            last_record_count=10,
            state="healthy",
        )
        session.add(target)
        session.flush()
        evaluate_coverage(session, now=NOW)
        evaluate_coverage(session, now=NOW + timedelta(minutes=1))
        session.flush()
        anomaly = session.scalar(select(Anomaly).where(Anomaly.kind == "target_stale"))
        assert target.state == "stale"
        assert anomaly is not None
        assert anomaly.occurrence_count == 2

        target.last_success_at = NOW + timedelta(minutes=2)
        evaluate_coverage(session, now=NOW + timedelta(minutes=3))
        assert target.state == "healthy"
        assert anomaly.resolved_at == NOW + timedelta(minutes=3)


def test_never_run_target_is_distinct_from_stale() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        target = CoverageTarget(
            chamber="dewan_negara",
            listing_kind="archive",
            language="ms",
            scope_key="",
            expected_interval_hours=168,
            state="healthy",
        )
        session.add(target)
        evaluate_coverage(session, now=NOW)
        assert target.state == "never_run"
