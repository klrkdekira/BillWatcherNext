from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import BackfillJob, Blob, SourceSnapshot
from billwatcher.scraper.ingest import replay_snapshot
from billwatcher.scraper.parse_archive import is_archive_index_url, parse_stored_listing
from billwatcher.storage.blobs import BlobStore
from billwatcher.version import PARSER_VERSION


def run_reparse(
    session: Session,
    *,
    blob_store: BlobStore,
    dry_run: bool = True,
    limit: int = 100,
) -> BackfillJob:
    job = BackfillJob(
        kind="reparse",
        to_version=PARSER_VERSION,
        filter_json={"limit": limit},
        dry_run=dry_run,
        state="running",
        started_at=datetime.now(UTC),
    )
    session.add(job)
    session.flush()
    snapshots = session.scalars(
        select(SourceSnapshot)
        .where(
            SourceSnapshot.parse_status == "succeeded",
            SourceSnapshot.blob_sha256.is_not(None),
        )
        .order_by(SourceSnapshot.requested_at)
        .limit(limit)
    ).all()
    # The archive index lists years, not bills. It is snapshotted because it decides what the
    # crawl fetched, but replaying it would be replaying a table of contents.
    snapshots = [row for row in snapshots if not is_archive_index_url(row.url)]
    processed = changes = failed = 0
    if dry_run:
        # Parsing still validates stored bytes, but no domain projection is changed.
        for snapshot in snapshots:
            try:
                blob = session.get(Blob, snapshot.blob_sha256)
                if blob is None:
                    raise ValueError("blob row missing")
                parse_stored_listing(
                    blob_store.get(blob.sha256, compression=blob.compression).decode("utf-8"),
                    url=snapshot.url,
                    source_url=snapshot.final_url,
                )
                processed += 1
            except Exception:
                failed += 1
    else:
        for snapshot in snapshots:
            target = infer_target(snapshot.url)
            if target is None:
                continue
            try:
                counts = replay_snapshot(
                    session,
                    snapshot,
                    blob_store=blob_store,
                    chamber=target[0],
                    language=target[1],
                    run_id=job.id,
                )
                changes += counts.changes
                processed += 1
            except Exception:
                failed += 1
    job.counts = {"processed": processed, "changes": changes, "failed": failed}
    job.state = "succeeded" if failed == 0 else "failed"
    job.finished_at = datetime.now(UTC)
    return job


def infer_target(url: str) -> tuple[str, str] | None:
    if "bills-dewan-rakyat" in url:
        chamber = "dewan_rakyat"
    elif "bills-dewan-negara" in url:
        chamber = "dewan_negara"
    else:
        return None
    language = "en" if "lang=en" in url else "ms"
    return chamber, language
