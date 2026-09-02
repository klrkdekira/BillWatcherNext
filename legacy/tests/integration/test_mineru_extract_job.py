import json
from collections.abc import Sequence
from datetime import UTC, datetime

from mineru_vl_utils.structs import ContentBlock
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.jobs.mineru_extract import run_mineru_extract
from billwatcher.models import BackfillJob, Bill, BillDocument, Blob, Document, DocumentVersion
from billwatcher.storage.audit_tree import AuditTree
from billwatcher.storage.blobs import FilesystemBlobStore
from tests.support.pdfs import sample_act

NOW = datetime(2026, 8, 21, tzinfo=UTC)


class FakeExtractor:
    model_name = "fake-mineru-model"

    def extract_pages(self, images: Sequence[Image.Image]) -> list[list[ContentBlock]]:
        return [
            [ContentBlock(type="text", bbox=[0.1, 0.1, 0.9, 0.2], content=f"page {index}")]
            for index in range(1, len(images) + 1)
        ]


def seed(
    session: Session, blob_store: FilesystemBlobStore, *, bills: list[Bill]
) -> DocumentVersion:
    for bill in bills:
        session.add(bill)
    session.flush()
    document = Document(
        document_kind="bill_as_introduced",
        language="unknown",
        canonical_source_url="https://www.parlimen.gov.my/DR152026.pdf",
        source_url_raw="https://www.parlimen.gov.my/DR152026.pdf",
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )
    session.add(document)
    session.flush()
    for bill in bills:
        session.add(
            BillDocument(
                bill_id=bill.id,
                document_id=document.id,
                chamber="dewan_rakyat",
                role="bill_text",
                first_seen_at=NOW,
                last_seen_at=NOW,
                source_url="https://www.parlimen.gov.my/bills-dewan-rakyat.html",
            )
        )
    content = sample_act()
    stored = blob_store.put(content, compress=False)
    session.add(
        Blob(
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            media_type="application/pdf",
            storage_path=stored.location,
            compression=stored.compression,
            ref_count=1,
        )
    )
    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        content_sha256=stored.sha256,
        blob_sha256=stored.sha256,
        byte_size=stored.byte_size,
        media_type_declared="application/pdf",
        media_type_detected="application/pdf",
        http_status=200,
        final_url=document.canonical_source_url,
        retrieved_at=NOW,
        last_verified_at=NOW,
        run_id="run-1",
        fetch_attempt_id="attempt-1",
        is_current=True,
        change_kind="initial",
        validation_status="accepted",
    )
    session.add(version)
    session.flush()
    return version


def bill(slug: str, identifier: str) -> Bill:
    return Bill(
        identifier_raw=identifier,
        identifier_normalized=identifier.replace(".", "").replace("/", "-"),
        slug=slug,
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )


def test_dry_run_reports_eligibility_and_writes_nothing(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    blob_store = FilesystemBlobStore(tmp_path / "blobs")
    tree = AuditTree(tmp_path / "audit")
    with Session(engine) as session:
        version = seed(session, blob_store, bills=[bill("dr-15-2026", "D.R.15/2026")])

        job = run_mineru_extract(
            session,
            blob_store=blob_store,
            audit_tree=tree,
            extractor=FakeExtractor(),
            render_dpi=72,
            mineru_base_url="http://mineru.loqasi.io",
            dry_run=True,
        )

        assert job.counts["eligible"] == 1
        assert job.counts["processed"] == 0
        # A manifest still lands (every step run leaves one, HANDOFF 27.1), but no markdown or
        # sidecar is written for the document itself in a dry run.
        directory = tree.extraction_dir(
            bill_slug="dr-15-2026",
            document_id=version.document_id,
            version_no=1,
            extractor_name="mineru",
            extractor_version="1.0.0",
        )
        assert not directory.exists()
        manifest_path = tmp_path / "audit" / "manifests" / "mineru-extract" / f"{job.id}.json"
        assert manifest_path.exists()


def test_apply_writes_markdown_and_sidecar_for_every_linked_bill(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    blob_store = FilesystemBlobStore(tmp_path / "blobs")
    tree = AuditTree(tmp_path / "audit")
    with Session(engine) as session:
        version = seed(
            session,
            blob_store,
            bills=[bill("dr-15-2026", "D.R.15/2026"), bill("dn-3-2026", "D.N.3/2026")],
        )

        job = run_mineru_extract(
            session,
            blob_store=blob_store,
            audit_tree=tree,
            extractor=FakeExtractor(),
            render_dpi=72,
            mineru_base_url="http://mineru.loqasi.io",
            dry_run=False,
        )
        session.commit()

        assert job.counts == {"eligible": 1, "processed": 1, "empty": 0, "failed": 0}

        for slug in ("dr-15-2026", "dn-3-2026"):
            directory = tree.extraction_dir(
                bill_slug=slug,
                document_id=version.document_id,
                version_no=1,
                extractor_name="mineru",
                extractor_version="1.0.0",
            )
            markdown = (directory / "document.md").read_text()
            assert "page 1" in markdown
            assert "page 3" in markdown
            sidecar = json.loads((directory / "metadata.json").read_text())
            assert sidecar["extractor_name"] == "mineru"
            assert sidecar["status"] == "succeeded"
            assert sidecar["model_name"] == "fake-mineru-model"
            assert sidecar["mineru_base_url"] == "http://mineru.loqasi.io"
            assert sidecar["render_dpi"] == 72
            assert sidecar["page_count"] == 3
            assert sidecar["raw_file"] == "document.md"
            assert sidecar["database"]["document_version_id"] == version.id

        manifest_path = tmp_path / "audit" / "manifests" / "mineru-extract" / f"{job.id}.json"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["processed"] == 1
        assert manifest["dry_run"] is False


def test_a_document_already_extracted_is_not_reprocessed(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    blob_store = FilesystemBlobStore(tmp_path / "blobs")
    tree = AuditTree(tmp_path / "audit")
    with Session(engine) as session:
        seed(session, blob_store, bills=[bill("dr-15-2026", "D.R.15/2026")])

        first = run_mineru_extract(
            session,
            blob_store=blob_store,
            audit_tree=tree,
            extractor=FakeExtractor(),
            render_dpi=72,
            mineru_base_url="http://mineru.loqasi.io",
            dry_run=False,
        )
        session.commit()
        assert first.counts["processed"] == 1

        second = run_mineru_extract(
            session,
            blob_store=blob_store,
            audit_tree=tree,
            extractor=FakeExtractor(),
            render_dpi=72,
            mineru_base_url="http://mineru.loqasi.io",
            dry_run=False,
        )
        session.commit()
        assert second.counts["eligible"] == 0
        assert second.counts["processed"] == 0


def test_a_document_with_no_bill_link_is_skipped(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    blob_store = FilesystemBlobStore(tmp_path / "blobs")
    tree = AuditTree(tmp_path / "audit")
    with Session(engine) as session:
        seed(session, blob_store, bills=[])

        job = run_mineru_extract(
            session,
            blob_store=blob_store,
            audit_tree=tree,
            extractor=FakeExtractor(),
            render_dpi=72,
            mineru_base_url="http://mineru.loqasi.io",
            dry_run=False,
        )
        session.commit()

        assert job.counts["eligible"] == 0
        assert session.scalar(select(BackfillJob)).kind == "mineru_extract"
