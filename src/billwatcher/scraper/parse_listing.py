import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

from billwatcher.scraper.normalize import (
    Identifier,
    normalize_identifier,
    normalize_status,
    normalize_text,
)


@dataclass(frozen=True, slots=True)
class ParsedListingBill:
    identifier: Identifier
    title: str
    status_raw: str
    status_normalized: str
    year: int | None
    presenter: str | None
    document_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParsedListing:
    records: tuple[ParsedListingBill, ...]
    headers: tuple[str, ...]
    structure_fingerprint: str


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


def parse_listing(html: str, *, source_url: str) -> ParsedListing:
    parser = _TableParser()
    parser.feed(html)
    if not parser.rows:
        raise ListingParseError("no table rows found")

    header_row = parser.rows[0]
    headers = tuple(cell[0] for cell in header_row)
    normalized_headers = tuple(_LABELS.get(value.casefold(), "") for value in headers)
    required = {"identifier", "title", "status"}
    if not required <= set(normalized_headers):
        raise ListingParseError(f"required semantic columns missing: {headers!r}")
    structure = "|".join(value.casefold() for value in headers).encode()
    fingerprint = hashlib.sha256(structure).hexdigest()

    records: list[ParsedListingBill] = []
    seen: set[str] = set()
    for row_no, row in enumerate(parser.rows[1:], start=2):
        if not any(cell[0] for cell in row):
            continue
        if len(row) != len(headers):
            raise ListingParseError(f"row {row_no} has {len(row)} cells; expected {len(headers)}")
        values = {
            semantic: row[index] for index, semantic in enumerate(normalized_headers) if semantic
        }
        try:
            identifier = normalize_identifier(values["identifier"][0])
        except ValueError as error:
            raise ListingParseError(f"row {row_no}: {error}") from error
        if identifier.normalized in seen:
            raise ListingParseError(f"duplicate identifier in listing: {identifier.normalized}")
        seen.add(identifier.normalized)
        title = values["title"][0]
        status_raw = values["status"][0]
        if not title or not status_raw:
            raise ListingParseError(f"row {row_no} has an empty required value")
        year_text = values.get("year", ("", []))[0]
        if year_text and (not year_text.isdigit() or len(year_text) != 4):
            raise ListingParseError(f"row {row_no} has invalid year: {year_text!r}")
        links = tuple(
            urljoin(source_url, link)
            for _value, cell_links in row
            for link in cell_links
            if link.lower().split("?", 1)[0].endswith(".pdf")
        )
        records.append(
            ParsedListingBill(
                identifier=identifier,
                title=title,
                status_raw=status_raw,
                status_normalized=normalize_status(status_raw),
                year=int(year_text) if year_text else None,
                presenter=values.get("presenter", ("", []))[0] or None,
                document_urls=links,
            )
        )
    if not records:
        raise ListingParseError("validated listing yielded zero records")
    return ParsedListing(tuple(records), headers, fingerprint)
