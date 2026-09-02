# Upstream observations

First reviewed reconnaissance: **2026-08-18**, from a crawl that stored every response, so
everything below was read out of saved bytes rather than a browser. Earlier sections of this file
that describe the parser's provisional vocabulary are kept for history; the observed sections take
precedence over them.

Second reviewed reconnaissance: **2026-08-18**, a full sweep of the archive tree — 67 XML
documents, both chambers, 1990 to 2024 — again read out of stored bytes. It settled the archive
request contract, the Dewan Negara detail labels, the English structure, the term/session
navigation (A8), the complete status vocabulary (A9), the date formats (A7), and corpus size (A12).

Still not verified: whether a revised document keeps its URL (A11), which needs two observations of
the same document over time and cannot be answered by one sweep.

This file intentionally does not present search-index observations from the handoff as
verification.

## 2026-08-18 — the current listing structure, verified

`GET /bills-dewan-rakyat.html?lang=bm&uweb=dr` (and the `uweb=dn` equivalent) return the complete
current listing in the initial HTML. No AJAX request is needed and no pagination request is
issued; the table carries a `paginated` class and is paged client-side, so one fetch yields every
row. Observed counts: 67 rows for Dewan Rakyat, 59 for Dewan Negara.

The bill table is `<table id="ruulist" class="table-style-two dr paginated">` with exactly four
columns:

| Header | Contents |
| --- | --- |
| `Kod` | The identifier, inside an `<a>` whose `onclick` carries the document path |
| `Tahun` | Four-digit year |
| `Tajuk` | Title |
| `Status` | The visible status, plus a hidden detail box |

**There is no presenter column, and there are no reading-date columns.** That corrects the
reconnaissance in HANDOFF section 5, which expected `Pembentang` and expanded date columns.
Everything beyond the four columns above lives in a hidden `<div class="alertBox">` inside the
status cell, containing a nested `<table>` of `Label : Value` rows:

| Detail label | Meaning | Observed count (DR) |
| --- | --- | --- |
| `Bacaan Pertama Pada` | First reading date | 67 |
| `Bacaan Kedua Pada` | Second reading date | 67 |
| `Diluluskan Pada` | Passage date | 59 |
| `Dirujuk JKPK Pada` | Referral to select committee | 4 |
| `Tidak Mendapat Undi 2/3 Pada` | Failed to reach a two-thirds majority | 1 |
| `Dibentang Oleh` | Presenter; repeated once per stage | 126 |

Two consequences for any parser:

1. **Table nesting must be tracked.** The detail table's rows are inside a `<td>` of the outer
   table. A parser that ignores nesting flattens them into the listing and every row appears
   malformed. This is what the first live crawl hit.
2. **The hidden box must not contribute to the cell's visible text.** The status cell's raw text
   otherwise becomes `Lulus D.R.22/2026 Tutup`, absorbing the popup heading and its close link.

## 2026-08-18 — the complete published status vocabulary (A9, resolved)

The distinct set across **everything the site publishes**: both current listings, both languages,
and all 2,130 archived rows from 1990 to 2024.

| Published status | Where | Count | Normalized |
| --- | --- | --- | --- |
| `Lulus` | current and archive | 2,185 | `passed` |
| `Ditarik Balik` | archive only | 31 | `withdrawn` |
| `Bacaan Kali Kedua dan Ketiga` | archive only | 27 | `third_read` |
| `Bacaan Kali Pertama` | current and archive | 6 | `first_read` |
| `Dirujuk ke JKPK` | current only | 4 | `referred` |
| `Tolak` | archive only | 2 | `defeated` |
| `Tidak Mendapat Undi 2/3 Peringkat Bacaan Ke-2` | current only | 1 | `defeated` |

and in English, for the same rows: `Passed`, `First Reading`, `Referred to JKPK`, and
`Did not obtain a two-thirds majority vote at the Second Reading stage.` — note the full stop,
which the Malay phrase does not have, so trailing punctuation is stripped before mapping.

Three of these appear **only** in the archive, which is why the current-listing sweep could not
close A9: a vocabulary designed from the current listings alone would have mapped 60 archived rows
to `unknown`, including every withdrawn bill in 35 years.

Two mappings are readings rather than transcriptions, and are recorded as such:

* `Tolak` is "rejected". It maps to `defeated`, alongside the current listing's much longer phrase
  for the same outcome.
* `Bacaan Kali Kedua dan Ketiga` is "second and third reading" — the Dewan Negara routinely takes
  both in one sitting and publishes them as a single status. The furthest stage it names is the
  third reading, so that is the normalized value. The raw phrase is retained either way.

Every observed phrase now maps; nothing in the published corpus normalizes to `unknown`.

## 2026-08-18 — upstream data defects the parser must survive

