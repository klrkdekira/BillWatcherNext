"""Application-owned maintenance of the HANDOFF 12.1 search units.

Units are rebuilt in the same transaction as the write that caused them; no database
trigger touches this table (ADR-006).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import Bill, BillDocument, ChamberRecord, DocumentVersion, SearchUnit

# One PostgreSQL tsvector is capped near 1 MB, so a single very long page is stored as
# several units rather than one row that would fail or silently truncate on indexing.
MAX_UNIT_CHARS = 200_000


def split_for_indexing(content: str, *, limit: int = MAX_UNIT_CHARS) -> list[str]:
    """Split one page into index-sized parts on whitespace where possible."""
    if len(content) <= limit:
        return [content]
    parts: list[str] = []
    remaining = content
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind(" ")
        if cut < limit // 2:
            cut = limit
        parts.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts


def rebuild_bill_metadata_unit(session: Session, bill: Bill) -> SearchUnit:
    """Refresh the weight A identifier text and weight B descriptive text for one bill."""
    chambers = session.scalars(select(ChamberRecord).where(ChamberRecord.bill_id == bill.id)).all()
    identifiers = "\n".join({bill.identifier_normalized, bill.identifier_raw})
    fields = [bill.title_bm or "", bill.title_en or "", str(bill.year or "")]
    for chamber in chambers:
        fields.extend(
            [
                chamber.chamber,
                chamber.status_raw,
                chamber.status_normalized,
                chamber.presenter_raw or "",
            ]
        )
    content = "\n".join(value for value in fields if value)
    unit = session.scalar(
        select(SearchUnit).where(
            SearchUnit.bill_id == bill.id,
            SearchUnit.unit_kind == "bill_metadata",
        )
    )
    if unit is None:
        unit = SearchUnit(
            unit_kind="bill_metadata",
            bill_id=bill.id,
            content_a=identifiers,
            content=content,
        )
        session.add(unit)
    else:
        unit.content_a = identifiers
        unit.content = content
        unit.is_current = True
    return unit


def index_document_extraction(
    session: Session,
    *,
    document_version_id: str,
    pages: tuple[str, ...],
) -> int:
    """Replace mutable search projections while preserving extraction/version rows."""
    version = session.get(DocumentVersion, document_version_id)
    if version is None:
        raise ValueError("document version does not exist")
    bill_ids = session.scalars(
        select(BillDocument.bill_id).where(BillDocument.document_id == version.document_id)
    ).all()
    if version.is_current:
        version_ids = select(DocumentVersion.id).where(
            DocumentVersion.document_id == version.document_id
        )
        for unit in session.scalars(
            select(SearchUnit).where(
                SearchUnit.unit_kind == "document_text",
                SearchUnit.document_version_id.in_(version_ids),
            )
        ):
            unit.is_current = False

    written = 0
    for bill_id in set(bill_ids):
        for page_number, page in enumerate(pages, start=1):
            if not page:
                continue
            for part_number, part in enumerate(split_for_indexing(page), start=1):
                page_unit = session.scalar(
                    select(SearchUnit).where(
                        SearchUnit.unit_kind == "document_text",
                        SearchUnit.bill_id == bill_id,
                        SearchUnit.document_version_id == version.id,
                        SearchUnit.page_from == page_number,
                        SearchUnit.part == part_number,
                    )
                )
                if page_unit is None:
                    page_unit = SearchUnit(
                        unit_kind="document_text",
                        bill_id=bill_id,
                        document_version_id=version.id,
                        page_from=page_number,
                        page_to=page_number,
                        part=part_number,
                        content=part,
                    )
                    session.add(page_unit)
                else:
                    page_unit.content = part
                page_unit.is_current = version.is_current
                written += 1
    return written
