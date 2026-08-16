# ADR-002: Canonical bill identifier rules

Status: proposed
Date: 2026-08-16

Normalize observed D.R.number/year and D.N.number/year values to DR-number-year and DN-number-year.
Stable slugs are lowercase normalized identifiers. The prefix is provisionally treated as
originating chamber (A5 remains open). Unknown formats are retained raw, reported as anomalies,
and never silently assigned an identity.