These are not shape questions; they are wrong values that a preservation archive has to carry
without either crashing or quietly inventing a correction.

| Defect | Occurrences | Handling |
| --- | --- | --- |
| `30/11/-0001` as a reading date | 13 | A zero date leaking out of the upstream database. Rejected as `unparseable_date`, raw retained, date left `NULL`. It must never become 1 BC or today. |
| `D.R.16//2017` — doubled separator | 2 rows, 1 bill | Normalized. It is the *only* spelling under which that bill is published, so refusing it would drop the bill (ADR-002). |
| `D.R.40/2017 ARKIB` — stray token | 1 | Rejected as `unparseable_identifier`, raw retained. A word is not punctuation. The same bill is also published cleanly. |
| `D.R 7/2024`, `D.R. 7/2024`, `D.R.  7/2024` | 245 | All normalize to one code. |
| `Al-Qur&#039;an`, `Al-Qur\&#039;an` in titles and `Dato&#039;` in presenter names | ~40 | Double-escaped HTML, and one `addslashes` escape that was never removed. Unescaped once on parse; republishing the escaping verbatim would put it on our own pages. |
| One bill titled two ways across chambers | 16 identifiers | Thirteen are the same title spelled differently (`RUU X` / `Rang Undang-Undang X`, `(No. 2)` / `(No.2)`, `Al-Quran` / `Al-Qur'an`) and are treated as one title. Three are genuinely different, including **D.R.11/2013, where the two chambers publish two entirely different bills under one code**; those raise `duplicate_identifier_conflict` and the first-recorded title stands. |

The date formats question (A7) is answered by the same sweep: **every** one of the 2,245 archived
dates is `DD/MM/YYYY`, with the 13 zero dates above as the only exceptions. No Malay month name and
no date range has ever been observed. The parser still accepts both, which costs nothing and is
covered by tests, but neither is upstream behaviour we have seen.

## 2026-08-18 — the published status vocabulary, first pass (A9, superseded)

> Superseded by the complete sweep above. Kept because it records what one chamber's current
> listing alone would have told us, which is the mistake A9 exists to prevent.

The complete distinct set observed on the Dewan Rakyat current listing:

| Published status | Count | Normalized |
| --- | --- | --- |
| `Lulus` | 59 | `passed` |
| `Dirujuk ke JKPK` | 4 | `referred` |
| `Bacaan Kali Pertama` | 3 | `first_read` |
| `Tidak Mendapat Undi 2/3 Peringkat Bacaan Ke-2` | 1 | `defeated` |

The handoff guessed `Diluluskan` for passage; the site publishes `Lulus`. Only one of the four
phrases matched the pre-live mapping, which is exactly why A9 forbids designing the status map
from a handful of assumed rows. The status also carries a CSS class (`ruustatus1`, `3`, `6`, `7`)
that correlates with the phrase; the phrase is parsed, not the class, because a class is
presentation.

This is still partial: it covers one chamber, one language, and current bills only. The archive
and the Dewan Negara set may add phrases.

## 2026-08-18 — document links (A10, partial)

Every document is reached through an inline script call, not a link:

```html
<a href="#" onclick="loadResult('/files/billindex/pdf/2026/DR/RUU Statistik 2026.pdf','...');">
```

There are **zero** `href` attributes ending in `.pdf` on the page. A parser that only collects
hrefs finds no documents at all. Paths contain spaces and must be percent-encoded to form a
usable URL.

Three current documents were downloaded and measured: all native-text PDFs, 17 to 33 pages, served
as `application/octet-stream` so magic bytes decide validity (A10, and the 2026-08-18 gate log
entry in `docs/status.md`).

The queue was then drained and the whole corpus downloaded, which replaced guesswork with
measurement. See "the document corpus, measured" below.

Age is not what decides whether a bill is machine-readable.
`/files/billindex/pdf/1995/DR011995.pdf` is 30 KB, four pages, and extracts cleanly —
`D.R. 1/95 Naskhah Sahih—Bahasa Kebangsaan` — so a 31-year-old bill is native text. Some far more
recent ones are not.

Three distinct path shapes are published, and a crawler must treat all of them as opaque:

| Shape | Where |
| --- | --- |
| `/files/billindex/pdf/2026/DR/RUU Statistik 2026.pdf` | current listing |
| `/files/billindex/pdf/2024/DR 17 BM.pdf` | archive tree (`BI` for English) |
| `/files/bm/billindex/pdf/2026/....pdf#page=4` | `carian.html` results, with a language segment and a page fragment |

Only the first two are queued. The third is the document search's own deep link and is not crawled.

## 2026-08-18 — the archive is a year-indexed XML tree (A3 and A8, resolved)

**This supersedes the section below it.** The `?arkib=yes` page really is a search form, and the
earlier reconnaissance stopped there and concluded that `carian.html` was therefore the archive.
Issuing the requests showed otherwise.

