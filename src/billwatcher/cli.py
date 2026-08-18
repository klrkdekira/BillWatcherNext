import json
import random
from datetime import UTC, datetime

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from billwatcher.config import get_settings
from billwatcher.db import SessionLocal
from billwatcher.jobs.rechunk import run_rechunk
from billwatcher.jobs.reembed import drop_superseded_model, run_reembed
from billwatcher.jobs.reextract import run_reextract
from billwatcher.jobs.replay import run_reparse
from billwatcher.jobs.retention import apply_retention
from billwatcher.models import (
    Blob,
    ChunkEmbedding,
    CoverageTarget,
    FetchQueueItem,
    ScrapeRun,
)
from billwatcher.operations import diagnose, evaluate_coverage, prune_unreferenced_blobs
from billwatcher.scraper.document_worker import process_one_document
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.policy import CrawlPolicy
from billwatcher.scraper.queue import CrawlBudget
from billwatcher.scraper.worker import ScrapeOrchestrator
from billwatcher.search.embeddings import EmbeddingProviderUnavailable, build_provider
from billwatcher.search.evaluation import evaluate
from billwatcher.search.rag import AnswerProviderUnavailable, build_answer_provider
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
    settings = get_settings()
    with SessionLocal() as session:
        failures = diagnose(session, blob_store=BlobStore(settings.blob_storage_root))
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
        try:
            report = prune_unreferenced_blobs(session, blob_store=store, dry_run=not apply)
        except ValueError as error:
            raise typer.BadParameter(str(error)) from None
        if apply:
            session.commit()
        typer.echo(json.dumps(report.as_counts()))


@app.command("retention")
def retention(apply: bool = typer.Option(False, "--apply")) -> None:
    """Aggregate expiring transport logs and release prunable blob references (HANDOFF 16.4)."""
    settings = get_settings()
    with SessionLocal() as session:
        report = apply_retention(
            session,
            fetch_attempt_retention_days=settings.fetch_attempt_retention_days,
            dry_run=not apply,
        )
        if apply:
            session.commit()
        typer.echo(json.dumps(report.as_counts()))


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
def rechunk(apply: bool = typer.Option(False, "--apply"), limit: int = 100) -> None:
    """Rebuild chunk sets at the current chunker version; older sets are demoted, not deleted."""
    with SessionLocal() as session:
        job = run_rechunk(session, dry_run=not apply, limit=limit)
        if apply:
            session.commit()
        typer.echo(json.dumps(job.counts))
        if job.state == "failed":
            raise typer.Exit(1)


@app.command("reembed")
def reembed(apply: bool = typer.Option(False, "--apply"), limit: int = 200) -> None:
    """Backfill vectors for the configured model alongside any previous model's vectors."""
    try:
        provider = build_provider(get_settings())
    except EmbeddingProviderUnavailable as error:
        typer.echo(f"FAIL: {error}", err=True)
        raise typer.Exit(2) from None
    with SessionLocal() as session:
        job = run_reembed(session, provider=provider, dry_run=not apply, limit=limit)
        if apply:
            session.commit()
        typer.echo(json.dumps(job.counts))
        if job.state == "failed":
            raise typer.Exit(1)


@app.command("semantic-index")
def semantic_index(
    apply: bool = typer.Option(False, "--apply"),
    lists: int = typer.Option(0, help="Unused; HNSW is built with m/ef_construction defaults."),
) -> None:
    """Build the HNSW cosine index once representative vectors exist (HANDOFF 12.3)."""
    with SessionLocal() as session:
        if session.get_bind().dialect.name != "postgresql":
            typer.echo("FAIL: a vector index requires PostgreSQL", err=True)
            raise typer.Exit(2)
        rows = session.scalar(select(func.count()).select_from(ChunkEmbedding)) or 0
        typer.echo(json.dumps({"vectors": rows, "dry_run": not apply}))
        if not apply:
            return
        if rows == 0:
            typer.echo("FAIL: refusing to build an index before any vectors exist", err=True)
            raise typer.Exit(1)
        session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_hnsw ON chunk_embeddings "
                "USING hnsw (embedding vector_cosine_ops)"
            )
        )
        session.commit()
        typer.echo("OK")


@app.command("evaluate")
def evaluate_retrieval(as_json: bool = typer.Option(False, "--json")) -> None:
    """Score the versioned retrieval/answer evaluation set (HANDOFF 13) offline."""
    settings = get_settings()
    try:
        embedding_provider = build_provider(settings)
    except EmbeddingProviderUnavailable as error:
        typer.echo(f"FAIL: {error}", err=True)
        raise typer.Exit(2) from None
    answer_provider = None
    if settings.rag_enabled:
        try:
            answer_provider = build_answer_provider(settings)
        except AnswerProviderUnavailable as error:
            typer.echo(f"WARN: {error}; scoring retrieval only", err=True)
    report = evaluate(
        settings=settings,
        embedding_provider=embedding_provider,
        answer_provider=answer_provider,
    )
    if as_json:
        typer.echo(json.dumps(report.as_dict(), indent=2))
    else:
        typer.echo(
            f"set {report.set_version} / corpus {report.corpus_version} "
            f"/ embeddings {report.embedding_model}"
        )
        for name, value in report.metrics.items():
            threshold = report.thresholds.get(name)
            mark = "ok " if threshold is None or value >= threshold else "LOW"
            typer.echo(f"  {mark} {name}: {value} (threshold {threshold})")
        for case in report.cases:
            if not case.passed:
                typer.echo(f"  failed: {case.case_id} — {case.detail}")
    if not report.met_thresholds:
        typer.echo(
            "Thresholds not met. Record this before enabling semantic search or RAG.", err=True
        )
        raise typer.Exit(1)


@app.command("drop-embedding-model")
def drop_embedding_model(model_id: str, apply: bool = typer.Option(False, "--apply")) -> None:
    """Remove a superseded model's vectors after its replacement has been validated."""
    with SessionLocal() as session:
        removed = drop_superseded_model(session, model_id=model_id, dry_run=not apply)
        if apply:
            session.commit()
        typer.echo(json.dumps({"model_id": model_id, "vectors": removed, "dry_run": not apply}))


if __name__ == "__main__":
    app()
