# ADR-009: Answer provider, prompt isolation, and answer data retention

Status: proposed
Date: 2026-08-18

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
stored. Choosing a provider requires confirming that the provider's own retention terms are
compatible with that position, and recording the confirmation in the manual gate log.

## Consequences

The feature is inert until three separate decisions are made and recorded: an embedding model
(ADR-008), an answer provider, and an accepted evaluation run. A provider outage returns the
retrieved passages and normal search links rather than an error page, and `RAG_ENABLED=false`
leaves indexing, lexical search, bill pages, and deployment untouched.
