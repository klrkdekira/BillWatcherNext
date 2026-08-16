from dataclasses import dataclass

from sqlalchemy import Select, case, func, or_, select, text
from sqlalchemy.orm import Session

from billwatcher.models import Bill, ChamberRecord, SearchUnit
from billwatcher.scraper.normalize import normalize_identifier


@dataclass(frozen=True, slots=True)
class SearchPage:
    items: tuple[Bill, ...]
    total: int
    page: int
    page_size: int


def search_bills(
    session: Session,
    *,
    query: str = "",
    chamber: str | None = None,
    status: str | None = None,
    year: int | None = None,
    page: int = 1,
    page_size: int = 20,
    include_superseded: bool = False,
) -> SearchPage:
    query = query.strip()
    if len(query) > 200:
        raise ValueError("query must not exceed 200 characters")
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValueError("invalid pagination")

    statement: Select[tuple[Bill]] = select(Bill)
    needs_chamber = chamber is not None or status is not None
    if needs_chamber:
        statement = statement.join(ChamberRecord, ChamberRecord.bill_id == Bill.id)
    if chamber:
        statement = statement.where(ChamberRecord.chamber == chamber)
    if status:
        statement = statement.where(ChamberRecord.status_normalized == status)
    if year:
        statement = statement.where(Bill.year == year)

    exact = None
    if query:
        try:
            exact = normalize_identifier(query).normalized
        except ValueError:
            exact = None
        statement = statement.join(SearchUnit, SearchUnit.bill_id == Bill.id)
        if not include_superseded:
            statement = statement.where(SearchUnit.is_current.is_(True))
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.where(
                text(
                    "search_units.tsv @@ websearch_to_tsquery('simple', :search_query)"
                ).bindparams(search_query=query)
            )
        else:
            pattern = f"%{query.casefold()}%"
            condition = or_(func.lower(SearchUnit.content).like(pattern))
            if exact:
                condition = or_(condition, Bill.identifier_normalized == exact)
            statement = statement.where(condition)

    statement = statement.distinct()
    count_statement = select(func.count()).select_from(statement.subquery())
    total = int(session.scalar(count_statement) or 0)
    if exact:
        statement = statement.order_by(
            case((Bill.identifier_normalized == exact, 0), else_=1),
            Bill.year.desc(),
            Bill.identifier_normalized,
        )
    else:
        statement = statement.order_by(Bill.year.desc().nullslast(), Bill.identifier_normalized)
    statement = statement.offset((page - 1) * page_size).limit(page_size)
    return SearchPage(tuple(session.scalars(statement).all()), total, page, page_size)
