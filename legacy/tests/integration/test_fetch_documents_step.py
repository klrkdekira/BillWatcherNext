import io
import json
from datetime import UTC, datetime

import httpx
from pypdf import PdfWriter
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.jobs.audit_rebuild import check_audit_tree
from billwatcher.models import Anomaly, Bill, BillDocument, Document, FetchQueueItem
from billwatcher.scraper.document_worker import run_fetch_documents_step
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.policy import CrawlPolicy
from billwatcher.storage.audit_tree import AuditTree
from billwatcher.storage.blobs import FilesystemBlobStore

NOW = datetime(2026, 8, 21, tzinfo=UTC)
POLICY = CrawlPolicy("BillWatcherNext/0.1 (+https://example.org/about)")


def pdf(title: str) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": title})
    writer.write(output)
    return output.getvalue()


def seed_queued_document(session: Session, *, slug: str, url: str) -> Document:
    bill = Bill(
        identifier_raw=f"D.R.{slug}/2026",
        identifier_normalized=slug.upper(),
        slug=slug,
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )
    session.add(bill)
    session.flush()
    document = Document(
        document_kind="bill_as_introduced",
        language="unknown",
        canonical_source_url=url,
        source_url_raw=url,
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )
    session.add(document)
    session.flush()
    session.add(
        BillDocument(
            bill_id=bill.id,
            document_id=document.id,
            chamber="dewan_rakyat",
            role="bill_text",
            first_seen_at=NOW,
            last_seen_at=NOW,
            source_url="https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr",
        )
    )
    session.add(
        FetchQueueItem(
            target_kind="document",
            url=url,
            document_id=document.id,
            state="pending",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.flush()
    return document


def fetcher_serving(bodies: dict[str, bytes]) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        body = bodies[str(request.url)]
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "application/pdf", "ETag": f'"{len(body)}"'},
            request=request,
        )

    return Fetcher(POLICY, transport=httpx.MockTransport(handler), sleep=lambda _delay: None)


def test_fetch_documents_step_drains_the_queue_and_writes_one_manifest(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    blob_store = FilesystemBlobStore(tmp_path / "blobs")
    tree = AuditTree(tmp_path / "audit")
    urls = {
        "https://www.parlimen.gov.my/one.pdf": pdf("one"),
        "https://www.parlimen.gov.my/two.pdf": pdf("two"),
    }
    with Session(engine) as session:
        seed_queued_document(session, slug="dr-1-2026", url="https://www.parlimen.gov.my/one.pdf")
        seed_queued_document(session, slug="dr-2-2026", url="https://www.parlimen.gov.my/two.pdf")
        session.commit()

        with fetcher_serving(urls) as fetcher:
            manifest = run_fetch_documents_step(
                session, fetcher=fetcher, blob_store=blob_store, audit_tree=tree, limit=10
            )

        assert manifest["considered"] == 2
        assert manifest["queue_drained"] is True

        manifest_path = (
            tmp_path / "audit" / "manifests" / "fetch-documents" / f"{manifest['run_id']}.json"
        )
        assert manifest_path.exists()
        on_disk = json.loads(manifest_path.read_text())
        assert on_disk["considered"] == 2

        document_id = _document_id(session, "dr-1-2026")
        v1_dir = tree.document_dir(bill_slug="dr-1-2026", document_id=document_id, version_no=1)
        assert (v1_dir / "document.pdf").exists()

        issues = check_audit_tree(session, audit_tree=tree, blob_store=blob_store, now=NOW)
        assert issues == []
        divergence = session.scalar(select(Anomaly).where(Anomaly.kind == "audit_tree_divergence"))
        assert divergence is None


def _document_id(session: Session, slug: str) -> str:
    bill = session.scalar(select(Bill).where(Bill.slug == slug))
    link = session.scalar(select(BillDocument).where(BillDocument.bill_id == bill.id))
    return link.document_id


def test_check_audit_tree_raises_a_critical_anomaly_on_divergence(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    blob_store = FilesystemBlobStore(tmp_path / "blobs")
    tree = AuditTree(tmp_path / "audit")
    url = "https://www.parlimen.gov.my/one.pdf"
    with Session(engine) as session:
        document = seed_queued_document(session, slug="dr-1-2026", url=url)
        session.commit()
        with fetcher_serving({url: pdf("one")}) as fetcher:
            run_fetch_documents_step(
                session, fetcher=fetcher, blob_store=blob_store, audit_tree=tree, limit=10
            )

        directory = tree.document_dir(bill_slug="dr-1-2026", document_id=document.id, version_no=1)
        (directory / "document.pdf").write_bytes(b"tampered")

        issues = check_audit_tree(session, audit_tree=tree, blob_store=blob_store, now=NOW)
        assert issues
        session.flush()
        anomaly = session.scalar(select(Anomaly).where(Anomaly.kind == "audit_tree_divergence"))
        assert anomaly is not None
        assert anomaly.severity == "critical"
