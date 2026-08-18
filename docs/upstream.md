# Upstream observations

No live reconnaissance has been accepted yet. The URLs and behavior in HANDOFF section 5 remain
assumptions. A production or scheduled crawl must not run until strict-TLS discovery has saved
robots.txt and the required listing fixtures, recorded response metadata, completed the bilingual
label/status sweep, and resolved the archive request contract.

This file intentionally does not present search-index observations from the handoff as verification.


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
