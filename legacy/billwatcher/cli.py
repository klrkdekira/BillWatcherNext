import json
import random
from datetime import UTC, datetime

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from billwatcher.config import get_settings
from billwatcher.db import SessionLocal
from billwatcher.jobs.audit_rebuild import check_audit_tree, rebuild_documents
from billwatcher.jobs.fixture_refresh import refresh_fixtures
from billwatcher.jobs.fixtures import load_fixture_listings
from billwatcher.jobs.mineru_extract import run_mineru_extract
from billwatcher.jobs.rechunk import run_rechunk
from billwatcher.jobs.reembed import drop_superseded_model, run_reembed
from billwatcher.jobs.reextract import run_reextract
from billwatcher.jobs.replay import run_reparse
from billwatcher.jobs.restructure import run_restructure
from billwatcher.jobs.retention import apply_retention
from billwatcher.mineru.client import MarkdownExtractorUnavailable
from billwatcher.mineru.client import build_extractor as build_mineru_extractor
from billwatcher.models import (
    Anomaly,
    Blob,
    ChunkEmbedding,
    CoverageTarget,
    FetchAttempt,
    FetchQueueItem,
    ScrapeRun,
)
from billwatcher.operations import (
    diagnose,
    evaluate_coverage,
    find_bill_number_gaps,
    prune_unreferenced_blobs,
)
from billwatcher.pipeline.cli import app as pipeline_app
from billwatcher.scraper.document_worker import (
    close_document_run,
    open_document_run,
    process_one_document,
    run_fetch_documents_step,
)
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.policy import CrawlPolicy
from billwatcher.scraper.queue import CrawlBudget
from billwatcher.scraper.worker import ScrapeOrchestrator
from billwatcher.search.embeddings import EmbeddingProviderUnavailable, build_provider
from billwatcher.search.evaluation import evaluate
from billwatcher.search.rag import AnswerProviderUnavailable, build_answer_provider
from billwatcher.storage import build_blob_store
from billwatcher.storage.audit_tree import AuditTree
from billwatcher.version import PARSER_VERSION


def audit_tree_store() -> AuditTree:
    return AuditTree(get_settings().audit_tree_root)


app = typer.Typer(no_args_is_help=True, help="BillWatcherNext operator commands.")
# The file-first pipeline (listings -> bills -> documents, no database, no object store) is a
# self-contained sub-app: it never imports billwatcher.db/models, only the Postgres-backed
# commands above do.
app.add_typer(pipeline_app, name="pipeline")


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
        ca_bundle=settings.upstream_ca_bundle,
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
    archive: bool = typer.Option(
        False, "--archive", help="Crawl only the archive tree, skipping the current listings"
    ),
    archive_years: int | None = typer.Option(
        None,
        "--archive-years",
        help="Read only the newest N archived years instead of all of them",
    ),
    approve_live: bool = typer.Option(False, "--approve-live"),
) -> None:
    if full and archive:
        raise typer.BadParameter("--full already includes the archive; pass one or the other")
    settings = get_settings()
    if not (settings.scrape_enabled or approve_live):
        raise typer.BadParameter(
            "live crawl is disabled; set SCRAPE_ENABLED=true or pass --approve-live"
        )
    # The archive is a different size of job, so it gets the budget HANDOFF 11.7 gives it.
    budget = (
        CrawlBudget(
            settings.archive_max_requests_per_run,
            settings.archive_max_bytes_per_run,
            settings.archive_max_duration_seconds,
            settings.archive_max_new_documents,
        )
        if full or archive
        else CrawlBudget(
            settings.scrape_max_requests_per_run,
            settings.scrape_max_bytes_per_run,
            settings.scrape_max_duration_seconds,
            settings.scrape_max_new_documents,
        )
    )
    with SessionLocal() as session, Fetcher(policy()) as fetcher:
        run = ScrapeOrchestrator(
            session=session,
            fetcher=fetcher,
            blob_store=build_blob_store(settings),
            budget=budget,
            count_drop_abort_fraction=settings.count_drop_abort_fraction,
            absence_streak_alert=settings.absence_streak_alert,
            allow_missing_robots=settings.robots_missing_policy == "allow",
            archive_year_limit=archive_years,
        ).run(mode="archive" if archive else "full" if full else "incremental")
        session.commit()
        typer.echo(
            json.dumps(
                {
                    "run_id": run.id,
                    "state": run.state,
                    "publish_decision": run.publish_decision,
                    "reason": run.publish_reason,
                    "fetched": run.fetched,
                    "parsed": run.parsed,
                    "inserted": run.inserted,
                    "updated": run.updated,
                }
            )
        )
        if run.state not in {"succeeded", "partial"}:
            _explain_failed_run(run)
            raise typer.Exit(1)


