# ADR-002: Canonical bill identifier rules

Status: accepted
Date: 2026-08-16
Accepted: 2026-08-18, against the whole published corpus

## Decision

Normalize observed D.R.number/year and D.N.number/year values to DR-number-year and DN-number-year.
Stable slugs are lowercase normalized identifiers. The prefix is treated as the **originating**
chamber — the chamber a bill was introduced in, not the chamber whose listing it appears on.
Unknown formats are retained raw, reported as anomalies, and never silently assigned an identity.

Normalization tolerates whitespace and punctuation differences, including a repeated separator. It
does not tolerate extra tokens.

## Evidence

Proposed on 2026-08-16 from reconnaissance. Accepted on 2026-08-18 against every bill identifier
the site publishes: both current listings and all 2,143 archived rows from 1990 to 2024, in both
chambers (`docs/upstream.md`, ADR-014).

* **1,229 distinct raw spellings, one canonical form each.** `D.R.7/2024`, `D.R. 7/2024`,
  `D.R 7/2024`, `D.R.  7/2024` and `D.R.16//2017` all occur, and all normalize. The tolerance the
  rule promises is the tolerance the data needs.
* **One row in 2,143 is rejected**: `D.R.40/2017 ARKIB`. A stray word is not punctuation, so it
  fails loudly with the raw value retained. It costs nothing — the same bill is also published
  cleanly as `D.R.40/2017` — and it is exactly the behaviour the rule asks for.
* **The originating-chamber reading is confirmed, for `D.R.`** The Dewan Negara's own listings and
  archive carry `D.R.` codes: 1,876 of them, for bills the Dewan Rakyat introduced and the Dewan
  Negara then considered. A single flat table keyed by listing chamber would have been wrong, and
  the bill/chamber split in HANDOFF 8 is what the data requires.
* **No `D.N.` identifier has ever been observed.** Not one, in either chamber, in 35 years of
  archive. The `D.N.` half of the mapping is therefore accepted as a rule and remains unexercised
  by real data; the parser accepts it, and the first `D.N.` row to appear will be the first test
  of it. This is why A5 is recorded as partially verified rather than verified.

## Consequences

Slugs are stable and derived, so no slug has needed correcting and the alias path in HANDOFF 10.2
remains untested by a real rename. That is a gap in coverage, not a defect: the alias mechanism
exists precisely so that accepting these rules now does not make a future correction a breaking
change.
