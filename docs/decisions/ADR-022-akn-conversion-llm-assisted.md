# ADR-022: The Akoma Ntoso conversion step reads structure with an LLM, not regex alone

Status: accepted
Date: 2026-08-21

## Context

ADR-021 established the file-first pipeline (listings → bills → documents) behind a
`PipelineStore` interface. The natural next step — directed as "next up for pipeline after
markdown conversion is conversion to the oasis format" — is converting each document's markdown
(produced elsewhere, per ADR-021, out of this pipeline's scope) into Akoma Ntoso (OASIS
LegalDocML) XML, the standard HANDOFF 26.4 already specified for a later stage of the
Postgres-backed pipeline.

A first version was built using only `billwatcher.legislation.vocabulary` — the Bahagian/Part,
Seksyen/Section, Fasal/Clause vocabulary and eId-prefix table already written for the (dormant)
Postgres-backed Stage L1 reading — driving a hand-written regex line classifier
(`parse_markdown_structure`). It worked for constructed test markdown, but it has one structural
limitation regex cannot solve without a signal markdown does not carry: a document's Arrangement
of Sections (table of contents) is textually identical to the body provisions it lists
(`5. Kewajipan untuk melaporkan` appears twice — once in the table of contents, once as the real
provision). Stage L1 solved the equivalent problem with a two-tree comparison because it had
page/geometry signals to split the Arrangement from the body on; markdown has neither.

Mid-session direction: "Akoma Ntoso XML parsing should use the help of the vllm server." The
operator already has a vLLM OpenAI-compatible endpoint (`https://llm.loqasi.io/v1`, used
elsewhere in this project for a different concern). Reading legislative structure out of
free-form markdown — recognising a table of contents contextually, telling a subsection from a
paragraph when the printed token is ambiguous — is exactly the kind of understanding task an LLM
is suited for and a regex is not.

## Decision

1. **Structure extraction is behind a `MarkdownStructureExtractor` protocol**
   (`pipeline.akn.MarkdownStructureExtractor`): one method, `extract(markdown_text, *, unit) ->
   Node`. `VllmMarkdownStructureExtractor` (`pipeline.akn_llm`) is the production implementation;
   `RegexMarkdownStructureExtractor` wraps the original regex parser and remains available for
   tests and for explicit offline use with no LLM configured — never as a silent production
   fallback. `convert_to_akn` takes an extractor injected, the same dependency-injection shape
   this project already uses for `EmbeddingProvider`, `AnswerProvider`, and `PageBlockExtractor`.
2. **What an extractor returns is structure only — type, printed number, heading, body text,
   nested children. It never assigns an eId.** `pipeline.akn.assign_eids` computes every eId
   deterministically from a node's own `node_type`/`num` and its parent's eId, applied uniformly
   after either extractor runs. This is the same discipline HANDOFF 26.2 requires of `wId`: an
   identifier is never guessed or invented by a model, only computed from what was actually
   printed.
3. **The vLLM call is a plain `httpx` request to `POST {base_url}/chat/completions`** — no
   vendor SDK, matching the existing `OpenAICompatibleAnswerProvider` pattern
   (`search/rag.py`) rather than introducing a new one. `response_format: {"type": "json_object"}`
   and a system prompt built from `legislation.vocabulary.NODE_LABELS` (so the vocabulary has
   exactly one source of truth) ask for the provision tree as JSON; `temperature: 0` because
   structure extraction should be as repeatable as an LLM call can be made.
4. **Configuration is separate from every other endpoint this project talks to**
   (`AKN_LLM_ENABLED`/`AKN_LLM_BASE_URL`/`AKN_LLM_MODEL_ID`/`AKN_LLM_API_KEY`), not reused from
   `RAG_*` (a different, Postgres-backed feature, currently dormant) or `MINERU_*` (a different
   model, for a different purpose). `build_structure_extractor` refuses outright when
   unconfigured — no silent regex fallback in production use.

## What a live smoke test found

Run once, by hand, against the real endpoint (`https://llm.loqasi.io/v1`, model `qwen-3.8-27b`)
— not part of the automated suite, mirroring this project's `test-live` pattern for a different
third party. Two things worth recording:

- **The model correctly solved the Arrangement/body problem this ADR exists for**, and did
  something the regex parser cannot: it placed a Part's title text (`PERMULAAN`, printed on its
  own line beneath `BAHAGIAN I`) into the part's own `heading` field by contextual understanding,
  rather than as a stray leading paragraph the way the regex parser reads it.
- **A real bug**: the model's first response wrapped every parenthesised token in its own
  printed punctuation — `"(1)"`, `"(a)"`, `"(i)"` instead of `"1"`, `"a"`, `"i"` — despite the
  prompt's instruction not to, which would have poisoned every eId beneath those nodes with
  literal parentheses (`subsec_(1)__para_(a)`). Fixed two ways: the prompt now states the rule
  with worked examples, and `_normalize_num` strips enclosing parentheses and a trailing period
  defensively regardless of what the model returns — because a model instruction is a request,
  not a guarantee, and eId correctness must not depend on the model always following it. Both
  fixes are pinned by tests; the second is what actually matters, since prompts drift and code
  does not.

## Consequences

- `pipeline.akn`'s `Node`, `render_akn`, and `assign_eids` are the only parts of this feature that
  are, and will remain, fully deterministic. Swapping the model, the prompt, or the extractor
  implementation never changes how a given tree becomes eIds or XML.
- The regex extractor's known Arrangement/body limitation (its own module docstring) is not
  fixed by this ADR — it is superseded for production use by the LLM path, which does not share
  that limitation, rather than patched.
- This is the third time in one session a vendor- or model-specific concern was kept out of step
  logic by an explicit protocol (`PageBlockExtractor` in ADR-020, `PipelineStore` in ADR-021, now
  `MarkdownStructureExtractor`). Reaching for this shape by default, for any future step that
  needs an external model or service, is now this project's default rather than a case-by-case
  decision.
- Nothing here touches a database or object store. `billwatcher.pipeline` remains file-only, per
  standing direction; a future database-backed `PipelineStore` is unaffected by any of this ADR's
  decisions, since none of them depend on the store implementation.
