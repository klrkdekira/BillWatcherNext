"""Serving our archived copy of an official document (HANDOFF 9.5, ADR-004, ADR-013).

Publication is gated on the rights review in assumption A14, so the default is off and the
official link never depends on this route.
"""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from billwatcher.config import Settings
from billwatcher.db import Base
from billwatcher.models import (
    Bill,
    BillDocument,
    Blob,
    Document,
    DocumentVersion,
    FetchAttempt,
    ScrapeRun,
)
from billwatcher.storage.blobs import FilesystemBlobStore
from billwatcher.web.app import create_app

NOW = datetime(2026, 8, 17, tzinfo=UTC)
PDF = b"%PDF-1.7\nthe archived bill\n%%EOF"
DIGEST = hashlib.sha256(PDF).hexdigest()
OFFICIAL = "https://www.parlimen.gov.my/files/billindex/pdf/2026/DR/RUU.pdf"


def build(tmp_path, *, serving: bool, quarantined: bool = False) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = FilesystemBlobStore(tmp_path)
    stored = store.put(PDF)

    with factory() as session:
        run = ScrapeRun(mode="fixture", trigger="manual", started_at=NOW, state="succeeded")
        session.add(run)
        session.flush()
        attempt = FetchAttempt(
            run_id=run.id,
            target_kind="document",
            url=OFFICIAL,
            method="GET",
            attempted_at=NOW,
            duration_ms=1,
            status_code=200,
        )
        bill = Bill(
            identifier_raw="D.R.15/2026",
            identifier_normalized="DR-15-2026",
            slug="dr-15-2026",
            title_bm="RUU Perlindungan Saksi",
            first_seen_at=NOW,
            last_seen_at=NOW,
            last_checked_at=NOW,
            last_changed_at=NOW,
        )
        document = Document(
            document_kind="bill_as_introduced",
            language="ms",
            canonical_source_url=OFFICIAL,
            source_url_raw=OFFICIAL,
            first_seen_at=NOW,
            last_seen_at=NOW,
            last_checked_at=NOW,
            last_changed_at=NOW,
        )
        session.add_all(
            [
                attempt,
                bill,
                document,
                Blob(
                    sha256=stored.sha256,
                    byte_size=stored.byte_size,
                    media_type="application/pdf",
                    storage_path=stored.location,
                    compression=stored.compression,
                    ref_count=1,
                ),
            ]
        )
        session.flush()
        session.add(
            BillDocument(
                bill_id=bill.id,
                document_id=document.id,
                chamber="dewan_rakyat",
                role="listing_document",
                first_seen_at=NOW,
                last_seen_at=NOW,
                source_url=OFFICIAL,
            )
        )
        version = DocumentVersion(
            document_id=document.id,
            version_no=1,
            content_sha256=DIGEST,
            blob_sha256=stored.sha256,
            byte_size=len(PDF),
            media_type_detected="application/pdf",
            http_status=200,
            final_url=OFFICIAL,
            retrieved_at=NOW,
            last_verified_at=NOW,
            run_id=run.id,
            fetch_attempt_id=attempt.id,
            is_current=True,
            change_kind="initial",
            validation_status="quarantined" if quarantined else "accepted",
        )
        session.add(version)
        session.flush()
        document.current_version_id = version.id
        session.commit()
        document_id = document.id

    settings = Settings(blob_storage_root=tmp_path, serve_archived_documents=serving)
    with TestClient(create_app(factory, settings=settings)) as client:
        client.document_id = document_id  # type: ignore[attr-defined]
        yield client


@pytest.fixture
def serving(tmp_path) -> Iterator[TestClient]:
    yield from build(tmp_path, serving=True)


@pytest.fixture
def withheld(tmp_path) -> Iterator[TestClient]:
    yield from build(tmp_path, serving=False)


def test_the_rights_gate_is_closed_by_default(withheld: TestClient) -> None:
    """HANDOFF 2 makes publishing mirrored bytes a non-goal until A14 concludes."""
    response = withheld.get(f"/documents/{withheld.document_id}/versions/1")
    assert response.status_code == 404
    # The message renders through an autoescaped template, so the apostrophe is escaped.
    assert "official documents rather than serving its own copies" in response.text
    # The bill page offers no download, but still links the official source.
    page = withheld.get("/bills/dr-15-2026").text
    assert "Download our copy" not in page
    assert OFFICIAL in page


def test_an_enabled_archive_serves_the_exact_stored_bytes(serving: TestClient) -> None:
    response = serving.get(f"/documents/{serving.document_id}/versions/1")
    assert response.status_code == 200
    assert response.content == PDF
    assert hashlib.sha256(response.content).hexdigest() == DIGEST
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-length"] == str(len(PDF))
    assert response.headers["etag"] == f'"{DIGEST}"'
    assert "immutable" in response.headers["cache-control"]
    # Our copy is not the authority, and must not be indexed as though it were.
    assert response.headers["x-robots-tag"] == "noindex"
    assert OFFICIAL in response.headers["link"]


def test_the_bill_page_offers_the_copy_beside_the_official_link(serving: TestClient) -> None:
    page = serving.get("/bills/dr-15-2026").text
    assert f"/documents/{serving.document_id}/versions/1" in page
    assert OFFICIAL in page
    assert "Parliament's own copy is the authority" in page
    assert "Our copy of this document was retrieved on" in page


def test_the_archived_copy_is_cacheable_by_content_hash(serving: TestClient) -> None:
    first = serving.get(f"/documents/{serving.document_id}/versions/1")
    again = serving.get(
        f"/documents/{serving.document_id}/versions/1",
        headers={"If-None-Match": first.headers["etag"]},
    )
    assert again.status_code == 304
    assert not again.content


def test_a_quarantined_version_is_never_published(tmp_path) -> None:
    """Bytes that failed validation are kept for the record but must not be served."""
    for client in build(tmp_path, serving=True, quarantined=True):
        response = client.get(f"/documents/{client.document_id}/versions/1")
        assert response.status_code == 404
        assert "not found" in response.text.casefold()


def test_an_unknown_document_or_version_is_a_plain_404(serving: TestClient) -> None:
    assert serving.get(f"/documents/{serving.document_id}/versions/99").status_code == 404
    assert serving.get("/documents/not-a-document/versions/1").status_code == 404


def test_the_route_cannot_be_pointed_at_an_arbitrary_path(serving: TestClient) -> None:
    """HANDOFF 17: a blob is never addressed by anything supplied in the request."""
    for attack in ("../../../etc/passwd", "..%2f..%2fetc%2fpasswd", "%2e%2e%2f"):
        response = serving.get(f"/documents/{attack}/versions/1")
        assert response.status_code in {404, 400}
        assert b"root:" not in response.content
