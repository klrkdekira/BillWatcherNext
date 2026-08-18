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
