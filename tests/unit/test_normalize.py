from datetime import date

import pytest

from billwatcher.scraper.normalize import (
    canonicalize_url,
    normalize_identifier,
    normalize_status,
    normalize_text,
    parse_dates,
)


def test_identifier_normalization_and_origin() -> None:
    result = normalize_identifier(" D.R. 15 / 2026 ")
    assert (result.normalized, result.slug, result.number, result.year) == (
        "DR-15-2026",
        "dr-15-2026",
        15,
        2026,
    )
    assert result.originating_chamber == "dewan_rakyat"


def test_identifier_rejects_malformed_value() -> None:
    with pytest.raises(ValueError):
        normalize_identifier("Bill 15")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("13/07/2026", [(date(2026, 7, 13), None)]),
        ("3-7-2026", [(date(2026, 7, 3), None)]),
        ("2026-07-13", [(date(2026, 7, 13), None)]),
        ("13 Julai 2026", [(date(2026, 7, 13), None)]),
        ("13 July 2026", [(date(2026, 7, 13), None)]),
        ("13–14 Julai 2026", [(date(2026, 7, 13), date(2026, 7, 14))]),
        ("13/07/2026 - 14/07/2026", [(date(2026, 7, 13), date(2026, 7, 14))]),
        ("13/07/2026; 14/07/2026", [(date(2026, 7, 13), None), (date(2026, 7, 14), None)]),
    ],
)
def test_date_formats(raw: str, expected: list[tuple[date, date | None]]) -> None:
    assert [(item.start, item.end) for item in parse_dates(raw)] == expected


def test_date_rejects_ambiguous_or_invalid_values() -> None:
    with pytest.raises(ValueError):
        parse_dates("01/13/2026")
    with pytest.raises(ValueError):
        parse_dates("01/02/26")


def test_text_is_nfc_and_whitespace_collapsed() -> None:
    assert normalize_text("  Cafe\u0301\n  bill ") == "Café bill"


def test_status_unknown_is_never_guessed() -> None:
    assert normalize_status("Diluluskan") == "passed"
    assert normalize_status("Unexpected new status") == "unknown"


def test_url_canonicalization_keeps_semantic_query() -> None:
    result = canonicalize_url(
        "HTTPS://WWW.PARLIMEN.GOV.MY:443/doc.pdf?id=4&utm_source=test#fragment"
    )
    assert result == "https://www.parlimen.gov.my/doc.pdf?id=4"
