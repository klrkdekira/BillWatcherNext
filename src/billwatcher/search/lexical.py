"""Lexical bill search over the HANDOFF 12.1 split search units.

Ranking order is: exact normalized identifier, identifier prefix, weighted full-text rank,
newest relevant event date, then the normalized identifier as a deterministic tie-break.
"""

import base64
import binascii
import hashlib
import html
import time
from dataclasses import dataclass, field
from datetime import date

import structlog
from sqlalchemy import (
    ColumnElement,
    Select,
    TextClause,
    case,
    func,
    literal,
    or_,
    select,
    text,
)
from sqlalchemy.orm import Session

from billwatcher.models import Bill, BillEvent, ChamberRecord, SearchUnit
from billwatcher.scraper.normalize import normalize_text, parse_identifier_query

MAX_QUERY_CHARS = 200
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
DEEP_OFFSET = 1_000

# Control characters cannot survive HTML escaping, so highlight markers are inserted by
# PostgreSQL, escaped with the surrounding text, and only then turned into real markup.
_HL_START = "\x01hl\x01"
_HL_STOP = "\x01/hl\x01"
_HEADLINE_OPTIONS = (
    f"StartSel={_HL_START}, StopSel={_HL_STOP}, "
    "MaxFragments=2, MaxWords=22, MinWords=6, FragmentDelimiter= … "
)

_log = structlog.get_logger("billwatcher.search")


@dataclass(frozen=True, slots=True)
class Passage:
    """A bounded, already-escaped excerpt of the unit that matched."""

    html: str
    kind: str
    document_version_id: str | None = None
    page_from: int | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    bill: Bill
    rank: float
    passage: Passage | None = None


@dataclass(frozen=True, slots=True)
class SearchPage:
    items: tuple[Bill, ...]
    total: int
    page: int
    page_size: int
    hits: tuple[SearchHit, ...] = field(default_factory=tuple)
    next_cursor: str | None = None


def query_fingerprint(query: str) -> str:
    """A stable, non-reversible handle for latency logs; the raw query is never stored."""
    return hashlib.sha256(normalize_text(query).casefold().encode()).hexdigest()[:16]


def encode_cursor(year: int | None, identifier: str) -> str:
    raw = f"{year if year is not None else -1}\x1f{identifier}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[int, str]:
    padding = "=" * (-len(cursor) % 4)
    try:
        year_text, identifier = base64.urlsafe_b64decode(cursor + padding).decode().split("\x1f", 1)
        return int(year_text), identifier
    except (ValueError, UnicodeDecodeError, binascii.Error) as error:
        raise ValueError("pagination cursor is not valid") from error


def search_bills(
    session: Session,
    *,
    query: str = "",
    chamber: str | None = None,
    status: str | None = None,
    year: int | None = None,
    lang: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    include_superseded: bool = False,
    cursor: str | None = None,
) -> SearchPage:
    started = time.monotonic()
    query = normalize_text(query)
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"query must not exceed {MAX_QUERY_CHARS} characters")
    if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ValueError("invalid pagination")
    offset = (page - 1) * page_size
    if query and offset >= DEEP_OFFSET:
        raise ValueError("Ranked results stop at this depth; add filters to narrow the search.")
    if not query and offset >= DEEP_OFFSET and cursor is None:
        raise ValueError("Use the Next link to page this deeply into the index.")

    is_postgres = session.get_bind().dialect.name == "postgresql"
    identifiers = parse_identifier_query(query) if query else parse_identifier_query("")

    base = _filtered(select(Bill.id), chamber=chamber, status=status, year=year, lang=lang)
    if query:
        ordered_ids, total = _ranked_ids(
            session,
            base,
            query=query,
            exact=identifiers.exact,
            prefix=identifiers.prefix,
            include_superseded=include_superseded,
            is_postgres=is_postgres,
            offset=offset,
            page_size=page_size,
        )
        next_cursor = None
    else:
        ordered_ids, total, next_cursor = _browse_ids(
            session, base, cursor=cursor, offset=offset, page_size=page_size
        )

    found_bills = session.scalars(select(Bill).where(Bill.id.in_(ordered_ids)))
    bills = {bill.id: bill for bill in found_bills}
    items = tuple(bills[bill_id] for bill_id in ordered_ids if bill_id in bills)
    passages: dict[str, Passage] = (
        _passages(session, ordered_ids, query=query, is_postgres=is_postgres) if query else {}
    )
    hits = tuple(SearchHit(bill=bill, rank=0.0, passage=passages.get(bill.id)) for bill in items)
    _log.info(
        "search.query",
        fingerprint=query_fingerprint(query) if query else None,
        has_query=bool(query),
        result_count=total,
        returned=len(items),
        page=page,
        filters={"chamber": chamber, "status": status, "year": year, "lang": lang},
        latency_ms=round((time.monotonic() - started) * 1000, 2),
    )
    return SearchPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        hits=hits,
        next_cursor=next_cursor,
    )