### `carian.html` is a document-text search, not a bill listing

With the form's own parameters, `GET /carian.html?str=kewangan&DATETYPE=0&doctype[]=DR-bill&...`
returns page-level hits inside bill PDFs:

```html
<div class="carian-search-result">
  <h3><a href="/files/bm/billindex/pdf/2026/RUU Perlembagaan (Pindaan) 2026.pdf#page=4&search=kewangan">
      Rang Undang-Undang - RUU Perlembagaan (Pindaan) 2026</a>
    <span class="carian-page-indicator">Halaman 4</span></h3>
  <p>IMPLIKASI <strong>KEWANGAN</strong> ...</p>
</div>
```

`100 Carian Ditemui dalam 0.0842 saat`, paginated with `page=N&ipp=30`. There is no bill code, no
status, and no reading date anywhere in the response — it could not produce a chamber record. It
is not crawled.

Two request-level facts are worth recording because they are easy to misread as failures:

* **A cookieless request is answered with a redirect, not results.** `carian.html` without a
  session returns `302` to `bills-dewan-rakyat.html?...` and a `Set-Cookie: GENPRO_SESSION=...`.
  Follow the redirect and you land on the *current* listing with the search parameters trailing
  behind, which looks convincingly like "the archive search returned the current bills". Keep the
  cookie and request again and the search renders its own results.
* **`lang=en` depends on the same session.** The first visit sets `GENPRO_SESSION` and
  `cookiesession1`; the language follows the session that serves it. The fetcher keeps cookies for
  the run, which is why the English documents work at all.

### The archive itself is a `dhtmlXTree`

The same `?arkib=yes` page renders a tree under the heading `Senarai Arkib`, which loads its own
XML:

```html
<div id="treeboxbox_tree"></div>
<script>
  tree.setXMLAutoLoading("https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr&arkib=yes&ajx=1");
  tree.loadXML("https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr&arkib=yes&ajx=0");
</script>
```

`ajx=0` returns one node per archived **year** — this is the answer to A8: the archive is
partitioned by calendar year, not by parliamentary term or session. The Dewan Rakyat offers 34
years and the Dewan Negara 33, both 1990 to 2024, with gaps (neither publishes 2003; the Dewan
Negara also skips 2001).

`ajx=1&id=0_<year>` returns that year's bills. One node, verbatim:

```xml
<item child='1' id='0_2024_0' text='D.R.17/2024 - RUU Penagih Dadah (Rawatan dan Pemulihan) (Pindaan) 2024 (Lulus) '>
  <userdata name='myurl'>#</userdata>
  <item text='D.R.17/2024' id='0_2024_0_1' child='0' im0='book_titel.gif'>
    <userdata name='myurl'>javascript:loadResult('/files/billindex/pdf/2024/DR 17 BM.pdf','DR 17 BM.pdf')</userdata>
  </item>
  <item text='Bacaan Pertama Pada:02/07/2024' id='0_2024_0_2' child='0'></item>
  <item text='Bacaan Kedua Pada:03/07/2024' id='0_2024_0_2' child='0'></item>
  <item text='Dibentang Oleh:YB Datuk Seri Dr. Shamsul Anuar bin Haji Nasarah - ...' child='0'></item>
  <item text='Diluluskan Pada:18/07/2024' id='0_2024_0_2' child='0'></item>
  <item text='Dibentang Oleh:YB Senator Datuk Seri Saifuddin Nasution bin Ismail - ...' child='0'></item>
</item>
```

Consequences for any parser:

1. **The status is inside the item text, as its last parenthesised group.** Titles routinely
   contain parentheses (`RUU Kerja (Pindaan) 2011`), so the status must be taken from the end, not
   from the first bracket. The archive also writes it with a leading space: `( Bacaan Kali Kedua
   dan Ketiga)`.
2. **The document is reached through `loadResult(...)` in a `userdata` element**, not an `href`,
   exactly as on the current listing, and the path contains spaces.
3. **A bill that never passed has no children at all** — no dates, no presenter, no document. All
   63 such rows in the corpus are `Ditarik Balik`, `Tolak`, `Bacaan Kali Pertama`, or
   `Bacaan Kali Kedua dan Ketiga`.
4. **The node year is the year the chamber considered the bill, not the bill's own year.** Ten 2010
   bills sit under the Dewan Negara's 2011 node. The bill's year is the identifier's.

### Corpus size (A12)

Read out of the stored sweep, after the parser's own collapsing of rows that upstream publishes
twice:

| | Dewan Rakyat | Dewan Negara | Both |
| --- | --- | --- | --- |
| Archived years offered | 34 (1990-2024) | 33 (1990-2024) | 67 documents |
| Archived bill rows parsed | 1,185 | 945 | 2,130 |
| Rows carrying a document link | 1,136 | 931 | 2,067 |
| Rows retained as issues, not records | 1 | 0 | 1 |
| Distinct bill identifiers | 1,185 | 945 | 1,202 |

