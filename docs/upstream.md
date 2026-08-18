# Upstream observations

First reviewed reconnaissance: **2026-08-18**, from a crawl that stored every response, so
everything below was read out of saved bytes rather than a browser. Earlier sections of this file
that describe the parser's provisional vocabulary are kept for history; the observed sections take
precedence over them.

Still not verified: the archive request contract's response shape, the Dewan Negara detail labels,
the bilingual (English) listing structure, and the parliamentary term/session navigation (A8).

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

## 2026-08-18 — the published status vocabulary (A9, partial)

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
usable URL. Whether the bytes are native-text or scanned PDFs is not yet measured; 127 documents
were queued and none downloaded during this run.

## 2026-08-18 — the archive is a search form, not a listing (A3, resolved)

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


## Provisional label vocabulary in the parser

The parser matches these column headers semantically. They are provisional and taken from the
HANDOFF section 5 reconnaissance (assumption A2), not from a saved fixture of the live site. The
discovery spike must confirm or replace them, and record the complete observed set here.

| Purpose | Headers currently matched |
| --- | --- |
| Identifier | `Kod`, `Code` |
| Year | `Tahun`, `Year` |
| Title | `Tajuk`, `Title` |
| Status | `Status` |
| Presenter | `Pembentang`, `Presenter` |
| First reading | `Bacaan Kali Pertama`, `Bacaan Pertama`, `First reading` |
| Second reading | `Bacaan Kali Kedua`, `Bacaan Kedua`, `Second reading` |
| Third reading | `Bacaan Kali Ketiga`, `Bacaan Ketiga`, `Third reading` |
| Committee referral | `Dirujuk Kepada Jawatankuasa`, `Rujukan Jawatankuasa`, `Committee referral`, `Referred to committee` |
| Passage date | `Tarikh Diluluskan`, `Diluluskan Pada`, `Date passed`, `Passed on` |

An unrecognised header is ignored rather than guessed at, and a page missing the identifier,
title, or status column fails to parse. A header change on a page that still parses is caught
separately by the structure fingerprint, which raises `structure_drift`.

The status phrase vocabulary in `billwatcher.scraper.normalize` is likewise provisional pending
the full sweep required by assumption A9. Anything unmapped stores `unknown`, keeps the raw
string, and raises `unmapped_status`.


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
