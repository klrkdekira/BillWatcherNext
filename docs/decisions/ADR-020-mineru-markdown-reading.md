# ADR-020: A MinerU vision-language markdown reading, as a local file artifact only

Status: accepted
Date: 2026-08-21

## Context

Directed on 2026-08-21: parse stored bill PDFs with a hosted MinerU instance
(`https://mineru.loqasi.io`) and produce markdown, kept local-file-based like the audit tree
built for the PDF download step (ADR-019).

MinerU2.5 is a 1.2B-parameter vision-language document-parsing model. The hosted instance serves
`opendatalab/MinerU2.5-Pro-2605-1.2B` behind a standard vLLM OpenAI-compatible Chat Completions
API — confirmed by querying `/v1/models`, `/version`, and `/openapi.json` directly. It reads a
*page image*, not a PDF; the exchange with the model (prompt template, sampling parameters per
block type, table-image masking) is intricate enough that the model's own maintainers ship
`mineru-vl-utils`, a thin official client, and warn against reimplementing it by hand.

The model's output is a list of `ContentBlock` objects — `type` (`text`, `table`, `equation`,
`title`, `header`, …), a normalised `bbox`, and `content` (recognised text, an HTML table, or
LaTeX) — not markdown directly. Assembling that into markdown is this project's own code, not the
vendor's.

Three things this project already knows shaped the design:

- **A second extraction tier will be silently destroyed if it writes to `document_extractions`.**
  `persist_current_extraction` demotes every `is_current` row for a version regardless of
  extractor name, and retention's pruning does not partition by extractor either (TODO 2.4). Stage
  L1 avoided this by writing to its own tables (ADR-016); the same hazard applies here.
- **`mineru-vl-utils`'s `http-client` backend builds its own internal `httpx.Client` with no
  injection point**, and construction itself issues a live request to check or discover the
  served model name. There is no way to point it at a test transport.
- **ADR-016 already set the bar for a rendering dependency**: permissively licensed, no imaging
  stack pulled in for its own sake. The same bar applies to whatever rasterises a PDF page to the
  image MinerU needs.

## Decision

1. **The vendor client is used, not reimplemented.** `mineru-vl-utils` (base install, no `vllm`
   extra — the `http-client` backend needs only `httpx`, `httpx-retries`, `pydantic`, `pillow`,
   `loguru`, `aiofiles`, `tqdm`) talks to the hosted endpoint over its documented HTTP contract.
2. **Pages are rendered with `pypdfium2`** (BSD-3-Clause/Apache-2.0), the same reasoning ADR-016
   used to reject PyMuPDF (AGPL) for the layout reader.
3. **The vendor client is wrapped behind `PageBlockExtractor`, a project-owned protocol**
   (`billwatcher.mineru.client`), exactly the shape `EmbeddingProvider` and `AnswerProvider`
   already use. Jobs depend on the protocol and take a real (`MineruHttpExtractor`) or fake
   implementation injected; no test in this project constructs the vendor client, and no test
   makes a live network call. The one deliberate exception is a smoke script run once, by hand,
   against `https://mineru.loqasi.io` — not part of the automated suite, mirroring this project's
   own `test-live` opt-in pattern for Parliament.
4. **The markdown assembly is this project's code** (`billwatcher.mineru.markdown`), trusting the
   order the model returns blocks in — its own two-stage layout analysis already determines
   reading order, and re-deriving one from bounding boxes is exactly the kind of naive assumption
   that breaks on multi-column legislative typesetting. Furniture types (`header`, `footer`,
   `page_number`, `page_footnote`) are dropped; math is wrapped in `$$…$$`; tables pass through as
   the HTML the model already returns; `merge_prev` joins a continuation onto the previous
   paragraph rather than starting a new one.
5. **The reading is written only as a local file artifact, never into `document_extractions`.**
   `billwatcher.jobs.mineru_extract` writes `document.md` plus a sidecar under
   `data/04-text/<bill-slug>/<doc-key>/v<NNN>/mineru@<version>/`, using the same `AuditTree`
   write-if-changed machinery the PDF tier uses (HANDOFF 27.2, 27.7). Eligibility for
   `mineru-extract` — has this document version already been read? — is decided by whether that
   file already exists, not by a database row, since nothing about this reading needs the
   database at all.
6. **A quarantined download still gets a directory when it was actually attempted** — the same
   philosophy as the document tier: a status is a fact about what happened, not something to hide
   by omission. The extraction status (`succeeded`/`empty`/`failed`) is recorded in the sidecar.
7. **The endpoint is configuration, gated off by default** (`MINERU_ENABLED`, `MINERU_BASE_URL`,
   optional `MINERU_MODEL_NAME`/`MINERU_API_KEY`), because sending official document images to a
   third-party inference host is a data-handling decision the same way ADR-009 treated the RAG
   endpoint, not a default.

### Alternatives rejected

- **Writing to `document_extractions` with `extractor_name = "mineru"`.** Rejected outright: it
  would trip the exact single-writer landmine TODO 2.4 already documents, silently demoting the
  native `pypdf` extraction's `is_current` flag the first time this job ran.
- **Re-deriving reading order from `bbox` instead of trusting block order.** Considered because it
  would make the assembler independent of model behaviour, but rejected: the model's own layout
  stage is a two-column-aware document understanding step, and a naive top-to-bottom,
  left-to-right sort would get exactly the multi-column and marginal-note cases wrong that this
  project's own Stage L1 work already spent real effort getting right for a different reader.
- **Converting HTML tables to markdown table syntax.** Rejected for now: markdown tables cannot
  represent merged cells, which MinerU's table recognition can already produce; passing the HTML
  through unchanged loses nothing, and CommonMark renderers accept raw HTML blocks.

## Consequences

- `document_structures` (Stage L1) and this MinerU reading are now two independent "second
  readings" of the same stored bytes, each avoiding the `document_extractions` landmine its own
  way — Stage L1 with its own tables, this one with the audit tree. Neither blocks the other.
- The audit tree gains a documented shape for `04-text/`, previously specified in HANDOFF 27.2 but
  unbuilt; `03-documents/` and `04-text/` now share one `AuditTree` class and one sidecar
  determinism guarantee.
- `mineru-extract` is deliberately not part of the scheduled worker loop or `make pipeline`: it
  costs a real network call and, on a hosted "instant" endpoint, likely a real cost per document.
  It runs only by explicit CLI/Make invocation, the same way `reextract`/`restructure` do.
- Nothing here reduces confidence in the pypdf-based extraction that lexical search already
  depends on; that path is untouched. A future decision about whether MinerU's markdown should
  ever feed search, chunking, or Stage L2 is explicitly out of scope for this ADR.