The chamber columns sum to more identifiers than the combined figure because 928 bills appear in
both chambers, which is the bill/chamber split working as HANDOFF 8 intends.

A full archive crawl is therefore 67 XML documents plus two indexes, about 4 MB of XML, and it
introduces roughly 2,000 documents into the fetch queue at once. That is why the archive mode has
its own budget (HANDOFF 11.7).

## 2026-08-18 — Dewan Negara and English structure, verified

The **Dewan Negara current listing** has the same four columns and the same three detail labels as
the Dewan Rakyat's: 59 rows, all `Lulus`, each with `Bacaan Pertama Pada`, `Bacaan Kedua Pada`, and
`Diluluskan Pada`, and each with a presenter. The detail-label question is closed.

The **English pages** are reached with `lang=en` and label the same rows differently:

| Malay | English |
| --- | --- |
| `Kod` / `Tahun` / `Tajuk` / `Status` | `Code` / `Year` / `Title` / `Status` |
| `Bacaan Pertama Pada` | `First reading` |
| `Bacaan Kedua Pada` | **`The second reading`** |
| `Diluluskan Pada` | **`Passed At`** |
| `Dibentang Oleh` | `Presented by` |

The two in bold are not the phrases a translator would guess, and the parser did not have them: an
English crawl parsed all 67 rows and kept **no dates at all**, silently. That is now fixed and
covered by a regression test. English document filenames use `BI` where Malay uses `BM`
(`DR 17 BI.pdf`).

## 2026-08-18 — the archive is a search form, not a listing (A3, superseded)

> Superseded by the section above. Reading the form was right; concluding that the form was the
> archive was wrong. Kept because the form is real and the reasoning is worth not repeating.

`?arkib=yes` does **not** return archived rows. It returns a search page whose only table header
is `Kembali Ke Senarai` ("back to list"), wrapping a form:

```html
<form method="GET" action="carian.html" class="formcarian">
  <input type="text"   name="str">            <!-- free-text query -->
  <input type="hidden" name="DATETYPE" value="dr">
  <input type="radio"  name="DATETYPE" value="2|5|0|1">   <!-- date-range mode -->
  <input type="text"   name="daterangeraw">
  <input type="text"   name="str2">
  <input type="hidden" name="doctype[]"  value="DR-bill">
  <input type="hidden" name="dokumen[]"  value="ruu">
  <input type="hidden" name="searchref"     value="bills-dewan-rakyat">
  <input type="hidden" name="searchrefcode" value="dr">
  <input type="submit" name="submit" value="CARI">
</form>
```

So the archive is a documented `GET /carian.html` endpoint with static parameters. **No browser
automation is required** — see ADR-011. The response shape of `carian.html`, its pagination, and
whether results must be partitioned by date range are not yet observed, so the archive crawl is
not implemented. Until it is, both archive coverage targets report `failing` on `/status` and the
run ends `partial` while the current listings publish normally.

## 2026-08-18 — a bill really does appear in both chambers (A4, verified)

`D.R.15/2026`, `D.R.15/2025`, and `D.R.42/2025` each hold two chamber records from one bill row
in each chamber's listing, with independent reading dates. The bill/chamber split in HANDOFF
section 8 is confirmed against real data: a single flat table would have overwritten one
chamber's history with the other's.


## Label vocabulary in the parser

The parser matches labels semantically, never by position or CSS class. **Observed** means the
label was read out of stored bytes from the live site; the rest were taken from the HANDOFF
section 5 reconnaissance and are kept because they cost nothing and would catch a page that starts
using them.

Column headers, of which the live site publishes exactly four:

| Purpose | Observed | Also accepted, never observed |
| --- | --- | --- |
| Identifier | `Kod`, `Code` | — |
| Year | `Tahun`, `Year` | — |
| Title | `Tajuk`, `Title` | — |
| Status | `Status` | — |
| Presenter | — | `Pembentang`, `Presenter` |
| Reading dates | — | `Bacaan Kali Pertama`, `First reading`, and the second- and third-reading equivalents |
| Committee referral | — | `Dirujuk Kepada Jawatankuasa`, `Referred to committee`, … |
| Passage date | — | `Tarikh Diluluskan`, `Date passed`, … |

Detail labels, which is where the readings and the presenter actually live — in the current
listing's hidden box and in the archive tree's child nodes:

| Purpose | Observed (Malay) | Observed (English) |
| --- | --- | --- |
| First reading | `Bacaan Pertama Pada` | `First reading` |
| Second reading | `Bacaan Kedua Pada` | `The second reading` |
| Passage | `Diluluskan Pada` | `Passed At` |
| Committee referral | `Dirujuk JKPK Pada` | — |
| Failed two-thirds vote | `Tidak Mendapat Undi 2/3 Pada` | — |
| Presenter | `Dibentang Oleh` | `Presented by` |

