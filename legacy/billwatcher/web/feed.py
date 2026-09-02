"""The public /changes feed (HANDOFF 10.2, 14).

Two different kinds of fact are merged here and must stay distinguishable: what Parliament
published, and what this index corrected about its own record.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import (
    Bill,
    BillDocument,
    ChamberRecord,
    Document,
    DocumentVersion,
    RecordChange,
)

CHANGE_KINDS = frozenset({"all", "record", "document_version"})
CHANGES_PAGE_SIZE = 50

_UPSTREAM_SOURCES = {"scrape"}


@dataclass(frozen=True, slots=True)
class ChangeEntry:
    changed_at: datetime
    kind: str
    origin: str
    summary: str
    detail: str
    bill_slug: str | None
    bill_identifier: str | None
    chamber: str | None


def recent_changes(
    session: Session,
    *,
    chamber: str | None = None,
    kind: str = "all",
    page: int = 1,
    page_size: int = CHANGES_PAGE_SIZE,
) -> tuple[list[ChangeEntry], bool]:
    """Return one page of merged changes plus whether a further page exists."""
    window = page * page_size + 1
    entries: list[ChangeEntry] = []
    if kind in {"all", "record"}:
        entries.extend(_record_entries(session, chamber=chamber, limit=window))
    if kind in {"all", "document_version"}:
        entries.extend(_document_entries(session, chamber=chamber, limit=window))
    entries.sort(key=lambda entry: entry.changed_at, reverse=True)
    start = (page - 1) * page_size
    page_entries = entries[start : start + page_size]
    return page_entries, len(entries) > start + page_size


def _chamber_lookup(session: Session) -> dict[str, set[str]]:
    lookup: dict[str, set[str]] = {}
    for bill_id, name in session.execute(
        select(ChamberRecord.bill_id, ChamberRecord.chamber)
    ).tuples():
        lookup.setdefault(bill_id, set()).add(name)
    return lookup


def _record_entries(session: Session, *, chamber: str | None, limit: int) -> list[ChangeEntry]:
    rows = session.scalars(
        select(RecordChange)
        .where(RecordChange.entity_type.in_(("bill", "chamber_record")))
        .order_by(RecordChange.changed_at.desc())
        .limit(limit * 4 if chamber else limit)
    ).all()
    if not rows:
        return []
    bills = {bill.id: bill for bill in session.scalars(select(Bill))}
    records = {record.id: record for record in session.scalars(select(ChamberRecord))}
    chambers_by_bill = _chamber_lookup(session)

    entries: list[ChangeEntry] = []
    for row in rows:
        if row.entity_type == "bill":
            bill = bills.get(row.entity_id)
            row_chamber = None
        else:
            record = records.get(row.entity_id)
            bill = bills.get(record.bill_id) if record else None
            row_chamber = record.chamber if record else None
        if bill is None:
            continue
        if chamber and row_chamber not in (None, chamber):
            continue
        if chamber and row_chamber is None and chamber not in chambers_by_bill.get(bill.id, set()):
            continue
        upstream = row.change_source in _UPSTREAM_SOURCES
        entries.append(
            ChangeEntry(
                changed_at=row.changed_at,
                kind="record",
                origin="upstream" if upstream else "index",
                summary=(
                    f"Published {row.field_path} changed"
                    if upstream
                    else f"We corrected {row.field_path}"
                ),
                detail=(
                    "Parliament published a different value in the listing we read."
                    if upstream
                    else f"Correction to our own record ({row.change_source})."
                ),
                bill_slug=bill.slug,
                bill_identifier=bill.identifier_raw,
                chamber=row_chamber,
            )
        )
        if len(entries) >= limit:
            break
    return entries


def _document_entries(session: Session, *, chamber: str | None, limit: int) -> list[ChangeEntry]:
    statement = (
        select(DocumentVersion, Document, BillDocument, Bill)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(BillDocument, BillDocument.document_id == Document.id)
        .join(Bill, Bill.id == BillDocument.bill_id)
        .where(DocumentVersion.validation_status == "accepted")
        .order_by(DocumentVersion.retrieved_at.desc())
        .limit(limit)
    )
    if chamber:
        statement = statement.where(BillDocument.chamber.in_((chamber, None)))
    entries: list[ChangeEntry] = []
    for version, document, link, bill in session.execute(statement).tuples():
        first = version.change_kind == "initial"
        entries.append(
            ChangeEntry(
                changed_at=version.retrieved_at,
                kind="document_version",
                origin="upstream",
                summary=(
                    f"First saved copy of {document.document_kind}"
                    if first
                    else f"Version {version.version_no} of {document.document_kind}"
                ),
                detail=(
                    "The official URL served content we had not stored before."
                    if first
                    else "The official URL served different bytes than our previous copy."
                ),
                bill_slug=bill.slug,
                bill_identifier=bill.identifier_raw,
                chamber=link.chamber,
            )
        )
    return entries
