# ADR-014: The archive is a year-indexed XML tree, not the search form

Status: accepted
Date: 2026-08-18

Supersedes the crawl mechanism in ADR-011. ADR-011's rejection of browser automation still
stands and is restated here.

## Context

ADR-011 read the `?arkib=yes` page correctly — it is a search form — and concluded that the
archive would therefore be crawled through `GET /carian.html`. That conclusion was wrong, and it
was wrong in the way the handoff's own assumption register warns about: a mechanism inferred from
one page's markup rather than from a request that was actually issued.

Two observations on 2026-08-18 settled it, both from stored bytes:

1. **`carian.html` is a full-text search over document pages, not a bill listing.** Issued with
   the form's own parameters it returns page-level hits — `Rang Undang-Undang - RUU Mata Wang
   2019 · Halaman 48` with a snippet and a deep link to
   `/files/bm/billindex/pdf/2019/....pdf#page=48` — paginated with `page=N&ipp=30`. There is no
   bill code, no status, and no reading date anywhere in the response. It could never have
   produced a chamber record.
2. **The archived listing is elsewhere on the same page.** The `?arkib=yes` page also renders a
   `dhtmlXTree` under the heading `Senarai Arkib`, and the tree loads its own XML:

   ```
   GET /bills-dewan-{rakyat,negara}.html?lang={bm,en}&uweb={dr,dn}&arkib=yes&ajx=0
   GET /bills-dewan-{rakyat,negara}.html?lang={bm,en}&uweb={dr,dn}&arkib=yes&ajx=1&id=0_<year>
   ```

   `ajx=0` returns one node per archived year; `ajx=1&id=0_<year>` returns that year's bills, each
   with its identifier, title, status, reading dates, presenter, and document path. A sweep of
   every year node in both chambers read 2,143 bills from 1990 to 2024.

The first request also has to establish a session: `carian.html` answers a cookieless request
with a 302 back to the listing page and a `Set-Cookie`, and `lang=en` likewise depends on the
session that serves it. The fetcher keeps cookies for the run, which is why the tree requests
work at all.

## Decision

The archive is crawled as a tree of ordinary HTTPS GETs:

* The **year index** (`ajx=0`) is one target per chamber. It is not a listing; its record count
  is the number of years it offered. If it will not parse, that chamber's archive state is
  unknown and the run fails rather than publishing a half-read archive.
* Each **year** (`ajx=1&id=0_<year>`) is a target of its own, carrying the year in
  `coverage_targets.scope_key`. One unreadable year degrades that year on `/status` and nothing
  else; 34 years of history are not withheld because 2007 broke.
* Each year's XML is reduced to the same `ParsedListing` the HTML listing parser produces, so
  ingestion, change tracking, event projection, and document queueing are shared rather than
  written twice.
* The archive is read only in the explicitly triggered `--archive` and `--full` modes, with the
  larger budget HANDOFF 11.7 requires. An incremental run does not touch it: reading 67 XML
  documents every twelve hours to re-observe closed years would be impolite and pointless.
* An archived year that has closed cannot change, so a scoped archive target is expected to be
  re-read monthly rather than weekly (`expected_interval_hours = 720`).
* **Browser automation stays rejected**, for ADR-011's reasons. The tree is XML fetched with a
  query string; nothing here needs script execution.

`carian.html` is not crawled at all. It is a document-text search, and we build our own over text
we extracted ourselves, from documents whose provenance we recorded.

### Drift detection without a header row

HANDOFF 11.6 fingerprints a listing's structure so a redesign that still parses is caught. A
listing's fingerprint is its header row; the tree has no header row, so there is nothing
equivalent to hash. What can silently corrupt this shape is a **renamed detail label**: rename
`Bacaan Pertama Pada` and every first reading disappears while the response still parses
perfectly.

The archive's fingerprint is therefore the set of detail labels the parser does **not**
recognise. Normally that set is empty, so the fingerprint is stable and a year gaining a bill is
not reported as drift. A renamed or added label puts a value in the set, which changes the
fingerprint, raises `structure_drift`, and withholds publication until someone looks.

## Consequences

Release 1's "current **and** archived listings for both chambers" criterion can now be met, and
assumption A8 (term/session navigation) is answered: the archive is partitioned by year, not by
parliamentary term.

The archive also settled the questions the current listings could not. The status vocabulary (A9)
is now a complete sweep of the published corpus rather than four phrases from one chamber, and it
turned up three phrases the current listings never show — `Ditarik Balik`, `Tolak`, and
`Bacaan Kali Kedua dan Ketiga`. Every observed date is `DD/MM/YYYY` (A7), with thirteen
exceptions that are a zero date leaking out of the upstream database and are rejected as
unparseable. Corpus size (A12) is measured: 2,143 archived bill rows, about 2,065 documents.

Two costs are accepted. The first archive run queues the whole back catalogue, so the archive
mode has its own document budget; without it the run would end `partial` on the document limit
and withhold every year it had read. And `/status` grows from four coverage rows to about
seventy, which is the honest shape of the target set — per-target freshness is the point of
HANDOFF 10.4, and a `Scope` column keeps it readable.
