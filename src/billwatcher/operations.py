from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import Anomaly, CoverageTarget


def evaluate_coverage(session: Session, *, now: datetime | None = None) -> list[CoverageTarget]:
    """Derive every target state and persist deduplicated staleness anomalies."""
    now = now or datetime.now(UTC)
    targets = list(session.scalars(select(CoverageTarget)))
    for target in targets:
        if target.last_success_at is None:
            target.state = "never_run"
            continue
        success = target.last_success_at
        if success.tzinfo is None:
            success = success.replace(tzinfo=UTC)
        stale = now - success > timedelta(hours=target.expected_interval_hours)
        target.state = "stale" if stale else "healthy"
        existing = session.scalar(
            select(Anomaly).where(
                Anomaly.kind == "target_stale",
                Anomaly.entity_type == "coverage_target",
                Anomaly.entity_id == target.id,
                Anomaly.resolved_at.is_(None),
            )
        )
        if stale:
            detail = {
                "last_success_at": success.isoformat(),
                "expected_interval_hours": target.expected_interval_hours,
            }
            if existing:
                existing.last_seen_at = now
                existing.occurrence_count += 1
                existing.detail_json = detail
            else:
                session.add(
                    Anomaly(
                        kind="target_stale",
                        severity="warn",
                        entity_type="coverage_target",
                        entity_id=target.id,
                        detail_json=detail,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                )
        elif existing:
            existing.resolved_at = now
    return targets
