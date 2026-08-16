import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from billwatcher.models import Anomaly, FetchQueueItem


@dataclass(slots=True)
class CrawlBudget:
    max_requests: int
    max_bytes: int
    max_duration_seconds: int
    max_new_documents: int
    requests: int = 0
    bytes_received: int = 0
    new_documents: int = 0
    started_monotonic: float = field(default_factory=time.monotonic, repr=False)

    def consume(self, *, byte_count: int = 0, new_documents: int = 0, request: bool = True) -> bool:
        if (
            time.monotonic() - self.started_monotonic > self.max_duration_seconds
            or self.requests + (1 if request else 0) > self.max_requests
            or self.bytes_received + byte_count > self.max_bytes
            or self.new_documents + new_documents > self.max_new_documents
        ):
            return False
        self.requests += 1 if request else 0
        self.bytes_received += byte_count
        self.new_documents += new_documents
        return True


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int = 5
    consecutive_failures: int = 0
    open: bool = False

    def record(self, *, failed: bool) -> None:
        self.consecutive_failures = self.consecutive_failures + 1 if failed else 0
        self.open = self.consecutive_failures >= self.failure_threshold


def lease_next(
    session: Session,
    *,
    owner: str,
    now: datetime,
    lease_for: timedelta = timedelta(minutes=10),
) -> FetchQueueItem | None:
    item = session.scalar(
        select(FetchQueueItem)
        .where(
            or_(
                (
                    (FetchQueueItem.state.in_(("pending", "failed")))
                    & (
                        FetchQueueItem.next_attempt_at.is_(None)
                        | (FetchQueueItem.next_attempt_at <= now)
                    )
                ),
                ((FetchQueueItem.state == "leased") & (FetchQueueItem.lease_expires_at <= now)),
            )
        )
        .order_by(FetchQueueItem.priority.desc(), FetchQueueItem.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if item is None:
        return None
    item.state = "leased"
    item.lease_owner = owner
    item.lease_expires_at = now + lease_for
    return item


def finish_item(item: FetchQueueItem, *, owner: str) -> None:
    _assert_owner(item, owner)
    item.state = "done"
    item.lease_owner = None
    item.lease_expires_at = None
    item.last_error = None


def fail_item(
    session: Session,
    item: FetchQueueItem,
    *,
    owner: str,
    now: datetime,
    error: str,
    attempt_ceiling: int = 5,
) -> None:
    _assert_owner(item, owner)
    item.attempts += 1
    item.last_error = error[:1000]
    item.lease_owner = None
    item.lease_expires_at = None
    if item.attempts >= attempt_ceiling:
        item.state = "dead"
        session.add(
            Anomaly(
                kind="queue_dead_letter",
                severity="warn",
                entity_type="fetch_queue",
                entity_id=item.id,
                url=item.url,
                detail_json={"attempts": item.attempts},
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    else:
        item.state = "failed"
        item.next_attempt_at = now + timedelta(seconds=min(2**item.attempts, 3600))


def _assert_owner(item: FetchQueueItem, owner: str) -> None:
    if item.state != "leased" or item.lease_owner != owner:
        raise RuntimeError("queue item is not leased by this worker")
