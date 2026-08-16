import json
import random
from datetime import UTC, datetime
from pathlib import Path

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from billwatcher.config import get_settings
from billwatcher.db import SessionLocal
from billwatcher.jobs.placeholders import record_deferred_job
from billwatcher.jobs.reextract import run_reextract
from billwatcher.jobs.replay import run_reparse
from billwatcher.models import (
    Anomaly,
    Blob,
    CoverageTarget,
    DocumentVersion,
    FetchQueueItem,
    ScrapeRun,
)
from billwatcher.operations import evaluate_coverage
from billwatcher.scraper.document_worker import process_one_document
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.policy import CrawlPolicy
from billwatcher.scraper.queue import CrawlBudget
from billwatcher.scraper.worker import ScrapeOrchestrator
from billwatcher.storage.blobs import BlobStore
from billwatcher.version import PARSER_VERSION

app = typer.Typer(no_args_is_help=True, help="BillWatcherNext operator commands.")


def policy() -> CrawlPolicy:
    settings = get_settings()
    return CrawlPolicy(
        user_agent=(
            f"BillWatcherNext/0.1 (+{settings.public_base_url}/about; "
            f"contact: {settings.contact_email})"
        ),
        delay_seconds=settings.scrape_delay_seconds,
        concurrency=settings.scrape_concurrency,
        max_response_bytes=settings.document_max_bytes,
    )


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    import uvicorn

    uvicorn.run("billwatcher.web.app:app", host=host, port=port, reload=reload)


@app.command()
def migrate() -> None:
    command.upgrade(Config("alembic.ini"), "head")


@app.command("scrape")
def scrape(
    full: bool = typer.Option(False, "--full"),
    approve_live: bool = typer.Option(False, "--approve-live"),
) -> None:
    settings = get_settings()
    if not (settings.scrape_enabled or approve_live):
        raise typer.BadParameter(
            "live crawl is disabled; set SCRAPE_ENABLED=true or pass --approve-live"
        )
    budget = CrawlBudget(
        settings.scrape_max_requests_per_run,
        settings.scrape_max_bytes_per_run,
        settings.scrape_max_duration_seconds,
        settings.scrape_max_new_documents,
    )
    with SessionLocal() as session, Fetcher(policy()) as fetcher:
        run = ScrapeOrchestrator(
            session=session,
            fetcher=fetcher,
            blob_store=BlobStore(settings.blob_storage_root),
            budget=budget,
            count_drop_abort_fraction=settings.count_drop_abort_fraction,
            absence_streak_alert=settings.absence_streak_alert,
        ).run(mode="full" if full else "incremental")
        session.commit()
        typer.echo(json.dumps({"run_id": run.id, "state": run.state}))
        if run.state not in {"succeeded", "partial"}:
            raise typer.Exit(1)


@app.command("worker")
def worker(poll_seconds: int = 60) -> None:
    """Run the scheduled crawl/document loop; live crawling remains feature-gated."""
    import time

    settings = get_settings()
    next_scrape_at = 0.0
    while True:
        try:
            if settings.scrape_enabled and time.monotonic() >= next_scrape_at:
                budget = CrawlBudget(
                    settings.scrape_max_requests_per_run,
                    settings.scrape_max_bytes_per_run,
                    settings.scrape_max_duration_seconds,
                    settings.scrape_max_new_documents,
                )
                with SessionLocal() as session, Fetcher(policy()) as fetcher:
                    ScrapeOrchestrator(
                        session=session,
                        fetcher=fetcher,
                        blob_store=BlobStore(settings.blob_storage_root),
                        budget=budget,
                        count_drop_abort_fraction=settings.count_drop_abort_fraction,
                        absence_streak_alert=settings.absence_streak_alert,
                    ).run()
                    session.commit()
                interval = settings.scrape_interval_hours * 3600
                next_scrape_at = time.monotonic() + interval * random.uniform(0.95, 1.05)
            with SessionLocal() as session, Fetcher(policy()) as fetcher:
                process_one_document(
                    session,
                    fetcher=fetcher,
                    blob_store=BlobStore(settings.blob_storage_root),
                    run_id="scheduled-document-worker",
                    owner=f"worker-{datetime.now(UTC).timestamp()}",
                )
                session.commit()
        except Exception as error:
            typer.echo(f"worker iteration failed: {type(error).__name__}", err=True)
        time.sleep(max(poll_seconds, 10))


@app.command("document-worker")
def document_worker(once: bool = True) -> None:
    settings = get_settings()
    with SessionLocal() as session, Fetcher(policy()) as fetcher:
        processed = process_one_document(
            session,
            fetcher=fetcher,
            blob_store=BlobStore(settings.blob_storage_root),
            run_id="document-worker",
            owner=f"cli-{datetime.now(UTC).timestamp()}",
        )
        session.commit()
    typer.echo("processed" if processed else "queue empty")
    if not once:
        typer.echo("continuous scheduling is provided by the container worker loop")


