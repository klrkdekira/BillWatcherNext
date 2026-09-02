# ADR-009: OpenAI-compatible answer provider and prompt isolation

Status: accepted
Date: 2026-08-18
Provider decision updated: 2026-08-19

## Context

HANDOFF 13 requires bounded, cited answers, prompt-injection controls, version-pinned citations,
a kill switch, and a recorded decision about the provider and its data handling. HANDOFF 21
forbids faking a model choice.

## Decision

Answers go through an `AnswerProvider` interface. No provider call appears in a route handler;
providers are resolved once per application. Two are registered:

- `echo` — a deterministic development provider, rejected in production configuration.
- `openai_compatible` — a self-hosted vLLM server exposing the OpenAI-compatible Chat
  Completions API. It requires an explicitly configured `RAG_MODEL_ID` and `RAG_BASE_URL`;
  `RAG_API_KEY` supplies an optional bearer token.

No model is defaulted. `RAG_ENABLED=true` is rejected without `RAG_PROVIDER`, `RAG_MODEL_ID`,
`RAG_BASE_URL`, and `SEMANTIC_SEARCH_ENABLED`. The production model remains an operator
decision that must pass the evaluation gate.

The provider sends one request to `/v1/chat/completions`, the endpoint documented by vLLM's
[OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/).
The system instruction and user payload are separate chat messages. No tools, batch API, Responses
API, code execution, or browser-side provider call is used.

Retrieved document text is supplied inside delimited `<source>` elements, labelled `S1`, `S2`,
and so on. The system prompt states that source content is untrusted data, never instruction. No
tools are offered to the model, so a document cannot cause a tool call. Citations are plain `[Sn]`
markers resolved in code against the exact set of sources supplied: a marker naming anything else
is stripped, counted, and surfaced as a note, and an answer left with no valid citation is
downgraded to "insufficient evidence" rather than published.

Every surviving citation carries the bill, the official document URL, the document version
number, the date we retrieved our copy, and the page range. A citation from a superseded version
is labelled as such on the page and in the API.

## Data handling

The application stores operational metadata only: model, latency, token counts, retrieved and
cited counts, and a non-reversible query fingerprint. It does not store raw questions or generated
answers.

vLLM is self-hosted within infrastructure controlled by the service owner. Therefore no
third-party retention arrangement, Claude-specific zero-data-retention assertion, or model
blacklist applies. `RAG_ZERO_RETENTION_CONFIRMED` is not part of the configuration.

The configured endpoint still receives each raw question and the retrieved parliamentary text
needed to answer it. Operators must keep `RAG_BASE_URL` pointed at the controlled vLLM service
and configure that service and its reverse proxy not to log request bodies. `RAG_API_KEY` should
be set when the endpoint is reachable outside an isolated private network.

## Consequences

The feature is inert until the embedding model, answer model, endpoint, and accepted evaluation
run are configured and recorded. It adds no answer-provider SDK dependency to the application
image. A provider outage or malformed response returns the retrieved passages and normal search
links rather than an error page. `RAG_ENABLED=false` leaves indexing, lexical search, bill pages,
and deployment untouched.
