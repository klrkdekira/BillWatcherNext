# ADR-005: Permit repeated content hashes in a document version chain

Status: accepted
Date: 2026-08-17

## Context

HANDOFF 1.1 section 8 required uniqueness on document ID plus content SHA-256, while section
9.3 requires bytes matching an older non-current version to create a new monotonic version row.
Those requirements are mutually exclusive.

## Decision

Retain uniqueness on document ID plus version number and the partial one-current-version index.
Do not make document ID plus content hash unique. Ordinary identical-current responses still create
no row. A hash matching an older version creates a new row pointing to the already stored blob,
which preserves the observed sequence A, B, A and supports the mandated rollback anomaly.

## Consequences

Blob storage remains deduplicated. Version rows represent observations of accepted content state,
not merely the set of hashes ever encountered. Rollback tests must prove monotonically increasing
version numbers and no extra blob bytes.
