import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from billwatcher.models import (
    Bill,
    Blob,
    ChamberRecord,
    CoverageTarget,
    FetchAttempt,
    ScrapeRun,
    SourceSnapshot,
)
from billwatcher.operations import record_anomaly
from billwatcher.scraper.fetch import Fetcher, FetchResult
from billwatcher.scraper.ingest import IngestCounts, ingest_listing
from billwatcher.scraper.parse_listing import ListingParseError, ParsedListing, parse_listing
from billwatcher.scraper.presence import record_full_run_presence
from billwatcher.scraper.queue import CircuitBreaker, CrawlBudget
from billwatcher.scraper.robots import parse_robots
from billwatcher.storage.blobs import BlobStore
from billwatcher.version import NORMALIZER_VERSION, PARSER_VERSION

SCRAPE_LOCK_KEY: Final = 0x42494C4C
BACKFILL_LOCK_KEY: Final = 0x4241434B


@dataclass(frozen=True, slots=True)
class ListingTarget:
    chamber: str
    listing_kind: str
    language: str
    url: str

    @property
    def scope_key(self) -> str:
        return ""


@dataclass(frozen=True, slots=True)
class PreparedListing:
    target: ListingTarget
    listing: ParsedListing
    snapshot: SourceSnapshot
    coverage: CoverageTarget
    observed_at: datetime
    expected_bill_ids: frozenset[str]


TARGETS: Final = (
    ListingTarget(
        "dewan_rakyat",
        "current",
        "ms",
        "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr",
    ),
    ListingTarget(
        "dewan_negara",
        "current",
        "ms",
        "https://www.parlimen.gov.my/bills-dewan-negara.html?lang=bm&uweb=dn",
    ),
    ListingTarget(
        "dewan_rakyat",
        "archive",
        "ms",
        "https://www.parlimen.gov.my/bills-dewan-rakyat.html?arkib=yes&lang=bm&uweb=dr",
    ),
    ListingTarget(
        "dewan_negara",
        "archive",
        "ms",
        "https://www.parlimen.gov.my/bills-dewan-negara.html?arkib=yes&lang=bm&uweb=dn",
    ),
)


class ScrapeRefused(RuntimeError):
    pass


class BudgetExhausted(ScrapeRefused):
    pass


@contextmanager
def advisory_lock(session: Session, key: int) -> Iterator[None]:
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        yield
        return
    acquired = bool(session.scalar(text("SELECT pg_try_advisory_lock(:key)").bindparams(key=key)))
    if not acquired:
        raise ScrapeRefused("another job holds the advisory lock")
    try:
        yield
    finally:
        session.execute(text("SELECT pg_advisory_unlock(:key)").bindparams(key=key))


