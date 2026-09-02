from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import Bill, CoverageTarget
from billwatcher.operations import find_bill_number_gaps

NOW = datetime(2026, 8, 21, tzinfo=UTC)


def bill(*, identifier: str, number: int, year: int, chamber: str = "dewan_rakyat") -> Bill:
    return Bill(
        identifier_raw=identifier,
        identifier_normalized=identifier.replace(".", "").replace("/", "-"),
        number=number,
        year=year,
        originating_chamber=chamber,
        slug=identifier.lower().replace(".", "").replace("/", "-"),
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )


def closed_archive_year(chamber: str, year: int) -> CoverageTarget:
    return CoverageTarget(
        chamber=chamber,
        listing_kind="archive",
        language="ms",
        scope_key=str(year),
        expected_interval_hours=0,
        state="healthy",
    )


def open_archive_year(chamber: str, year: int) -> CoverageTarget:
    return CoverageTarget(
        chamber=chamber,
        listing_kind="archive",
        language="ms",
        scope_key=str(year),
        expected_interval_hours=720,
        state="healthy",
    )


def test_a_hole_in_a_closed_years_numbering_is_reported() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(closed_archive_year("dewan_rakyat", 2011))
        session.add_all(
            [
                bill(identifier="D.R.01/2011", number=1, year=2011),
                bill(identifier="D.R.02/2011", number=2, year=2011),
                # 3 is missing
                bill(identifier="D.R.04/2011", number=4, year=2011),
            ]
        )
        session.flush()

        gaps = find_bill_number_gaps(session)

        assert len(gaps) == 1
        assert gaps[0].chamber == "dewan_rakyat"
        assert gaps[0].year == 2011
        assert gaps[0].missing_numbers == [3]
        assert (gaps[0].lowest, gaps[0].highest) == (1, 4)


def test_a_sequential_closed_year_reports_no_gaps() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(closed_archive_year("dewan_rakyat", 2011))
        session.add_all(
            [
                bill(identifier="D.R.01/2011", number=1, year=2011),
                bill(identifier="D.R.02/2011", number=2, year=2011),
                bill(identifier="D.R.03/2011", number=3, year=2011),
            ]
        )
        session.flush()

        assert find_bill_number_gaps(session) == []


def test_a_hole_in_an_open_year_is_not_reported() -> None:
    """An open year is still growing; a gap there is a bill not yet fetched, not a defect."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(open_archive_year("dewan_rakyat", 2026))
        session.add_all(
            [
                bill(identifier="D.R.01/2026", number=1, year=2026),
                bill(identifier="D.R.15/2026", number=15, year=2026),
            ]
        )
        session.flush()

        assert find_bill_number_gaps(session) == []


def test_a_year_with_no_closed_coverage_target_at_all_is_skipped() -> None:
    """Fixture-only data, with no coverage target recorded, must not be flagged either."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                bill(identifier="D.R.01/2011", number=1, year=2011),
                bill(identifier="D.R.04/2011", number=4, year=2011),
            ]
        )
        session.flush()

        assert find_bill_number_gaps(session) == []


def test_chambers_are_isolated_from_one_another() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(closed_archive_year("dewan_rakyat", 2011))
        session.add(closed_archive_year("dewan_negara", 2011))
        session.add_all(
            [
                bill(identifier="D.R.01/2011", number=1, year=2011, chamber="dewan_rakyat"),
                bill(identifier="D.R.03/2011", number=3, year=2011, chamber="dewan_rakyat"),
                bill(identifier="D.N.01/2011", number=1, year=2011, chamber="dewan_negara"),
                bill(identifier="D.N.02/2011", number=2, year=2011, chamber="dewan_negara"),
            ]
        )
        session.flush()

        gaps = find_bill_number_gaps(session)

        assert len(gaps) == 1
        assert gaps[0].chamber == "dewan_rakyat"
        assert gaps[0].missing_numbers == [2]


def test_bills_with_unparsed_number_or_chamber_are_skipped_not_counted_as_gaps() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(closed_archive_year("dewan_rakyat", 2011))
        malformed = bill(identifier="D.R.40/2017 ARKIB", number=1, year=2011)
        malformed.number = None
        malformed.originating_chamber = None
        session.add(malformed)
        session.add_all(
            [
                bill(identifier="D.R.01/2011", number=1, year=2011),
                bill(identifier="D.R.02/2011", number=2, year=2011),
            ]
        )
        session.flush()

        assert find_bill_number_gaps(session) == []