# Operator guidance for failures whose cause is not obvious from the message alone.
_FAILURE_HINTS: dict[str, str] = {
    "CERTIFICATE_VERIFY_FAILED": (
        "The upstream TLS chain did not verify. This is usually an incomplete chain served by "
        "the site (a missing intermediate certificate) rather than a problem with this host: "
        "browsers hide it by fetching the intermediate themselves, and Python does not. "
        "Check `openssl s_client -connect www.parlimen.gov.my:443 -servername "
        "www.parlimen.gov.my`; if only one certificate is shown, add the missing intermediate "
        "to a bundle and point UPSTREAM_CA_BUNDLE at it. See docs/upstream.md. "
        "Never disable verification."
    ),
    "robots.txt": (
        "Crawl policy could not be established. HANDOFF section 5 requires a readable "
        "robots.txt before any crawl, so the run stopped and prior data is untouched."
    ),
}


def _explain_failed_run(run: ScrapeRun) -> None:
    detail = ""
    if run.error_details:
        detail = f"{run.error_details.get('class', '')}: {run.error_details.get('detail', '')}"
    message = run.publish_reason or detail or "no reason recorded"
    typer.echo(f"FAIL: {message}", err=True)
    haystack = f"{message} {detail}"
    for needle, hint in _FAILURE_HINTS.items():
        if needle in haystack:
            typer.echo(f"\n{hint}", err=True)
            break
    typer.echo(
        f"\nInspect the run with: uv run billwatcher run-report {run.id}",
        err=True,
    )


