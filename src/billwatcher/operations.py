from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from billwatcher.models import Anomaly, Blob, CoverageTarget, DocumentVersion
from billwatcher.storage.blobs import BlobStore


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


def diagnose(session: Session, *, blob_store: BlobStore) -> list[str]:
    """Evaluate the release and daily-operations gate that stands in for CI (HANDOFF 10.5)."""
    failures: list[str] = []
    critical = (
        session.scalar(
            select(func.count())
            .select_from(Anomaly)
            .where(
                Anomaly.severity == "critical",
                Anomaly.resolved_at.is_(None),
                Anomaly.acknowledged_at.is_(None),
            )
        )
        or 0
    )
    if critical:
        failures.append(f"{critical} unresolved critical anomalies")
    unaccepted = session.scalars(
        select(DocumentVersion).where(
            DocumentVersion.is_current.is_(True),
            DocumentVersion.validation_status != "accepted",
        )
    ).all()
    if unaccepted:
        failures.append("a current document version is not accepted")
    for blob in session.scalars(select(Blob)):
        if not blob_store.verify(blob.sha256, compression=blob.compression):
            failures.append(f"blob missing or corrupt: {blob.sha256}")
    return failures


@dataclass(frozen=True, slots=True)
class PruneReport:
    database_candidates: int
    orphans: int
    deleted: int
    dry_run: bool

    def as_counts(self) -> dict[str, int | bool]:
        return {
            "database_candidates": self.database_candidates,
            "orphans": self.orphans,
            "deleted": self.deleted,
            "dry_run": self.dry_run,
        }


def prune_unreferenced_blobs(
    session: Session, *, blob_store: BlobStore, dry_run: bool = True
) -> PruneReport:
    """Delete only blobs nothing references. A shared blob keeps a positive reference count."""
    candidates = list(session.scalars(select(Blob).where(Blob.ref_count <= 0)).all())
    referenced = set(session.scalars(select(Blob.sha256)))
    orphans = sorted(blob_store.stored_digests() - referenced)
    deleted = 0
    if not dry_run:
        root = blob_store.root.resolve()
        for blob in candidates:
            path = Path(blob.storage_path)
            try:
                path.resolve().relative_to(root)
            except ValueError as error:
                raise ValueError("recorded blob path escapes storage root") from error
            path.unlink(missing_ok=True)
            session.delete(blob)
            deleted += 1
        for digest in orphans:
            blob_store.path_for(digest).unlink(missing_ok=True)
            deleted += 1
    return PruneReport(
        database_candidates=len(candidates),
        orphans=len(orphans),
        deleted=deleted,
        dry_run=dry_run,
    )
