import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import quote, urljoin

from billwatcher.download.normalize import (
    DateRange,
    Identifier,
    normalize_identifier,
    normalize_status,
    normalize_text,
    parse_dates,
    same_title,
)

# Document links are carried in an inline script call, not an href.
_LOAD_RESULT = re.compile(r"loadResult\(\s*'([^']+)'")


@dataclass(frozen=True, slots=True)
class Cell:
    """One table cell: its text, any links it carries, and any nested detail pairs."""

    text: str
    links: tuple[str, ...] = ()
    detail: tuple[tuple[str, str], ...] = ()


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
    # Which language the page turned out to be written in, read from its own labels rather than
    # from the request that asked for it — `None` when the labels do not settle it. See
    # `observed_language` for why a crawl cannot take the request's word for it.
    observed_language: str | None = None


class ListingParseError(ValueError):
    pass


class _TableParser(HTMLParser):
    """Collect the outer listing rows, and the detail table nested inside each status cell.

    The live listing puts an expanded per-bill detail table inside a hidden div in the status
    cell. Without nesting awareness those inner rows flatten into the outer table and every row
    looks malformed, so table depth is tracked explicitly and only depth 1 builds listing rows.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.in_cell = False
        self.in_row = False
        self.cell_parts: list[str] = []
        self.row: list[Cell] = []
        self.rows: list[list[Cell]] = []
        self.cell_links: list[str] = []
        self.current_tag = ""
        # Detail state, accumulated while inside a nested table within the current outer cell.
        self.detail_rows: list[list[str]] = []
        self.detail_row: list[str] = []
        self.detail_parts: list[str] = []
        self.in_detail_cell = False
        # Depth of nested elements inside a hidden detail box. Its text is the expanded detail,
        # not the cell's visible value, so it must not leak into the status or title.
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self.hidden_depth:
            if tag == "div":
                self.hidden_depth += 1
        elif tag == "div" and _is_hidden(attributes):
            self.hidden_depth = 1
        if tag == "table":
            self.depth += 1
            return
        if self.depth > 1:
            if tag == "tr":
                self.detail_row = []
            elif tag in {"td", "th"}:
                self.in_detail_cell = True
                self.detail_parts = []
            return
        if tag == "tr":
            self.in_row = True
            self.row = []
        elif self.in_row and tag in {"th", "td"}:
            self.in_cell = True
            self.current_tag = tag
            self.cell_parts = []
            self.cell_links = []
            self.detail_rows = []
        elif self.in_cell and tag == "a":
            href = attributes.get("href")
            if href and href not in {"#"}:
                self.cell_links.append(href)
            # Documents are opened through a script call rather than a plain link.
            for target in _LOAD_RESULT.findall(attributes.get("onclick") or ""):
                self.cell_links.append(target)

    def handle_data(self, data: str) -> None:
        if self.depth > 1:
            if self.in_detail_cell:
                self.detail_parts.append(data)
            return
        if self.in_cell and not self.hidden_depth:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.hidden_depth:
            self.hidden_depth -= 1
            return
        if tag == "table":
            self.depth = max(0, self.depth - 1)
            return
        if self.depth > 1:
            if tag in {"td", "th"} and self.in_detail_cell:
                self.detail_row.append(normalize_text("".join(self.detail_parts)))
                self.in_detail_cell = False
            elif tag == "tr" and self.detail_row:
                self.detail_rows.append(self.detail_row)
                self.detail_row = []
            return
        if self.in_cell and tag == self.current_tag:
            self.row.append(
                Cell(
                    text=normalize_text("".join(self.cell_parts)),
                    links=tuple(self.cell_links),
                    detail=tuple(_detail_pairs(self.detail_rows)),
                )
            )
            self.in_cell = False
            self.detail_rows = []
        elif tag == "tr" and self.in_row:
            if self.row:
                self.rows.append(self.row)
            self.in_row = False


def _is_hidden(attributes: dict[str, str | None]) -> bool:
    """A detail box the page only reveals on demand; its text is not the cell's value."""
    classes = (attributes.get("class") or "").casefold().split()
    if "alertbox" in classes:
        return True
    style = (attributes.get("style") or "").casefold().replace(" ", "")
    return "display:none" in style