A third-reading detail label has never been observed in either language, even though the archive
publishes a combined second-and-third-reading *status*. `Bacaan Ketiga Pada` and
`The third reading` are accepted defensively.

An unrecognised header is ignored rather than guessed at, and a page missing the identifier,
title, or status column fails to parse. A header change on a page that still parses is caught by
the structure fingerprint, which raises `structure_drift`. The archive tree has no header row, so
its fingerprint is the set of detail labels the parser does not recognise — see ADR-014.

The status phrase vocabulary in `billwatcher.scraper.normalize` is no longer provisional: it is the
complete published set recorded above. Anything unmapped still stores `unknown`, keeps the raw
string, and raises `unmapped_status`, because upstream may add a phrase at any sitting.


## 2026-08-18 — the site's published policies, read in full (A13 and A14 evidence)

Every page footer links the complete set of policy pages: `Peta Laman` (sitemap), `Dasar Privasi`,
`Dasar Keselamatan`, `Soalan Lazim`, `Penafian`, `Bantuan`, and `RSS`. All were fetched and read.

| Page | What it says | Anything about crawling or reuse? |
| --- | --- | --- |
| `/penafian.html` — Penafian (disclaimer) | No warranty, express or implied, as to the completeness or accuracy of the information; no liability for errors, omissions, or consequential damages. Last updated 6 April 2016. | **No** |
| `/dasar-privasi.html` — Dasar Privasi | Visitors' personal data. No personal information is collected while browsing except what a visitor sends by email; it may be shared with other public agencies to answer a complaint. | **No** |
| `/dasar-keselamatan.html` — Dasar Keselamatan | *Their* protection of data submitted to them: encryption in transit and at rest, controls against unauthorised access. | **No** |
| `/soalan-lazim.html` — FAQ | Visiting Parliament, sittings, member enquiries. | **No** |

**There is no terms-of-use page and no copyright policy page.** `/hakcipta.html` and
`/terma-penggunaan.html` both answer `An error has occurred. The requested page cannot be found.`
— and, in keeping with the rest of this site, they answer it with **HTTP 200**, not 404. No footer
link to either exists. The only copyright statement anywhere is the footer line on every page:

```
2026 © Hakcipta Terpelihara Parlimen Malaysia
```

"Hakcipta Terpelihara" is "copyright reserved". No licence, no grant of reuse, no conditions.

Two consequences, and they point in opposite directions:

* **For crawling (A13):** the question "do the site's terms of use permit crawling?" has no
  document to answer it. Nothing published restricts automated access, sets a rate, or forbids
  reuse — there is no robots.txt and no terms. The recorded decision (RFC 9309 treats an absent
  policy as unrestricted; crawl at one request every two seconds; raise `robots_absent` on every
  run so the decision stays visible) now rests on a complete reading of everything the site
  publishes, rather than on not having looked.
* **For republishing our stored PDFs (A14):** the absence cuts the other way. There is no licence
  and no permission — only "all rights reserved". Nothing here supports republishing the bytes, so
  ADR-004's official-link-only position stands and `SERVE_ARCHIVED_DOCUMENTS` stays off. Whether a
  statutory exception applies, or whether permission should simply be asked for, is a legal
  judgement for the service owner; this note records only what the site does and does not say.

## 2026-08-18 — the document corpus, measured

The whole queue was drained: **1,295 archived and current documents fetched**, one request every
two seconds, each hashed, validated, stored, and text-extracted.

| | |
| --- | --- |
| Documents fetched | 1,295 (queue fully drained, nothing dead-lettered) |
| Stored, validated versions | 1,264 |
| Quarantined | **31** — see dead links below |
| Total stored bytes | **0.24 GB** |
| Total pages | **27,575** |
| Pages per document | 1 to 679, mean 22 |
| Text extracted successfully | 1,242 |
| Extracted empty | 12 |
| Extraction failed | 10 |
| Documents with a second version | **0** |

### 31 archive links are dead, and the server says so with a 200

Thirty-one documents the archive index links do not exist. The server answers with **HTTP 200**, a
`Content-Type: text/html`, and a 23-byte body:

```
File does not exist (1)
```

Magic-byte validation caught all 31 and refused to store any of them as a document — which is the
whole reason HANDOFF 11.4 step 3 validates content rather than trusting a status code. They are
spread across 2004-2010 and are permanent: there is nothing to re-crawl. Each raised a critical
`document_quarantined` anomaly, and all 31 have been acknowledged with that reason recorded, so
`make doctor` is green while `/status` still shows them.

### 22 documents have no extractable text, and it is not the old ones

