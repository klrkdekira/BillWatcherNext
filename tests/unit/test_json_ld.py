from datetime import UTC, datetime

from billwatcher.models import Bill, ChamberRecord
from billwatcher.web.schemas import legislation_json_ld

NOW = datetime(2026, 8, 17, tzinfo=UTC)


def bill(**values):
    defaults = {
        "identifier_raw": "D.R.15/2026",
        "identifier_normalized": "DR-15-2026",
        "slug": "dr-15-2026",
        "title_bm": "RUU Perlindungan Saksi",
        "identifier_scheme_version": 1,
        "first_seen_at": NOW,
        "last_seen_at": NOW,
        "last_checked_at": NOW,
        "last_changed_at": NOW,
    }
    defaults.update(values)
    return Bill(**defaults)


def chamber(status: str = "first_read") -> ChamberRecord:
    return ChamberRecord(
        bill_id="bill",
        chamber="dewan_rakyat",
        status_raw="Bacaan Kali Pertama",
        status_normalized=status,
        source_url="https://www.parlimen.gov.my/list",
        source_snapshot_id="snapshot",
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )


def test_current_bill_omits_unsupported_legal_claims() -> None:
    data = legislation_json_ld(bill(), [chamber()])
    assert data["@type"] == "Legislation"
    assert data["inLanguage"] == ["ms"]
    assert data["sameAs"] == "https://www.parlimen.gov.my/list"
    assert "legislationDate" not in data
    assert "legislationLegalForce" not in data
    assert "legislationPassedBy" not in data


def test_passed_and_bilingual_bill_remains_truthful() -> None:
    data = legislation_json_ld(
        bill(title_en="Witness Protection Bill"),
        [chamber("passed")],
    )
    assert data["alternateName"] == "Witness Protection Bill"
    assert data["inLanguage"] == ["ms", "en"]
    assert "legislationDate" not in data
    assert "legislationLegalForce" not in data
