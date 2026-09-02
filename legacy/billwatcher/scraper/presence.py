from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import Anomaly, Bill, PresenceObservation


def record_full_run_presence(
    session: Session,
    *,
    run_id: str,
    listing_url: str,
    expected_bill_ids: set[str],
    present_bill_ids: set[str],
    observed_at: datetime,
    alert_threshold: int = 3,
) -> None:
    """Evaluate absence only after a validated, published full listing run."""
    for bill_id in expected_bill_ids | present_bill_ids:
        present = bill_id in present_bill_ids
        session.add(
            PresenceObservation(
                run_id=run_id,
                entity_type="bill",
                entity_id=bill_id,
                listing_url=listing_url,
                present=present,
                observed_at=observed_at,
            )
        )
        bill = session.get(Bill, bill_id)
        if bill is None:
            continue
        if present:
            bill.absent_streak = 0
            bill.last_seen_at = observed_at
            continue
        bill.absent_streak += 1
        bill.last_absent_at = observed_at
        if bill.absent_streak >= alert_threshold:
            _upsert_document_gone(session, bill, observed_at)


def _upsert_document_gone(session: Session, bill: Bill, now: datetime) -> None:
    anomaly = session.scalar(
        select(Anomaly).where(
            Anomaly.kind == "document_gone",
            Anomaly.entity_type == "bill",
            Anomaly.entity_id == bill.id,
            Anomaly.resolved_at.is_(None),
        )
    )
    detail = {"absent_streak": bill.absent_streak}
    if anomaly:
        anomaly.last_seen_at = now
        anomaly.occurrence_count += 1
        anomaly.detail_json = detail
    else:
        session.add(
            Anomaly(
                kind="document_gone",
                severity="warn",
                entity_type="bill",
                entity_id=bill.id,
                detail_json=detail,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