@app.command("anomalies")
def list_anomalies(
    severity: str | None = typer.Option(None, "--severity", help="critical, warn, or info"),
    kind: str | None = typer.Option(None, "--kind"),
    include_resolved: bool = typer.Option(False, "--include-resolved"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """List anomalies with their ids, which is what acknowledging or resolving one needs.

    `status` reports counts; this reports the work list.
    """
    with SessionLocal() as session:
        query = select(Anomaly).order_by(Anomaly.severity, Anomaly.last_seen_at.desc())
        if not include_resolved:
            query = query.where(Anomaly.resolved_at.is_(None))
        if severity:
            query = query.where(Anomaly.severity == severity)
        if kind:
            query = query.where(Anomaly.kind == kind)
        rows = session.scalars(query.limit(limit)).all()
        typer.echo(
            json.dumps(
                [
                    {
                        "id": row.id,
                        "kind": row.kind,
                        "severity": row.severity,
                        "entity": f"{row.entity_type}:{row.entity_id}" if row.entity_type else None,
                        "url": row.url,
                        "occurrences": row.occurrence_count,
                        "first_seen": row.first_seen_at.isoformat(),
                        "last_seen": row.last_seen_at.isoformat(),
                        "acknowledged_at": row.acknowledged_at.isoformat()
                        if row.acknowledged_at
                        else None,
                        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
                        "detail": row.detail_json,
                    }
                    for row in rows
                ],
                indent=2,
            )
        )


def _close_anomaly(anomaly_id: str, *, by: str, note: str, resolve: bool) -> None:
    """Record a human decision about one anomaly.

    `make doctor` is the gate that stands in for CI, and it fails on unresolved critical
    anomalies. Without a way to close one, the first critical finding would leave the gate red for
    ever and an operator would learn to ignore it — which is exactly the failure mode the anomaly
    table was introduced to prevent (HANDOFF 25.2 defect 13).
    """
    now = datetime.now(UTC)
    with SessionLocal() as session:
        anomaly = session.get(Anomaly, anomaly_id)
        if anomaly is None:
            typer.echo(f"FAIL: no anomaly with id {anomaly_id}", err=True)
            raise typer.Exit(2)
        if not by.strip() or not note.strip():
            raise typer.BadParameter("both --by and --note are required; the reason is the record")
        anomaly.acknowledged_at = anomaly.acknowledged_at or now
        anomaly.acknowledged_by = by
        detail = dict(anomaly.detail_json)
        decisions = list(detail.get("decisions", []))
        decisions.append({"at": now.isoformat(), "by": by, "note": note, "resolved": resolve})
        detail["decisions"] = decisions[-10:]
        anomaly.detail_json = detail
        if resolve:
            anomaly.resolved_at = now
        session.commit()
        typer.echo(
            json.dumps(
                {
                    "id": anomaly.id,
                    "kind": anomaly.kind,
                    "acknowledged_at": anomaly.acknowledged_at.isoformat(),
                    "resolved_at": anomaly.resolved_at.isoformat() if anomaly.resolved_at else None,
                }
            )
        )


@app.command("acknowledge-anomaly")
def acknowledge_anomaly(
    anomaly_id: str,
    by: str = typer.Option(..., "--by", help="Who reviewed it"),
    note: str = typer.Option(..., "--note", help="What was decided, and why"),
) -> None:
    """Record that a critical anomaly has been reviewed and is deliberately not blocking.

    The condition stays visible on `/status` and keeps counting occurrences; it stops failing
    `make doctor`. Use this when upstream is at fault and there is nothing to fix here.
    """
    _close_anomaly(anomaly_id, by=by, note=note, resolve=False)


@app.command("resolve-anomaly")
def resolve_anomaly(
    anomaly_id: str,
    by: str = typer.Option(..., "--by", help="Who resolved it"),
    note: str = typer.Option(..., "--note", help="What was done"),
) -> None:
    """Close an anomaly whose cause has been dealt with. It reappears if the cause recurs."""
    _close_anomaly(anomaly_id, by=by, note=note, resolve=True)


@app.command("run-report")
def run_report(run_id: str) -> None:
    """Print everything recorded about one scrape run, including why it stopped."""
    with SessionLocal() as session:
        run = session.get(ScrapeRun, run_id)
        if run is None:
            typer.echo(f"FAIL: no run with id {run_id}", err=True)
            raise typer.Exit(2)
        attempts = session.scalars(
            select(FetchAttempt)
            .where(FetchAttempt.run_id == run_id)
            .order_by(FetchAttempt.attempted_at)
        ).all()
        anomalies = session.scalars(
            select(Anomaly)
            .where(Anomaly.resolved_at.is_(None))
            .order_by(Anomaly.last_seen_at.desc())
            .limit(20)
        ).all()
        typer.echo(
            json.dumps(
                {
                    "run": {
                        "id": run.id,
                        "mode": run.mode,
                        "trigger": run.trigger,
                        "state": run.state,
                        "started_at": run.started_at,
                        "ended_at": run.ended_at,
                        "publish_decision": run.publish_decision,
                        "publish_reason": run.publish_reason,
                        "error_details": run.error_details,
                        "counts": {
                            "fetched": run.fetched,
                            "parsed": run.parsed,
                            "inserted": run.inserted,
                            "updated": run.updated,
                            "failed": run.failed,
                        },
                    },
                    "attempts": [
                        {
                            "url": attempt.url,
                            "status_code": attempt.status_code,
                            "error_class": attempt.error_class,
                            "error_detail": attempt.error_detail,
                            "bytes": attempt.bytes_received,
                        }
                        for attempt in attempts
                    ],
                    "open_anomalies": [
                        {
                            "kind": anomaly.kind,
                            "severity": anomaly.severity,
                            "occurrences": anomaly.occurrence_count,
                            "detail": anomaly.detail_json,
                        }
                        for anomaly in anomalies
                    ],
                },
                indent=2,
                default=str,
            )
        )


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
                        blob_store=build_blob_store(settings),
                        budget=budget,
                        count_drop_abort_fraction=settings.count_drop_abort_fraction,
                        absence_streak_alert=settings.absence_streak_alert,
                        allow_missing_robots=settings.robots_missing_policy == "allow",
                    ).run()
                    session.commit()
                interval = settings.scrape_interval_hours * 3600
                next_scrape_at = time.monotonic() + interval * random.uniform(0.95, 1.05)
            with SessionLocal() as session, Fetcher(policy()) as fetcher:
                run = open_document_run(session, trigger="schedule")
                session.commit()
                processed = int(
                    process_one_document(
                        session,
                        fetcher=fetcher,
                        blob_store=build_blob_store(settings),
                        run_id=run.id,
                        owner=f"worker-{datetime.now(UTC).timestamp()}",
                    )
                )
                close_document_run(session, run, processed=processed)
                session.commit()
        except Exception as error:
            typer.echo(f"worker iteration failed: {type(error).__name__}", err=True)
        time.sleep(max(poll_seconds, 10))


@app.command("document-worker")
def document_worker(once: bool = True, limit: int = 1) -> None:
    """Download queued documents. Every attempt is attributed to a real run row."""
    settings = get_settings()
    with SessionLocal() as session, Fetcher(policy()) as fetcher:
        run = open_document_run(session, trigger="manual")
        session.commit()
        store = build_blob_store(settings)
        processed = 0
        for _ in range(max(1, limit)):
            if not process_one_document(
                session,
                fetcher=fetcher,
                blob_store=store,
                run_id=run.id,
                owner=f"cli-{datetime.now(UTC).timestamp()}",
            ):
                break
            processed += 1
            session.commit()
        close_document_run(session, run, processed=processed)
        session.commit()
    typer.echo(json.dumps({"run_id": run.id, "processed": processed}))
    if not once:
        typer.echo("continuous scheduling is provided by the container worker loop")


@app.command("fetch-documents")
def fetch_documents(
    limit: int = typer.Option(
        5000, "--limit", help="Safety cap on items drained in one process, not a live-crawl budget"
    ),
    approve_live: bool = typer.Option(False, "--approve-live"),
) -> None:
    """Step S3 (HANDOFF 27.1): drain the document queue, writing PDFs + sidecars to the audit tree.

    Unlike `document-worker`, this is the auditable pipeline step: it runs until the queue is
    empty (or the safety cap is hit) and materialises every accepted or quarantined download into
    `03-documents/` as it downloads it, one manifest per run. It issues live HTTP requests to the
    same allowlisted hosts as `scrape`, so it is gated the same way.
    """
    settings = get_settings()
    if not (settings.scrape_enabled or approve_live):
        raise typer.BadParameter(
            "live document fetch is disabled; set SCRAPE_ENABLED=true or pass --approve-live"
        )
    with SessionLocal() as session, Fetcher(policy()) as fetcher:
        manifest = run_fetch_documents_step(
            session,
            fetcher=fetcher,
            blob_store=build_blob_store(settings),
            audit_tree=audit_tree_store(),
            trigger="manual",
            limit=limit,
        )
    typer.echo(json.dumps(manifest, default=str))


@app.command("load-fixtures")
def load_fixtures(
    confirm_production: bool = typer.Option(
        False, "--confirm-production", help="Required to seed a production database."
    ),
) -> None:
    """Ingest the committed listing fixtures offline so the whole site works with no network."""
    settings = get_settings()
    if settings.environment == "production" and not confirm_production:
        typer.echo(
            "FAIL: refusing to load fixture data into a production database; "
            "pass --confirm-production if that is really intended",
            err=True,
        )
        raise typer.Exit(2)
    with SessionLocal() as session:
        report = load_fixture_listings(session, blob_store=build_blob_store(settings))
        session.commit()
        typer.echo(json.dumps(report.as_counts()))


@app.command("refresh-fixtures")
def refresh_fixtures_command(
    apply: bool = typer.Option(False, "--apply", help="Overwrite the committed fixtures"),
    records: int = typer.Option(4, "--records", help="How many records to keep per fixture"),
) -> None:
    """Regenerate the committed fixtures from stored snapshots, offline (HANDOFF 16.3).

    Writes to `tests/fixtures/parliament/regenerated/` for review unless `--apply` is given.
    Never contacts Parliament: the only input is a snapshot already in the blob store.
    """
    settings = get_settings()
    with SessionLocal() as session:
        report = refresh_fixtures(
            session,
            blob_store=build_blob_store(settings),
            apply=apply,
            record_limit=records,
        )
        typer.echo(json.dumps(report.as_counts(), indent=2))
        if not report.refreshed:
            typer.echo(
                "No fixture could be regenerated: no stored upstream snapshot matches any "
                "fixture target. Run a crawl first, or seed from fixtures and crawl live.",
                err=True,
            )
            raise typer.Exit(1)


@app.command("status")
def runtime_status() -> None:
    with SessionLocal() as session:
        evaluate_coverage(session)
        session.commit()
        targets = [
            {
                "chamber": row.chamber,
                "kind": row.listing_kind,
                "scope": row.scope_key,
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


@app.command("completeness")
def completeness() -> None:
    """Report candidate bill-numbering gaps in closed archive years.

    A heuristic, not a gate: nothing confirms Parliament numbers bills with no gaps at all, so a
    reported gap means "worth checking the archive by hand," never "a bug." Restricted to years
    whose archive coverage target is closed (HANDOFF 10.4) — the current or a partially-crawled
    year is still growing, and a hole there is just a bill not yet fetched.
    """
    with SessionLocal() as session:
        gaps = find_bill_number_gaps(session)
    typer.echo(
        json.dumps(
            [
                {
                    "chamber": gap.chamber,
                    "year": gap.year,
                    "range": [gap.lowest, gap.highest],
                    "missing_numbers": gap.missing_numbers,
                }
                for gap in gaps
            ],
            indent=2,
        )
    )
    if gaps:
        typer.echo(
            f"\n{len(gaps)} chamber-year group(s) with candidate gaps — for review, not a "
            "failure; make doctor does not fail on this.",
            err=True,
        )


@app.command()
def doctor() -> None:
    settings = get_settings()
    with SessionLocal() as session:
        failures = diagnose(session, blob_store=build_blob_store(settings))
    for failure in failures:
        typer.echo(f"FAIL: {failure}", err=True)
    if failures:
        raise typer.Exit(1)
    typer.echo("OK")


@app.command("verify-storage")
def verify_storage() -> None:
    settings = get_settings()
    store = build_blob_store(settings)
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


@app.command("verify-audit")
def verify_audit() -> None:
    """Re-hash the audit tree against the database and exit non-zero on any divergence.

    Scoped to `03-documents/` today (Package K): the listing and processing tiers are not built
    yet. A clean result here does not certify a tier this command does not check.
    """
    settings = get_settings()
    with SessionLocal() as session:
        issues = check_audit_tree(
            session,
            audit_tree=audit_tree_store(),
            blob_store=build_blob_store(settings),
            now=datetime.now(UTC),
        )
        session.commit()
    for issue in issues:
        typer.echo(issue, err=True)
    typer.echo(json.dumps({"issues": len(issues)}))
    if issues:
        raise typer.Exit(1)


@app.command("audit-rebuild")
def audit_rebuild() -> None:
    """Regenerate the audit tree from the database and blob store.

    Byte-identical and a no-op over an already-correct tree (HANDOFF 27.4): every write goes
    through the write-if-changed rule, so this is also the recovery path after deleting the
    tree and the backfill path after a sidecar schema bump. Scoped to `03-documents/` today.
    """
    settings = get_settings()
    with SessionLocal() as session:
        report = rebuild_documents(
            session, blob_store=build_blob_store(settings), audit_tree=audit_tree_store()
        )
    typer.echo(json.dumps(report))


@app.command("prune-blobs")
def prune_blobs(apply: bool = typer.Option(False, "--apply")) -> None:
    settings = get_settings()
    store = build_blob_store(settings)
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
            blob_store=build_blob_store(get_settings()),
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
            blob_store=build_blob_store(get_settings()),
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


@app.command("restructure")
def restructure(apply: bool = typer.Option(False, "--apply"), limit: int = 100) -> None:
    """Read structure from stored bytes and record each document's Gate L1 verdict.

    Offline: it never contacts Parliament. A reading that fails the gate is stored for review
    and is not promoted, so nothing downstream builds on an unvalidated tree (HANDOFF 26.3).
    """
    with SessionLocal() as session:
        job = run_restructure(
            session, blob_store=build_blob_store(get_settings()), dry_run=not apply, limit=limit
        )
        if apply:
            session.commit()
        typer.echo(json.dumps(job.counts))
        if job.state == "failed":
            raise typer.Exit(1)


@app.command("mineru-extract")
def mineru_extract(apply: bool = typer.Option(False, "--apply"), limit: int = 50) -> None:
    """A second, independently versioned markdown reading of stored PDFs via MinerU.

    Never contacts Parliament, but does call the configured MinerU endpoint over the network for
    each eligible document. Written only as a local file artifact under `data/04-text/` — never
    into `document_extractions` (HANDOFF 27.7). Eligibility is decided by what markdown already
    exists on disk, so re-running costs nothing for a document already processed.
    """
    settings = get_settings()
    try:
        extractor = build_mineru_extractor(settings)
    except MarkdownExtractorUnavailable as error:
        typer.echo(f"FAIL: {error}", err=True)
        raise typer.Exit(2) from None
    with SessionLocal() as session:
        job = run_mineru_extract(
            session,
            blob_store=build_blob_store(settings),
            audit_tree=audit_tree_store(),
            extractor=extractor,
            render_dpi=settings.mineru_render_dpi,
            mineru_base_url=settings.mineru_base_url,
            dry_run=not apply,
            limit=limit,
        )
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
    # HANDOFF 20 makes the manual gate log in docs/status.md the record that substitutes for CI,
    # so the useful thing this command can do is emit the line to paste into it. A result nobody
    # writes down is not a gate.
    verdict = "MET" if report.met_thresholds else "NOT MET"
    typer.echo("")
    typer.echo("Gate-log line for docs/status.md (HANDOFF 20):")
    typer.echo(
        f"- {datetime.now(UTC).date().isoformat()} — <your name> — Evaluation set "
        f"{report.set_version} / corpus {report.corpus_version} against embeddings "
        f"`{report.embedding_model}`"
        + (f" and answers `{report.answer_model}`" if report.answer_model else "")
        + f". Thresholds **{verdict}**: "
        + ", ".join(f"{name} {value}" for name, value in report.metrics.items())
        + "."
    )
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
