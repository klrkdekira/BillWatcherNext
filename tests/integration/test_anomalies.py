"""The anomaly taxonomy is the alert channel, so every kind must exist and dedupe (HANDOFF 10.5)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import Anomaly
from billwatcher.operations import record_anomaly
from billwatcher.scraper.pagination import PaginationGuard, PaginationLoop
from billwatcher.scraper.service import record_pagination_loop

NOW = datetime(2026, 8, 17, tzinfo=UTC)

# HANDOFF 10.5's minimum set. Each is raised somewhere in the application and provoked by a test.
REQUIRED_KINDS = {
    "unmapped_status",
    "unparseable_identifier",
    "unparseable_date",
    "structure_drift",
    "zero_records",
    "count_drop",
    "duplicate_identifier_conflict",
    "pagination_loop",
    "document_quarantined",
    "document_rollback",
    "document_gone",
    "extraction_failure_spike",
    "override_conflict",
    "robots_changed",
    "target_stale",
    "queue_dead_letter",
    "budget_exhausted",
}


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


def test_every_kind_in_the_minimum_set_is_raised_somewhere() -> None:
    from pathlib import Path

    sources = "\n".join(path.read_text() for path in Path("src/billwatcher").rglob("*.py"))
    missing = {kind for kind in REQUIRED_KINDS if f'"{kind}"' not in sources}
    assert missing == set()


def test_a_recurring_condition_accumulates_on_one_row(session: Session) -> None:
    for index in range(3):
        record_anomaly(
            session,
            kind="structure_drift",
            severity="critical",
            entity_type="source_snapshot",
            entity_id="snapshot-1",
            detail={"attempt": index},
            now=NOW + timedelta(minutes=index),
        )
    session.flush()
    anomaly = session.scalars(select(Anomaly)).one()
    assert anomaly.occurrence_count == 3
    assert anomaly.detail_json == {"attempt": 2}
    assert anomaly.first_seen_at.replace(tzinfo=UTC) == NOW
    assert anomaly.last_seen_at.replace(tzinfo=UTC) == NOW + timedelta(minutes=2)


def test_distinct_entities_and_kinds_stay_separate(session: Session) -> None:
    record_anomaly(
        session,
        kind="structure_drift",
        severity="critical",
        entity_type="source_snapshot",
        entity_id="one",
        detail={},
        now=NOW,
    )
    record_anomaly(
        session,
        kind="structure_drift",
        severity="critical",
        entity_type="source_snapshot",
        entity_id="two",
        detail={},
        now=NOW,
    )
    record_anomaly(
        session,
        kind="zero_records",
        severity="critical",
        entity_type="source_snapshot",
        entity_id="one",
        detail={},
        now=NOW,
    )
    session.flush()
    assert session.scalar(select(func.count()).select_from(Anomaly)) == 3


def test_a_resolved_anomaly_is_not_reopened_in_place(session: Session) -> None:
    first = record_anomaly(
        session, kind="target_stale", severity="warn", detail={}, now=NOW, entity_id="t1"
    )
    session.flush()
    first.resolved_at = NOW
    session.flush()

    record_anomaly(
        session,
        kind="target_stale",
        severity="warn",
        detail={},
        now=NOW + timedelta(days=1),
        entity_id="t1",
    )
    session.flush()
    rows = session.scalars(select(Anomaly).order_by(Anomaly.first_seen_at)).all()
    assert len(rows) == 2
    assert rows[0].resolved_at is not None
    assert rows[1].resolved_at is None


def test_a_pagination_loop_is_recorded_as_a_warning(session: Session) -> None:
    guard = PaginationGuard()
    body = b"<table>identical</table>"
    guard.observe(body)
    with pytest.raises(PaginationLoop) as caught:
        guard.observe(body)

    record_pagination_loop(
        session,
        url="https://www.parlimen.gov.my/bills-dewan-rakyat.html?arkib=yes",
        snapshot_id="snapshot-1",
        error=caught.value,
        page=caught.value.page,
        now=NOW,
    )
    session.flush()
    anomaly = session.scalars(select(Anomaly).where(Anomaly.kind == "pagination_loop")).one()
    assert anomaly.severity == "warn"
    assert anomaly.detail_json["page"] == 2
    assert "repeats the body" in anomaly.detail_json["reason"]
    assert anomaly.url.endswith("arkib=yes")
