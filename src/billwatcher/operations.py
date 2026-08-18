from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from billwatcher.models import Anomaly, Blob, CoverageTarget, DocumentVersion
from billwatcher.storage.blobs import BlobStore


def _aware(value: datetime | None) -> datetime | None:
    """SQLite drops timezone information on round trip; treat stored timestamps as UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def record_anomaly(
    session: Session,
    *,
    kind: str,
    severity: str,
    detail: dict[str, Any],
    now: datetime,
    entity_type: str | None = None,
    entity_id: str | None = None,
    url: str | None = None,
) -> Anomaly:
    """Upsert one anomaly, deduplicating by kind plus entity (HANDOFF 8).

    A recurring condition must accumulate an occurrence count on one row rather than filling
    the table with copies, because `/status` and `make doctor` read these as a work list.
    """
    lookup = select(Anomaly).where(
        Anomaly.kind == kind,
        Anomaly.resolved_at.is_(None),
    )
    lookup = lookup.where(
        Anomaly.entity_type.is_(None) if entity_type is None else Anomaly.entity_type == entity_type
    )
    lookup = lookup.where(
        Anomaly.entity_id.is_(None) if entity_id is None else Anomaly.entity_id == entity_id
    )
    if entity_type is None and url is not None:
        # A condition that belongs to an upstream *document* rather than to a row we store has no
        # entity id — `entity_id` is a 36-character key for our own primary keys, not a place to
        # put a URL. The document's identity is its URL, so that is what deduplicates it. Without
        # this, every parse-issue anomaly for every listing would collapse onto one row.
        lookup = lookup.where(Anomaly.url == url)
    existing = session.scalar(lookup)
    if existing is not None:
        existing.last_seen_at = now
        existing.occurrence_count += 1
        existing.detail_json = detail
        if url:
            existing.url = url
        return existing
    anomaly = Anomaly(
        kind=kind,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        url=url,
        detail_json=detail,
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(anomaly)
    return anomaly


def evaluate_coverage(session: Session, *, now: datetime | None = None) -> list[CoverageTarget]:
    """Derive every target state and persist deduplicated staleness anomalies."""
    now = now or datetime.now(UTC)
    targets = list(session.scalars(select(CoverageTarget)))
    for target in targets:
        attempt = _aware(target.last_attempt_at)
        success = _aware(target.last_success_at)
        if success is None:
            # A target that has been tried and never succeeded is failing, which says more than
            # "never run" — that state is for a target nothing has attempted yet.
            target.state = "failing" if attempt is not None else "never_run"
            continue
        if attempt is not None and attempt > success:
            # The most recent attempt did not succeed, so the target is broken right now even
            # though it has succeeded before.
            target.state = "failing"
            continue
        # An interval of zero means the target is not expected to be read again, so staleness
        # cannot apply to it. That is the honest state of a *closed* archived year: 1994 will
        # never gain another bill, and demanding a monthly re-read of 66 immutable years would
        # produce 66 warnings that mean nothing and teach an operator to skim past all of them.
        # The newest archived year keeps a real interval, because it can still change.
        if target.expected_interval_hours == 0:
            target.state = "healthy"
            if existing_stale := _open_staleness(session, target):
                existing_stale.resolved_at = now
            continue
        stale = now - success > timedelta(hours=target.expected_interval_hours)
        target.state = "stale" if stale else "healthy"
        existing = _open_staleness(session, target)
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


def _open_staleness(session: Session, target: CoverageTarget) -> Anomaly | None:
    return session.scalar(
        select(Anomaly).where(
            Anomaly.kind == "target_stale",
            Anomaly.entity_type == "coverage_target",
            Anomaly.entity_id == target.id,
            Anomaly.resolved_at.is_(None),
        )
    )


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
        for blob in candidates:
            # Delete through the backend by digest. The recorded storage_path is provenance,
            # never something we turn back into a filesystem operation.
            blob_store.delete(blob.sha256)
            session.delete(blob)
            deleted += 1
        for digest in orphans:
            blob_store.delete(digest)
            deleted += 1
    return PruneReport(
        database_candidates=len(candidates),
        orphans=len(orphans),
        deleted=deleted,
        dry_run=dry_run,
    )