| Year | Not extractable | Documents that year |
| --- | --- | --- |
| 1998 | 1 | 32 |
| 2001 | 1 | 50 |
| 2010 | 8 | 40 |
| 2013 | 3 | 11 |
| 2017 | 2 | 46 |
| 2018 | 7 | 34 |

1.7% of the corpus. The pattern is not age: a bill from **1995** extracts cleanly
(`D.R. 1/95 Naskhah Sahih—Bahasa Kebangsaan`), while **2010, 2013 and 2018** are the worst years.
Those documents have real page counts and roughly 45 KB per page, which is what a scanned image
looks like — they were published as scans rather than as typeset text. Ten more are simply
malformed PDFs, one of which reports zero pages.

**This is the justification for the optional OCR worker in HANDOFF 11.4 step 7.** It is a small,
identifiable subset rather than the whole archive, and until it is run those 22 bills are findable
by their listing metadata but not by their contents. Recording `empty` and `failed` as distinct
outcomes is what makes the subset addressable at all.

### One document, several URLs (A11)

**62 sets of byte-identical documents are published at more than one URL.** The usual shape is one
copy per chamber:

```
/files/billindex/pdf/2025/DR/DR2_2025%20-%20BM.pdf
/files/billindex/pdf/2025/DN/DR2_2025%20-%20BM.pdf
```

and in the archive, the same file under the year each chamber considered it
(`/pdf/2010/DR302010.pdf` and `/pdf/2011/DR302010.pdf`), or the same bill under both a terse and a
descriptive name (`DR572007.pdf` and `DR 57_2007-RUU Suruhanjaya Aduan Khas 2007.pdf`).

Content-hash identity collapses all of these correctly: 62 shared hashes, one stored blob each,
linked from every bill that points at them. URL-based identity would have created two documents for
each and counted the archive twice. That is ADR-003's central decision, and this is the first
evidence for it at scale.

What it does **not** settle is A11 as asked — whether a *revised* document keeps its URL. After
fetching all 1,295 documents, **not one has a second version**, so no revision has been observed.
The related and more dangerous assumption is now dead, though: a document plainly does not have one
canonical URL.

## 2026-08-18 — upstream certificate incident: incomplete chain

`https://www.parlimen.gov.my` serves **only its leaf certificate** and omits the intermediate
that signs it, so the chain cannot be built from a normal trust store.

```
$ openssl s_client -connect www.parlimen.gov.my:443 -servername www.parlimen.gov.my
depth=0 CN = *.parlimen.gov.my
verify error:num=20:unable to get local issuer certificate
subject=CN = *.parlimen.gov.my
issuer=C = GB, O = Sectigo Limited, CN = Sectigo Public Server Authentication CA DV R36
Verify return code: 21 (unable to verify the first certificate)
```

Only `depth=0` is presented. The signing intermediate,
`Sectigo Public Server Authentication CA DV R36`, is not sent, and its root
(`Sectigo Public Server Authentication Root R46`) *is* present in an ordinary trust store. The
leaf's Authority Information Access extension points at
`http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt`.

This is why the site loads in a browser but fails from this crawler: browsers fetch the missing
intermediate themselves via AIA, and Python's `ssl` module deliberately does not. Verification
succeeds as soon as the intermediate is supplied.

**This is an upstream misconfiguration, not a local trust-store problem, and it is not a reason
to weaken verification.** There is no setting in this project that disables TLS verification, and
HANDOFF section 5 forbids adding one. The supported remedy adds a trust anchor without lowering
the bar:

```bash
curl -sS http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt -o intermediate.crt
openssl x509 -inform DER -in intermediate.crt -out intermediate.pem
cat /etc/ssl/certs/ca-certificates.crt intermediate.pem > /etc/billwatcher/upstream-ca.pem
# then set, in .env:
#   UPSTREAM_CA_BUNDLE=/etc/billwatcher/upstream-ca.pem
```

Re-check this before each release: if Parliament fixes its chain, drop the setting rather than
carrying a pinned intermediate that will eventually expire. The intermediate above is valid only
until its own notAfter date, and a stale bundle will fail closed — which is the correct
behaviour, but the cause will not be obvious unless this note is kept current.

## 2026-08-18 — upstream observation: no robots.txt

`https://www.parlimen.gov.my/robots.txt` returns **404 Not Found** with an HTML error body.

RFC 9309 section 2.3.1.3 treats a 4xx as "no restrictions", but assumption A13 is still open and
HANDOFF section 5 requires crawl permission to be established and recorded before any crawl. A
404 is therefore treated as *policy absent*, and the run refuses by default.

Proceeding requires a recorded decision — review the site's published terms of use, record the
outcome in the manual gate log in `docs/status.md`, and only then set
`ROBOTS_MISSING_POLICY=allow`. When set, each run still records a critical anomaly noting that it
crawled without a published policy, so the decision stays visible on `/status` rather than
becoming invisible configuration.

