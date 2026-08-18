from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import (
    Bill,
    BillDocument,
    Document,
    DocumentVersion,
    SearchUnit,
)
from billwatcher.search.indexer import MAX_UNIT_CHARS, index_document_extraction
from billwatcher.search.lexical import search_bills

NOW = datetime(2026, 8, 17, tzinfo=UTC)


def seed(session: Session) -> tuple[Bill, Document, DocumentVersion]:
    bill = Bill(
        identifier_raw="D.R.5/2026",
        identifier_normalized="DR-5-2026",
        number=5,
        year=2026,
        originating_chamber="dewan_rakyat",
        slug="dr-5-2026",
        title_bm="Rang Undang-Undang Besar",
        identifier_scheme_version=1,
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )
    document = Document(
        document_kind="bill_as_introduced",
        language="ms",
        canonical_source_url="https://www.parlimen.gov.my/large.pdf",
        source_url_raw="https://www.parlimen.gov.my/large.pdf",
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )
    session.add_all([bill, document])
    session.flush()
    session.add(
        BillDocument(
            bill_id=bill.id,
            document_id=document.id,
            role="listing_document",
            first_seen_at=NOW,
            last_seen_at=NOW,
            source_url="https://www.parlimen.gov.my/list",
        )
    )
    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        content_sha256="a" * 64,
        blob_sha256="a" * 64,
        byte_size=10,
        http_status=200,
        final_url=document.canonical_source_url,
        retrieved_at=NOW,
        last_verified_at=NOW,
        run_id="run",
        fetch_attempt_id="attempt",
        is_current=True,
        change_kind="initial",
        validation_status="accepted",
    )
    session.add(version)
    session.flush()
    document.current_version_id = version.id
    return bill, document, version


def test_document_pages_search_and_scale_guard() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bill, _document, version = seed(session)
        huge_page = "peruntukan " + " ".join("xylem" for _ in range(220_000))
        assert len(huge_page) > 1_000_000
        written = index_document_extraction(
            session,
            document_version_id=version.id,
            pages=("frasa undang undang unik", huge_page),
        )
        session.flush()
        units = session.scalars(
            select(SearchUnit)
            .where(SearchUnit.unit_kind == "document_text")
            .order_by(SearchUnit.page_from, SearchUnit.part)
        ).all()
        assert len(units) == written > 2
        assert units[0].page_from == units[0].page_to == 1
        assert units[0].part == 1
        # Every long page is split into units that stay inside the tsvector size limit.
        long_page_units = [unit for unit in units if unit.page_from == 2]
        assert len(long_page_units) > 1
        assert [unit.part for unit in long_page_units] == list(range(1, len(long_page_units) + 1))
        assert max(len(unit.content) for unit in units) <= MAX_UNIT_CHARS
        assert sum(len(unit.content) for unit in long_page_units) >= len(huge_page) - len(
            long_page_units
        )
        result = search_bills(session, query="frasa undang undang unik")
        assert result.items == (bill,)
        assert result.hits[0].passage is not None
        assert "<mark>" in result.hits[0].passage.html


def test_new_version_demotes_superseded_text_by_default() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bill, document, first = seed(session)
        index_document_extraction(
            session, document_version_id=first.id, pages=("teks lama sahaja",)
        )
        first.is_current = False
        second = DocumentVersion(
            document_id=document.id,
            version_no=2,
            content_sha256="b" * 64,
            blob_sha256="b" * 64,
            byte_size=11,
            http_status=200,
            final_url=document.canonical_source_url,
            retrieved_at=NOW,
            last_verified_at=NOW,
            run_id="run",
            fetch_attempt_id="attempt-two",
            supersedes_version_id=first.id,
            is_current=True,
            change_kind="content_changed",
            validation_status="accepted",
        )
        session.add(second)
        session.flush()
        document.current_version_id = second.id
        index_document_extraction(session, document_version_id=second.id, pages=("teks baharu",))
        session.flush()
        assert search_bills(session, query="lama sahaja").total == 0
        assert search_bills(session, query="teks baharu").items == (bill,)
        old_unit = session.scalar(
            select(SearchUnit).where(SearchUnit.document_version_id == first.id)
        )
        assert old_unit is not None and not old_unit.is_current
