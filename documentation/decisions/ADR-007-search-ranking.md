# ADR-007: Search unit weighting, ranking, and deep pagination

Status: accepted
Date: 2026-08-18

## Context

HANDOFF 12.1 requires weighted units (A and B for bill metadata, C for document text), a ranking
order that puts an exact bill code first, bounded snippets built only for the rendered page, and
keyset pagination beyond a configurable offset. It also warns that a `tsvector` is capped near
1 MB, which a single long page of a scanned bill can still approach even after the unit split.

## Decision

`search_units` carries `content_a` (weight A, the raw and normalized identifiers) and `content`
(weight B for bill metadata, C for document text). The stored `tsv` is a generated column that
applies both weights; the weight for `content` is derived from `unit_kind` in the generated
expression, so no application code can write an inconsistent weight.

A page longer than 200,000 characters is stored as several units distinguished by a `part`
number, keeping every tsvector far below the PostgreSQL limit while preserving the page range.

Ranking is a single query ordering by: exact normalized identifier, identifier prefix,
`ts_rank_cd` over the weighted vector, newest `bill_events.event_on`, then the normalized
identifier. Because `websearch_to_tsquery('simple', 'D.R. 15/2026')` does not tokenize to the
same lexemes as the stored identifier, an explicit normalized-identifier predicate runs alongside
the full-text predicate rather than relying on tokenization.

Snippets come from `ts_headline` using control-character sentinels. The result is HTML-escaped
first and only then are the sentinels replaced with `<mark>`; database output is never trusted as
markup.

Pagination: the browsable index (no query) uses keyset pagination on
`(coalesce(year, -1) DESC, identifier_normalized ASC)` and exposes a cursor on the Next link.
Ranked search refuses offsets at or beyond 1,000 results with a helpful 400 asking for filters,
because a keyset over a fused relevance score is not stable across requests.

## Consequences

Search behaviour that only exists on PostgreSQL is covered by an opt-in suite
(`tests/integration/test_postgres_search.py`) that skips with a clear message when no disposable
database is configured. SQLite keeps a substring fallback so the offline suite still exercises
the same call paths, with the ordering contract preserved and the relevance approximated.
