"""PostgreSQL-only proof of the HANDOFF 12.1 search contract.

These run only against a disposable database (see tests/conftest.py) because the weighted
tsvector, websearch_to_tsquery ranking, and ts_headline snippets have no SQLite equivalent.
"""

import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from billwatcher.models import (
    Bill,
    BillDocument,
    BillEvent,
    Blob,
    Document,
    DocumentVersion,
    FetchAttempt,
    ScrapeRun,
    SearchUnit,
    SourceSnapshot,
)
from billwatcher.scraper.ingest import ingest_listing
from billwatcher.scraper.parse_listing import parse_listing
from billwatcher.search.indexer import (
    MAX_UNIT_CHARS,
    index_document_extraction,
    rebuild_bill_metadata_unit,
)
from billwatcher.search.lexical import search_bills

FIXTURES = Path("tests/fixtures/parliament")
NOW = datetime(2026, 8, 17, tzinfo=UTC)
URL = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr"


@pytest.fixture
def session(postgres_engine: Engine) -> Iterator[Session]:
    with Session(postgres_engine) as database:
        database.execute(
            text(
                "TRUNCATE TABLE search_units, bill_events, bill_documents, document_extractions,"
                " document_versions, documents, chamber_records, record_changes,"
                " presence_observations, anomalies, fetch_attempts, source_snapshots,"
                " scrape_runs, blobs, bills CASCADE"
            )
        )
        database.commit()
        yield database
        database.rollback()


def provenance(session: Session) -> tuple[str, str, str]:
    """Create the run, snapshot, and attempt rows every domain row must be attributable to."""
    run = ScrapeRun(mode="fixture", trigger="manual", started_at=NOW, state="running")
    session.add(run)
    session.flush()
    snapshot = SourceSnapshot(
        run_id=run.id,
        url=URL,
        final_url=URL,
        requested_at=NOW,
        status_code=200,
        parser_version="1.0.0",
        parse_status="succeeded",
    )
    attempt = FetchAttempt(
        run_id=run.id,
        target_kind="listing",
        url=URL,
        method="GET",
        attempted_at=NOW,
        duration_ms=1,
        status_code=200,
    )
    session.add_all([snapshot, attempt])
    session.flush()
    return run.id, snapshot.id, attempt.id


def seed(session: Session) -> tuple[str, str, str]:
    run_id, snapshot_id, attempt_id = provenance(session)
    for name, chamber in (
        ("current_dr_bm.html", "dewan_rakyat"),
        ("archive_dn_bm.html", "dewan_negara"),
    ):
        ingest_listing(
            session,
            parse_listing((FIXTURES / name).read_text(), source_url=URL),
            chamber=chamber,
            language="ms",
            source_url=URL,
            snapshot_id=snapshot_id,
            run_id=run_id,
            checked_at=NOW,
        )
    session.flush()
    return run_id, snapshot_id, attempt_id


def test_weighted_vector_is_generated_and_indexed(session: Session) -> None:
    seed(session)
    session.flush()
    row = session.execute(
        text(
            "SELECT tsv::text FROM search_units WHERE unit_kind = 'bill_metadata' "
            "ORDER BY content LIMIT 1"
        )
    ).scalar_one()
    # Identifier lexemes carry weight A and the descriptive text carries weight B.
    assert re.search(r":\d+A", row), row
    assert re.search(r":\d+B", row), row
    indexes = session.execute(
        text("SELECT indexname FROM pg_indexes WHERE tablename = 'search_units'")
    ).scalars()
    assert "ix_search_units_tsv" in set(indexes)


@pytest.mark.parametrize(
    "query",
    ["D.R. 15/2026", "D.R.15/2026", "DR-15-2026", "dr 15/2026"],
)
def test_exact_identifier_wins_whatever_the_spacing(session: Session, query: str) -> None:
    seed(session)
    session.flush()
    results = search_bills(session, query=query)
    assert results.total >= 1
    assert results.items[0].identifier_normalized == "DR-15-2026"


def test_identifier_prefix_ranks_above_plain_text(session: Session) -> None:
    seed(session)
    session.flush()
    results = search_bills(session, query="D.R.15")
    assert results.items[0].identifier_normalized == "DR-15-2026"


def test_malay_phrase_and_presenter_match_with_escaped_snippets(session: Session) -> None:
    seed(session)
    session.flush()
    malay = search_bills(session, query="Perlindungan Saksi")
    assert malay.total == 1
    passage = malay.hits[0].passage
    assert passage is not None
    assert "<mark>" in passage.html
    assert "\x01" not in passage.html

    presenter = search_bills(session, query="Menteri")
    assert presenter.total >= 1


def test_headline_output_is_escaped_before_markup(session: Session) -> None:
    seed(session)
    bill = session.scalars(select(Bill)).first()
    assert bill is not None
    bill.title_bm = "Dasar & Perlindungan <script>alert(1)</script> Saksi"
    rebuild_bill_metadata_unit(session, bill)
    session.flush()
    results = search_bills(session, query="Perlindungan")
    passage = results.hits[0].passage
    assert passage is not None
    # Only <mark> may reach the page; everything the database returned is escaped first.
    assert "<script>" not in passage.html
    assert "alert(1)" in passage.html
    assert "&amp;" in passage.html
    assert set(re.findall(r"<[^>]+>", passage.html)) <= {"<mark>", "</mark>"}


