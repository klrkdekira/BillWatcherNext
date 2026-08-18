# ADR-011: The archive is a search endpoint, and needs no browser automation

Status: superseded by ADR-014
Date: 2026-08-18
Superseded: 2026-08-18

> **Superseded.** The mechanism recorded below is wrong. `carian.html` is a full-text search over
> document pages and carries no bill metadata at all; the archived listing is a `dhtmlXTree` whose
> XML is fetched from the same page with `&ajx=0` and `&ajx=1&id=0_<year>`. ADR-014 records the
> real contract and the observations that settled it. What survives from this ADR is its rejection
> of browser automation, which ADR-014 restates and keeps.
>
> The error is worth keeping visible: this ADR inferred a request mechanism from one page's markup
> without ever issuing the request. Reading the form was correct; concluding that the form was the
> archive was not.

## Context

Assumption A3 held that "the archive listing requires a form/AJAX request rather than returning
all rows in initial HTML", at low confidence, and HANDOFF 21 requires a recorded decision on the
exact mechanism and on whether browser automation is needed. The first reviewed crawl settled it
from stored bytes (see `docs/upstream.md`, 2026-08-18).

## Decision

`?arkib=yes` returns a search **form**, not archived rows. The form is a plain
`GET /carian.html` with static parameter names: `str`, `str2`, `DATETYPE`, `daterangeraw`,
`doctype[]`, `dokumen[]`, `searchref`, `searchrefcode`, `submit`. There is no XHR on the page and
no JavaScript-constructed request.

The archive will therefore be crawled with ordinary HTTP requests to `carian.html`. **Browser
automation is rejected**: it would add a large dependency, a headless browser in the production
image, and an execution surface for upstream content, for no capability we need. That decision
stands unless `carian.html` is later observed to require script execution, which would require
superseding this ADR.

Until the `carian.html` response shape, its pagination, and any date-range partitioning are
observed and fixtured, the archive is **not crawled**. The two archive coverage targets report
`failing`, each raises a `listing_unavailable` warning, and the run ends `partial` while the
current listings publish. Nothing about the archive is guessed at in the meantime.

## Consequences

A3 is resolved and the `document_relations` question it gated (HANDOFF 25.3) can be revisited
once archived reprints are visible. Release 1's "current and archived listings for both chambers"
criterion is **not** met yet, and `docs/status.md` records that.

The `pagination_loop` guard already exists and is tested; the archive crawl is its first real
caller, which is why it was built before a paginated target existed.
