"""The fixed set of Parliament listing entry points this pipeline reads.

Deliberately duplicated from `billwatcher.scraper.worker.TARGETS` rather than imported: that
module pulls in the Postgres-backed `ScrapeOrchestrator` and its model imports, and this package
must not depend on any of that (`billwatcher.pipeline`'s own docstring). The URLs themselves are
upstream facts, not application logic, so duplicating four string literals costs far less than
the coupling importing them would add.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ListingTarget:
    chamber: str
    listing_kind: str  # "current" | "archive_index"
    language: str
    url: str


TARGETS: tuple[ListingTarget, ...] = (
    ListingTarget(
        "dewan_rakyat",
        "current",
        "ms",
        "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr",
    ),
    ListingTarget(
        "dewan_negara",
        "current",
        "ms",
        "https://www.parlimen.gov.my/bills-dewan-negara.html?lang=bm&uweb=dn",
    ),
    # The archive entry point is the tree index, not the `arkib=yes` HTML page: that page is a
    # search form and a JavaScript tree, and it carries no bill rows at all (ADR-014).
    ListingTarget(
        "dewan_rakyat",
        "archive_index",
        "ms",
        "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr&arkib=yes&ajx=0",
    ),
    ListingTarget(
        "dewan_negara",
        "archive_index",
        "ms",
        "https://www.parlimen.gov.my/bills-dewan-negara.html?lang=bm&uweb=dn&arkib=yes&ajx=0",
    ),
)


def archive_year_url(index_url: str, year: int) -> str:
    """The tree request for one archived year, derived from the chamber's index request."""
    return index_url.replace("ajx=0", "ajx=1") + f"&id=0_{year}"
