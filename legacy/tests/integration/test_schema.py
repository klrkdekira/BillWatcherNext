from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import Bill, ChamberRecord, Document, DocumentVersion


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


def bill(now: datetime) -> Bill:
    return Bill(
        identifier_raw="D.R.15/2026",
        identifier_normalized="DR-15-2026",
        number=15,
        year=2026,
        originating_chamber="dewan_rakyat",
        slug="dr-15-2026",
        first_seen_at=now,
        last_seen_at=now,
        last_checked_at=now,
        last_changed_at=now,
    )


def test_schema_contains_release_one_contract() -> None:
    required = {
        "bills",
        "bill_slug_aliases",
        "chamber_records",
        "bill_events",
        "blobs",
        "source_snapshots",
        "fetch_attempts",
        "fetch_queue",
        "documents",
        "bill_documents",
        "document_versions",
        "document_extractions",
        "record_changes",
        "field_overrides",
        "presence_observations",
        "coverage_targets",
        "scrape_runs",
        "backfill_jobs",
        "anomalies",
        "search_units",
    }
    assert required <= set(Base.metadata.tables)


def test_one_bill_can_have_two_chamber_records(session: Session) -> None:
    now = datetime.now(UTC)
    record = bill(now)
    session.add(record)
    session.flush()
    base = dict(
        bill_id=record.id,
        status_raw="Dibentangkan",
        status_normalized="tabled",
        source_url="https://www.parlimen.gov.my/list",
        source_snapshot_id="snapshot",
        first_seen_at=now,
        last_seen_at=now,
        last_checked_at=now,
        last_changed_at=now,
    )
    # Disable FK enforcement in SQLite fixture; uniqueness is the invariant under test.
    session.add_all(
        [
            ChamberRecord(chamber="dewan_rakyat", **base),
            ChamberRecord(chamber="dewan_negara", **base),
        ]
    )
    session.commit()
    assert session.query(ChamberRecord).count() == 2


def test_only_one_current_version_per_document(session: Session) -> None:
    now = datetime.now(UTC)
    document = Document(
        document_kind="bill_as_introduced",
        language="ms",
        canonical_source_url="https://www.parlimen.gov.my/doc.pdf",
        source_url_raw="https://www.parlimen.gov.my/doc.pdf",
        first_seen_at=now,
        last_seen_at=now,
        last_checked_at=now,
        last_changed_at=now,
    )
    session.add(document)
    session.flush()
    common = dict(
        document_id=document.id,
        blob_sha256="a" * 64,
        byte_size=10,
        http_status=200,
        final_url=document.canonical_source_url,
        retrieved_at=now,
        last_verified_at=now,
        run_id="run",
        fetch_attempt_id="attempt",
        change_kind="initial",
        validation_status="accepted",
        is_current=True,
    )
    session.add(DocumentVersion(version_no=1, content_sha256="a" * 64, **common))
    session.add(DocumentVersion(version_no=2, content_sha256="b" * 64, **common))
    with pytest.raises(IntegrityError):
        session.commit()
