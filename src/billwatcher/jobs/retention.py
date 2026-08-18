"""Retention jobs for HANDOFF 16.4.

Nothing here may ever remove a document version, its blob, a record change, a bill event, or a
presence observation. Those are the archive. Only transport logs, superseded extractions, and
blobs behind failed or quarantined responses are prunable, and blob bytes are only ever removed
by the reference-checked pruner, never inline.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from billwatcher.models import (
    Blob,
    DailyFetchMetric,
    DocumentExtraction,
    DocumentVersion,
    FetchAttempt,
    SourceSnapshot,
)

QUARANTINE_BLOB_RETENTION_DAYS = 90


@dataclass(frozen=True, slots=True)
class RetentionReport:
    fetch_attempts_aggregated: int
    fetch_attempts_deleted: int
    daily_rows_written: int
    extractions_pruned: int
    snapshot_blobs_dereferenced: int
    dry_run: bool

    def as_counts(self) -> dict[str, int | bool]:
        return {
            "fetch_attempts_aggregated": self.fetch_attempts_aggregated,
            "fetch_attempts_deleted": self.fetch_attempts_deleted,
            "daily_rows_written": self.daily_rows_written,
            "extractions_pruned": self.extractions_pruned,
            "snapshot_blobs_dereferenced": self.snapshot_blobs_dereferenced,
            "dry_run": self.dry_run,
        }


def _host_of(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "unknown").lower()


def apply_retention(
    session: Session,
    *,
    fetch_attempt_retention_days: int,
    keep_extractor_versions: int = 2,
    now: datetime | None = None,
    dry_run: bool = True,
) -> RetentionReport:
    now = now or datetime.now(UTC)
    attempt_cutoff = now - timedelta(days=fetch_attempt_retention_days)
    blob_cutoff = now - timedelta(days=QUARANTINE_BLOB_RETENTION_DAYS)

    expired = list(
        session.scalars(select(FetchAttempt).where(FetchAttempt.attempted_at < attempt_cutoff))
    )
    daily_written = _aggregate_attempts(session, expired, dry_run=dry_run)
    if not dry_run:
        for attempt in expired:
            session.delete(attempt)

    pruned = _prune_extractions(session, keep=keep_extractor_versions, dry_run=dry_run)
    dereferenced = _dereference_failed_snapshot_blobs(session, cutoff=blob_cutoff, dry_run=dry_run)

    return RetentionReport(
        fetch_attempts_aggregated=len(expired),
        fetch_attempts_deleted=0 if dry_run else len(expired),
        daily_rows_written=daily_written,
        extractions_pruned=pruned,
        snapshot_blobs_dereferenced=dereferenced,
        dry_run=dry_run,
    )


def _aggregate_attempts(
    session: Session, attempts: Sequence[FetchAttempt], *, dry_run: bool
) -> int:
    """Roll expiring transport rows into daily counters so the audit trail survives deletion."""
    buckets: dict[tuple[object, str, int | None], list[FetchAttempt]] = {}
    for attempt in attempts:
        key = (attempt.attempted_at.date(), _host_of(attempt.url), attempt.status_code)
        buckets.setdefault(key, []).append(attempt)
    if dry_run:
        return len(buckets)
    written = 0
    for (day, host, status_code), rows in buckets.items():
        total_bytes = sum(row.bytes_received for row in rows)
        mean_duration = sum(row.duration_ms for row in rows) / len(rows)
        existing = session.scalar(
            select(DailyFetchMetric).where(
                DailyFetchMetric.day == day,
                DailyFetchMetric.host == host,
                DailyFetchMetric.status_code.is_(status_code)
                if status_code is None
                else DailyFetchMetric.status_code == status_code,
            )
        )
        if existing is None:
            session.add(
                DailyFetchMetric(
                    day=day,
                    host=host,
                    status_code=status_code,
                    count=len(rows),
                    bytes_received=total_bytes,
                    mean_duration_ms=mean_duration,
                )
            )
        else:
            combined = existing.count + len(rows)
            existing.mean_duration_ms = (
                existing.mean_duration_ms * existing.count + mean_duration * len(rows)
            ) / combined
            existing.count = combined
            existing.bytes_received += total_bytes
        written += 1
    return written


def _prune_extractions(session: Session, *, keep: int, dry_run: bool) -> int:
    """Keep the current extractor version and the previous one for each document version."""
    pruned = 0
    version_ids = session.scalars(select(DocumentExtraction.document_version_id).distinct()).all()
    for version_id in version_ids:
        rows = session.scalars(
            select(DocumentExtraction)
            .where(DocumentExtraction.document_version_id == version_id)
            .order_by(DocumentExtraction.created_at.desc())
        ).all()
        keepers = {row.id for row in rows if row.is_current}
        for row in rows:
            if len(keepers) >= keep:
                break
            keepers.add(row.id)
        for row in rows:
            if row.id in keepers:
                continue
            pruned += 1
            if not dry_run:
                session.delete(row)
    return pruned


def _dereference_failed_snapshot_blobs(session: Session, *, cutoff: datetime, dry_run: bool) -> int:
    """Release blob references held by old failed page fetches; bytes go via prune-blobs."""
    snapshots = session.scalars(
        select(SourceSnapshot).where(
            SourceSnapshot.requested_at < cutoff,
            SourceSnapshot.retention_class == "routine",
            SourceSnapshot.parse_status.in_(("failed", "quarantined")),
            SourceSnapshot.blob_sha256.is_not(None),
        )
    ).all()
    released = 0
    for snapshot in snapshots:
        digest = snapshot.blob_sha256
        if digest is None:
            continue
        still_used = session.scalar(
            select(func.count())
            .select_from(DocumentVersion)
            .where(DocumentVersion.blob_sha256 == digest)
        )
        if still_used:
            continue
        released += 1
        if dry_run:
            continue
        blob = session.get(Blob, digest)
        snapshot.blob_sha256 = None
        if blob is not None and blob.ref_count > 0:
            blob.ref_count -= 1
    return released
