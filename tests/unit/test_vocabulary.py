"""The controlled vocabularies are one source of truth (HANDOFF 8)."""

from billwatcher.domain.vocabulary import (
    CHAMBERS,
    EVENT_TYPE_TO_CHAMBER_FIELD,
    EVENT_TYPES,
    NORMALIZED_STATUSES,
)
from billwatcher.models import ChamberRecord
from billwatcher.scraper.normalize import normalize_status


def test_the_status_map_can_only_produce_declared_statuses() -> None:
    for phrase in ("Diluluskan", "Bacaan Kali Ketiga", "Luput", "Ditolak", "gibberish"):
        assert normalize_status(phrase) in NORMALIZED_STATUSES


def test_every_reading_and_outcome_the_handoff_names_is_declared() -> None:
    assert {"first_read", "second_read", "third_read", "committee", "referred"} <= (
        NORMALIZED_STATUSES
    )
    assert {"passed", "withdrawn", "lapsed", "defeated", "tabled", "unknown"} <= (
        NORMALIZED_STATUSES
    )
    assert {"first_reading", "second_reading", "third_reading"} <= EVENT_TYPES


def test_dated_columns_project_onto_real_chamber_record_columns() -> None:
    columns = set(ChamberRecord.__table__.columns.keys())
    assert set(EVENT_TYPE_TO_CHAMBER_FIELD) <= EVENT_TYPES
    assert set(EVENT_TYPE_TO_CHAMBER_FIELD.values()) <= columns


def test_the_web_filter_vocabulary_is_not_a_second_copy() -> None:
    from billwatcher.web.routes import CHAMBERS as ROUTE_CHAMBERS
    from billwatcher.web.routes import STATUSES as ROUTE_STATUSES

    assert ROUTE_STATUSES is NORMALIZED_STATUSES
    assert ROUTE_CHAMBERS is CHAMBERS
