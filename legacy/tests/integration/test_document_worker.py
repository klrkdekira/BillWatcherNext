import io
from datetime import UTC, datetime

import httpx
from pypdf import PdfWriter
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import (
    Document,
    DocumentExtraction,
    DocumentVersion,
    FetchQueueItem,
)
from billwatcher.scraper.document_worker import process_one_document
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.policy import CrawlPolicy
from billwatcher.storage.blobs import FilesystemBlobStore

NOW = datetime(2026, 8, 17, tzinfo=UTC)
URL = "https://www.parlimen.gov.my/a.pdf"
POLICY = CrawlPolicy("BillWatcherNext/0.1 (+https://example.org/about)")


def pdf(title: str) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": title})
    writer.write(output)
    return output.getvalue()


def seed(session: Session) -> tuple[Document, FetchQueueItem]:
    document = Document(
        document_kind="bill_as_introduced",
        language="ms",
        canonical_source_url=URL,
        source_url_raw=URL,
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )
    session.add(document)
    session.flush()
    item = FetchQueueItem(
        target_kind="document",
        url=URL,
        document_id=document.id,
        state="pending",
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(item)
    session.flush()
    return document, item


def fetcher(body: bytes, *, status: int = 200) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            content=body,
            headers={"Content-Type": "application/pdf", "ETag": f'"{len(body)}"'},
            request=request,
        )

    return Fetcher(POLICY, transport=httpx.MockTransport(handler), sleep=lambda _delay: None)


def test_worker_preserves_versions_and_extractions(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        document, item = seed(session)
        with fetcher(pdf("first")) as first_fetcher:
            assert process_one_document(
                session,
                fetcher=first_fetcher,
                blob_store=FilesystemBlobStore(tmp_path),
                run_id="run-one",
                owner="worker",
                now=NOW,
            )
        session.flush()
        assert item.state == "done"
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 1
        assert session.scalar(select(func.count()).select_from(DocumentExtraction)) == 1

        item.state = "pending"
        with fetcher(pdf("second")) as second_fetcher:
            process_one_document(
                session,
                fetcher=second_fetcher,
                blob_store=FilesystemBlobStore(tmp_path),
                run_id="run-two",
                owner="worker",
                now=NOW,
            )
        session.flush()
        versions = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.version_no)
        ).all()
        assert len(versions) == 2
        assert [version.is_current for version in versions] == [False, True]
        assert session.scalar(select(func.count()).select_from(DocumentExtraction)) == 2
        assert document.current_version_id == versions[1].id


def test_304_does_not_create_version(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _document, item = seed(session)
        with fetcher(pdf("first")) as initial:
            process_one_document(
                session,
                fetcher=initial,
                blob_store=FilesystemBlobStore(tmp_path),
                run_id="run-one",
                owner="worker",
                now=NOW,
            )
        session.flush()
        item.state = "pending"
        with fetcher(b"", status=304) as unchanged:
            process_one_document(
                session,
                fetcher=unchanged,
                blob_store=FilesystemBlobStore(tmp_path),
                run_id="run-two",
                owner="worker",
                now=NOW,
            )
        session.flush()
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 1
        assert item.state == "done"
