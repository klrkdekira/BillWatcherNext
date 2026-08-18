"""Offline fixture ingestion (HANDOFF 18, acceptance walkthrough step 5).

Loads the committed listing fixtures into the configured database as a `fixture`-mode run so
the whole site — browse, search, bill detail, timelines, changes, status — can be exercised
without a single upstream request. Provenance is real: every row is attributable to a run and a
stored snapshot, exactly as a live crawl would be.

Re-running adds a new observation (snapshots are append-only) but no duplicate bills, chamber
records, events, or recorded changes.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import Blob, CoverageTarget, ScrapeRun, SourceSnapshot
from billwatcher.scraper.ingest import ingest_listing
from billwatcher.scraper.parse_archive import parse_stored_listing
from billwatcher.storage.blobs import BlobStore
from billwatcher.version import NORMALIZER_VERSION, PARSER_VERSION

FIXTURES_DIR = Path("tests/fixtures/parliament")


@dataclass(frozen=True, slots=True)
class FixtureTarget:
    fixture: str
    chamber: str
    listing_kind: str
    language: str
    url: str
    # An archived year is one target per year, exactly as the live crawl reads it, so a seeded
    # database has the same coverage shape a real one does.
    scope: str = ""
    media_type: str = "text/html"


# The dated variants are used for the current listings so a seeded site shows real chamber
# timelines rather than status alone.
FIXTURE_TARGETS: Final = (
    FixtureTarget(
        "current_dr_bm_dated.html",
        "dewan_rakyat",
        "current",
        "ms",
        "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr",
    ),
    FixtureTarget(
        "current_dn_bm_dated.html",
        "dewan_negara",
        "current",
        "ms",
        "https://www.parlimen.gov.my/bills-dewan-negara.html?lang=bm&uweb=dn",
    ),
    FixtureTarget(
        "current_dr_en.html",
        "dewan_rakyat",
        "current",
        "en",
        "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=en&uweb=dr",
    ),
    # The archive is the tree Parliament serves for `arkib=yes`, one XML document per year
    # (ADR-014). The year index is not seeded because it lists years, not bills; a seeded
    # database therefore shows the archived years healthy and the index never run, which is
    # exactly what happened.
    FixtureTarget(
        "archive_year_dr_2024.xml",
        "dewan_rakyat",
        "archive",
        "ms",
        "https://www.parlimen.gov.my/bills-dewan-rakyat.html"
        "?lang=bm&uweb=dr&arkib=yes&ajx=1&id=0_2024",
        scope="2024",
        media_type="text/xml",
    ),
    FixtureTarget(
        "archive_year_dn_2011.xml",
        "dewan_negara",
        "archive",
        "ms",
        "https://www.parlimen.gov.my/bills-dewan-negara.html"
        "?lang=bm&uweb=dn&arkib=yes&ajx=1&id=0_2011",
        scope="2011",
        media_type="text/xml",
    ),
)


@dataclass(frozen=True, slots=True)
class FixtureLoadReport:
    run_id: str
    targets: int
    records: int
    bills_inserted: int
    chamber_records_inserted: int
    events_inserted: int
    changes: int
    documents_queued: int

    def as_counts(self) -> dict[str, int | str]:
        return {
            "run_id": self.run_id,
            "targets": self.targets,
            "records": self.records,
            "bills_inserted": self.bills_inserted,
            "chamber_records_inserted": self.chamber_records_inserted,
            "events_inserted": self.events_inserted,
            "changes": self.changes,
            "documents_queued": self.documents_queued,
        }


def load_fixture_listings(
    session: Session,
    *,
    blob_store: BlobStore,
    fixtures_dir: Path = FIXTURES_DIR,
    targets: tuple[FixtureTarget, ...] = FIXTURE_TARGETS,
    now: datetime | None = None,
) -> FixtureLoadReport:
    observed_at = now or datetime.now(UTC)
    run = ScrapeRun(
        mode="fixture",
        trigger="manual",
        started_at=observed_at,
        state="running",
        policy_snapshot={
            "source": "committed fixtures",
            "network": "none",
            "parser_version": PARSER_VERSION,
            "normalizer_version": NORMALIZER_VERSION,
        },
    )
    session.add(run)
    session.flush()

    records = bills = chambers = events = changes = queued = 0
    for target in targets:
        path = fixtures_dir / target.fixture
        if not path.exists():
            raise FileNotFoundError(f"fixture is missing: {path}")
        body = path.read_bytes()
        snapshot = _snapshot(session, run, target, body, blob_store, observed_at)
        listing = parse_stored_listing(body.decode("utf-8"), url=target.url, source_url=target.url)
        snapshot.parse_status = "succeeded"
        snapshot.parsed_at = observed_at
        snapshot.records_parsed = len(listing.records)
        snapshot.structure_fingerprint = listing.structure_fingerprint
        snapshot.retention_class = "permanent"

        counts = ingest_listing(
            session,
            listing,
            chamber=target.chamber,
            language=target.language,
            source_url=target.url,
            snapshot_id=snapshot.id,
            run_id=run.id,
            checked_at=observed_at,
        )
        records += len(listing.records)
        bills += counts.bills_inserted
        chambers += counts.chamber_records_inserted
        events += counts.events_inserted
        changes += counts.changes
        queued += counts.documents_queued
        _update_coverage(session, target, run, len(listing.records), observed_at)

    run.state = "succeeded"
    run.ended_at = datetime.now(UTC)
    run.fetched = len(targets)
    run.parsed = records
    run.inserted = bills + chambers
    run.publish_decision = "published"
    run.publish_reason = "offline fixture ingestion"
    session.flush()
    return FixtureLoadReport(
        run_id=run.id,
        targets=len(targets),
        records=records,
        bills_inserted=bills,
        chamber_records_inserted=chambers,
        events_inserted=events,
        changes=changes,
        documents_queued=queued,
    )


def _snapshot(
    session: Session,
    run: ScrapeRun,
    target: FixtureTarget,
    body: bytes,
    blob_store: BlobStore,
    observed_at: datetime,
) -> SourceSnapshot:
    stored = blob_store.put(body, compress=True)
    blob = session.get(Blob, stored.sha256)
    if blob is None:
        blob = Blob(
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            media_type=target.media_type,
            storage_path=stored.location,
            compression=stored.compression,
            ref_count=0,
        )
        session.add(blob)
    blob.ref_count += 1
    snapshot = SourceSnapshot(
        run_id=run.id,
        url=target.url,
        final_url=target.url,
        requested_at=observed_at,
        status_code=200,
        response_headers={"content-type": f"{target.media_type}; charset=utf-8"},
        blob_sha256=stored.sha256,
        parser_version=PARSER_VERSION,
        parse_status="pending",
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _expected_interval_hours(target: FixtureTarget) -> int:
    """Mirror the live crawl's intervals so a seeded `/status` reads like a real one."""
    if target.listing_kind == "current":
        return 12
    return 720 if target.scope else 168


def _update_coverage(
    session: Session,
    target: FixtureTarget,
    run: ScrapeRun,
    record_count: int,
    observed_at: datetime,
) -> None:
    row = session.scalar(
        select(CoverageTarget).where(
            CoverageTarget.chamber == target.chamber,
            CoverageTarget.listing_kind == target.listing_kind,
            CoverageTarget.language == target.language,
            CoverageTarget.scope_key == target.scope,
        )
    )
    if row is None:
        row = CoverageTarget(
            chamber=target.chamber,
            listing_kind=target.listing_kind,
            language=target.language,
            scope_key=target.scope,
            expected_interval_hours=_expected_interval_hours(target),
            state="never_run",
        )
        session.add(row)
    row.last_attempt_at = observed_at
    row.last_success_at = observed_at
    row.last_success_run_id = run.id
    row.last_record_count = record_count
    row.state = "healthy"
    session.flush()
