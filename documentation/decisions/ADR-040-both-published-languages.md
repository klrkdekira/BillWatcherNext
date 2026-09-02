# ADR-040: Both published languages are crawled, and a document's language is recorded, not asserted

Status: accepted
Date: 2026-08-27

## Context

Directed by the commissioner on 2026-08-27: **"I noticed that only the bahasa malaysia bills are
scrapped. I want the english counter part too."**

That was accurate. `download/targets.py` held four entry points, all `lang=bm`, so the 1,269-bill
corpus was the Malay half of what Parliament publishes. Nothing else was missing: the listing parser
already carried the English column headers and the English detail labels (`Code`/`Year`/`Title`,
`First reading`, **`The second reading`**, **`Passed At`**, `Presented by`), the status vocabulary
already mapped `Passed` and the English two-thirds phrase, `titles` was already keyed
`raw_{language}`, `frbr.AKN_LANGUAGES` already mapped `en → eng`, and `publish/dataset.py` already
projected one Expression per language per Work. The English fixtures were committed
(`current_dr_en.html`, `archive_year_dr_en_2024.xml`) from the 2026-08-18 sweep. Only the four URLs
that would ever fetch such a page were absent.

Two upstream facts decide the shape of the rest of this decision.

**The English pages name different documents.** The archive publishes `DR 17 BM.pdf` on its Malay
pages and `DR 17 BI.pdf` on its English ones (`documentation/upstream.md`, A10). These are not one
document behind a translated chrome; they are two Expressions of one Work, which is exactly what
ADR-024's FRBR identifiers exist to distinguish. Crawling one language published half the corpus
while reporting success.

**Upstream's language follows the session, not only the URL.** The first visit sets `GENPRO_SESSION`
and a `language` cookie, and a cookieless archive-search request is answered with a `302` to the
*current Malay* listing (`documentation/upstream.md`, 2026-08-18). So a `lang=en` request can be
answered with a Malay page that parses perfectly. The failure that would cause is not a missing
row — it is a Malay title filed under `titles.raw_en` and English recorded as the language of a
Malay PDF, which becomes a permanent, wrong Expression IRI.

## Decision

1. **`TARGETS` holds eight entry points**: both chambers × {current listing, archive index} ×
   {`lang=bm`, `lang=en`}. Archive year requests derive from their index URL, so the language rides
   along and the English tree needs no separate derivation.

2. **A parsed listing reports the language of its own labels** (`ParsedListing.observed_language`),
   read from the column headers and the detail labels rather than from the request. `None` is a
   valid answer: a year of bills that never passed carries no detail rows and so no words in either
   language.

3. **`parse_listings` refuses a snapshot whose labels disagree with the language it was fetched
   under**, counts it as `listings_wrong_language`, names it with its URL, and merges nothing from
   it. It is deliberately *not* counted as a parse failure: the bytes parsed, and it is the fetch
   that has to be repeated.

4. **A document records which listing languages named it** (`documents[].languages`), and
   `download.documents.language_of` reads a language off it only when exactly one did. Two means
   Parliament links one file from pages of both languages — the pre-2012 paths carry no `BM`/`BI`
   marker — and one file cannot be two Expressions of one bill, so nothing is claimed.

5. **`extract-markdown --language` becomes the fallback, not the assertion.** Each document is read
   in the language of the listing that named it; the flag covers only what that leaves unsettled,
   and the step counts `language_from_listing` against `language_fallback` so a run says how much of
   it leaned on the operator's word.

6. **Language-bearing fields in a chamber record are kept per language, language-agnostic ones are
   not.** `statuses_raw` and `source_urls` become `{language: value}` maps, replacing the single
   `status_raw` and `source_url`; `status_normalized`, `dates` and `presenter` stay single-valued,
   because `Lulus`/`Passed` is one outcome and 02/07/2024 is one date. Two guards come with that: a
   phrase one language publishes and the vocabulary does not have (`unknown`) never erases a value
   the other language established, and a listing that yielded no dates never empties the dates we
   have.

## Consequences

- **The cold crawl roughly doubles.** Listings go from 69 documents to ~137, and the document queue
  from ~1,295 PDFs to an expected ~2,400. At one request every two seconds that is about another
  fifty minutes of downloading. Nothing about the existing corpus is refetched: ADR-034's resume
  logic skips every closed Malay year already stored, so the added cost is only the English half.
- **The published dataset gains a second Expression per bill** wherever an English document exists,
  with no change to `publish/dataset.py` — it was already written for it. A Work with only a Malay
  document is unaffected.
- **`bills/<slug>/bill.json` changes shape**: `chambers[*].status_raw` → `statuses_raw`,
  `chambers[*].source_url` → `source_urls`, and `documents[].languages` is new. Nothing outside
  `download/bills.py` read the two renamed fields. The migration needs no crawl — `parse-listings`
  replays every stored listing on every run, so re-running it over the existing corpus rewrites all
  1,269 records in place and a second run is byte-identical.
- **A wrong-language response is now a reported event rather than a silent corruption.** The cost is
  that a session upstream decides to serve in the wrong language withholds that page's rows until
  the next crawl — the correct trade, because the alternative is a permanent identifier asserting a
  language nobody established.
- **One live check cannot be replaced by a fixture**, so it is an opt-in live test: that upstream
  answers a `lang=en` request in English at all. If that ever stops holding, the English half of
  the corpus stops updating loudly instead of filling up with mislabelled Malay bills.
- **The two synthesized fixtures are labelled as such.** `current_dn_en.html` and
  `archive_year_dn_en_2011.xml` were derived from their Malay counterparts using the English
  vocabulary observed on 2026-08-18, because the sweep stored English bytes for the Dewan Rakyat
  only. Every other fixture in that directory is verbatim, and these two say in a comment that they
  are not.

## Addendum, 2026-08-27: the crawl holds a session per language

Implementing the decision above surfaced an upstream fact it did not anticipate, and one of its
consequences was wrong as written.

§2-3 assumed the language hazard was confined to *listings* — that a `lang=en` request could be
answered with a Malay page, and that reading the language off the page's own labels was therefore
enough. It is not confined to listings. **Upstream also picks which document it serves from the
session's language**, answering a mismatch with HTTP 200 and `File does not exist (3)`
(`documentation/upstream.md`, 2026-08-27). A cookieless client is answered as a Malay one, so
`fetch-documents` — which opened no session at all — failed every one of the 1,256 English
documents while the Malay half kept working.

Two additions, no change to §1-6:

7. **`fetch_documents` groups its queue by language and opens a session per language**
   (`Fetcher.begin_session`, which clears cookies and warms the new session from that language's
   listing target). Grouped rather than per document: the whole cost is one extra request per
   language instead of one per PDF.

8. **A document whose language is unsettled is attempted under every language before it is called
   failed**, and the failure quotes what each language answered. This is forced by the ambiguity of
   the soft 404 — the same twenty-three bytes mean "dead link" and "wrong language" — and it is what
   keeps the §4 decision (claim nothing for a file both languages name) from silently costing those
   files their download.

The predicted cold-crawl cost in *Consequences* holds: 1,287 documents outstanding against the 2,552
now referenced, and the 31 that fail under a Malay session are dead links in Parliament's own index
that failed the same way before this change.
