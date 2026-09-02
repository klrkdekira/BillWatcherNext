"""Parse the archive tree Parliament serves behind `arkib=yes`.

The archive is not a paginated HTML listing, and it is not the `carian.html` search form either
— that form is a full-text search over document *pages* and carries no bill metadata at all.
`?arkib=yes` renders a `dhtmlXTree` whose XML is fetched separately:

* `&arkib=yes&ajx=0` returns one node per archived year.
* `&arkib=yes&ajx=1&id=0_<year>` returns that year's bills.

See `docs/upstream.md` for the observed bytes and ADR-014 for the decision this replaced.

Each year's XML is reduced to the same `ParsedListing` the HTML listing parser produces, so
ingestion, change tracking, event projection, and document queueing are shared rather than
reimplemented for a second shape. The grammar of one bill node, observed across all 67 stored
year documents (1990-2024, both chambers):

    <item text='D.R.17/2024 - RUU ... (Pindaan) 2024 (Lulus) '>
      <item text='D.R.17/2024' im0='book_titel.gif'>
        <userdata name='myurl'>javascript:loadResult('/files/.../DR 17 BM.pdf','...')</userdata>
      </item>
      <item text='Bacaan Pertama Pada:02/07/2024'/>
      <item text='Dibentang Oleh:YB ...'/>
    </item>

A bill that never passed carries no children at all: no dates, no presenter, and no document.
"""

import hashlib
import html
import re
from dataclasses import dataclass
from xml.etree import ElementTree

from billwatcher.download.normalize import (
    normalize_identifier,
    normalize_status,
    normalize_text,
    parse_dates,
    same_title,
)
from billwatcher.download.parse_listing import (
    ListingParseError,
    ParsedDateCell,
    ParsedListing,
    ParsedListingBill,
    ParseIssue,
    absolute_document_url,
    observed_language,
    parse_listing,
)

# `{identifier} - {title} ({status})`. The status is the last parenthesised group and may not
# itself contain parentheses; titles routinely do (`RUU Kerja (Pindaan) 2011`), which is why the
# expression is anchored at the end rather than reading left to right.
_ITEM_TEXT = re.compile(
    r"^\s*(?P<identifier>.*?)\s+-\s+(?P<title>.*?)\s*\((?P<status>[^()]*)\)\s*$"
)
_LOAD_RESULT = re.compile(r"loadResult\(\s*'([^']+)'")
_YEAR = re.compile(r"^\s*(\d{4})\s*$")

