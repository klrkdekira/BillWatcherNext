from datetime import UTC, datetime

from sqlalchemy.orm import Session

from billwatcher.models import BackfillJob
from billwatcher.version import CHUNKER_VERSION


def record_deferred_job(session: Session, *, kind: str, dry_run: bool = True) -> BackfillJob:
    """Record Release 3 rechunk/reembed requests while their feature flag is disabled."""
    target = CHUNKER_VERSION if kind == "rechunk" else "unconfigured"
    job = BackfillJob(
        kind=kind,
        to_version=target,
        filter_json={"deferred_release": 3},
        dry_run=dry_run,
        state="succeeded" if dry_run else "failed",
        counts={"eligible": 0, "processed": 0},
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        error=None if dry_run else "Release 3 pipeline is not configured",
    )
    session.add(job)
    return job