def _detail_pairs(rows: list[list[str]]) -> list[tuple[str, str]]:
    """Reduce `Label : Value` detail rows to pairs, dropping the separator cell."""
    pairs: list[tuple[str, str]] = []
    for row in rows:
        cells = [cell for cell in row if cell and cell != ":"]
        if len(cells) >= 2:
            pairs.append((cells[0], " ".join(cells[1:])))
    return pairs


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
# type (HANDOFF 11.3 step 6). The live site publishes no dated *columns* at all — its readings live
# in the detail box below — so none of these has ever been observed. They are kept because a column
# is the shape the handoff expected and a redesign could produce one; the labels that matter in
# practice are in `_DETAIL_DATE_LABELS`.
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
    headers = tuple(cell.text for cell in header_row)
    normalized_headers = tuple(_semantic(value) for value in headers)
    required = {"identifier", "title", "status"}
    if not required <= set(normalized_headers):
        raise ListingParseError(f"required semantic columns missing: {headers!r}")
    structure = "|".join(value.casefold() for value in headers).encode()
    fingerprint = hashlib.sha256(structure).hexdigest()

    records: list[ParsedListingBill] = []
    issues: list[ParseIssue] = []
    detail_labels: list[list[str]] = []
    by_identifier: dict[str, ParsedListingBill] = {}
    for row_no, row in enumerate(parser.rows[1:], start=2):
        if not any(cell.text for cell in row):
            continue
        if len(row) != len(headers):
            raise ListingParseError(f"row {row_no} has {len(row)} cells; expected {len(headers)}")
        values = {
            semantic: row[index] for index, semantic in enumerate(normalized_headers) if semantic
        }
        raw_values = tuple(cell.text for cell in row)
        raw_identifier = values["identifier"].text
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
        title = values["title"].text
        status_raw = values["status"].text
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
        year_text = _text_of(values.get("year"))
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
            absolute_document_url(source_url, link)
            for cell in row
            for link in cell.links
            if link.lower().split("?", 1)[0].endswith(".pdf")
        )
        # The expanded detail carries the dates and the presenter on the live listing.
        detail = tuple(pair for cell in row for pair in cell.detail)
        detail_labels.append([label for label, _value in detail])
        presenter = _presenter_from(detail) or _text_of(values.get("presenter")) or None
        record = ParsedListingBill(
            identifier=identifier,
            title=title,
            status_raw=status_raw,
            status_normalized=normalize_status(status_raw),
            year=int(year_text) if year_text else None,
            presenter=presenter,
            document_urls=links,
            dates=_date_cells(headers, normalized_headers, row) + _detail_dates(detail),
        )

        existing = by_identifier.get(identifier.normalized)
        if existing is None:
            by_identifier[identifier.normalized] = record
            records.append(record)
            continue
        if same_title(existing.title, record.title) and existing.status_raw == record.status_raw:
            # A benign repeat of the same row; collapse it rather than inventing a second bill.
            # Titles are compared as titles, not as strings: the site publishes `RUU X` and
            # `Rang Undang-Undang X` for one bill, and that is not a conflict.
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
    # Both the column headers and the detail labels are read: a page can only be judged by the words
    # it actually publishes, and the four headers alone settle it for a listing that has rows.
    labels = list(headers) + [label for _row_labels in detail_labels for label in _row_labels]
    return ParsedListing(
        tuple(records),
        headers,
        fingerprint,
        tuple(issues),
        observed_language=observed_language(labels),
    )


def _date_cells(
    headers: tuple[str, ...],
    normalized_headers: tuple[str, ...],
    row: list[Cell],
) -> tuple[ParsedDateCell, ...]:
    """Parse every dated column, keeping ranges, multiple dates, and unparseable raw text."""
    cells: list[ParsedDateCell] = []
    for index, semantic in enumerate(normalized_headers):
        if not semantic.startswith("date:"):
            continue
        raw = row[index].text
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