def test_document_text_is_searchable_and_superseded_text_is_opt_in(session: Session) -> None:
    run_id, _snapshot_id, attempt_id = seed(session)
    bill = session.scalars(select(Bill)).first()
    assert bill is not None
    first = _document_version(
        session, bill, version_no=1, digest="a", run_id=run_id, attempt_id=attempt_id
    )
    index_document_extraction(
        session, document_version_id=first.id, pages=("peruntukan khas bagi saksi terlindung",)
    )
    session.flush()
    assert search_bills(session, query="saksi terlindung").total == 1

    first.is_current = False
    second = _document_version(
        session,
        bill,
        version_no=2,
        digest="b",
        run_id=run_id,
        attempt_id=attempt_id,
        document=first.document_id,
    )
    index_document_extraction(session, document_version_id=second.id, pages=("teks baharu",))
    session.flush()
    assert search_bills(session, query="saksi terlindung").total == 0
    assert search_bills(session, query="saksi terlindung", include_superseded=True).total == 1
    assert search_bills(session, query="teks baharu").total == 1


def test_multi_megabyte_page_indexes_without_error(session: Session) -> None:
    run_id, _snapshot_id, attempt_id = seed(session)
    bill = session.scalars(select(Bill)).first()
    assert bill is not None
    version = _document_version(
        session, bill, version_no=1, digest="c", run_id=run_id, attempt_id=attempt_id
    )
    huge = "peruntukan " + " ".join(f"perkataan{index % 997}" for index in range(120_000))
    assert len(huge) > 1_000_000
    index_document_extraction(session, document_version_id=version.id, pages=(huge,))
    session.flush()
    units = session.scalars(select(SearchUnit).where(SearchUnit.unit_kind == "document_text")).all()
    assert len(units) > 1
    assert max(len(unit.content) for unit in units) <= MAX_UNIT_CHARS
    assert search_bills(session, query="perkataan42").total == 1


def test_filters_pagination_and_deep_offset_guard(session: Session) -> None:
    seed(session)
    session.flush()
    assert search_bills(session, query="", chamber="dewan_negara").total >= 1
    assert search_bills(session, query="", year=1999).total == 0
    first = search_bills(session, query="", page=1, page_size=1)
    assert len(first.items) == 1
    assert first.next_cursor
    second = search_bills(session, query="", page=2, page_size=1, cursor=first.next_cursor)
    assert second.items and second.items[0].id != first.items[0].id
    with pytest.raises(ValueError, match="add filters"):
        search_bills(session, query="saksi", page=200, page_size=20)


def test_newest_event_breaks_full_text_ties(session: Session) -> None:
    run_id, snapshot_id, _attempt_id = seed(session)
    bills = session.scalars(select(Bill).order_by(Bill.identifier_normalized)).all()
    assert len(bills) >= 2
    for bill in bills:
        bill.title_bm = "Rang Undang Undang Serupa"
    for bill in bills:
        rebuild_bill_metadata_unit(session, bill)
    session.add(
        BillEvent(
            bill_id=bills[-1].id,
            chamber="dewan_rakyat",
            event_type="second_reading",
            event_on=date(2026, 12, 31),
            sequence=0,
            source_label="Bacaan Kali Kedua",
            source_value="31/12/2026",
            source_url=URL,
            snapshot_id=snapshot_id,
            run_id=run_id,
            parser_version="1.0.0",
            observed_at=NOW,
            fingerprint="tie-break-event",
        )
    )
    session.flush()
    results = search_bills(session, query="Serupa")
    assert results.items[0].id == bills[-1].id


def _document_version(
    session: Session,
    bill: Bill,
    *,
    version_no: int,
    digest: str,
    run_id: str,
    attempt_id: str,
    document: str | None = None,
) -> DocumentVersion:
    if document is None:
        record = Document(
            document_kind="bill_as_introduced",
            language="ms",
            canonical_source_url=f"https://www.parlimen.gov.my/{bill.slug}-{digest}.pdf",
            source_url_raw=f"https://www.parlimen.gov.my/{bill.slug}-{digest}.pdf",
            first_seen_at=NOW,
            last_seen_at=NOW,
            last_checked_at=NOW,
            last_changed_at=NOW,
        )
        session.add(record)
        session.flush()
        session.add(
            BillDocument(
                bill_id=bill.id,
                document_id=record.id,
                chamber="dewan_rakyat",
                role="primary",
                first_seen_at=NOW,
                last_seen_at=NOW,
                source_url=URL,
            )
        )
        document = record.id
    sha = (digest * 64)[:64]
    if session.get(Blob, sha) is None:
        session.add(
            Blob(
                sha256=sha,
                byte_size=10,
                media_type="application/pdf",
                storage_path=f"var/blobs/{sha}",
                compression="none",
                ref_count=1,
            )
        )
        session.flush()
    version = DocumentVersion(
        document_id=document,
        version_no=version_no,
        content_sha256=sha,
        blob_sha256=sha,
        byte_size=10,
        http_status=200,
        final_url="https://www.parlimen.gov.my/doc.pdf",
        retrieved_at=NOW,
        last_verified_at=NOW,
        run_id=run_id,
        fetch_attempt_id=attempt_id,
        is_current=True,
        change_kind="initial" if version_no == 1 else "content_changed",
        validation_status="accepted",
    )
    session.add(version)
    session.flush()
    return version
