import io
import json
from datetime import UTC, datetime

import httpx
from pypdf import PdfWriter
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.jobs.audit_rebuild import rebuild_documents, verify_documents
from billwatcher.models import Bill, BillDocument, Document, DocumentVersion, FetchQueueItem
from billwatcher.scraper.document_worker import process_one_document
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.policy import CrawlPolicy
from billwatcher.storage.audit_tree import AuditTree
from billwatcher.storage.blobs import FilesystemBlobStore

NOW = datetime(2026, 8, 21, tzinfo=UTC)
URL = "https://www.parlimen.gov.my/DR152026.pdf"
POLICY = CrawlPolicy("BillWatcherNext/0.1 (+https://example.org/about)")


def pdf(title: str) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": title})
    writer.write(output)
    return output.getvalue()


def seed(session: Session) -> tuple[Document, FetchQueueItem]:
    bill = Bill(
        identifier_raw="D.R.15/2026",
        identifier_normalized="DR-15-2026",
        slug="dr-15-2026",
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
        canonical_source_url=URL,
        source_url_raw=URL,
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


def test_second_version_gets_its_own_directory_and_the_first_survives(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    blob_store = FilesystemBlobStore(tmp_path / "blobs")
    tree = AuditTree(tmp_path / "audit")
    with Session(engine) as session:
        document, item = seed(session)

        with fetcher(pdf("first")) as first_fetcher:
            process_one_document(
                session,
                fetcher=first_fetcher,
                blob_store=blob_store,
                run_id="run-one",
                owner="worker",
                now=NOW,
                audit_tree=tree,
            )
        session.flush()

        v1_dir = tree.document_dir(bill_slug="dr-15-2026", document_id=document.id, version_no=1)
        assert (v1_dir / "document.pdf").read_bytes() == pdf("first")
        sidecar_v1 = json.loads((v1_dir / "metadata.json").read_text())
        assert sidecar_v1["bill"]["slug"] == "dr-15-2026"
        assert sidecar_v1["version_no"] == 1
        assert sidecar_v1["is_current"] is True
        assert sidecar_v1["validation_status"] == "accepted"
        assert sidecar_v1["chambers"] == ["dewan_rakyat"]
        assert sidecar_v1["source"]["url"] == URL
        assert sidecar_v1["source"]["upstream_filename"] == "DR152026.pdf"

        item.state = "pending"
        with fetcher(pdf("second")) as second_fetcher:
            process_one_document(
                session,
                fetcher=second_fetcher,
                blob_store=blob_store,
                run_id="run-two",
                owner="worker",
                now=NOW,
                audit_tree=tree,
            )
        session.flush()

        v2_dir = tree.document_dir(bill_slug="dr-15-2026", document_id=document.id, version_no=2)
        assert (v2_dir / "document.pdf").read_bytes() == pdf("second")
        # The superseded version's own artifact is untouched by the live write path — the
        # first PDF's bytes are exactly as retrieved, but its cached `is_current` flag is now
        # stale until a rebuild refreshes it (HANDOFF 27.4).
        assert (v1_dir / "document.pdf").read_bytes() == pdf("first")
        stale_sidecar_v1 = json.loads((v1_dir / "metadata.json").read_text())
        assert stale_sidecar_v1["is_current"] is True

        issues = verify_documents(session, audit_tree=tree, blob_store=blob_store)
        assert any("v001" in issue for issue in issues)

        report = rebuild_documents(session, blob_store=blob_store, audit_tree=tree)
        assert report["versions_considered"] == 2

        fresh_sidecar_v1 = json.loads((v1_dir / "metadata.json").read_text())
        assert fresh_sidecar_v1["is_current"] is False
        assert verify_documents(session, audit_tree=tree, blob_store=blob_store) == []


def test_verify_catches_a_tampered_byte(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    blob_store = FilesystemBlobStore(tmp_path / "blobs")
    tree = AuditTree(tmp_path / "audit")
    with Session(engine) as session:
        document, _item = seed(session)
        with fetcher(pdf("first")) as first_fetcher:
            process_one_document(
                session,
                fetcher=first_fetcher,
                blob_store=blob_store,
                run_id="run-one",
                owner="worker",
                now=NOW,
                audit_tree=tree,
            )
        session.flush()
        assert verify_documents(session, audit_tree=tree, blob_store=blob_store) == []

        directory = tree.document_dir(bill_slug="dr-15-2026", document_id=document.id, version_no=1)
        (directory / "document.pdf").write_bytes(b"tampered")

        issues = verify_documents(session, audit_tree=tree, blob_store=blob_store)
        assert any("document.pdf" in issue for issue in issues)


def test_quarantined_download_is_still_written_to_the_tree(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    blob_store = FilesystemBlobStore(tmp_path / "blobs")
    tree = AuditTree(tmp_path / "audit")
    with Session(engine) as session:
        document, _item = seed(session)
        with fetcher(b"<html>not a pdf</html>") as bad_fetcher:
            process_one_document(
                session,
                fetcher=bad_fetcher,
                blob_store=blob_store,
                run_id="run-one",
                owner="worker",
                now=NOW,
                audit_tree=tree,
            )
        session.flush()
        version = session.scalar(select(DocumentVersion))
        assert version.validation_status == "quarantined"
        directory = tree.document_dir(bill_slug="dr-15-2026", document_id=document.id, version_no=1)
        assert (directory / "document.pdf").exists()
        sidecar = json.loads((directory / "metadata.json").read_text())
        assert sidecar["validation_status"] == "quarantined"
        assert sidecar["is_current"] is False
