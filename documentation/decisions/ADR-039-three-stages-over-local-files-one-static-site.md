# ADR-039: Three stages over local files, one static site, one Makefile

Status: accepted
Date: 2026-08-27

Supersedes the two-implementation arrangement ADR-021 introduced and ADR-029/031/033 built on.
Amends ADR-033 (the site tree), ADR-035 (local reading first, MinerU as cross-reference) and
ADR-022 (LLM-assisted AKN conversion).

## Context

Directed by the commissioner: *"this project has become way overcomplicated, reorganise for me.
My priority of the pipeline should be only local files for now. All serving should be static."*

The project had grown two complete implementations of overlapping work:

1. **The Postgres-backed system** — FastAPI, SQLAlchemy, Alembic, pgvector, an S3 gateway, a
   queue-driven crawler, lexical and semantic search, a RAG answer path, an audit tree. Roughly
   20,000 lines, and dormant: its own configuration comments said so.
2. **The file-first pipeline** (ADR-021) — the one actually being run, and the one that had
   produced the corpus of 1,265 stored PDFs and 1,253 markdown readings.

Both were held to the same quality gates and both had to be reasoned about on every change, against
a database no step in the live path touched. On top of that, publication had grown two surfaces
(`export-static` into `public-cache/`, `build-site` into `dist/`) projecting the same corpus through
the same rules, and the landing page was 884 lines of Python emitting inline CSS and JavaScript.

Measured before: 38,889 lines across `src/` and `tests/`, 180 source files, ~50 settings, 19
runtime dependencies, 96 test files.

## Decision

**1. The package is the pipeline, and its shape is the three stages.** `src/billwatcher/` becomes
`download/` (the only stage that touches the network), `markdown/`, `graph/`, and `publish/`, over
a shared spine of `store`, `files`, `frbr`, `provenance`, `reporting` and `verify`. The
`pipeline.` prefix goes: when the whole package is the pipeline, the word carries no information.

**2. The Postgres-backed stack moves to `legacy/`, frozen.** Not deleted — the design is worth
reading and the decisions behind it are cited throughout the code — but not built, not imported,
not linted, not tested, and its dependencies removed from the project. `legacy/README.md` records
what it was and that commit `b0bfb77` is the reliable point to revive it from.

**3. The pipeline runs on local files only.** The two steps requiring a remote model endpoint are
dropped: the MinerU cross-check (amending ADR-035's second tier) and LLM-assisted structure
extraction (amending ADR-022). Both have model-free equivalents already built — the geometric
reading, and the deterministic parser plus the `structure-handoff` packet — and both dropped steps
remain recoverable from `b0bfb77`.

   The cost is stated rather than hidden: the deterministic parser passes Gate P1 on **146 of 1,253
   documents (12%)**, against the Arrangement/body split the LLM path handled. `structure-handoff`
   is the route to closing that, and `documentation/status.md` records it as the project's open
   question rather than an accepted state.

**4. One publication surface, into `docs/`.** `export-static` and `build-site` collapse into
`publish`. GitHub Pages serves this repository's `docs/` directory, so `public-cache/` and `dist/`
both go. `pipeline-data/` becomes `corpus/`, which is what it is.

**5. `docs/` has two writers, and neither may delete the other's files.** `publish` owns `akn/`,
`definitions/`, `index.json`, `checksums.sha256` and `CNAME`; the frontend build owns
`index.html`, `404.html`, `assets/` and `.nojekyll`. The reconciliation that already scoped itself
to owned namespaces — so the tree could be pointed at a repository checkout without deleting
`.git/` — is what makes this safe, and it is now the normal case rather than an edge one.

**6. The landing page becomes a React application** (React 19, TypeScript, Vite, pnpm 7, oxlint,
oxfmt), building into `docs/` beside the dataset. It reads `index.json` and the published files
over HTTP — the same bytes at the same URLs any other consumer gets — so the page is a reader for
the dataset rather than a second, privileged representation of it.

   `404.html` is a copy of the application. Pages serves it for any path with no file behind it,
   which is exactly what an FRBR Work IRI is, so `/akn/my/bill/dr/2024/11` resolves in a browser
   while `/akn/my/bill/dr/2024/11/msa@.jsonld` is still served as the file it is.

**7. `SITE_PREFIX` is the single authority for the published domain.** It is written into `CNAME`
*and* is the base of every published FRBR IRI, validated once at configuration load as a bare
hostname.

**8. One Makefile is the build.** `make setup`, `make download` (live), `make build` (offline,
`markdown → akn → graph → publish → site`), `make check`. Both toolchains are locked — `uv.lock`
and `pnpm-lock.yaml`, with pnpm pinned by `packageManager` and fetched through corepack.

## Consequences

- **Measured after: 16,625 lines across `src/` and `tests/`, 36 source files, 16 settings, 6
  runtime dependencies, 28 test files, 395 tests passing.** Plus a frontend of 1,576 lines with its
  own 8 tests. The frontend's dependencies are locked separately and never enter the pipeline's.

- **`make build` over an unchanged corpus is 15 seconds, and writes nothing.** It was 11 minutes
  before: `extract-markdown` re-read every stored PDF and *then* discovered the result was
  identical, because the compare-before-write happened after the expensive part rather than before
  it. Making the provenance record the gate — its inputs are the source hash and the producer, both
  known without opening the PDF — is what makes "replicable build" mean a build you can afford to
  re-run.

- **A live defect was fixed as a side effect of decision 7.** The previously published graph
  carried `http://127.0.0.1:8000/…` as the base of its identifiers — the development value of the
  setting it was built with — so every published FRBR IRI dereferenced to nothing. Deriving the
  base from the validated hostname makes that unreachable rather than merely unlikely.

- **Publishing is now gated locally too, and that is stricter than before.** `docs/` is committed,
  so a local publish is one push from a permanent one; the rights confirmations are therefore
  required in every environment, not only production.

- **Two capabilities are genuinely gone from the running system**, and neither loss is cost-free.
  The MinerU cross-check was the only check that could judge a reading against the *page* rather
  than against itself, which Gate P1 structurally cannot do. `robots.txt` is still fetched and
  stored as evidence, but nothing enforces it any more: enforcement lived in the legacy crawler.
  Both are recorded as open in `documentation/status.md` rather than quietly absorbed.

- **`billwatcher/pipeline/site.py` was deleted without being moved to `legacy/`.** It was untracked
  at the time, so unlike everything else in `legacy/` it is not recoverable from git. What it
  encoded is not lost: its hostname contract is restated in `config.normalise_prefix` and pinned by
  the same cases its own test used, and the page it rendered is superseded by the frontend.

- **Repository growth becomes a live constraint.** Committing `docs/` means every rebuild that
  changes bytes adds a revision to history. ADR-031 flagged this and deferred it; nothing here
  settles it.
