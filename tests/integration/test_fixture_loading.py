"""Offline fixture ingestion proves the whole site with no network (HANDOFF 18)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.jobs.fixtures import FIXTURE_TARGETS, load_fixture_listings
from billwatcher.models import (
    Bill,
    BillEvent,
    Blob,
    ChamberRecord,
    CoverageTarget,
    FetchQueueItem,
    RecordChange,
    ScrapeRun,
    SearchUnit,
    SourceSnapshot,
)
from billwatcher.storage.blobs import BlobStore


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


def test_loading_fixtures_populates_a_browsable_site(session: Session, tmp_path) -> None:
    report = load_fixture_listings(session, blob_store=BlobStore(tmp_path))
    session.flush()

    assert report.targets == len(FIXTURE_TARGETS)
    assert report.bills_inserted == 3
    assert report.chamber_records_inserted == 4
    assert report.events_inserted > 0
    assert report.documents_queued == 1

    # One bill shared by both chambers, with two distinct chamber records.
    shared = session.scalars(select(Bill).where(Bill.identifier_normalized == "DR-15-2026")).one()
    chambers = session.scalars(
        select(ChamberRecord).where(ChamberRecord.bill_id == shared.id)
    ).all()
    assert {record.chamber for record in chambers} == {"dewan_rakyat", "dewan_negara"}
    assert shared.title_bm and shared.title_en

    # Everything is attributable to a fixture-mode run and a stored snapshot.
    run = session.scalars(select(ScrapeRun)).one()
    assert run.mode == "fixture"
    assert run.state == "succeeded"
    assert run.publish_decision == "published"
    snapshots = session.scalars(select(SourceSnapshot)).all()
    assert len(snapshots) == len(FIXTURE_TARGETS)
    assert all(snapshot.parse_status == "succeeded" for snapshot in snapshots)
    assert all(snapshot.blob_sha256 for snapshot in snapshots)
    assert all(snapshot.retention_class == "permanent" for snapshot in snapshots)
    assert session.scalar(select(func.count()).select_from(Blob)) == len(FIXTURE_TARGETS)

    # The status page has per-target coverage, and search has units to query.
    targets = session.scalars(select(CoverageTarget)).all()
    assert len(targets) == len(FIXTURE_TARGETS)
    assert all(target.state == "healthy" for target in targets)
    assert all(target.last_record_count for target in targets)
    assert session.scalar(select(func.count()).select_from(SearchUnit)) >= 3
    assert session.scalar(select(func.count()).select_from(FetchQueueItem)) == 1


def test_a_first_load_records_only_genuine_changes(session: Session, tmp_path) -> None:
    """Inserting a record is not a change to it; only the English reconciliation is."""
    load_fixture_listings(session, blob_store=BlobStore(tmp_path))
    session.flush()
    changes = session.scalars(select(RecordChange)).all()
    assert [change.field_path for change in changes] == ["title_en"]


def test_reloading_adds_an_observation_but_no_duplicates(session: Session, tmp_path) -> None:
    store = BlobStore(tmp_path)
    load_fixture_listings(session, blob_store=store)
    session.flush()
    bills = session.scalar(select(func.count()).select_from(Bill))
    events = session.scalar(select(func.count()).select_from(BillEvent))
    changes = session.scalar(select(func.count()).select_from(RecordChange))

    second = load_fixture_listings(session, blob_store=store)
    session.flush()

    assert second.bills_inserted == 0
    assert second.chamber_records_inserted == 0
    assert second.events_inserted == 0
    assert second.changes == 0
    assert session.scalar(select(func.count()).select_from(Bill)) == bills
    assert session.scalar(select(func.count()).select_from(BillEvent)) == events
    assert session.scalar(select(func.count()).select_from(RecordChange)) == changes

    # Snapshots are append-only observations, so a second load records a second look.
    assert session.scalar(select(func.count()).select_from(SourceSnapshot)) == (
        2 * len(FIXTURE_TARGETS)
    )
    # Identical bytes deduplicate to the same blobs.
    assert session.scalar(select(func.count()).select_from(Blob)) == len(FIXTURE_TARGETS)


def test_the_english_listing_never_overwrites_the_malay_record(session: Session, tmp_path) -> None:
    """HANDOFF 11.3 step 8: reconcile English titles by identifier, and nothing else."""
    load_fixture_listings(session, blob_store=BlobStore(tmp_path))
    session.flush()
    bill = session.scalars(select(Bill).where(Bill.identifier_normalized == "DR-15-2026")).one()
    rakyat = session.scalars(
        select(ChamberRecord).where(
            ChamberRecord.bill_id == bill.id, ChamberRecord.chamber == "dewan_rakyat"
        )
    ).one()
    assert bill.title_en == "Witness Protection Bill"
    # The published Malay status and presenter survive the English pass.
    assert rakyat.status_raw == "Diluluskan"
    assert rakyat.presenter_raw == "Menteri di Jabatan Perdana Menteri"


def test_a_missing_fixture_fails_loudly(session: Session, tmp_path) -> None:
    from billwatcher.jobs.fixtures import FixtureTarget

    with pytest.raises(FileNotFoundError, match="fixture is missing"):
        load_fixture_listings(
            session,
            blob_store=BlobStore(tmp_path),
            targets=(FixtureTarget("nope.html", "dewan_rakyat", "current", "ms", "https://x/y"),),
        )
