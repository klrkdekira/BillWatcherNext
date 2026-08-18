# ADR-008: Embedding model selection is deferred; the vector width is schema

Status: proposed — the shortlist and recommendation below are recorded; the choice is the service
owner's, and needs the evaluation gate run against a real model
Date: 2026-08-18
Shortlist recorded: 2026-08-18

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

## The shortlist, and what the owner still has to decide

Recorded 2026-08-18 so that "deferred" does not mean "unexamined". Two constraints narrow the
field before any benchmark:

1. **The answer provider cannot supply the embeddings.** Anthropic publishes no embeddings
   endpoint — the Claude API surface is Messages, Token Counting, Batches, Files, and Models. So
   the embedding vendor is a second, independent choice, and ADR-009's retention reasoning does not
   carry over to it. If the embedding provider is a hosted API, every indexed chunk *and* every
   user query is sent to a third party.
2. **The stored width is 1024** (`EMBEDDING_DIMENSION`, migration 0003). Any model of another width
   is a migration plus a `reembed`, so a 1024-wide model is materially cheaper to adopt.

Candidates that are multilingual and already 1024-wide, so they need no migration:

| Model | Licence | Hosting | Notes |
| --- | --- | --- | --- |
| **BGE-M3** | MIT | self-hosted | 100+ languages; dense, sparse and multi-vector in one model |
| multilingual-e5-large | MIT | self-hosted | instruction-tuned multilingual encoder |
| Cohere embed multilingual v3/v4 | commercial API | hosted | 100+ languages |

**Recommendation: BGE-M3, self-hosted.** It is the option that matches what this project already
is. The site makes no third-party requests by design (HANDOFF 14, and the CSP that enforces it),
the archive exists so that provenance is ours rather than a vendor's, and a self-hosted encoder
means a user's question never leaves the host — which answers for retrieval the same question
ADR-009 has to answer for answers. MIT licensing removes the per-query cost and the licence review.
The cost moves from per-query billing to memory and CPU on the host, which is a capacity decision
rather than a contract.

What the owner must still do, and what no amount of analysis substitutes for:

- **Confirm Malay coverage empirically.** "100+ languages" is a vendor claim; published benchmarks
  are thin on Malay and thinner on Malaysian legislative register. The evaluation set exists for
  exactly this, and it is bilingual.
- **Run `make evaluate` against the chosen model** and record the result in the manual gate log.
  The command now prints the gate-log line to paste, and exits non-zero when a threshold is missed.
  Per HANDOFF 20 that log is the record which substitutes for CI; nothing in the code can check it,
  which is why it is a manual gate and not an automated one.
- **Accept the hosting cost** if self-hosting, or the licence and per-query cost if not.

Until then the flag stays off and `build_provider` keeps refusing to invent a choice.

## Consequences

Semantic search cannot be switched on by accident, and turning it on forces a model decision to
be written down. The evaluation gate in `docs/evals/README.md` must be run against the chosen
model and its result recorded in the manual gate log before the flag is enabled.
