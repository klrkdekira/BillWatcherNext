import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "phpsessid",
    "sessionid",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}
_IDENTIFIER_RE = re.compile(r"^\s*D\s*[.\-]?\s*([RN])\s*[.\-]?\s*(\d+)\s*/\s*(\d{4})\s*$", re.I)
_IDENTIFIER_QUERY_RE = re.compile(
    r"^\s*D\s*[.\-]?\s*([RN])\s*[.\-]?\s*(\d+)?\s*(?:/\s*(\d{4}))?\s*$", re.I
)
_MONTHS = {
    "januari": 1,
    "january": 1,
    "jan": 1,
    "februari": 2,
    "february": 2,
    "feb": 2,
    "mac": 3,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "mei": 5,
    "may": 5,
    "jun": 6,
    "june": 6,
    "julai": 7,
    "july": 7,
    "jul": 7,
    "ogos": 8,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "oktober": 10,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "disember": 12,
    "december": 12,
    "dec": 12,
}


@dataclass(frozen=True, slots=True)
class Identifier:
    raw: str
    normalized: str
    number: int
    year: int
    originating_chamber: str
    slug: str


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date | None = None


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def normalize_identifier(raw: str) -> Identifier:
    value = normalize_text(raw)
    match = _IDENTIFIER_RE.fullmatch(value)
    if not match:
        raise ValueError(f"unparseable bill identifier: {raw!r}")
    chamber_code, number_text, year_text = match.groups()
    number, year = int(number_text), int(year_text)
    prefix = f"D{chamber_code.upper()}"
    chamber = "dewan_rakyat" if chamber_code.upper() == "R" else "dewan_negara"
    normalized = f"{prefix}-{number}-{year}"
    return Identifier(raw, normalized, number, year, chamber, normalized.lower())


def canonicalize_url(raw: str) -> str:
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("URL must be absolute HTTP(S)")
    host = parts.hostname.lower()
    port = parts.port
    default_port = (parts.scheme.lower(), port) in {
        ("http", 80),
        ("https", 443),
    }
    netloc = host if port is None or default_port else f"{host}:{port}"
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMETERS
        ),
        doseq=True,
        quote_via=quote,
    )
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", query, ""))


def _single_date(
    value: str, *, inherited_month: int | None = None, inherited_year: int | None = None
) -> date:
    text = normalize_text(value).strip(".,")
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
        return date.fromisoformat(text)
    numeric = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if numeric:
        day, month, year = map(int, numeric.groups())
        if month > 12:
            raise ValueError(f"invalid Malaysian date: {value!r}")
        return date(year, month, day)
    named = re.fullmatch(r"(\d{1,2})\s+([^\W\d_]+)\s+(\d{4})", text, re.UNICODE)
    if named:
        day_text, month_text, year_text = named.groups()
        parsed_month = _MONTHS.get(month_text.casefold().rstrip("."))
        if parsed_month is None:
            raise ValueError(f"unknown month name: {month_text!r}")
        return date(int(year_text), parsed_month, int(day_text))
    if inherited_month is not None and inherited_year is not None and text.isdigit():
        return date(inherited_year, inherited_month, int(text))
    raise ValueError(f"unparseable date: {value!r}")


def parse_dates(raw: str) -> list[DateRange]:
    """Parse Malaysian listing dates, ranges, and semicolon-separated dates."""
    value = normalize_text(raw)
    if not value or value in {"-", "—", "N/A"}:
        return []
    results: list[DateRange] = []
    for item in re.split(r"\s*[;,]\s*", value):
        named_range = re.fullmatch(
            r"(\d{1,2})\s*[–-]\s*(\d{1,2})\s+([^\W\d_]+)\s+(\d{4})", item, re.UNICODE
        )
        if named_range:
            start_day, end_day, month_name, year_text = named_range.groups()
            month = _MONTHS.get(month_name.casefold().rstrip("."))
            if month is None:
                raise ValueError(f"unknown month name: {month_name!r}")
            year = int(year_text)
            results.append(
                DateRange(date(year, month, int(start_day)), date(year, month, int(end_day)))
            )
            continue
        numeric_range = re.fullmatch(
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})\s+[–-]\s+(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
            item,
        )
        if numeric_range:
            results.append(
                DateRange(
                    _single_date(numeric_range.group(1)), _single_date(numeric_range.group(2))
                )
            )
            continue
        results.append(DateRange(_single_date(item)))
    return results


_STATUS_MAP = {
    "bacaan kali pertama": "first_read",
    "first reading": "first_read",
    "bacaan kali kedua": "second_read",
    "second reading": "second_read",
    "dalam jawatankuasa": "committee",
    "committee": "committee",
    "dirujuk": "referred",
    "referred": "referred",
    "bacaan kali ketiga": "third_read",
    "third reading": "third_read",
    "diluluskan": "passed",
    "passed": "passed",
    "ditarik balik": "withdrawn",
    "withdrawn": "withdrawn",
    "luput": "lapsed",
    "lapsed": "lapsed",
    "ditolak": "defeated",
    "defeated": "defeated",
    "dibentangkan": "tabled",
    "tabled": "tabled",
}


def normalize_status(raw: str) -> str:
    return _STATUS_MAP.get(normalize_text(raw).casefold(), "unknown")


@dataclass(frozen=True, slots=True)
class IdentifierQuery:
    """A user query interpreted as a whole or partial bill identifier."""

    exact: str | None
    prefix: str | None


def parse_identifier_query(raw: str) -> IdentifierQuery:
    """Interpret free text as a bill code so search can rank exact and prefix hits first."""
    value = normalize_text(raw)
    match = _IDENTIFIER_QUERY_RE.fullmatch(value)
    if not match:
        return IdentifierQuery(None, None)
    chamber_code, number_text, year_text = match.groups()
    prefix = f"D{chamber_code.upper()}"
    if number_text is None:
        return IdentifierQuery(None, prefix)
    prefix = f"{prefix}-{int(number_text)}"
    if year_text is None:
        return IdentifierQuery(None, prefix)
    exact = f"{prefix}-{int(year_text)}"
    return IdentifierQuery(exact, exact)
