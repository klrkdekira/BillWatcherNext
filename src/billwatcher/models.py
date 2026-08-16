import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from billwatcher.db import Base


def uuid4() -> str:
    return str(uuid.uuid4())


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    identifier_raw: Mapped[str] = mapped_column(Text)
    identifier_normalized: Mapped[str] = mapped_column(Text, unique=True)
    number: Mapped[int | None] = mapped_column(Integer)
    year: Mapped[int | None] = mapped_column(SmallInteger)
    originating_chamber: Mapped[str | None] = mapped_column(String(32))
    parliament_term: Mapped[str | None] = mapped_column(Text)
    session: Mapped[int | None] = mapped_column(SmallInteger)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    title_bm: Mapped[str | None] = mapped_column(Text)
    title_en: Mapped[str | None] = mapped_column(Text)
    bill_kind: Mapped[str | None] = mapped_column(Text)
    introduced_on: Mapped[date | None] = mapped_column(Date)
    identifier_scheme_version: Mapped[int] = mapped_column(SmallInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_absent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    absent_streak: Mapped[int] = mapped_column(Integer, default=0)
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillSlugAlias(Base):
    __tablename__ = "bill_slug_aliases"

    slug: Mapped[str] = mapped_column(Text, primary_key=True)
    bill_id: Mapped[str] = mapped_column(ForeignKey("bills.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reason: Mapped[str] = mapped_column(Text)


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    mode: Mapped[str] = mapped_column(String(16))
    trigger: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16))
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    not_modified: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    parsed: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    new_document_versions: Mapped[int] = mapped_column(Integer, default=0)
    quarantined_versions: Mapped[int] = mapped_column(Integer, default=0)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    publish_decision: Mapped[str] = mapped_column(String(16), default="withheld")
    publish_reason: Mapped[str | None] = mapped_column(Text)


class Blob(Base):
    __tablename__ = "blobs"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(Text)
    compression: Mapped[str] = mapped_column(String(16))
    first_stored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ref_count: Mapped[int] = mapped_column(Integer, default=0)


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(ForeignKey("scrape_runs.id"))
    url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status_code: Mapped[int] = mapped_column(Integer)
    response_headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    blob_sha256: Mapped[str | None] = mapped_column(ForeignKey("blobs.sha256"))
    parser_version: Mapped[str] = mapped_column(String(32))
    parse_status: Mapped[str] = mapped_column(String(16), default="pending")
    parse_error: Mapped[str | None] = mapped_column(Text)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_parsed: Mapped[int | None] = mapped_column(Integer)
    structure_fingerprint: Mapped[str | None] = mapped_column(String(64))
    retention_class: Mapped[str] = mapped_column(String(16), default="routine")


class ChamberRecord(Base):
    __tablename__ = "chamber_records"
    __table_args__ = (UniqueConstraint("bill_id", "chamber"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    bill_id: Mapped[str] = mapped_column(ForeignKey("bills.id"))
    chamber: Mapped[str] = mapped_column(String(32))
    status_raw: Mapped[str] = mapped_column(Text)
    status_normalized: Mapped[str] = mapped_column(String(32))
    first_read_on: Mapped[date | None] = mapped_column(Date)
    second_read_on: Mapped[date | None] = mapped_column(Date)
    third_read_on: Mapped[date | None] = mapped_column(Date)
    passed_on: Mapped[date | None] = mapped_column(Date)
    referred_on: Mapped[date | None] = mapped_column(Date)
    presenter_raw: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    source_snapshot_id: Mapped[str] = mapped_column(ForeignKey("source_snapshots.id"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_absent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    absent_streak: Mapped[int] = mapped_column(Integer, default=0)


class BillEvent(Base):
    __tablename__ = "bill_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    bill_id: Mapped[str] = mapped_column(ForeignKey("bills.id"))
    chamber: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(32))
    event_on: Mapped[date | None] = mapped_column(Date)
    event_on_end: Mapped[date | None] = mapped_column(Date)
    actor_raw: Mapped[str | None] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(SmallInteger, default=0)
    source_label: Mapped[str] = mapped_column(Text)
    source_value: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("source_snapshots.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("scrape_runs.id"))
    parser_version: Mapped[str] = mapped_column(String(32))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)


class FetchAttempt(Base):
    __tablename__ = "fetch_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(ForeignKey("scrape_runs.id"))
    target_kind: Mapped[str] = mapped_column(String(24))
    url: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(8))
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer)
    status_code: Mapped[int | None] = mapped_column(Integer)
    bytes_received: Mapped[int] = mapped_column(BigInteger, default=0)
    conditional: Mapped[bool] = mapped_column(Boolean, default=False)
    not_modified: Mapped[bool] = mapped_column(Boolean, default=False)
    error_class: Mapped[str | None] = mapped_column(String(128))
    error_detail: Mapped[str | None] = mapped_column(String(1000))
    blob_sha256: Mapped[str | None] = mapped_column(ForeignKey("blobs.sha256"))


class FetchQueueItem(Base):
    __tablename__ = "fetch_queue"
    __table_args__ = (UniqueConstraint("target_kind", "url"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    target_kind: Mapped[str] = mapped_column(String(24))
    url: Mapped[str] = mapped_column(Text)
    bill_id: Mapped[str | None] = mapped_column(ForeignKey("bills.id"))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    priority: Mapped[int] = mapped_column(SmallInteger, default=0)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    document_kind: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(16))
    title_raw: Mapped[str | None] = mapped_column(Text)
    canonical_source_url: Mapped[str] = mapped_column(Text, unique=True)
    source_url_raw: Mapped[str] = mapped_column(Text)
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_versions.id", use_alter=True)
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_absent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    absent_streak: Mapped[int] = mapped_column(Integer, default=0)


class BillDocument(Base):
    __tablename__ = "bill_documents"
    __table_args__ = (UniqueConstraint("bill_id", "chamber", "document_id", "role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    bill_id: Mapped[str] = mapped_column(ForeignKey("bills.id"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    chamber: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str] = mapped_column(Text)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64))
    blob_sha256: Mapped[str] = mapped_column(ForeignKey("blobs.sha256"))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    media_type_declared: Mapped[str | None] = mapped_column(Text)
    media_type_detected: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int] = mapped_column(Integer)
    final_url: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[str] = mapped_column(ForeignKey("scrape_runs.id"))
    fetch_attempt_id: Mapped[str] = mapped_column(ForeignKey("fetch_attempts.id"))
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("source_snapshots.id"))
    supersedes_version_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id"))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    change_kind: Mapped[str] = mapped_column(String(24))
    validation_status: Mapped[str] = mapped_column(String(16))
    validation_error: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("document_id", "version_no"),
        Index(
            "uq_document_versions_one_current",
            "document_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current = 1"),
        ),
        Index("ix_document_versions_current", "document_id", "is_current"),
    )


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"
    __table_args__ = (
        UniqueConstraint("document_version_id", "extractor_name", "extractor_version", "mode"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"))
    extractor_name: Mapped[str] = mapped_column(String(64))
    extractor_version: Mapped[str] = mapped_column(String(32))
    pipeline_version: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    text_sha256: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(Integer)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    duration_ms: Mapped[int] = mapped_column(Integer)


class RecordChange(Base):
    __tablename__ = "record_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(36))
    field_path: Mapped[str] = mapped_column(Text)
    value_before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    value_after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    change_source: Mapped[str] = mapped_column(String(16))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("scrape_runs.id"))
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("source_snapshots.id"))
    source_url: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)