class ScrapeOrchestrator:
    def __init__(
        self,
        *,
        session: Session,
        fetcher: Fetcher,
        blob_store: BlobStore,
        budget: CrawlBudget,
        sleep: Callable[[float], None] = time.sleep,
        count_drop_abort_fraction: float = 0.30,
        absence_streak_alert: int = 3,
    ) -> None:
        self.session = session
        self.fetcher = fetcher
        self.blob_store = blob_store
        self.budget = budget
        self.sleep = sleep
        self.count_drop_abort_fraction = count_drop_abort_fraction
        self.absence_streak_alert = absence_streak_alert
        self.breaker = CircuitBreaker()

    def run(self, *, mode: str = "incremental", trigger: str = "manual") -> ScrapeRun:
        now = datetime.now(UTC)
        run = ScrapeRun(
            mode=mode,
            trigger=trigger,
            started_at=now,
            state="running",
            policy_snapshot={
                "user_agent": self.fetcher.policy.user_agent,
                "delay_seconds": self.fetcher.policy.delay_seconds,
                "concurrency": self.fetcher.policy.concurrency,
                "parser_version": PARSER_VERSION,
                "normalizer_version": NORMALIZER_VERSION,
                "max_requests": self.budget.max_requests,
                "max_bytes": self.budget.max_bytes,
                "max_duration_seconds": self.budget.max_duration_seconds,
                "max_new_documents": self.budget.max_new_documents,
            },
            publish_decision="withheld",
        )
        self.session.add(run)
        self.session.flush()
        try:
            with advisory_lock(self.session, SCRAPE_LOCK_KEY):
                self._preflight(run)
                prepared = [self._prepare_target(run, target) for target in TARGETS]
                publication = self.session.begin_nested()
                applied: list[IngestCounts] = []
                budget_target: str | None = None
                try:
                    for item in prepared:
                        counts = self._ingest_prepared(run, item)
                        self.session.flush()
                        if not self.budget.consume(
                            request=False, new_documents=counts.documents_queued
                        ):
                            budget_target = item.target.url
                            break
                        applied.append(counts)
                    if budget_target is None and mode == "full":
                        self._record_presence(run, prepared)
                    self.session.flush()
                except Exception:
                    publication.rollback()
                    raise
                if budget_target is not None:
                    publication.rollback()
                    run.state = "partial"
                    run.publish_reason = "new document budget exhausted"
                    self._anomaly(
                        "budget_exhausted",
                        "info",
                        None,
                        None,
                        {"target": budget_target},
                        datetime.now(UTC),
                    )
                else:
                    publication.commit()
                    for counts in applied:
                        self._apply_counts(run, counts)
                    run.state = "succeeded"
                    run.publish_decision = "published"
        except BudgetExhausted as error:
            run.state = "partial"
            run.publish_decision = "withheld"
            run.publish_reason = str(error)[:1000]
            self._anomaly(
                "budget_exhausted",
                "info",
                None,
                None,
                {"detail": str(error)[:1000]},
                datetime.now(UTC),
            )
        except Exception as error:
            run.state = "failed"
            run.publish_decision = "withheld"
            run.publish_reason = str(error)[:1000]
            run.error_details = {"class": type(error).__name__, "detail": str(error)[:1000]}
        run.ended_at = datetime.now(UTC)
        self.session.flush()
        return run

    def _preflight(self, run: ScrapeRun) -> None:
        url = "https://www.parlimen.gov.my/robots.txt"
        result = self._fetch(run, "robots", url)
        policy = parse_robots(result.body, fetched_url=result.final_url)
        previous = self.session.scalar(
            select(SourceSnapshot)
            .where(
                SourceSnapshot.url == url,
                SourceSnapshot.id != self._latest_snapshot_id(run.id, url),
            )
            .order_by(SourceSnapshot.requested_at.desc())
            .limit(1)
        )
        if previous and previous.blob_sha256 != policy.sha256:
            self._anomaly(
                "robots_changed",
                "critical",
                "source_snapshot",
                previous.id,
                {"before": previous.blob_sha256, "after": policy.sha256},
                result.requested_at,
                url=url,
            )
            raise ScrapeRefused("robots.txt changed; manual review required")
        for target in TARGETS:
            if not policy.permits(self.fetcher.policy.user_agent, target.url):
                raise ScrapeRefused(f"robots.txt disallows {target.url}")
        upstream_delay = policy.crawl_delay(self.fetcher.policy.user_agent)
        if upstream_delay and upstream_delay > self.fetcher.policy.delay_seconds:
            raise ScrapeRefused("configured crawl delay is below robots.txt Crawl-delay")

    def _prepare_target(self, run: ScrapeRun, target: ListingTarget) -> PreparedListing:
        if self.breaker.open:
            raise ScrapeRefused("host circuit breaker is open")
        result = self._fetch(run, target.listing_kind, target.url)
        coverage = self._coverage(target)
        coverage.last_attempt_at = result.requested_at
        snapshot = self._snapshot_for(run.id, target.url)
        if snapshot is None:
            raise RuntimeError("fetch did not create a source snapshot")
        try:
            listing = parse_listing(result.body.decode("utf-8"), source_url=result.final_url)
        except (UnicodeDecodeError, ListingParseError) as error:
            snapshot.parse_status = "failed"
            snapshot.parse_error = str(error)[:1000]
            self.breaker.record(failed=False)
            raise
        snapshot.parse_status = "succeeded"
        snapshot.parsed_at = datetime.now(UTC)
        snapshot.records_parsed = len(listing.records)
        snapshot.structure_fingerprint = listing.structure_fingerprint

        if target.listing_kind == "current" and not listing.records:
            self._anomaly(
                "zero_records",
                "critical",
                "source_snapshot",
                snapshot.id,
                {"target": target.url},
                result.requested_at,
                url=target.url,
            )
            raise ScrapeRefused("current listing parsed to zero records")

        if coverage.last_record_count and (
            len(listing.records) < coverage.last_record_count * (1 - self.count_drop_abort_fraction)
        ):
            self._anomaly(
                "count_drop",
                "critical",
                "coverage_target",
                coverage.id,
                {"before": coverage.last_record_count, "after": len(listing.records)},
                result.requested_at,
                url=target.url,
            )
            raise ScrapeRefused("record count dropped beyond publication threshold")
        previous_shape = self.session.scalar(
            select(SourceSnapshot.structure_fingerprint)
            .where(
                SourceSnapshot.url == target.url,
                SourceSnapshot.id != snapshot.id,
                SourceSnapshot.parse_status == "succeeded",
            )
            .order_by(SourceSnapshot.requested_at.desc())
            .limit(1)
        )
        if previous_shape and previous_shape != listing.structure_fingerprint:
            self._anomaly(
                "structure_drift",
                "critical",
                "source_snapshot",
                snapshot.id,
                {"before": previous_shape, "after": listing.structure_fingerprint},
                result.requested_at,
                url=target.url,
            )
            raise ScrapeRefused("listing structure changed; publication withheld")

        expected = frozenset(
            self.session.scalars(
                select(ChamberRecord.bill_id).where(
                    ChamberRecord.chamber == target.chamber,
                    ChamberRecord.source_url == target.url,
                )
            )
        )
        run.parsed += len(listing.records)
        self.breaker.record(failed=False)
        self.sleep(self.fetcher.policy.delay_seconds)
        return PreparedListing(target, listing, snapshot, coverage, result.requested_at, expected)

    def _ingest_prepared(self, run: ScrapeRun, item: PreparedListing) -> IngestCounts:
        counts = ingest_listing(
            self.session,
            item.listing,
            chamber=item.target.chamber,
            language=item.target.language,
            source_url=item.target.url,
            snapshot_id=item.snapshot.id,
            run_id=run.id,
            checked_at=item.observed_at,
        )
        item.coverage.last_success_at = item.observed_at
        item.coverage.last_success_run_id = run.id
        item.coverage.last_record_count = len(item.listing.records)
        item.coverage.state = "healthy"
        return counts

    def _record_presence(self, run: ScrapeRun, prepared: list[PreparedListing]) -> None:
        expected: set[str] = set()
        present: set[str] = set()
        provenance: dict[str, tuple[str, datetime]] = {}
        for item in prepared:
            normalized = [record.identifier.normalized for record in item.listing.records]
            item_present = set(
                self.session.scalars(
                    select(Bill.id).where(Bill.identifier_normalized.in_(normalized))
                )
            )
            expected.update(item.expected_bill_ids)
            present.update(item_present)
            for bill_id in set(item.expected_bill_ids) | item_present:
                provenance[bill_id] = (item.target.url, item.observed_at)
        for bill_id in expected | present:
            listing_url, observed_at = provenance[bill_id]
            record_full_run_presence(
                self.session,
                run_id=run.id,
                listing_url=listing_url,
                expected_bill_ids={bill_id},
                present_bill_ids={bill_id} if bill_id in present else set(),
                observed_at=observed_at,
                alert_threshold=self.absence_streak_alert,
            )

    def _fetch(self, run: ScrapeRun, target_kind: str, url: str) -> FetchResult:
        if not self.budget.consume():
            raise BudgetExhausted("crawl budget exhausted before required preflight")
        attempted = datetime.now(UTC)
        try:
            result = self.fetcher.get(url)
            if not self.budget.consume(byte_count=len(result.body), request=False):
                raise BudgetExhausted("crawl byte budget exhausted")
        except Exception as error:
            self.session.add(
                FetchAttempt(
                    run_id=run.id,
                    target_kind=target_kind,
                    url=url,
                    method="GET",
                    attempted_at=attempted,
                    duration_ms=0,
                    bytes_received=0,
                    error_class=type(error).__name__,
                    error_detail=str(error)[:1000],
                )
            )
            self.breaker.record(failed=True)
            raise
        stored = self.blob_store.put(
            result.body,
            compress=(result.headers.get("content-type", "").split(";", 1)[0] != "application/pdf"),
        )
        blob = self.session.get(Blob, stored.sha256)
        if blob is None:
            blob = Blob(
                sha256=stored.sha256,
                byte_size=stored.byte_size,
                media_type=result.headers.get("content-type", "application/octet-stream"),
                storage_path=str(stored.path),
                compression=stored.compression,
                ref_count=0,
            )
            self.session.add(blob)
        blob.ref_count += 1
        attempt = FetchAttempt(
            run_id=run.id,
            target_kind=target_kind,
            url=url,
            method="GET",
            attempted_at=result.requested_at,
            duration_ms=result.duration_ms,
            status_code=result.status_code,
            bytes_received=len(result.body),
            conditional=False,
            not_modified=result.not_modified,
            blob_sha256=stored.sha256,
        )
        self.session.add(attempt)
        snapshot = SourceSnapshot(
            run_id=run.id,
            url=url,
            final_url=result.final_url,
            requested_at=result.requested_at,
            status_code=result.status_code,
            response_headers=dict(result.headers),
            blob_sha256=stored.sha256,
            parser_version=PARSER_VERSION,
            parse_status="pending",
            retention_class="routine",
        )
        self.session.add(snapshot)
        self.session.flush()
        run.fetched += 1
        return result

    def _coverage(self, target: ListingTarget) -> CoverageTarget:
        row = self.session.scalar(
            select(CoverageTarget).where(
                CoverageTarget.chamber == target.chamber,
                CoverageTarget.listing_kind == target.listing_kind,
                CoverageTarget.language == target.language,
                CoverageTarget.scope_key == target.scope_key,
            )
        )
        if row is None:
            row = CoverageTarget(
                chamber=target.chamber,
                listing_kind=target.listing_kind,
                language=target.language,
                scope_key=target.scope_key,
                expected_interval_hours=12 if target.listing_kind == "current" else 168,
                state="never_run",
            )
            self.session.add(row)
            self.session.flush()
        return row

    def _snapshot_for(self, run_id: str, url: str) -> SourceSnapshot | None:
        return self.session.scalar(
            select(SourceSnapshot)
            .where(SourceSnapshot.run_id == run_id, SourceSnapshot.url == url)
            .order_by(SourceSnapshot.requested_at.desc())
            .limit(1)
        )

    def _latest_snapshot_id(self, run_id: str, url: str) -> str:
        snapshot = self._snapshot_for(run_id, url)
        return snapshot.id if snapshot else ""

    @staticmethod
    def _apply_counts(run: ScrapeRun, counts: IngestCounts) -> None:
        run.inserted += counts.bills_inserted + counts.chamber_records_inserted
        run.updated += counts.bills_updated

    def _anomaly(
        self,
        kind: str,
        severity: str,
        entity_type: str | None,
        entity_id: str | None,
        detail: dict[str, object],
        now: datetime,
        *,
        url: str | None = None,
    ) -> None:
        record_anomaly(
            self.session,
            kind=kind,
            severity=severity,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
            now=now,
            url=url,
        )