def _filtered(
    statement: Select[tuple[str]],
    *,
    chamber: str | None,
    status: str | None,
    year: int | None,
    lang: str | None,
) -> Select[tuple[str]]:
    statement = statement.where(Bill.tombstoned_at.is_(None))
    if chamber is not None or status is not None:
        statement = statement.join(ChamberRecord, ChamberRecord.bill_id == Bill.id)
    if chamber:
        statement = statement.where(ChamberRecord.chamber == chamber)
    if status:
        statement = statement.where(ChamberRecord.status_normalized == status)
    if year:
        statement = statement.where(Bill.year == year)
    if lang == "bm":
        statement = statement.where(Bill.title_bm.is_not(None))
    elif lang == "en":
        statement = statement.where(Bill.title_en.is_not(None))
    return statement


def _newest_event() -> ColumnElement[date | None]:
    return (
        select(func.max(BillEvent.event_on))
        .where(BillEvent.bill_id == Bill.id)
        .correlate(Bill)
        .scalar_subquery()
    )


def _ranked_ids(
    session: Session,
    base: Select[tuple[str]],
    *,
    query: str,
    exact: str | None,
    prefix: str | None,
    include_superseded: bool,
    is_postgres: bool,
    offset: int,
    page_size: int,
) -> tuple[list[str], int]:
    statement = base.join(SearchUnit, SearchUnit.bill_id == Bill.id)
    if not include_superseded:
        statement = statement.where(SearchUnit.is_current.is_(True))

    identifier_match = []
    if exact:
        identifier_match.append(Bill.identifier_normalized == exact)
    if prefix:
        identifier_match.append(Bill.identifier_normalized.startswith(prefix))

    matches: ColumnElement[bool] | TextClause
    rank: ColumnElement[float]
    if is_postgres:
        matches = text(
            "search_units.tsv @@ websearch_to_tsquery('simple', :search_query)"
        ).bindparams(search_query=query)
        rank = func.max(
            func.ts_rank_cd(
                text("search_units.tsv"),
                func.websearch_to_tsquery("simple", query),
            )
        )
    else:
        # SQLite backs the offline suite; substring matching plus unit counting keeps the
        # same ordering contract without a full-text engine.
        matches = func.lower(SearchUnit.content).like(f"%{query.casefold()}%")
        primary = func.lower(func.coalesce(SearchUnit.content_a, "")).like(f"%{query.casefold()}%")
        matches = or_(matches, primary)
        rank = func.count(SearchUnit.id) * 1.0  # type: ignore[assignment]

    statement = statement.where(or_(matches, *identifier_match))
    # Build only the branches that apply; an unmatchable placeholder value is not portable.
    branches: list[tuple[ColumnElement[bool], int]] = []
    if exact:
        branches.append((Bill.identifier_normalized == exact, 0))
    if prefix:
        branches.append((Bill.identifier_normalized.startswith(prefix), 1))
    tier: ColumnElement[int] = case(*branches, else_=2) if branches else literal(2)
    grouped = (
        statement.add_columns(
            tier.label("tier"),
            rank.label("rank"),
            _newest_event().label("newest_event"),
            Bill.identifier_normalized.label("identifier"),
        )
        .group_by(Bill.id, Bill.identifier_normalized)
        .order_by(
            text("tier"),
            text("rank DESC"),
            text("newest_event DESC NULLS LAST")
            if is_postgres
            else text("newest_event IS NULL, newest_event DESC"),
            text("identifier"),
        )
    )
    total = int(session.scalar(select(func.count()).select_from(grouped.subquery())) or 0)
    rows = session.execute(grouped.offset(offset).limit(page_size)).all()
    return [str(row[0]) for row in rows], total


