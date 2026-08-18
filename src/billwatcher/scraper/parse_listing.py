import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

from billwatcher.scraper.normalize import (
    DateRange,
    Identifier,
    normalize_identifier,
    normalize_status,
    normalize_text,
    parse_dates,
)


@dataclass(frozen=True, slots=True)
class ParsedDateCell:
    """One dated listing column for one bill.

    A cell may hold a range (`13-14 Julai 2026`) or several dates; both are preserved rather
    than collapsed, because HANDOFF 11.5 requires an end date and a sequence. An unparseable
    cell keeps its raw text and reports an error instead of silently becoming NULL.
    """

    event_type: str
    label: str
    raw: str
    ranges: tuple[DateRange, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ParseIssue:
    """A row that could not be turned into a record, retained so it is never silently dropped."""

    row_number: int
    reason: str
    raw_identifier: str
    raw_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParsedListingBill:
    identifier: Identifier
    title: str
    status_raw: str
    status_normalized: str
    year: int | None
    presenter: str | None
    document_urls: tuple[str, ...]
    dates: tuple[ParsedDateCell, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedListing:
    records: tuple[ParsedListingBill, ...]
    headers: tuple[str, ...]
    structure_fingerprint: str
    issues: tuple[ParseIssue, ...] = ()


class ListingParseError(ValueError):
    pass


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_cell = False
        self.in_row = False
        self.cell_parts: list[str] = []
        self.row: list[tuple[str, list[str]]] = []
        self.rows: list[list[tuple[str, list[str]]]] = []
        self.cell_links: list[str] = []
        self.current_tag = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.in_row = True
            self.row = []
        elif self.in_row and tag in {"th", "td"}:
            self.in_cell = True
            self.current_tag = tag
            self.cell_parts = []
            self.cell_links = []
        elif self.in_cell and tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.cell_links.append(href)

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.in_cell and tag == self.current_tag:
            self.row.append((normalize_text("".join(self.cell_parts)), self.cell_links.copy()))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.row:
                self.rows.append(self.row)
            self.in_row = False


_LABELS = {
    "kod": "identifier",
    "code": "identifier",
    "tahun": "year",
    "year": "year",
    "tajuk": "title",
    "title": "title",
    "status": "status",
    "pembentang": "presenter",
    "presenter": "presenter",
}

# Dated columns are matched semantically, never by position, and each projects onto one event
# type (HANDOFF 11.3 step 6). Provisional until the bilingual label sweep (assumption A2).
_DATE_LABELS = {
    "bacaan kali pertama": "first_reading",
    "bacaan pertama": "first_reading",
    "first reading": "first_reading",
    "bacaan kali kedua": "second_reading",
    "bacaan kedua": "second_reading",
    "second reading": "second_reading",
    "bacaan kali ketiga": "third_reading",
    "bacaan ketiga": "third_reading",
    "third reading": "third_reading",
    "dirujuk kepada jawatankuasa": "committee_referral",
    "rujukan jawatankuasa": "committee_referral",
    "committee referral": "committee_referral",
    "referred to committee": "committee_referral",
    "tarikh diluluskan": "passed",
    "diluluskan pada": "passed",
    "date passed": "passed",
    "passed on": "passed",
}


def _semantic(label: str) -> str:
    folded = label.casefold()
    if folded in _LABELS:
        return _LABELS[folded]
    if folded in _DATE_LABELS:
        return f"date:{_DATE_LABELS[folded]}"
    return ""


def parse_listing(html: str, *, source_url: str) -> ParsedListing:
    parser = _TableParser()
    parser.feed(html)
    if not parser.rows:
        raise ListingParseError("no table rows found")

    header_row = parser.rows[0]
    headers = tuple(cell[0] for cell in header_row)
    normalized_headers = tuple(_semantic(value) for value in headers)
    required = {"identifier", "title", "status"}
    if not required <= set(normalized_headers):
        raise ListingParseError(f"required semantic columns missing: {headers!r}")
    structure = "|".join(value.casefold() for value in headers).encode()
    fingerprint = hashlib.sha256(structure).hexdigest()

    records: list[ParsedListingBill] = []
    issues: list[ParseIssue] = []
    by_identifier: dict[str, ParsedListingBill] = {}
    for row_no, row in enumerate(parser.rows[1:], start=2):
        if not any(cell[0] for cell in row):
            continue
        if len(row) != len(headers):
            raise ListingParseError(f"row {row_no} has {len(row)} cells; expected {len(headers)}")
        values = {
            semantic: row[index] for index, semantic in enumerate(normalized_headers) if semantic
        }
        raw_values = tuple(cell[0] for cell in row)
        raw_identifier = values["identifier"][0]
        try:
            identifier = normalize_identifier(raw_identifier)
        except ValueError as error:
            # HANDOFF 11.3 step 7: keep the raw row and report it; never drop it, and never
            # discard the rest of a page because one code is malformed.
            issues.append(
                ParseIssue(
                    row_number=row_no,
                    reason=str(error),
                    raw_identifier=raw_identifier,
                    raw_values=raw_values,
                )
            )
            continue
        title = values["title"][0]
        status_raw = values["status"][0]
        if not title or not status_raw:
            issues.append(
                ParseIssue(
                    row_number=row_no,
                    reason="row is missing a required title or status value",
                    raw_identifier=raw_identifier,
                    raw_values=raw_values,
                )
            )
            continue
        year_text = values.get("year", ("", []))[0]
        if year_text and (not year_text.isdigit() or len(year_text) != 4):
            issues.append(
                ParseIssue(
                    row_number=row_no,
                    reason=f"invalid year: {year_text!r}",
                    raw_identifier=raw_identifier,
                    raw_values=raw_values,
                )
            )
            continue
        links = tuple(
            urljoin(source_url, link)
            for _value, cell_links in row
            for link in cell_links
            if link.lower().split("?", 1)[0].endswith(".pdf")
        )
        record = ParsedListingBill(
            identifier=identifier,
            title=title,
            status_raw=status_raw,
            status_normalized=normalize_status(status_raw),
            year=int(year_text) if year_text else None,
            presenter=values.get("presenter", ("", []))[0] or None,
            document_urls=links,
            dates=_date_cells(headers, normalized_headers, row),
        )

        existing = by_identifier.get(identifier.normalized)
        if existing is None:
            by_identifier[identifier.normalized] = record
            records.append(record)
            continue
        if existing.title == record.title and existing.status_raw == record.status_raw:
            # A benign repeat of the same row; collapse it rather than inventing a second bill.
            continue
        issues.append(
            ParseIssue(
                row_number=row_no,
                reason=(
                    f"duplicate identifier {identifier.normalized} with a conflicting title: "
                    f"{existing.title!r} then {record.title!r}"
                ),
                raw_identifier=raw_identifier,
                raw_values=raw_values,
            )
        )

    if not records:
        raise ListingParseError("validated listing yielded zero records")
    return ParsedListing(tuple(records), headers, fingerprint, tuple(issues))


def _date_cells(
    headers: tuple[str, ...],
    normalized_headers: tuple[str, ...],
    row: list[tuple[str, list[str]]],
) -> tuple[ParsedDateCell, ...]:
    """Parse every dated column, keeping ranges, multiple dates, and unparseable raw text."""
    cells: list[ParsedDateCell] = []
    for index, semantic in enumerate(normalized_headers):
        if not semantic.startswith("date:"):
            continue
        raw = row[index][0]
        if not raw:
            continue
        event_type = semantic.removeprefix("date:")
        try:
            ranges = tuple(parse_dates(raw))
        except ValueError as error:
            cells.append(
                ParsedDateCell(
                    event_type=event_type, label=headers[index], raw=raw, error=str(error)
                )
            )
            continue
        cells.append(
            ParsedDateCell(event_type=event_type, label=headers[index], raw=raw, ranges=ranges)
        )
    return tuple(cells)
