"""The extraction failure spike anomaly (HANDOFF 10.5)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import (
    Anomaly,
    Blob,
    Document,
    DocumentExtraction,
    DocumentVersion,
    FetchAttempt,
    ScrapeRun,
)
from billwatcher.scraper.service import evaluate_extraction_health

NOW = datetime(2026, 8, 17, tzinfo=UTC)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


def seed_extractions(session: Session, statuses: list[str]) -> None:
    offset = session.scalar(select(func.count()).select_from(Blob)) or 0
    run = ScrapeRun(mode="fixture", trigger="manual", started_at=NOW, state="succeeded")
    session.add(run)
    session.flush()
    attempt = FetchAttempt(
        run_id=run.id,
        target_kind="document",
        url="https://www.parlimen.gov.my/doc.pdf",
        method="GET",
        attempted_at=NOW,
        duration_ms=1,
        status_code=200,
    )
    session.add(attempt)
    session.flush()
    for position, status in enumerate(statuses):
        index = offset + position
        digest = f"{index:064d}"
        session.add(
            Blob(
                sha256=digest,
                byte_size=1,
                media_type="application/pdf",
                storage_path=f"var/blobs/{digest}",
                compression="none",
                ref_count=1,
            )
        )
        document = Document(
            document_kind="bill_as_introduced",
            language="ms",
            canonical_source_url=f"https://www.parlimen.gov.my/{index}.pdf",
            source_url_raw=f"https://www.parlimen.gov.my/{index}.pdf",
            first_seen_at=NOW,
            last_seen_at=NOW,
            last_checked_at=NOW,
            last_changed_at=NOW,
        )
        session.add(document)
        session.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_no=1,
            content_sha256=digest,
            blob_sha256=digest,
            byte_size=1,
            http_status=200,
            final_url=document.canonical_source_url,
            retrieved_at=NOW,
            last_verified_at=NOW,
            run_id=run.id,
            fetch_attempt_id=attempt.id,
            is_current=True,
            change_kind="initial",
            validation_status="accepted",
        )
        session.add(version)
        session.flush()
        session.add(
            DocumentExtraction(
                document_version_id=version.id,
                extractor_name="pypdf",
                extractor_version="1.0.0",
                pipeline_version="1.0.0",
                mode="native",
                status=status,
                extracted_text="teks" if status == "succeeded" else None,
                text_sha256=digest,
                page_count=1,
                char_count=4,
                is_current=True,
                created_at=NOW + timedelta(minutes=index),
                duration_ms=1,
            )
        )
    session.flush()


def test_too_little_data_is_not_a_spike(session: Session) -> None:
    seed_extractions(session, ["failed", "failed"])
    assert evaluate_extraction_health(session, now=NOW) is None
    assert session.scalars(select(Anomaly)).all() == []


def test_an_ordinary_failure_rate_raises_nothing(session: Session) -> None:
    seed_extractions(session, ["succeeded"] * 8 + ["failed", "empty"])
    rate = evaluate_extraction_health(session, now=NOW)
    assert rate == pytest.approx(0.2)
    assert session.scalars(select(Anomaly)).all() == []


def test_a_failure_spike_raises_a_warning_and_clears_when_it_recovers(session: Session) -> None:
    seed_extractions(session, ["failed"] * 6 + ["succeeded"] * 2)
    rate = evaluate_extraction_health(session, now=NOW)
    assert rate == pytest.approx(0.75)
    anomaly = session.scalars(
        select(Anomaly).where(Anomaly.kind == "extraction_failure_spike")
    ).one()
    assert anomaly.severity == "warn"
    assert anomaly.detail_json["failed"] == 6
    assert anomaly.detail_json["sample"] == 8

    # A healthy window afterwards resolves it rather than leaving a stale warning.
    session.query(DocumentExtraction).delete()
    session.flush()
    seed_extractions(session, ["succeeded"] * 10)
    evaluate_extraction_health(session, now=NOW + timedelta(hours=1))
    session.flush()
    assert (
        session.scalars(select(Anomaly).where(Anomaly.kind == "extraction_failure_spike"))
        .one()
        .resolved_at
        is not None
    )


def test_scanned_documents_counted_as_empty_still_signal_a_spike(session: Session) -> None:
    seed_extractions(session, ["empty"] * 7 + ["succeeded"])
    evaluate_extraction_health(session, now=NOW)
    assert session.scalars(select(Anomaly).where(Anomaly.kind == "extraction_failure_spike")).one()
