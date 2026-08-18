"""Operational gates that substitute for CI: doctor, blob pruning, and retention."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.jobs.retention import apply_retention
from billwatcher.models import (
    Anomaly,
    Bill,
    Blob,
    DailyFetchMetric,
    Document,
    DocumentExtraction,
    DocumentVersion,
    FetchAttempt,
    SourceSnapshot,
)
from billwatcher.operations import diagnose, prune_unreferenced_blobs
from billwatcher.storage.blobs import BlobStore

NOW = datetime(2026, 8, 17, tzinfo=UTC)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


def anomaly(kind: str, severity: str) -> Anomaly:
    return Anomaly(
        kind=kind, severity=severity, detail_json={}, first_seen_at=NOW, last_seen_at=NOW
    )


def test_doctor_fails_on_a_seeded_critical_anomaly_and_clears_when_resolved(
    session: Session, tmp_path
) -> None:
    store = BlobStore(tmp_path)
    assert diagnose(session, blob_store=store) == []

    session.add(anomaly("structure_drift", "critical"))
    session.flush()
    failures = diagnose(session, blob_store=store)
    assert failures == ["1 unresolved critical anomalies"]

    session.scalars(select(Anomaly)).one().resolved_at = NOW
    session.flush()
    assert diagnose(session, blob_store=store) == []


def test_doctor_ignores_warnings_but_reports_a_missing_blob(session: Session, tmp_path) -> None:
    store = BlobStore(tmp_path)
    session.add(anomaly("unmapped_status", "warn"))
    stored = store.put(b"%PDF-1.7 present", compress=False)
    session.add(
        Blob(
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            media_type="application/pdf",
            storage_path=str(stored.path),
            compression=stored.compression,
            ref_count=1,
        )
    )
    session.flush()
    assert diagnose(session, blob_store=store) == []

    stored.path.unlink()
    assert diagnose(session, blob_store=store) == [f"blob missing or corrupt: {stored.sha256}"]


def test_prune_keeps_a_blob_two_documents_share(session: Session, tmp_path) -> None:
    store = BlobStore(tmp_path)
    shared = store.put(b"%PDF-1.7 shared bytes", compress=False)
    orphan = store.put(b"%PDF-1.7 nothing points here", compress=False)
    session.add_all(
        [
            Blob(
                sha256=shared.sha256,
                byte_size=shared.byte_size,
                media_type="application/pdf",
                storage_path=str(shared.path),
                compression=shared.compression,
                ref_count=2,
            ),
            Blob(
                sha256=orphan.sha256,
                byte_size=orphan.byte_size,
                media_type="application/pdf",
                storage_path=str(orphan.path),
                compression=orphan.compression,
                ref_count=0,
            ),
        ]
    )
    session.flush()

    dry = prune_unreferenced_blobs(session, blob_store=store, dry_run=True)
    assert dry.database_candidates == 1
    assert dry.deleted == 0
    assert shared.path.exists() and orphan.path.exists()

    applied = prune_unreferenced_blobs(session, blob_store=store, dry_run=False)
    session.flush()
    assert applied.deleted == 1
    assert shared.path.exists()
    assert not orphan.path.exists()
    assert session.get(Blob, shared.sha256) is not None
    assert session.get(Blob, orphan.sha256) is None


def test_retention_rolls_up_transport_logs_without_touching_the_archive(session: Session) -> None:
    run = _run(session)
    old = NOW - timedelta(days=200)
    for index in range(3):
        session.add(
            FetchAttempt(
                run_id=run,
                target_kind="listing",
                url="https://www.parlimen.gov.my/bills-dewan-rakyat.html",
                method="GET",
                attempted_at=old,
                duration_ms=100 + index,
                status_code=200,
                bytes_received=1000,
            )
        )
    session.add(
        FetchAttempt(
            run_id=run,
            target_kind="listing",
            url="https://www.parlimen.gov.my/bills-dewan-negara.html",
            method="GET",
            attempted_at=NOW,
            duration_ms=90,
            status_code=200,
            bytes_received=500,
        )
    )
    session.flush()

    dry = apply_retention(session, fetch_attempt_retention_days=180, now=NOW, dry_run=True)
    assert dry.fetch_attempts_aggregated == 3
    assert dry.fetch_attempts_deleted == 0
    assert session.scalar(select(DailyFetchMetric)) is None

    applied = apply_retention(session, fetch_attempt_retention_days=180, now=NOW, dry_run=False)
    session.flush()
    assert applied.fetch_attempts_deleted == 3
    metric = session.scalars(select(DailyFetchMetric)).one()
    assert metric.count == 3
    assert metric.bytes_received == 3000
    assert metric.host == "www.parlimen.gov.my"
    remaining = session.scalars(select(FetchAttempt)).all()
    assert len(remaining) == 1
    assert remaining[0].attempted_at.replace(tzinfo=UTC) == NOW


def test_retention_keeps_current_and_previous_extractions_only(session: Session) -> None:
    version = _document_version(session)
    for index, extractor_version in enumerate(("0.8.0", "0.9.0", "1.0.0")):
        session.add(
            DocumentExtraction(
                document_version_id=version,
                extractor_name="pypdf",
                extractor_version=extractor_version,
                pipeline_version=extractor_version,
                mode="native",
                status="succeeded",
                extracted_text="teks",
                text_sha256="a" * 64,
                page_count=1,
                char_count=4,
                is_current=extractor_version == "1.0.0",
                created_at=NOW + timedelta(minutes=index),
                duration_ms=1,
            )
        )
    session.flush()

    report = apply_retention(session, fetch_attempt_retention_days=180, now=NOW, dry_run=False)
    session.flush()
    assert report.extractions_pruned == 1
    kept = session.scalars(select(DocumentExtraction)).all()
    assert {row.extractor_version for row in kept} == {"1.0.0", "0.9.0"}
    # The document version and its bytes are never retention targets.
    assert session.get(DocumentVersion, version) is not None


def _run(session: Session) -> str:
    from billwatcher.models import ScrapeRun

    run = ScrapeRun(mode="fixture", trigger="manual", started_at=NOW, state="succeeded")
    session.add(run)
    session.flush()
    return run.id


def _document_version(session: Session) -> str:
    run = _run(session)
    bill = Bill(
        identifier_raw="D.R.15/2026",
        identifier_normalized="DR-15-2026",
        slug="dr-15-2026",
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )
    document = Document(
        document_kind="bill_as_introduced",
        language="ms",
        canonical_source_url="https://www.parlimen.gov.my/dr15.pdf",
        source_url_raw="https://www.parlimen.gov.my/dr15.pdf",
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )
    session.add_all([bill, document])
    session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        content_sha256="d" * 64,
        blob_sha256="d" * 64,
        byte_size=8,
        http_status=200,
        final_url=document.canonical_source_url,
        retrieved_at=NOW,
        last_verified_at=NOW,
        run_id=run,
        fetch_attempt_id="attempt",
        is_current=True,
        change_kind="initial",
        validation_status="accepted",
    )
    session.add(version)
    session.flush()
    return version.id


def test_retention_releases_only_failed_snapshot_blobs(session: Session, tmp_path) -> None:
    run = _run(session)
    store = BlobStore(tmp_path)
    stored = store.put(b"<html>gateway error</html>", compress=True)
    session.add(
        Blob(
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            media_type="text/html",
            storage_path=str(stored.path),
            compression=stored.compression,
            ref_count=1,
        )
    )
    session.add(
        SourceSnapshot(
            run_id=run,
            url="https://www.parlimen.gov.my/bills-dewan-rakyat.html",
            final_url="https://www.parlimen.gov.my/bills-dewan-rakyat.html",
            requested_at=NOW - timedelta(days=120),
            status_code=200,
            blob_sha256=stored.sha256,
            parser_version="1.0.0",
            parse_status="failed",
            retention_class="routine",
        )
    )
    session.flush()

    report = apply_retention(session, fetch_attempt_retention_days=180, now=NOW, dry_run=False)
    session.flush()
    assert report.snapshot_blobs_dereferenced == 1
    blob = session.get(Blob, stored.sha256)
    assert blob is not None and blob.ref_count == 0
    # Retention never deletes bytes; only the reference-checked pruner may.
    assert stored.path.exists()