# The detail labels observed across every stored archive document and both current listings, in
# both languages. A label outside this set changes the structure fingerprint, so it withholds
# publication instead of silently dropping a date (HANDOFF 11.6).
ARCHIVE_DATE_LABELS = {
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
ARCHIVE_PRESENTER_LABELS = frozenset({"dibentang oleh", "presented by"})

# A year index this long means the page changed shape, not that Parliament gained centuries.
MAX_ARCHIVE_YEARS = 200


class ArchiveParseError(ListingParseError):
    """The archive XML was not the tree we understand. Subclasses the listing error so the
    orchestrator's existing degrade-one-target path applies unchanged."""


@dataclass(frozen=True, slots=True)
class ParsedArchiveIndex:
    """The years the archive offers, newest first as the site orders them."""

    years: tuple[int, ...]
    structure_fingerprint: str


def _tree_root(xml: str) -> ElementTree.Element:
    """Parse the tree document, refusing any doctype.

    `xml.etree` does not fetch external entities, but it does expand internal ones, which is a
    denial-of-service vector on untrusted bytes. No observed response carries a doctype, so
    refusing one costs nothing and removes the entity-expansion question entirely.
    """
    if re.search(r"<!(DOCTYPE|ENTITY)", xml, re.I):
        raise ArchiveParseError("archive XML declares a doctype; refusing to expand entities")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise ArchiveParseError(f"archive XML is not well formed: {error}") from error
    if root.tag != "tree":
        raise ArchiveParseError(f"archive XML root is {root.tag!r}, expected 'tree'")
    return root


def parse_archive_index(xml: str, *, source_url: str) -> ParsedArchiveIndex:
    """Read the year nodes out of the `ajx=0` tree.

    `source_url` is unused for resolution — the index carries no links — but is part of the
    signature so callers cannot forget which document they parsed.
    """
    del source_url
    root = _tree_root(xml)
    years: list[int] = []
    unexpected: list[str] = []
    for item in root.findall("item"):
        text = normalize_text(item.get("text") or "")
        match = _YEAR.match(text)
        if match is None:
            unexpected.append(text[:60])
            continue
        year = int(match.group(1))
        if year not in years:
            years.append(year)
    if not years:
        raise ArchiveParseError("archive index carried no year nodes")
    if len(years) > MAX_ARCHIVE_YEARS:
        raise ArchiveParseError(f"archive index carried {len(years)} year nodes; refusing")
    structure = ("archive-index-v1|" + "|".join(sorted(unexpected))).encode()
    return ParsedArchiveIndex(tuple(years), hashlib.sha256(structure).hexdigest())


def parse_archive_year(xml: str, *, source_url: str) -> ParsedListing:
    """Reduce one year of the archive tree to the listing shape the rest of the pipeline eats."""
    root = _tree_root(xml)
    items = root.findall("item")
    if not items:
        raise ArchiveParseError("archive year carried no bill nodes")

    records: list[ParsedListingBill] = []
    issues: list[ParseIssue] = []
    unknown_labels: set[str] = set()
    detail_labels: list[str] = []
    by_identifier: dict[str, ParsedListingBill] = {}

    for row_no, item in enumerate(items, start=1):
        raw_text = normalize_text(item.get("text") or "")
        match = _ITEM_TEXT.match(raw_text)
        if match is None:
            issues.append(
                ParseIssue(
                    row_number=row_no,
                    reason="archive node text is not 'identifier - title (status)'",
                    raw_identifier="",
                    raw_values=(raw_text[:200],),
                )
            )
            continue
        raw_identifier = match.group("identifier").strip()
        title = _unescape(match.group("title"))
        status_raw = _unescape(match.group("status"))
        try:
            identifier = normalize_identifier(raw_identifier)
        except ValueError as error:
            # HANDOFF 11.3 step 7: the row is retained and reported, never dropped, and one bad
            # code never costs the rest of the year.
            issues.append(
                ParseIssue(
                    row_number=row_no,
                    reason=str(error),
                    raw_identifier=raw_identifier,
                    raw_values=(raw_text[:200],),
                )
            )
            continue
        if not title or not status_raw:
            issues.append(
                ParseIssue(
                    row_number=row_no,
                    reason="archive node is missing a required title or status value",
                    raw_identifier=raw_identifier,
                    raw_values=(raw_text[:200],),
                )
            )
            continue

        detail, documents, node_unknown = _read_children(item, source_url=source_url)
        unknown_labels |= node_unknown
        detail_labels.extend(label for label, _value in detail)
        record = ParsedListingBill(
            identifier=identifier,
            title=title,
            status_raw=status_raw,
            status_normalized=normalize_status(status_raw),
            # The tree groups a bill under the year the chamber considered it, which is not
            # always the year in its code: ten 2010 bills sit under the Dewan Negara's 2011
            # node. The bill's own year is the identifier's, and the node year is the crawl
            # scope, recorded on the coverage target instead.
            year=identifier.year,
            presenter=_presenter_from(detail),
            document_urls=documents,
            dates=_detail_dates(detail),
        )

        existing = by_identifier.get(identifier.normalized)
        if existing is None:
            by_identifier[identifier.normalized] = record
            records.append(record)
            continue
        if same_title(existing.title, record.title) and existing.status_raw == record.status_raw:
            continue
        issues.append(
            ParseIssue(
                row_number=row_no,
                reason=(
                    f"duplicate identifier {identifier.normalized} with a conflicting title: "
                    f"{existing.title!r} then {record.title!r}"
                ),
                raw_identifier=raw_identifier,
                raw_values=(raw_text[:200],),
            )
        )

    if not records:
        raise ArchiveParseError("validated archive year yielded zero records")

    for label in sorted(unknown_labels):
        issues.append(
            ParseIssue(
                row_number=0,
                reason=f"unmapped detail label: {label!r}",
                raw_identifier="",
                raw_values=(label[:200],),
            )
        )
    # The tree declares no header row, so there is no schema to fingerprint. What can silently
    # corrupt this shape is a renamed detail label, which would drop dates while still parsing.
    # Fingerprinting the labels we do *not* understand catches exactly that and stays stable
    # while the vocabulary holds, so an archived year gaining a bill never reads as drift.
    structure = ("archive-year-v1|" + "|".join(sorted(unknown_labels))).encode()
    return ParsedListing(
        tuple(records),
        ("Kod", "Tajuk", "Status"),
        hashlib.sha256(structure).hexdigest(),
        tuple(issues),
        # The tree has no headers, so its detail labels are the only words on the page that are
        # written in one language rather than the other — `First reading` against `Bacaan Pertama
        # Pada`. A year of bills that never passed carries no detail rows and so no answer, which
        # is why this is allowed to be `None` (see `observed_language`).
        observed_language=observed_language(detail_labels),
    )


def _unescape(value: str) -> str:
    """Undo the escaping the tree leaks into its own text.

    Titles and presenter names arrive as `Dato&#039; Sri` because the value was HTML-escaped
    after it had already been escaped once, and one title arrives as `Al-Qur\\'an` from a
    database escape that was never removed. Both are upstream accidents rather than what
    Parliament published, and showing either verbatim would put the escaping on our own pages.
    """
    return html.unescape(html.unescape(value)).replace("\\'", "'").replace('\\"', '"').strip()


def _read_children(
    item: ElementTree.Element, *, source_url: str
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...], set[str]]:
    """Split a bill node's children into detail pairs, document links, and unknown labels."""
    detail: list[tuple[str, str]] = []
    documents: list[str] = []
    unknown: set[str] = set()
    for child in item.findall("item"):
        for userdata in child.findall("userdata"):
            if userdata.get("name") != "myurl" or not userdata.text:
                continue
            found = _LOAD_RESULT.search(userdata.text)
            if found and found.group(1).lower().split("?", 1)[0].endswith(".pdf"):
                url = absolute_document_url(source_url, found.group(1))
                if url not in documents:
                    documents.append(url)
        text = normalize_text(child.get("text") or "")
        label, separator, value = text.partition(":")
        if not separator:
            continue
        label = label.strip()
        value = _unescape(value)
        folded = label.casefold()
        if folded in ARCHIVE_DATE_LABELS or folded in ARCHIVE_PRESENTER_LABELS:
            detail.append((label, value))
        elif label:
            unknown.add(label)
    return tuple(detail), tuple(documents), unknown