Note the earlier code defect this uncovered: the preflight parsed the response body without
checking the status code, and an HTML error page parses to an empty ruleset, which reads as
"crawl anything". That is now fixed and covered by tests.

## 2026-08-20 — AGC discovery spike (`lom.agc.gov.my`): TLS clean, robots.txt errors, terms found

A one-time, read-only discovery pass — not a crawl — settling the questions HANDOFF 26.7 raised
about a second publisher. Eight GET requests total, honestly identified
(`BillWatcherNext-discovery-spike/0.1 (research; one-time reconnaissance; contact:
cheeleong@tuxuri.com)`), spaced several seconds apart: the portal root, `robots.txt` (twice, to
rule out a transient error), `tnc.php`, `faq.php`, and one `robots.txt` check against
`www.agc.gov.my` for context. Nothing was downloaded beyond these HTML pages; no legislation
document was fetched.

**TLS chain is complete**, unlike parlimen.gov.my's. `openssl`/`curl` verify cleanly against the
system CA bundle alone: leaf `CN=*.agc.gov.my`, issued by DigiCert Global G3 TLS ECC SHA384 2020
CA1, expiring 2027-02-07. No `UPSTREAM_CA_BUNDLE` equivalent would be needed for this host.

**`robots.txt` returns HTTP 500, not 404.** `https://lom.agc.gov.my/robots.txt` consistently
returns a 170-byte nginx `500 Internal Server Error` body, on two separate requests. This is not
the same fact as parlimen.gov.my's clean 404: a 500 does not read as RFC 9309 "no restrictions"
the way a 4xx does; it reads as the endpoint being broken or misconfigured, which is a different
condition and needs its own recorded decision rather than reusing `ROBOTS_MISSING_POLICY`'s
reasoning by analogy. (For contrast, `https://www.agc.gov.my/robots.txt` — a different subdomain,
checked only for context — returns a clean 404.)

**Terms & Conditions (`tnc.php`) and FAQ (`faq.php`) were read in full.** Both are public, no
login, and carry substantive text rather than boilerplate:

- The s.61 Interpretation Acts 1948/1967 disclaimer HANDOFF 26.7 already cited is confirmed
  verbatim from the live source (T&C clauses 9–10; FAQ 3): a printout from the portal is *not* a
  copy of the Gazette printed by PNMB for the purposes of proving the law in court.
- **FAQ 3 also says more than parlimen.gov.my's policy pages ever did**: "The legislation can be
  downloaded and printed from this portal **for purposes of reference**." This is not a blanket
  licence — it says nothing about redistribution, mirroring, or building a derivative structured
  database, which is what this pipeline would do — but it is materially more permissive language
  than exists anywhere on parlimen.gov.my, where the only copyright statement is "all rights
  reserved" with no mention of any permitted use at all. Whether "for purposes of reference"
  covers this project's intended use is a legal judgement, not a fact this spike can settle, and
  is not decided here.
- **FAQ 4 raises a legal nuance a lawyer should read, not resolved here**: subsection 18(4) of the
  Interpretation Acts is quoted as making "the date of publication of the Gazette... the date the
  Gazette is first published in any form," and the FAQ states that from 26 April 2011 the portal
  "shall be the first official Gazette published to the public." Read together with the s.61
  disclaimer about *printouts*, this suggests the portal's *online* publication may carry
  different evidentiary status from a *printed copy* of it — a distinction this project is not
  qualified to interpret and which HANDOFF 26.7's legal sign-off item exists for.
- **The pre-2011 coverage boundary is now confirmed from AGC's own FAQ, not inferred**: "Principal
  legislation made prior to 26 April 2011 can be obtained from the Attorney General's Chambers'
  portal (www.agc.gov.my) and Percetakan Nasional Malaysia Berhad's (PNMB) portal
  (www.lawnet.com.my)... Printed copies... can be purchased from PNMB." This matches HANDOFF's
  Stage 0 sources table exactly, now with a primary citation rather than an assumption. It also
  reconfirms `lawnet.com.my` sits outside `lom.agc.gov.my` entirely, consistent with TODO.md 1.6
  treating it as a separate, paid-subscription risk class.
