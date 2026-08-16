import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import Anomaly, FetchQueueItem
from billwatcher.scraper.queue import (
    CircuitBreaker,
    CrawlBudget,
    fail_item,
    finish_item,
    lease_next,
)

NOW = datetime(2026, 8, 17, tzinfo=UTC)


def test_budget_never_partially_consumes_over_limit() -> None:
    budget = CrawlBudget(2, 10, 60, 1)
    assert budget.consume(byte_count=6, new_documents=1)
    assert not budget.consume(byte_count=5)
    assert (budget.requests, budget.bytes_received, budget.new_documents) == (1, 6, 1)


def test_budget_enforces_wall_clock_without_consuming() -> None:
    budget = CrawlBudget(2, 10, 60, 1)
    budget.started_monotonic = time.monotonic() - 61
    assert not budget.consume(byte_count=1)
    assert budget.requests == budget.bytes_received == 0


def test_circuit_breaker_resets_after_success() -> None:
    breaker = CircuitBreaker(failure_threshold=2)
    breaker.record(failed=True)
    assert not breaker.open
    breaker.record(failed=False)
    assert breaker.consecutive_failures == 0
    breaker.record(failed=True)
    breaker.record(failed=True)
    assert breaker.open


def test_expired_lease_recovers_and_dead_letter_is_anomaly() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        item = FetchQueueItem(
            target_kind="document",
            url="https://www.parlimen.gov.my/a.pdf",
            priority=2,
            state="leased",
            lease_owner="crashed",
            lease_expires_at=NOW - timedelta(seconds=1),
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(item)
        session.flush()
        leased = lease_next(session, owner="worker", now=NOW)
        assert leased is item
        assert item.lease_owner == "worker"
        fail_item(
            session,
            item,
            owner="worker",
            now=NOW,
            error="upstream failed",
            attempt_ceiling=1,
        )
        session.flush()
        assert item.state == "dead"
        assert (
            session.scalar(select(Anomaly.kind).where(Anomaly.kind == "queue_dead_letter"))
            == "queue_dead_letter"
        )


def test_finish_requires_owner_and_clears_lease() -> None:
    item = FetchQueueItem(
        target_kind="document",
        url="https://www.parlimen.gov.my/a.pdf",
        state="leased",
        lease_owner="worker",
    )
    finish_item(item, owner="worker")
    assert item.state == "done"
    assert item.lease_owner is None