def _presenter_from(detail: tuple[tuple[str, str], ...]) -> str | None:
    for label, value in detail:
        if label.casefold() in ARCHIVE_PRESENTER_LABELS and value:
            return value
    return None


def _detail_dates(detail: tuple[tuple[str, str], ...]) -> tuple[ParsedDateCell, ...]:
    """Read the dated detail rows, keeping an unparseable value visible.

    Thirteen archive rows publish `30/11/-0001`, which is a zero date leaking out of the
    upstream database. It must never become a plausible date; it is retained raw and reported.
    """
    cells: list[ParsedDateCell] = []
    for label, value in detail:
        event_type = ARCHIVE_DATE_LABELS.get(label.casefold())
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


def is_archive_index_url(url: str) -> bool:
    """Whether a stored URL is the archive's year index, which carries no bills to replay."""
    return "arkib=yes" in url and "ajx=0" in url


def is_archive_year_url(url: str) -> bool:
    """Whether a stored URL is one year of the archive tree."""
    return "arkib=yes" in url and "ajx=1" in url


def parse_stored_listing(body: str, *, url: str, source_url: str) -> ParsedListing:
    """Parse a stored snapshot the way the crawl that stored it did.

    Replay reads bytes that were saved months ago, so the shape has to be recovered from the
    request URL rather than guessed from the body. Without this, replaying an archive snapshot
    would hand XML to the HTML listing parser and report a parse failure that is really a
    dispatch bug (HANDOFF 9.6).
    """
    if is_archive_index_url(url):
        raise ArchiveParseError("the archive index is not a listing; there is nothing to replay")
    if is_archive_year_url(url):
        return parse_archive_year(body, source_url=source_url)
    return parse_listing(body, source_url=source_url)
