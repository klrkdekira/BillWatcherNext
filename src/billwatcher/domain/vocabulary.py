"""Pure controlled vocabularies shared by the parser, the database, and the web layer.

These are domain rules, not presentation choices, so they live in exactly one place. Nothing in
this module performs I/O or imports the database.
"""

from types import MappingProxyType

CHAMBERS = frozenset({"dewan_rakyat", "dewan_negara"})

CHAMBER_LABELS = MappingProxyType({"dewan_rakyat": "Dewan Rakyat", "dewan_negara": "Dewan Negara"})

# HANDOFF 8. Provisional until the full bilingual status sweep (assumption A9).
NORMALIZED_STATUSES = frozenset(
    {
        "introduced",
        "tabled",
        "first_read",
        "second_read",
        "committee",
        "referred",
        "third_read",
        "passed",
        "withdrawn",
        "lapsed",
        "defeated",
        "unknown",
    }
)

EVENT_TYPES = frozenset(
    {
        "introduced",
        "first_reading",
        "second_reading",
        "committee_referral",
        "committee_report",
        "third_reading",
        "passed",
        "withdrawn",
        "lapsed",
        "document_published",
        "status_observed",
        "other",
    }
)

# Which chamber_records date column each dated listing column projects onto. The events are the
# authoritative history; these columns are a convenient current projection (HANDOFF 8).
EVENT_TYPE_TO_CHAMBER_FIELD = MappingProxyType(
    {
        "first_reading": "first_read_on",
        "second_reading": "second_read_on",
        "third_reading": "third_read_on",
        "committee_referral": "referred_on",
        "passed": "passed_on",
    }
)

DOCUMENT_KINDS = frozenset(
    {
        "bill_as_introduced",
        "bill_as_passed",
        "bill_revised",
        "explanatory_statement",
        "amendment_paper",
        "reprint",
        "translation",
        "other",
        "unknown",
    }
)

# BCP 47 everywhere except when building an upstream query string, which uses `bm`.
LANGUAGES = frozenset({"ms", "en", "mixed", "unknown"})
