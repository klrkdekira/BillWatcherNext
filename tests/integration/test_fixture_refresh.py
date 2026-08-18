"""`make fixtures-refresh` regenerates fixtures from stored snapshots, offline (HANDOFF 16.3)."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.jobs.fixture_refresh import refresh_fixtures
from billwatcher.jobs.fixtures import FIXTURE_TARGETS, load_fixture_listings
from billwatcher.scraper.parse_archive import parse_stored_listing
from billwatcher.storage.blobs import FilesystemBlobStore
from tests.integration.test_archive_crawl import crawl, transport

FIXTURES = Path("tests/fixtures/parliament")


def database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_a_refresh_reproduces_the_committed_fixtures_from_stored_bytes(tmp_path) -> None:
    store = FilesystemBlobStore(tmp_path / "blobs")
    staging = tmp_path / "regenerated"
    with database() as session:
        crawl(session, tmp_path / "blobs", transport(), mode="full")
        session.flush()

        report = refresh_fixtures(session, blob_store=store, staging_dir=staging, record_limit=4)
        by_name = {item.fixture: item for item in report.refreshed}

        # Every archived year the crawl read is regenerated, and the current listings too.
        assert set(by_name) == {
            "current_dr_bm_dated.html",
            "current_dn_bm_dated.html",
            "current_dr_en.html",
            "archive_year_dr_2024.xml",
            "archive_year_dn_2011.xml",
        } - {item[0] for item in report.skipped}
        assert "archive_year_dr_2024.xml" in by_name

        archived = by_name["archive_year_dr_2024.xml"]
        assert archived.records_kept == 4
        assert archived.written_to.parent == staging
        # The crawl served exactly the committed fixture, so refreshing it changes nothing but
        # the provenance header.
        assert archived.changed is False

        # And the regenerated file is still a fixture the parser accepts, with the same records.
        regenerated = parse_stored_listing(
            archived.written_to.read_text(), url=archived.url, source_url=archived.url
        )
        committed = parse_stored_listing(
            (FIXTURES / archived.fixture).read_text(), url=archived.url, source_url=archived.url
        )
        assert [record.identifier.normalized for record in regenerated.records] == [
            record.identifier.normalized for record in committed.records
        ]
        assert regenerated.structure_fingerprint == committed.structure_fingerprint


def test_a_refresh_keeps_the_retained_bytes_verbatim(tmp_path) -> None:
    """A fixture that has been rewritten is no longer evidence of what upstream sent."""
    store = FilesystemBlobStore(tmp_path / "blobs")
    staging = tmp_path / "regenerated"
    with database() as session:
        crawl(session, tmp_path / "blobs", transport(), mode="archive")
        session.flush()
        refresh_fixtures(session, blob_store=store, staging_dir=staging, record_limit=2)

    reduced = (staging / "archive_year_dr_2024.xml").read_text()
    source = (FIXTURES / "archive_year_dr_2024.xml").read_text()
    kept = source[source.index("<item") : source.index("<item", source.index("</item>"))]
    assert kept in reduced
    assert reduced.count("<item child='1'") == 2


def test_a_listing_row_is_cut_out_without_breaking_its_nested_detail_table(tmp_path) -> None:
    """The live listing hides a table inside the status cell; a naive cut truncates a row."""
    from billwatcher.jobs.fixture_refresh import _reduce_listing

    live = (FIXTURES / "live_current_dr_bm.html").read_text()
    reduced, kept = _reduce_listing(live, limit=1)
    assert kept == 1
    url = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr"
    parsed = parse_stored_listing(reduced, url=url, source_url=url)
    assert len(parsed.records) == 1
    # The detail table inside the retained row survived the cut, dates and all.
    assert parsed.records[0].dates
    assert parsed.records[0].presenter


def test_a_refresh_without_any_stored_snapshot_regenerates_nothing(tmp_path) -> None:
    """Seeded fixtures are not evidence of upstream, so they may not refresh themselves."""
    store = FilesystemBlobStore(tmp_path / "blobs")
    with database() as session:
        load_fixture_listings(session, blob_store=store)
        session.flush()
        report = refresh_fixtures(session, blob_store=store, staging_dir=tmp_path / "regenerated")
        assert report.refreshed == ()
        assert len(report.skipped) == len(FIXTURE_TARGETS)
        assert all("no stored snapshot" in reason for _, reason in report.skipped)