- Coverage start dates are reconfirmed exactly: subsidiary legislation (P.U.(A)/P.U.(B), out of
  this project's scope) from 26 April 2011; Principal and Amending Acts passed by Parliament from
  March 2011, published on the portal from 2 June 2011.
- The copyright year is inconsistent on the site itself: the T&C body text says "Copyright 2023",
  the page footer says "Copyrights © 2026" — a real observation, not a transcription error here,
  noted because this project's own discipline (A9, A7) is to record what a source actually
  publishes rather than smooth over its inconsistencies.
- The site sets a `language=BI` cookie by default on first visit; the nav offers a BM/ENG toggle.
  What "BI" denotes in this specific site's own vocabulary was not confirmed — noted rather than
  guessed, matching the standing rule against designing a vocabulary from a handful of samples.

**What this settles and what it does not.** A16 (§4) moves from *unresolved, no request ever
issued* to *partially observed*: the TLS half is answered cleanly (no chain fix needed), and
whether reprints state an "incorporating amendments up to" date is still unconfirmed — no
document listing or reprint page was fetched, since that would start to be a listing crawl rather
than a policy discovery, and stays out of scope for a read-only reconnaissance pass. **No decision
to crawl AGC has been made here.** The `robots.txt` 500 needs its own recorded decision distinct
from `ROBOTS_MISSING_POLICY`'s absent-policy reasoning; the "for purposes of reference" language
and the online-Gazette-status nuance are legal questions for the service owner and, per HANDOFF
26.7, a lawyer — not something this spike resolves by finding favourable-sounding text.

## 2026-08-27 — the English half of the corpus, crawled and measured (ADR-040)

The first crawl of both published languages. `lang=en` was requested for both chambers' current
listings and their whole archive trees, and the parser read the language off each page's own labels
rather than off the request (`ParsedListing.observed_language`).

- **`lang=en` was honoured on every request.** 130 listing snapshots parsed, `listings_wrong_language`
  **0**. The session-language hazard recorded on 2026-08-18 — a cookieless archive-search request
  answered with a `302` to the current *Malay* listing — did not fire once across a full cold crawl
  of the English tree. It is still guarded rather than assumed: the count is reported per run, and
  the opt-in live check `test_the_english_listing_is_served_in_english` asserts it directly.
- **The fetch cost matched the estimate.** 68 fetched, 67 skipped, 0 failed: the skips are the closed
  Malay archive years already stored, so the added cost was the English half alone (ADR-034's resume
  logic, working as designed).
- **Titles: 1,246 of 1,273 bills now carry both languages.** 23 are Malay-only and 4 are
  English-only — Parliament does not publish every bill in both languages, and the record says which
  it published rather than inferring a missing translation.
- **Documents: 1,282 named only by Malay listings, 1,256 named only by English ones, and 14 named by
  both.** Those 14 are the pre-2012 paths that carry no `BM`/`BI` marker in the filename. One file
  cannot be two Expressions of one bill, so `language_of` claims nothing for them and they fall to
  `extract-markdown`'s fallback — the case ADR-040 §4 was written for, now with a count.
- **A trust-store note.** The crawl reads `.env`, not `.env.development`. With `UPSTREAM_CA_BUNDLE`
  blank there, all nine targets failed on the incomplete chain recorded on 2026-08-18 — and the step
  still exited 0, which is what prompted the "reached nothing" exit guard now in `cli._report`.

## 2026-08-27 — a document is served only to a session in its own language

Discovered while downloading the English half: **every** English PDF answered with HTTP 200 and the
twenty-three bytes `File does not exist (3)` — 36 of 36 in a sample spread across 1990-2026, which
is too uniform to be genuine absence. It is not the path that decides which document upstream
serves, it is the session.

Measured directly, with one client per session and the same two URLs:

| session opened on | `DR 1_2021 - bm-merged.pdf` | `DR 1_2021- BI_merged.pdf` |
| --- | --- | --- |
| *(cookieless)* | 384 KB PDF | `File does not exist (3)` |
| `lang=bm` listing | 384 KB PDF | `File does not exist (3)` |
| `lang=en` listing | `File does not exist (3)` | 334 KB PDF |

The same symmetry held for `DR 17 BM.pdf` / `D.R. 16 BI.pdf`. Three things follow.

- **A cookieless client is answered as a Malay one.** This is why a Malay-only crawl never had to
  know any of this, and why the bug was invisible until the English targets were added: the first
  English run failed all 1,256 of its documents and, at the time, still exited 0.
- **The soft 404 is ambiguous by nature.** The same twenty-three bytes mean "this link is dead" and
  "you asked under the wrong language". `fetch_documents` resolves the ambiguity by construction: it
  opens a session per language and only reports a document as unserved once every language has
  refused it, quoting what each one said.
- **The session is worth two requests per run, not two per document.** The queue is grouped by
  language and crawled a language at a time (`Fetcher.begin_session`), so the whole cost of this
  discovery is one extra request per language.

**What this does not settle.** Whether the language lives in `GENPRO_SESSION` server-side state or
in the `language` cookie was not isolated — the session is cleared and re-warmed as a unit, which is
correct either way and does not depend on knowing which. The 31 Malay documents that fail under a
Malay session are a separate, older fact: those are dead links in Parliament's own bill index, and
they failed the same way before any of this changed.
