# ADR-010: Retention sign-off

Status: accepted
Date: 2026-08-18

## Context

HANDOFF 16.4 sets retention per class of data and HANDOFF 21 requires the policy, including the
decision never to auto-prune document versions, to be recorded rather than left implicit.

## Decision

`billwatcher retention` (dry run by default) is the only scheduled retention path, and it may
touch exactly three things:

1. `fetch_attempts` older than `FETCH_ATTEMPT_RETENTION_DAYS` are aggregated into
   `daily_fetch_metrics` by day, host, and status code, and only then deleted. The politeness
   audit trail survives as counters.
2. `document_extractions` are reduced to the current extractor version and the one before it.
3. Blob references held by failed or quarantined page snapshots older than 90 days are released.
   Retention never deletes bytes; `prune-blobs` does, and only for blobs with no references.

Never prunable, by any job: `document_versions` and their blobs, `record_changes`, `bill_events`,
`presence_observations`, and any snapshot row. `document_versions` in particular are the archive
and have no automatic pruning path at all — there is no flag that enables one.

## Consequences

Storage growth from document versions is unbounded by design and is a capacity decision, not a
retention decision. Sizing stays provisional until the first reviewed full crawl measures the
corpus (assumption A12).