def _browse_ids(
    session: Session,
    base: Select[tuple[str]],
    *,
    cursor: str | None,
    offset: int,
    page_size: int,
) -> tuple[list[str], int, str | None]:
    total = int(session.scalar(select(func.count()).select_from(base.distinct().subquery())) or 0)
    sort_year = func.coalesce(Bill.year, -1)
    statement = base.add_columns(
        sort_year.label("sort_year"), Bill.identifier_normalized
    ).distinct()
    if cursor:
        cursor_year, cursor_identifier = decode_cursor(cursor)
        statement = statement.where(
            or_(
                sort_year < cursor_year,
                (sort_year == cursor_year) & (Bill.identifier_normalized > cursor_identifier),
            )
        )
    else:
        statement = statement.offset(offset)
    rows = session.execute(
        statement.order_by(sort_year.desc(), Bill.identifier_normalized).limit(page_size)
    ).all()
    next_cursor = (
        encode_cursor(int(rows[-1][1]), str(rows[-1][2])) if len(rows) == page_size else None
    )
    return [str(row[0]) for row in rows], total, next_cursor


def _passages(
    session: Session,
    bill_ids: list[str],
    *,
    query: str,
    is_postgres: bool,
) -> dict[str, Passage]:
    """Build one bounded excerpt per rendered result, never for the whole result set."""
    if not bill_ids:
        return {}
    if is_postgres:
        rows = session.execute(
            text(
                "SELECT DISTINCT ON (bill_id) bill_id, unit_kind, document_version_id, page_from,"
                " ts_headline('simple', coalesce(content_a, '') || E'\\n' || content,"
                "   websearch_to_tsquery('simple', :q), :opts) AS snippet"
                " FROM search_units"
                " WHERE bill_id = ANY(:ids) AND is_current"
                "   AND tsv @@ websearch_to_tsquery('simple', :q)"
                " ORDER BY bill_id,"
                "   ts_rank_cd(tsv, websearch_to_tsquery('simple', :q)) DESC"
            ).bindparams(q=query, opts=_HEADLINE_OPTIONS, ids=bill_ids)
        ).all()
        return {
            str(row.bill_id): Passage(
                html=_render_highlights(str(row.snippet)),
                kind="document" if row.unit_kind == "document_text" else "metadata",
                document_version_id=row.document_version_id,
                page_from=row.page_from,
            )
            for row in rows
        }

    needle = query.casefold()
    found: dict[str, Passage] = {}
    units = session.scalars(
        select(SearchUnit)
        .where(SearchUnit.bill_id.in_(bill_ids), SearchUnit.is_current.is_(True))
        .order_by(SearchUnit.unit_kind, SearchUnit.page_from)
    )
    for unit in units:
        if unit.bill_id in found:
            continue
        haystack = f"{unit.content_a or ''}\n{unit.content}"
        position = haystack.casefold().find(needle)
        if position < 0:
            continue
        start = max(0, position - 60)
        excerpt = haystack[start : position + len(needle) + 120]
        marked = (
            excerpt[: position - start]
            + _HL_START
            + excerpt[position - start : position - start + len(needle)]
            + _HL_STOP
            + excerpt[position - start + len(needle) :]
        )
        found[unit.bill_id] = Passage(
            html=_render_highlights(marked),
            kind="document" if unit.unit_kind == "document_text" else "metadata",
            document_version_id=unit.document_version_id,
            page_from=unit.page_from,
        )
    return found


def _render_highlights(snippet: str) -> str:
    """Escape database text first, then turn the sentinels into the only allowed markup."""
    escaped = html.escape(snippet, quote=False)
    escaped = escaped.replace(html.escape(_HL_START, quote=False), "<mark>")
    escaped = escaped.replace(html.escape(_HL_STOP, quote=False), "</mark>")
    return escaped.replace("\x01", "")
