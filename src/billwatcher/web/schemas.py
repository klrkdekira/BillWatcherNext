"""Serialization shapes for the public JSON API and for structured page metadata.

Field names here are the versioned `/api/v1` contract: a breaking change needs a new path
(HANDOFF 9.1), so these live apart from the route handlers that emit them.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.config import get_settings
from billwatcher.models import Bill, ChamberRecord
from billwatcher.search.rag import Answer
from billwatcher.version import (
    CHUNKER_VERSION,
    EXTRACTOR_VERSION,
    LAYOUT_EXTRACTOR_VERSION,
    NORMALIZER_VERSION,
    PARSER_VERSION,
    STRUCTURE_VERSION,
)

SCHEMA_VERSION = "v1"


def legislation_json_ld(bill: Bill, chambers: list[ChamberRecord]) -> dict[str, Any]:
    base = get_settings().public_base_url.rstrip("/")
    source = chambers[0].source_url if chambers else None
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Legislation",
        "@id": f"{base}/bills/{bill.slug}#bill",
        "url": f"{base}/bills/{bill.slug}",
        "name": bill.title_bm or bill.title_en or bill.identifier_raw,
        "legislationIdentifier": bill.identifier_raw,
        "legislationJurisdiction": "Malaysia",
        "legislationType": "Bill",
        "isPartOf": {"@type": "WebSite", "name": "BillWatcherNext", "url": f"{base}/"},
    }
    if bill.title_en:
        data["alternateName"] = bill.title_en
    languages = [code for code, title in (("ms", bill.title_bm), ("en", bill.title_en)) if title]
    if languages:
        data["inLanguage"] = languages
    if source:
        data["sameAs"] = source
    return data


def serialize_bill(bill: Bill, session: Session) -> dict[str, Any]:
    source_url = session.scalar(
        select(ChamberRecord.source_url)
        .where(ChamberRecord.bill_id == bill.id)
        .order_by(ChamberRecord.chamber)
        .limit(1)
    )
    return {
        "identifier": bill.identifier_normalized,
        "identifier_raw": bill.identifier_raw,
        "slug": bill.slug,
        "title_bm": bill.title_bm,
        "title_en": bill.title_en,
        "year": bill.year,
        "source_url": source_url,
        "updated_at": bill.updated_at.isoformat() if bill.updated_at else None,
        "last_checked_at": bill.last_checked_at.isoformat(),
        "last_changed_at": bill.last_changed_at.isoformat(),
    }


def pipeline_versions() -> dict[str, str]:
    return {
        "parser": PARSER_VERSION,
        "normalizer": NORMALIZER_VERSION,
        "extractor": EXTRACTOR_VERSION,
        "layout extractor": LAYOUT_EXTRACTOR_VERSION,
        "structure": STRUCTURE_VERSION,
        "chunker": CHUNKER_VERSION,
    }


def answer_payload(answer: Answer) -> dict[str, Any]:
    """The /api/v1/ask body. Every citation names its document version and retrieval date."""
    return {
        "schema_version": SCHEMA_VERSION,
        "status": answer.status,
        "answer": answer.text,
        "disclaimer": answer.disclaimer,
        "notes": list(answer.notes),
        "citations": [
            {
                "label": citation.label,
                "bill": citation.bill_identifier,
                "bill_url": f"/bills/{citation.bill_slug}",
                "official_document_url": citation.document_source_url,
                "document_version": citation.document_version_no,
                "our_copy_retrieved_at": citation.document_retrieved_at,
                "page_start": citation.page_start,
                "page_end": citation.page_end,
                "current_version": citation.is_current_version,
                "anchor": citation.anchor,
            }
            for citation in answer.citations
        ],
    }