class FieldOverride(Base):
    __tablename__ = "field_overrides"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(36))
    field_path: Mapped[str] = mapped_column(Text)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    upstream_value_at_creation: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class PresenceObservation(Base):
    __tablename__ = "presence_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(ForeignKey("scrape_runs.id"))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(36))
    listing_url: Mapped[str] = mapped_column(Text)
    present: Mapped[bool] = mapped_column(Boolean)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CoverageTarget(Base):
    __tablename__ = "coverage_targets"
    __table_args__ = (UniqueConstraint("chamber", "listing_kind", "language", "scope_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    chamber: Mapped[str] = mapped_column(String(32))
    listing_kind: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(8))
    scope_key: Mapped[str] = mapped_column(Text, default="")
    expected_interval_hours: Mapped[int] = mapped_column(Integer)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_run_id: Mapped[str | None] = mapped_column(ForeignKey("scrape_runs.id"))
    last_record_count: Mapped[int | None] = mapped_column(Integer)
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), default="never_run")


class BackfillJob(Base):
    __tablename__ = "backfill_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(16))
    from_version: Mapped[str | None] = mapped_column(String(32))
    to_version: Mapped[str] = mapped_column(String(32))
    filter_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(16))
    counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    url: Mapped[str | None] = mapped_column(Text)
    detail_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchUnit(Base):
    __tablename__ = "search_units"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    unit_kind: Mapped[str] = mapped_column(String(24))
    bill_id: Mapped[str] = mapped_column(ForeignKey("bills.id"), index=True)
    document_version_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.id"))
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyFetchMetric(Base):
    __tablename__ = "daily_fetch_metrics"
    __table_args__ = (UniqueConstraint("day", "host", "status_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    day: Mapped[date] = mapped_column(Date)
    host: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer)
    bytes_received: Mapped[int] = mapped_column(BigInteger)
    mean_duration_ms: Mapped[float] = mapped_column(Float)
