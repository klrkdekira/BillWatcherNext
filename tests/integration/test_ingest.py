from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.models import (
    Anomaly,
    Bill,
    BillDocument,
    BillEvent,
    Blob,
    ChamberRecord,
    Document,
    FetchQueueItem,
    FieldOverride,
    PresenceObservation,
    RecordChange,
    SourceSnapshot,
)
from billwatcher.scraper.ingest import ingest_listing, replay_snapshot
from billwatcher.scraper.parse_listing import parse_listing
from billwatcher.storage.blobs import BlobStore
from billwatcher.version import PARSER_VERSION

FIXTURES = Path("tests/fixtures/parliament")
URL = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr"
NOW = datetime(2026, 8, 17, tzinfo=UTC)


def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def listing(name: str = "current_dr_bm.html"):
    return parse_listing((FIXTURES / name).read_text(), source_url=URL)


def test_second_identical_run_has_no_duplicates_or_changes() -> None:
    with session() as database:
        first = ingest_listing(
            database,
            listing(),
            chamber="dewan_rakyat",
            language="ms",
            source_url=URL,
            snapshot_id="snapshot-1",
            run_id="run-1",
            checked_at=NOW,
        )
        database.flush()
        second = ingest_listing(
            database,
            listing(),
            chamber="dewan_rakyat",
            language="ms",
            source_url=URL,
            snapshot_id="snapshot-2",
            run_id="run-2",
            checked_at=NOW + timedelta(hours=12),
        )
        database.flush()

        assert first.bills_inserted == 1
        assert first.events_inserted == 1
        assert first.documents_queued == 1
        assert second == second.__class__()
        assert database.scalar(select(func.count()).select_from(Bill)) == 1
        assert database.scalar(select(func.count()).select_from(ChamberRecord)) == 1
        assert database.scalar(select(func.count()).select_from(BillEvent)) == 1
        assert database.scalar(select(func.count()).select_from(Document)) == 1
        assert database.scalar(select(func.count()).select_from(BillDocument)) == 1
        assert database.scalar(select(func.count()).select_from(FetchQueueItem)) == 1
        assert database.scalar(select(func.count()).select_from(RecordChange)) == 0
        assert database.scalar(select(func.count()).select_from(PresenceObservation)) == 0

        bill = database.scalar(select(Bill))
        assert bill is not None
        assert bill.last_seen_at.replace(tzinfo=UTC) == NOW + timedelta(hours=12)
        assert bill.last_changed_at.replace(tzinfo=UTC) == NOW


def test_shared_bill_keeps_distinct_chamber_records() -> None:
    with session() as database:
        ingest_listing(
            database,
            listing("current_dr_bm.html"),
            chamber="dewan_rakyat",
            language="ms",
            source_url=URL,
            snapshot_id="dr",
            run_id="run",
            checked_at=NOW,
        )
        ingest_listing(
            database,
            listing("current_dn_bm.html"),
            chamber="dewan_negara",
            language="ms",
            source_url=URL.replace("rakyat", "negara"),
            snapshot_id="dn",
            run_id="run",
            checked_at=NOW,
        )
        database.flush()
        assert database.scalar(select(func.count()).select_from(Bill)) == 1
        chambers = set(database.scalars(select(ChamberRecord.chamber)))
        assert chambers == {"dewan_rakyat", "dewan_negara"}


def test_real_field_diff_writes_one_attributed_change() -> None:
    with session() as database:
        ingest_listing(
            database,
            listing(),
            chamber="dewan_rakyat",
            language="ms",
            source_url=URL,
            snapshot_id="one",
            run_id="run-one",
            checked_at=NOW,
        )
        changed_html = (
            (FIXTURES / "current_dr_bm.html")
            .read_text()
            .replace("RUU Perlindungan Saksi", "RUU Perlindungan Saksi (Pindaan)")
        )
        changed = parse_listing(changed_html, source_url=URL)
        counts = ingest_listing(
            database,
            changed,
            chamber="dewan_rakyat",
            language="ms",
            source_url=URL,
            snapshot_id="two",
            run_id="run-two",
            checked_at=NOW + timedelta(days=1),
        )
        database.flush()
        rows = database.scalars(select(RecordChange)).all()
        assert counts.changes == 1
        assert len(rows) == 1
        assert rows[0].field_path == "title_bm"
        assert rows[0].run_id == "run-two"
        assert rows[0].snapshot_id == "two"
        assert rows[0].change_source == "scrape"


def test_active_override_survives_and_conflict_is_anomaly() -> None:
    with session() as database:
        ingest_listing(
            database,
            listing(),
            chamber="dewan_rakyat",
            language="ms",
            source_url=URL,
            snapshot_id="one",
            run_id="run-one",
            checked_at=NOW,
        )
        database.flush()
        bill = database.scalar(select(Bill))
        assert bill is not None
        database.add(
            FieldOverride(
                entity_type="bill",
                entity_id=bill.id,
                field_path="title_bm",
                value=bill.title_bm,
                reason="confirmed correction",
                actor="operator",
                created_at=NOW,
                upstream_value_at_creation=bill.title_bm,
            )
        )
        changed_html = (
            (FIXTURES / "current_dr_bm.html")
            .read_text()
            .replace("RUU Perlindungan Saksi", "Unexpected upstream replacement")
        )
        ingest_listing(
            database,
            parse_listing(changed_html, source_url=URL),
            chamber="dewan_rakyat",
            language="ms",
            source_url=URL,
            snapshot_id="two",
            run_id="run-two",
            checked_at=NOW + timedelta(days=1),
        )
        database.flush()
        database.refresh(bill)
        assert bill.title_bm == "RUU Perlindungan Saksi"
        assert (
            database.scalar(select(Anomaly.kind).where(Anomaly.kind == "override_conflict"))
            == "override_conflict"
        )


def test_snapshot_replay_is_offline_and_same_parser_is_noop(tmp_path) -> None:
    with session() as database:
        store = BlobStore(tmp_path)
        stored = store.put((FIXTURES / "current_dr_bm.html").read_bytes(), compress=True)
        database.add(
            Blob(
                sha256=stored.sha256,
                byte_size=stored.byte_size,
                media_type="text/html",
                storage_path=str(stored.path),
                compression=stored.compression,
                ref_count=1,
            )
        )
        snapshot = SourceSnapshot(
            id="snapshot",
            run_id="original-run",
            url=URL,
            final_url=URL,
            requested_at=NOW,
            status_code=200,
            blob_sha256=stored.sha256,
            parser_version=PARSER_VERSION,
            parse_status="succeeded",
            records_parsed=1,
            structure_fingerprint="a" * 64,
            retention_class="permanent",
        )
        database.add(snapshot)
        database.flush()
        initial = replay_snapshot(
            database,
            snapshot,
            blob_store=store,
            chamber="dewan_rakyat",
            language="ms",
            run_id="initial-replay",
        )
        database.flush()
        again = replay_snapshot(
            database,
            snapshot,
            blob_store=store,
            chamber="dewan_rakyat",
            language="ms",
            run_id="second-replay",
        )
        database.flush()
        assert initial.bills_inserted == 1
        assert again.changes == 0
        assert database.scalar(select(func.count()).select_from(RecordChange)) == 0
