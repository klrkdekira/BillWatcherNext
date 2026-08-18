# ADR-008: Embedding model selection is deferred; the vector width is schema

Status: proposed
Date: 2026-08-18

## Context

HANDOFF 21 requires a recorded decision on the embedding model, its dimension, licence,
multilingual evaluation, and operating cost, and HANDOFF 8 requires the dimension to live in a
migration and never be silently mixed. No model has been evaluated for Malay and English
parliamentary text, and no operating budget has been agreed.

## Decision

No production model is chosen here, and none is defaulted. `EMBEDDING_PROVIDER` and
`EMBEDDING_MODEL_ID` are empty by default and `SEMANTIC_SEARCH_ENABLED=true` is rejected without
both. A provider whose dimension differs from the schema width is refused at construction rather
than silently truncated.

The stored width is `EMBEDDING_DIMENSION = 1024` in `billwatcher.models`, created by migration
0003. Adopting a model with another width is a new migration plus a recorded `reembed` job, never
an in-place change. Two models may coexist: `reembed` backfills alongside the incumbent, and the
superseded model's vectors are removed only by the explicit `drop-embedding-model` command once
the replacement has been validated.

A `deterministic` provider ships for development and tests. It is a hashed bag-of-words
projection with no semantic understanding, it is documented as such, and production configuration
rejects it.

The HNSW cosine index is not created by a migration. `billwatcher semantic-index --apply` builds
it, and refuses to run before any vectors exist, per HANDOFF 12.3.

## Consequences

Semantic search cannot be switched on by accident, and turning it on forces a model decision to
be written down. The evaluation gate in `docs/evals/README.md` must be run against the chosen
model and its result recorded in the manual gate log before the flag is enabled.
