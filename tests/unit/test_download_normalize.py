from datetime import date

import pytest

from billwatcher.download.normalize import (
    canonicalize_url,
    normalize_identifier,
    normalize_status,
    normalize_text,
    parse_dates,
    same_title,
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


def test_identifier_tolerates_the_punctuation_the_site_publishes() -> None:
    """`D.R.7/2024`, `D.R. 7/2024`, `D.R 7/2024` and `D.R.16//2017` are all one bill code."""
    spellings = ["D.R.16//2017", "D.R 16/2017", "D.R. 16/2017", "D.R.  16/2017", "d.r.16/2017"]
    assert {normalize_identifier(raw).normalized for raw in spellings} == {"DR-16-2017"}


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


def test_every_status_phrase_the_sweep_observed_is_mapped() -> None:
    """The 2026-08-18 sweep read both current listings, both languages, and all 2,143 archived
    bills from 1990 to 2024. Nothing it published may normalize to `unknown` (A9)."""
    observed = {
        # Current listings, Malay then English.
        "Lulus": "passed",
        "Dirujuk ke JKPK": "referred",
        "Bacaan Kali Pertama": "first_read",
        "Tidak Mendapat Undi 2/3 Peringkat Bacaan Ke-2": "defeated",
        "Passed": "passed",
        "Referred to JKPK": "referred",
        "First Reading": "first_read",
        "Did not obtain a two-thirds majority vote at the Second Reading stage.": "defeated",
        # Archive only.
        "Ditarik Balik": "withdrawn",
        "Bacaan Kali Kedua dan Ketiga": "third_read",
        "Tolak": "defeated",
    }
    assert {phrase: normalize_status(phrase) for phrase in observed} == observed
    # The archive writes the combined status with a leading space inside its parentheses.
    assert normalize_status(" Bacaan Kali Kedua dan Ketiga") == "third_read"


def test_one_title_in_two_published_forms_is_the_same_title() -> None:
    """`RUU` is the site's abbreviation of `Rang Undang-Undang` and it uses both for one bill."""
    assert same_title(
        "RUU Dadah Berbahaya (Pindaan) 2017",
        "Rang Undang-Undang Dadah Berbahaya (Pindaan) 2017",
    )
    # Upstream typography and escaping accidents, all observed in the archive.
    assert same_title(
        "Rang Undang-undangArkitek (Pindaan) 2014", "Rang Undang-undang Arkitek (Pindaan) 2014"
    )
    assert same_title("Kewangan (No. 2) 2014", "Kewangan (No.2) 2014")
    assert same_title(
        "Pencetakan Teks Al-Qur\\'an (Pindaan) 1997", "Pencetakan Teks Al-Quran (Pindaan) 1997"
    )
    assert same_title(
        "RUU Pencetakan Teks Al-Qur&#039;an 2023", "RUU Pencetakan Teks Al-Quran 2023"
    )


def test_a_different_bill_is_not_the_same_title() -> None:
    assert not same_title("RUU Kewangan 2026", "RUU Kewangan (No. 2) 2026")
    assert not same_title(
        "Rang Undang-undang Kesalahan Keselamatan (Langkah-Langkah Khas) (Pindaan) 2013",
        "Rang Undang-undang Pencegahan Jenayah (Pindaan dan Pemerluasan) 2013",
    )
    assert not same_title("RUU Perbekalan 2021", None)


def test_url_canonicalization_keeps_semantic_query() -> None:
    result = canonicalize_url(
        "HTTPS://WWW.PARLIMEN.GOV.MY:443/doc.pdf?id=4&utm_source=test#fragment"
    )
    assert result == "https://www.parlimen.gov.my/doc.pdf?id=4"