# Labels observed inside the expanded per-bill detail on the live listing (docs/upstream.md).
# Observed in the hidden detail box of both current listings and in the archive tree, in both
# languages (docs/upstream.md, 2026-08-18). The English page writes "The second reading" and
# "Passed At"; without those two entries an English crawl parses every row and silently keeps
# no dates at all.
_DETAIL_DATE_LABELS = {
    "bacaan pertama pada": "first_reading",
    "bacaan kedua pada": "second_reading",
    "bacaan ketiga pada": "third_reading",
    "diluluskan pada": "passed",
    "dirujuk jkpk pada": "committee_referral",
    "dirujuk ke jkpk pada": "committee_referral",
    "first reading": "first_reading",
    "the second reading": "second_reading",
    "the third reading": "third_reading",
    "passed at": "passed",
}
_PRESENTER_LABELS = {"dibentang oleh", "presented by"}

# The labels that are only ever written one way in one language, folded and stripped of the trailing
# colon the detail rows carry. `Status` is in neither set: the site spells it identically in both.
_LANGUAGE_MARKERS: dict[str, frozenset[str]] = {
    "ms": frozenset(
        {
            "kod",
            "tahun",
            "tajuk",
            "pembentang",
            "bacaan pertama pada",
            "bacaan kedua pada",
            "bacaan ketiga pada",
            "diluluskan pada",
            "dirujuk jkpk pada",
            "dirujuk ke jkpk pada",
            "dibentang oleh",
        }
    ),
    "en": frozenset(
        {
            "code",
            "year",
            "title",
            "presenter",
            "first reading",
            "the second reading",
            "the third reading",
            "passed at",
            "presented by",
        }
    ),
}


def observed_language(labels: Iterable[str]) -> str | None:
    """Which language a page is actually written in, or `None` when its labels do not say.

    A crawl cannot take `lang=en` at its word. The site's language follows the session that serves
    the request — the first visit sets `GENPRO_SESSION` and a `language` cookie, and a cookieless
    request to the archive search is answered with a redirect to the *current* Malay listing
    (`documentation/upstream.md`, 2026-08-18). So an English request can be answered with a Malay
    page that parses perfectly, and the only thing that distinguishes them is the labels.

    Getting this wrong is not cosmetic: the language of a listing decides which `titles.raw_*` key a
    title lands under and which language is recorded for the documents it names, and that language
    becomes a permanent component of the Expression IRI (ADR-024). Reading it back off the page is
    what lets `parse_listings` refuse a mismatch instead of minting a wrong identifier.

    `None` is a real answer, not a failure: an archived year whose bills never passed carries no
    detail rows at all, so there is nothing in it that is written in either language.
    """
    folded = {label.casefold().rstrip(":").strip() for label in labels}
    scores = {language: len(folded & markers) for language, markers in _LANGUAGE_MARKERS.items()}
    best = max(scores.values())
    if best == 0:
        return None
    winners = [language for language, score in scores.items() if score == best]
    # A page that scores equally in both is not evidence for either — a mixed page is exactly the
    # kind of thing that should reach an operator rather than be resolved by a coin toss.
    return winners[0] if len(winners) == 1 else None


def _text_of(cell: Cell | None) -> str:
    return cell.text if cell is not None else ""


def absolute_document_url(source_url: str, link: str) -> str:
    """Resolve a listing link, percent-encoding the spaces real document paths contain.

    Shared with the archive tree parser, which reaches documents through the same
    `loadResult('<path>')` call with the same unencoded spaces.
    """
    return urljoin(source_url, quote(link, safe="/:?=&%#"))


def _presenter_from(detail: tuple[tuple[str, str], ...]) -> str | None:
    for label, value in detail:
        if label.casefold().rstrip(":") in _PRESENTER_LABELS and value:
            return value
    return None


def _detail_dates(detail: tuple[tuple[str, str], ...]) -> tuple[ParsedDateCell, ...]:
    """Read the dated rows out of the expanded detail table."""
    cells: list[ParsedDateCell] = []
    for label, value in detail:
        event_type = _DETAIL_DATE_LABELS.get(label.casefold().rstrip(":"))
        if event_type is None or not value:
            continue
        try:
            ranges = tuple(parse_dates(value))
        except ValueError as error:
            cells.append(
                ParsedDateCell(event_type=event_type, label=label, raw=value, error=str(error))
            )
            continue
        if ranges:
            cells.append(
                ParsedDateCell(event_type=event_type, label=label, raw=value, ranges=ranges)
            )
    return tuple(cells)
