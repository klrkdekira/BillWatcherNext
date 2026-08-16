from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import Bill, ChamberRecord, SearchUnit


def rebuild_bill_metadata_unit(session: Session, bill: Bill) -> SearchUnit:
    chambers = session.scalars(select(ChamberRecord).where(ChamberRecord.bill_id == bill.id)).all()
    fields = [
        bill.identifier_normalized,
        bill.identifier_raw,
        bill.title_bm or "",
        bill.title_en or "",
        str(bill.year or ""),
    ]
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
        unit = SearchUnit(unit_kind="bill_metadata", bill_id=bill.id, content=content)
        session.add(unit)
    else:
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
    from billwatcher.models import BillDocument, DocumentVersion

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
            page_unit = session.scalar(
                select(SearchUnit).where(
                    SearchUnit.unit_kind == "document_text",
                    SearchUnit.bill_id == bill_id,
                    SearchUnit.document_version_id == version.id,
                    SearchUnit.page_from == page_number,
                    SearchUnit.page_to == page_number,
                )
            )
            if page_unit is None:
                page_unit = SearchUnit(
                    unit_kind="document_text",
                    bill_id=bill_id,
                    document_version_id=version.id,
                    page_from=page_number,
                    page_to=page_number,
                    content=page,
                )
                session.add(page_unit)
            else:
                page_unit.content = page
            page_unit.is_current = version.is_current
            written += 1
    return written
