# ADR-009: Answer provider, prompt isolation, and answer data retention

Status: accepted for the technical contract and the provider's retention terms; the ZDR
arrangement itself is a commercial step the service owner must complete
Date: 2026-08-18
Retention terms verified: 2026-08-18

## Context

HANDOFF 13 requires bounded, cited answers, prompt-injection controls, version-pinned citations,
a kill switch, and a recorded decision about the provider and its data-retention policy. HANDOFF
21 forbids faking a model choice.

## Decision

Answers go through an `AnswerProvider` interface. No provider call appears in a route handler;
providers are resolved once per application. Two are registered:

- `echo` — a deterministic development provider, rejected in production configuration.
- `anthropic` — the Anthropic Messages API, requiring the optional `rag` dependency group, an
  explicitly configured `RAG_MODEL_ID`, and credentials in the environment.

No provider or model is defaulted. `RAG_ENABLED=true` is rejected without `RAG_PROVIDER`,
`RAG_MODEL_ID`, and `SEMANTIC_SEARCH_ENABLED`.

Retrieved document text is supplied inside delimited `<source>` elements, labelled `S1`, `S2`,
and so on. The system prompt states that source content is untrusted data, never instruction. No
tools are offered to the model at all, so a document cannot cause a tool call. Citations are
plain `[Sn]` markers resolved in code against the exact set of sources supplied: a marker naming
anything else is stripped, counted, and surfaced as a note, and an answer left with no valid
citation is downgraded to "insufficient evidence" rather than published.

Every surviving citation carries the bill, the official document URL, the document version
number, the date we retrieved our copy, and the page range. A citation from a superseded version
is labelled as such on the page and in the API.

Retention: we store operational metadata only — model, latency, token counts, retrieved and cited
counts, and a non-reversible query fingerprint. Raw questions and generated answers are not
stored. Storing nothing ourselves is only half the claim, though: the provider must not store them
either, or the promise made on `/ask` is false.

### The provider's half, checked against its published terms

Read 2026-08-18 from `platform.claude.com/docs/en/manage-claude/api-and-data-retention`. Anthropic
offers **zero data retention (ZDR)**: under it, prompts and responses are not stored at rest after
the response is returned. It is enabled **per organization**, by arrangement with Anthropic's sales
team — not a request parameter and not self-serve, so it cannot be switched on from this
repository. The published per-feature eligibility, for the surface this service uses:

| Feature | ZDR-eligible | Relevance here |
| --- | --- | --- |
| Messages API | **Yes** | the only endpoint the answer provider calls |
| Citations | **Yes** | available if we ever move citation extraction into the API |
| Token counting | **Yes** | usable for pre-flight bounds |
| Prompt caching | **Yes** | prompts and outputs still not stored; KV representations are the bounded artifact |
| Batch processing | **No** — 29-day retention | therefore forbidden on the answer path |
| Code execution | **No** — container data up to 30 days | never declared; the model is offered no tools at all |

Three consequences are now normative for this service:

1. **The answer path uses `/v1/messages` only.** No Batches, no code execution, no Managed Agents.
   The current provider already does exactly this, so the constraint costs nothing today and
   exists to stop a later optimisation quietly voiding the retention claim.
2. **Claude Fable 5 and Claude Mythos 5 may not be used.** They require 30-day retention and are
   not available under ZDR. This is the rare case where the most capable model is the wrong choice:
   the promise on the page outranks answer quality. Claude Opus 5 is ZDR-eligible and is the
   recommended model.
3. **The API is never called from a browser.** CORS is unsupported for ZDR organizations, and the
   service calls the API server-side only. A browser-side call would both break and leak.

Anthropic may still retain data where required by law or where its automated trust-and-safety
systems flag content. That is not something a configuration can remove, and `/about` should say so
rather than promising more than can be delivered.

### What the owner must still do

ZDR is a commercial arrangement, so the remaining step is not an engineering one: contact
Anthropic to enable ZDR for the organization whose API key this service will use, then record the
confirmation in the manual gate log. Because that cannot be verified from inside the process,
`RAG_ZERO_RETENTION_CONFIRMED` must be set before RAG will start in production — an operator
asserting, in configuration, that the arrangement exists. It defaults to false, and the failure is
a refusal to start rather than a silently weaker promise.

## Consequences

The feature is inert until four things are true and recorded: an embedding model (ADR-008), an
answer provider, a ZDR arrangement asserted through `RAG_ZERO_RETENTION_CONFIRMED`, and an accepted
evaluation run. A provider outage returns the
retrieved passages and normal search links rather than an error page, and `RAG_ENABLED=false`
leaves indexing, lexical search, bill pages, and deployment untouched.
