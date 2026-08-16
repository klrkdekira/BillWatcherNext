from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import Anomaly, Blob, Document, DocumentVersion
from billwatcher.scraper.service import persist_document_observation
from billwatcher.scraper.versioning import DownloadObservation, VersionAction
from billwatcher.storage.blobs import BlobStore

PDF_A = b"%PDF-1.7\nA"
PDF_B = b"%PDF-1.7\nB"
NOW = datetime(2026, 8, 17, tzinfo=UTC)


def document() -> Document:
    return Document(
        document_kind="bill_as_introduced",
        language="ms",
        canonical_source_url="https://www.parlimen.gov.my/a.pdf",
        source_url_raw="https://www.parlimen.gov.my/a.pdf",
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )


def persist(
    session: Session,
    item: Document,
    store: BlobStore,
    body: bytes | None,
    when: datetime,
    status: int = 200,
    media_type: str = "application/pdf",
):
    return persist_document_observation(
        session,
        document=item,
        observation=DownloadObservation(status, when, body, media_type),
        blob_store=store,
        run_id="run",
        fetch_attempt_id="attempt",
        final_url=item.canonical_source_url,
    )


def test_changed_identical_rollback_and_quarantine_are_preserved(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    store = BlobStore(tmp_path)
    with Session(engine) as session:
        item = document()
        session.add(item)
        session.flush()

        assert persist(session, item, store, PDF_A, NOW).action == VersionAction.CREATED
        session.flush()
        first_id = item.current_version_id

        assert (
            persist(session, item, store, PDF_A, NOW + timedelta(hours=1)).action
            == VersionAction.VERIFIED
        )
        assert len(session.scalars(select(DocumentVersion)).all()) == 1

        assert (
            persist(session, item, store, PDF_B, NOW + timedelta(hours=2)).action
            == VersionAction.CREATED
        )
        session.flush()
        assert item.current_version_id != first_id

        assert (
            persist(session, item, store, PDF_A, NOW + timedelta(hours=3)).action
            == VersionAction.ROLLBACK
        )
        session.flush()
        versions = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.version_no)
        ).all()
        assert [version.version_no for version in versions] == [1, 2, 3]
        assert versions[0].blob_sha256 == versions[2].blob_sha256
        assert [version.is_current for version in versions] == [False, False, True]
        assert (
            session.scalar(select(Anomaly.kind).where(Anomaly.kind == "document_rollback"))
            == "document_rollback"
        )

        current_id = item.current_version_id
        bad = b"<html>session expired</html>"
        assert (
            persist(
                session, item, store, bad, NOW + timedelta(hours=4), media_type="text/html"
            ).action
            == VersionAction.QUARANTINED
        )
        session.flush()
        assert item.current_version_id == current_id
        quarantined = session.scalars(
            select(DocumentVersion).where(DocumentVersion.validation_status == "quarantined")
        ).one()
        assert not quarantined.is_current
        assert (
            session.scalar(select(Anomaly.kind).where(Anomaly.kind == "document_quarantined"))
            == "document_quarantined"
        )

        blobs = session.scalars(select(Blob)).all()
        assert len(blobs) == 3
        assert next(blob for blob in blobs if blob.sha256 == versions[0].blob_sha256).ref_count == 2


def test_304_only_advances_check_and_verification_times(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        item = document()
        session.add(item)
        session.flush()
        store = BlobStore(tmp_path)
        persist(session, item, store, PDF_A, NOW)
        session.flush()
        changed_at = item.last_changed_at
        checked = NOW + timedelta(days=1)
        decision = persist(session, item, store, None, checked, status=304)
        current = session.get(DocumentVersion, item.current_version_id)
        assert decision.action == VersionAction.NOT_MODIFIED
        assert item.last_checked_at == checked
        assert item.last_changed_at == changed_at
        assert current is not None and current.last_verified_at == checked
