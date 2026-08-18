from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from billwatcher.config import Settings
from billwatcher.db import Base
from billwatcher.models import Anomaly, CoverageTarget
from billwatcher.operations import evaluate_coverage
from billwatcher.web.app import create_app

NOW = datetime(2026, 8, 17, tzinfo=UTC)


def target(
    chamber: str,
    listing_kind: str,
    *,
    last_success_at: datetime | None,
    expected_interval_hours: int = 12,
) -> CoverageTarget:
    return CoverageTarget(
        chamber=chamber,
        listing_kind=listing_kind,
        language="ms",
        expected_interval_hours=expected_interval_hours,
        last_success_at=last_success_at,
        last_record_count=10 if last_success_at else None,
    )


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


def test_homepage_freshness_reports_the_oldest_healthy_target() -> None:
    """HANDOFF 10.4: the newest success would let a healthy crawl mask a stale one."""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    # Coverage state is derived against the real clock, so anchor the fixtures to it.
    now = datetime.now(UTC)
    fresh = now - timedelta(hours=1)
    older = now - timedelta(hours=6)
    with factory() as database:
        database.add_all(
            [
                target(
                    "dewan_rakyat",
                    "current",
                    last_success_at=fresh,
                    expected_interval_hours=12,
                ),
                target(
                    "dewan_negara",
                    "current",
                    last_success_at=older,
                    expected_interval_hours=12,
                ),
                # A never-run target must not be mistaken for a fresh one.
                target("dewan_rakyat", "archive", last_success_at=None),
            ]
        )
        database.commit()

    with TestClient(create_app(factory, settings=Settings())) as browser:
        home = browser.get("/")
        assert home.status_code == 200
        shown = home.text.replace("+00:00", "")
        assert older.isoformat(sep=" ")[:16] in shown
        assert fresh.isoformat(sep=" ")[:16] not in shown


def test_freshness_is_absent_until_a_target_has_ever_succeeded() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as database:
        database.add(target("dewan_rakyat", "current", last_success_at=None))
        database.commit()
    with TestClient(create_app(factory, settings=Settings())) as browser:
        assert "No successful crawl has been recorded yet." in browser.get("/").text
