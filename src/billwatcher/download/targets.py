"""The fixed set of Parliament listing entry points this pipeline reads.

Eight string literals, and the only place in this pipeline that knows where Parliament publishes.
They are upstream facts rather than application logic, which is why they sit in a module of their
own: a target that moves is an edit here, not a search through the fetching code.

Parliament publishes every listing twice — `lang=bm` and `lang=en` — and both are crawled, because
the English pages are not a translation layer over the Malay ones: they name a *different document*
(`DR 17 BI.pdf` beside `DR 17 BM.pdf`), and that document is the English Expression of the bill,
with its own permanent identifier (ADR-040, ADR-024). Crawling one language would publish half the
corpus while reporting success.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ListingTarget:
    chamber: str
    listing_kind: str  # "current" | "archive_index"
    language: str
    url: str


# The Malay targets are listed first, and the order is stable: a crawl reports its progress by
# target, and an operator comparing two runs should not have to work out whether the list moved.
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
    ListingTarget(
        "dewan_rakyat",
        "current",
        "en",
        "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=en&uweb=dr",
    ),
    ListingTarget(
        "dewan_negara",
        "current",
        "en",
        "https://www.parlimen.gov.my/bills-dewan-negara.html?lang=en&uweb=dn",
    ),
    ListingTarget(
        "dewan_rakyat",
        "archive_index",
        "en",
        "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=en&uweb=dr&arkib=yes&ajx=0",
    ),
    ListingTarget(
        "dewan_negara",
        "archive_index",
        "en",
        "https://www.parlimen.gov.my/bills-dewan-negara.html?lang=en&uweb=dn&arkib=yes&ajx=0",
    ),
)


def archive_year_url(index_url: str, year: int) -> str:
    """The tree request for one archived year, derived from the chamber's index request.

    The language rides along in `index_url`, which is why the English tree needs no separate
    derivation: `lang=en&...&ajx=1&id=0_2024` is the English 2024 node.
    """
    return index_url.replace("ajx=0", "ajx=1") + f"&id=0_{year}"