@app.command("status")
def runtime_status() -> None:
    with SessionLocal() as session:
        evaluate_coverage(session)
        session.commit()
        targets = [
            {
                "chamber": row.chamber,
                "kind": row.listing_kind,
                "language": row.language,
                "state": row.state,
                "last_success": row.last_success_at.isoformat() if row.last_success_at else None,
                "records": row.last_record_count,
            }
            for row in session.scalars(select(CoverageTarget))
        ]
        latest = session.scalar(select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(1))
        queue: dict[str, int] = {
            state: int(count)
            for state, count in session.execute(
                select(FetchQueueItem.state, func.count()).group_by(FetchQueueItem.state)
            ).tuples()
        }
    typer.echo(
        json.dumps(
            {
                "pipeline": {"parser": PARSER_VERSION},
                "coverage": targets,
                "queue": queue,
                "latest_run": latest.state if latest else None,
            },
            default=str,
        )
    )


@app.command()
def doctor() -> None:
    failures: list[str] = []
    settings = get_settings()
    with SessionLocal() as session:
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
        missing_current = session.scalars(
            select(DocumentVersion).where(
                DocumentVersion.is_current.is_(True),
                DocumentVersion.validation_status != "accepted",
            )
        ).all()
        if missing_current:
            failures.append("a current document version is not accepted")
        for blob in session.scalars(select(Blob)):
            if not BlobStore(settings.blob_storage_root).verify(
                blob.sha256, compression=blob.compression
            ):
                failures.append(f"blob missing or corrupt: {blob.sha256}")
    for failure in failures:
        typer.echo(f"FAIL: {failure}", err=True)
    if failures:
        raise typer.Exit(1)
    typer.echo("OK")


@app.command("verify-storage")
def verify_storage() -> None:
    settings = get_settings()
    store = BlobStore(settings.blob_storage_root)
    failures = 0
    orphaned = 0
    with SessionLocal() as session:
        database_digests = set(session.scalars(select(Blob.sha256)))
        for blob in session.scalars(select(Blob)):
            if not store.verify(blob.sha256, compression=blob.compression):
                typer.echo(f"missing-or-corrupt {blob.sha256}")
                failures += 1
        for digest in sorted(store.stored_digests() - database_digests):
            typer.echo(f"orphan {digest}")
            orphaned += 1
    typer.echo(json.dumps({"failures": failures, "orphans": orphaned}))
    if failures or orphaned:
        raise typer.Exit(1)


@app.command("prune-blobs")
def prune_blobs(apply: bool = typer.Option(False, "--apply")) -> None:
    settings = get_settings()
    store = BlobStore(settings.blob_storage_root)
    with SessionLocal() as session:
        candidates = list(session.scalars(select(Blob).where(Blob.ref_count == 0)).all())
        referenced = set(session.scalars(select(Blob.sha256)))
        orphaned = store.stored_digests() - referenced
        typer.echo(
            json.dumps(
                {
                    "database_candidates": len(candidates),
                    "orphans": len(orphaned),
                    "dry_run": not apply,
                }
            )
        )
        if apply:
            for blob in candidates:
                path = Path(blob.storage_path)
                try:
                    path.resolve().relative_to(settings.blob_storage_root.resolve())
                except ValueError:
                    raise typer.BadParameter("recorded blob path escapes storage root") from None
                path.unlink(missing_ok=True)
                session.delete(blob)
            for digest in orphaned:
                store.path_for(digest).unlink(missing_ok=True)
            session.commit()


@app.command("reparse")
def reparse(apply: bool = typer.Option(False, "--apply"), limit: int = 100) -> None:
    with SessionLocal() as session:
        job = run_reparse(
            session,
            blob_store=BlobStore(get_settings().blob_storage_root),
            dry_run=not apply,
            limit=limit,
        )
        session.commit()
        typer.echo(json.dumps(job.counts))


@app.command("reextract")
def reextract(apply: bool = typer.Option(False, "--apply"), limit: int = 100) -> None:
    with SessionLocal() as session:
        job = run_reextract(
            session,
            blob_store=BlobStore(get_settings().blob_storage_root),
            dry_run=not apply,
            limit=limit,
        )
        session.commit()
        typer.echo(json.dumps(job.counts))


@app.command("rechunk")
def rechunk(apply: bool = typer.Option(False, "--apply")) -> None:
    with SessionLocal() as session:
        job = record_deferred_job(session, kind="rechunk", dry_run=not apply)
        session.commit()
        typer.echo(json.dumps(job.counts))
        if job.state == "failed":
            raise typer.Exit(1)


@app.command("reembed")
def reembed(apply: bool = typer.Option(False, "--apply")) -> None:
    with SessionLocal() as session:
        job = record_deferred_job(session, kind="reembed", dry_run=not apply)
        session.commit()
        typer.echo(json.dumps(job.counts))
        if job.state == "failed":
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
