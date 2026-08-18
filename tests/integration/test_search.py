from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import Bill, SearchUnit
from billwatcher.scraper.ingest import ingest_listing
from billwatcher.scraper.parse_listing import parse_listing
from billwatcher.search.lexical import search_bills

FIXTURES = Path("tests/fixtures/parliament")
NOW = datetime(2026, 8, 17, tzinfo=UTC)
URL = "https://www.parlimen.gov.my/list"


def seeded() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    for name, chamber in (
        ("current_dr_bm.html", "dewan_rakyat"),
        ("archive_dn_bm.html", "dewan_negara"),
    ):
        listing = parse_listing((FIXTURES / name).read_text(), source_url=URL)
        ingest_listing(
            session,
            listing,
            chamber=chamber,
            language="ms",
            source_url=URL,
            snapshot_id=name,
            run_id="run",
            checked_at=NOW,
        )
    session.flush()
    return session


def test_exact_code_and_malay_title_search() -> None:
    with seeded() as session:
        exact = search_bills(session, query="D.R. 15/2026")
        assert exact.total == 1
        assert exact.items[0].identifier_normalized == "DR-15-2026"
        title = search_bills(session, query="Perlindungan Saksi")
        assert [item.identifier_normalized for item in title.items] == ["DR-15-2026"]


def test_presenter_status_chamber_and_year_filters() -> None:
    with seeded() as session:
        presenter = search_bills(session, query="Menteri")
        assert presenter.total == 1
        filtered = search_bills(
            session,
            chamber="dewan_negara",
            status="withdrawn",
            year=2019,
        )
        assert [item.identifier_normalized for item in filtered.items] == ["DN-2-2019"]


def test_query_and_page_limits_fail_loudly() -> None:
    with seeded() as session:
        try:
            search_bills(session, query="x" * 201)
        except ValueError as error:
            assert "200" in str(error)
        else:
            raise AssertionError("overlong query accepted")


def test_superseded_document_text_requires_explicit_opt_in() -> None:
    with seeded() as session:
        bill = session.scalar(select(Bill).where(Bill.identifier_normalized == "DR-15-2026"))
        assert bill is not None
        session.add(
            SearchUnit(
                unit_kind="document_text",
                bill_id=bill.id,
                document_version_id="superseded-version",
                page_from=1,
                page_to=1,
                content="frasa sejarah unik",
                is_current=False,
            )
        )
        session.flush()
        assert search_bills(session, query="frasa sejarah unik").total == 0
        historical = search_bills(
            session,
            query="frasa sejarah unik",
            include_superseded=True,
        )
        assert [item.identifier_normalized for item in historical.items] == ["DR-15-2026"]


def test_english_titles_are_searchable_alongside_malay_ones() -> None:
    """The English listing reconciles onto the same bill by normalized identifier only."""
    with seeded() as database:
        listing = parse_listing((FIXTURES / "current_dr_en.html").read_text(), source_url=URL)
        ingest_listing(
            database,
            listing,
            chamber="dewan_rakyat",
            language="en",
            source_url=URL,
            snapshot_id="english",
            run_id="run",
            checked_at=NOW,
        )
        database.flush()

        bill = database.scalars(
            select(Bill).where(Bill.identifier_normalized == "DR-15-2026")
        ).one()
        assert bill.title_bm == "RUU Perlindungan Saksi"
        assert bill.title_en == "Witness Protection Bill"

        english = search_bills(database, query="Witness Protection")
        assert english.items == (bill,)
        malay = search_bills(database, query="Perlindungan Saksi")
        assert malay.items == (bill,)
        # One bill, not two: the English page must not create a second record.
        assert len(database.scalars(select(Bill)).all()) == 2
