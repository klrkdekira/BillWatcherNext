# BillWatcherNext

Bills of the Malaysian Parliament, downloaded as files, read into markdown, and published as a
semantic knowledge graph.

Three stages, one direction, no database and no server:

```
  Parliament  ──download──▶  corpus/  ──markdown──▶  corpus/  ──graph──▶  corpus/  ──publish──▶  docs/
                (live)                  (offline)               (offline)            (offline)
```

Everything after `download` is offline and re-runnable. Each stage reads files, writes files, and
records what it did beside what it produced — so a build can be interrupted, resumed, and audited
after the fact.

---

## End to end

Six steps, in order. Only step 3 touches the network; everything else is local, offline and safe to
re-run. Run `make` on its own for the full list of targets.

### 1. Prerequisites

| | |
| --- | --- |
| **Python** | 3.12.13 or newer, below 3.14. `uv` installs and pins it — you do not need a system Python. |
| **[uv](https://docs.astral.sh/uv/)** | Manages the Python toolchain and the locked dependency set. |
| **Node with corepack** | The repository pins no version; Vite 8 needs Node 20.19+, and it is built here on 24. `corepack` fetches the pinned pnpm 7.33.7, so whichever pnpm is on `PATH` does not matter. |

Nothing else: no database, no object store, no model endpoint.

### 2. Install and configure

```sh
git clone <this repository> && cd BillWatcherNext
make setup
```

`make setup` runs `make env` first, then installs both locked toolchains — `uv sync --locked` for
Python and `pnpm install --frozen-lockfile` for the frontend.

`make env` creates `.env` from `.env.development` if you do not already have one, and leaves an
existing `.env` alone. The development defaults are ready to build with: they confirm the two
publication rights so that `make publish` will run locally, since building the tree is how the
publish step is exercised at all. `.env.example` documents every setting with its shipped default,
and `src/billwatcher/config.py` is the authority.

Two values are worth setting deliberately before a real run:

- `CONTACT_EMAIL` — named in the crawler's User-Agent so Parliament can reach a person about a
  request. `ENVIRONMENT=production` refuses to start on the placeholder.
- `SITE_PREFIX` — the domain the published tree claims. See [Configuration](#configuration).

If you intend to crawl, do the certificate step now rather than fifty minutes in:

```sh
make ca-bundle      # then paste the line it prints into .env
```

Parliament serves an incomplete certificate chain; `make ca-bundle` builds a trust store containing
the intermediate it fails to send, and prints the `UPSTREAM_CA_BUNDLE=` line to add. There is
deliberately no setting that disables verification. See `documentation/upstream.md`.

### 3. Get a corpus

`make build` needs PDFs on disk. If `corpus/` already holds them, skip to step 4.

```sh
make download
```

This is the only step that contacts Parliament, and it is slow on purpose: requests are spaced by
`DOWNLOAD_DELAY_SECONDS`, floored at two seconds in code, and nothing fetches in parallel. It reads
every listing in **both published languages** — a cold run is roughly 134 listing snapshots and
~2,550 document requests, about an hour and a half. The last full document crawl fetched 1,219 PDFs
in 47 minutes.

**Interrupting it is safe, and re-running it resumes.** A closed archive year already stored is
skipped, and a document already in the corpus is not fetched again; the current listings and the
current year are always re-fetched, because that is how new bills are discovered. Every step
narrates itself on stderr.

Live steps refuse to run unless an operator says so in the same breath — `DOWNLOAD_ENABLED=true` in
`.env`, or `--approve-live`, which the Makefile passes for you.

```sh
make download-listings                  # just the listings and the archive tree
make download-documents                 # just the PDFs already named in the bills
make download ARGS=--archive-years=3    # only the newest N archived years
```

### 4. Build

```sh
make build
```

Offline, from the corpus to a complete `docs/`. It runs five steps in order, and each skips work
that is already current:

| Step | What it does | Roughly |
| --- | --- | --- |
| `make markdown` | Reads every stored PDF locally into markdown. No model in the loop. | 10 min for ~1,200 unread PDFs; **1 second** when nothing changed |
| `make akn` | Reads a provision structure out of that markdown and renders Akoma Ntoso, gated. | 10 s |
| `make graph` | Akoma Ntoso to ELI JSON-LD and RDF N-Quads. | seconds |
| `make publish` | Projects the gate-passing corpus into `docs/`. | 10 s |
| `make site` | Builds the React frontend into `docs/`, beside the dataset. | seconds |

Each is separately runnable. Every step prints one JSON object on stdout — pipe it into `jq` —
names each failure on stderr, and leaves a manifest under `corpus/manifests/<step>/` recording what
it did and which code versions did it.

`make build` finishes with `make coverage`, which writes `documentation/coverage.md`. That file is
tracked, so `git diff` after a build shows coverage moving.

### 5. Look at what you built

```sh
make dev        # the frontend against the published tree, with hot reload
make coverage   # what the corpus holds and what is missing; always exits 0
make verify     # re-hash the corpus against its own sidecars, provenance and gate verdicts
```

`make verify` is offline and writes nothing, which is what makes it safe to run between two steps
that do. It exits non-zero on any issue. A clean run certifies only what it can recompute from
stored files — it says nothing about whether a reading is a *correct* reading of the printed page.

The published tree is plain files, so `curl` and `jq` work as well as the browser does:

```sh
jq '{publication_mode, representations, works: (.works | length)}' docs/index.json
ls docs/akn/my/bill/dr/2024/11/          # msa@.md, eng@.md, and a graph if it passed the gate
```

### 6. Publish

`docs/` is a complete, self-contained tree: publishing is copying it into the repository that
serves <https://cheeleong.dev/data-parlimen/> and pushing there (or point `SITE_ROOT` at that
checkout and build in place). Before that, confirm the tree is what you think it is:

```sh
git status --short docs
jq '{publication_mode, representations}' docs/index.json
```

A path-hosted tree carries no `CNAME` — the domain belongs to whatever serves the root of
`cheeleong.dev`; a tree published at a domain apex gets one written from `SITE_PREFIX`.

A published tree may be mirrored and cannot be withdrawn. See
[Publishing is gated](#publishing-is-gated-in-every-environment) — the gate applies locally too,
because a local publish is one push away from a permanent one.

---

## Where it stands

From the last full build, over the real corpus:

| | |
| --- | --- |
| Bills | 1,273 |
| Documents stored | 2,484 of 2,552 referenced (68 absent upstream) |
| Markdown readings | 2,447 |
| Readings passing the fidelity gate | **146** |
| Published works | 1,207 — 2,341 expressions (1,192 Malay, 1,149 English) |
| — of those, with a JSON-LD/N-Quads graph | 139 |

The gate's pass rate is the open problem, and it is a property of the deterministic parser rather
than of the corpus: most rejections are the signature of a reader that cannot tell a bill's
Arrangement of Clauses from its body. Until it closes, this is a **complete corpus of readings with
a graph over a fraction of it**. `documentation/status.md` records the detail.

## What is where

| Path | What it is |
| --- | --- |
| `src/billwatcher/` | The pipeline. One package per stage: `download`, `markdown`, `graph`, `publish`. |
| `web/` | The React frontend: a static reader for the published files. |
| `docs/` | **The published site.** GitHub Pages serves this directory. Committed. |
| `corpus/` | The pipeline's own record: PDFs, markdown, structures, provenance. Local, never committed. |
| `tests/` | The Python suite. The frontend's lives in `web/src/__tests__/`. |
| `documentation/` | Decision records, operational notes, and the project's history. |
| `legacy/` | The Postgres/FastAPI stack this replaced, frozen where it stood. Not built, not imported. |

### The corpus on disk

The corpus *is* the record, not a projection of a database. Every artefact sits beside the bytes it
was derived from, with a provenance sidecar saying what produced it:

```
corpus/
  listings/<target>-<lang>/           one stored snapshot per fetched listing page
  bills/<bill-id>/bill.json           one record per bill
  documents/<bill-id>/<doc-id>/v001/
    document.pdf                      the stored bytes, verbatim
    metadata.json                     where they came from
    document.md                       the reading            + .markdown.provenance.json
    document.akn.xml                  the structure, if it passed the gate
    document.akn.rejected.xml         the structure, if it did not
    document.akn.gate.json            the gate's verdict     + .akn.provenance.json
    document.jsonld  document.nq      the graph              + .semantic.provenance.json
  manifests/<step>/<run-id>.json      what each run did, and which code did it
```

### The published tree

```
docs/
  akn/my/bill/dr/<year>/<number>/     msa@.md, eng@.md, msa@.jsonld, msa@.nq
  definitions/                        the AKN schema, the JSON-LD context, the vocabulary
  index.json                          the catalogue: every work, its expressions and their files
  checksums.sha256                    every published file, hashed
  CNAME                               only at a domain apex: written verbatim from SITE_PREFIX
  index.html  404.html  assets/       the compiled frontend, built against SITE_PREFIX's path
```

## The stages

**1. Download** (`src/billwatcher/download/`) — the only stage that touches the network. Fetches
Parliament's listings and the whole year-indexed archive **in both published languages**, parses
them into one record per bill, and downloads every document PDF named in those records. Malay and
English are two Expressions of one bill, not a page translated: the archive names `DR 17 BM.pdf`
and `DR 17 BI.pdf` (ADR-040). Every request goes through one rate-limited client; every response is
stored verbatim beside a sidecar saying where it came from. A document already in the corpus is not
fetched again.

**2. Markdown** (`src/billwatcher/markdown/`) — reads every stored PDF locally, with no model in
the loop. The reader is geometry-aware, which matters more than it sounds: a marginal note is
typeset on the same baseline as the provision it annotates, so a reader that joins lines by
position splices an annotation into the middle of the legal text. Each document is read in the
language of the listing that named it; `LANG_CODE` (default `ms`) is only the fallback for what
that leaves unsettled. Readings whose measured shape is far outside the corpus are counted as
`suspect` and named rather than hidden.

**3. Graph** (`src/billwatcher/graph/`) — reads a provision structure out of that markdown, renders
Akoma Ntoso XML on stable FRBR identifiers, and serialises the result as ELI JSON-LD and RDF
N-Quads from one graph, so the two cannot disagree.

Structure extraction has two model-free routes, and which one produced a reading is recorded rather
than blended away: `make akn` uses the deterministic parser, and `make handoff OUT=…` writes one
self-contained work packet per document for a coding agent or a person to answer, which
`make akn FROM=…` reads back through the identical conversion, gate and provenance path. See
`documentation/operations.md` for the rejection reasons and the handoff loop.

Either way, a reading that cannot account for the markdown it came from is rejected by the fidelity
gate and never reaches the published dataset. The rejected render is kept beside the verdict.

**4. Publish** (`src/billwatcher/publish/`) — projects the gate-passing corpus into `docs/`.

## Two writers, one directory

`docs/` is written by both halves of the build, and neither may delete the other's files:

| Owner | Entries |
| --- | --- |
| `make publish` | `akn/`, `definitions/`, `index.json`, `checksums.sha256`, `CNAME` |
| `make site` | `index.html`, `404.html`, `assets/`, `.nojekyll` |

Each reconciles only what it owns. The frontend build runs with `emptyOutDir: false` for exactly
this reason: emptying the directory would delete a corpus that took a live crawl to produce.

`404.html` is a copy of the app. GitHub Pages serves it for any path with no file behind it, which
is precisely what an FRBR Work IRI is — `/akn/my/bill/dr/2024/11` is a directory holding
`msa@.jsonld`, not a page. That copy is what makes the identifiers resolve in a browser while real
files still win over the fallback.

**A build is additive.** `make publish` reports files it no longer publishes and leaves them in
place; `make rebuild` deletes them. That default was bought expensively: a build run while the
corpus was mid-repair found nothing to emit and would have deleted the published tree that was, by
then, the only surviving copy.

## Publishing is gated, in every environment

A published tree may be mirrored and cannot be withdrawn, so `make publish` refuses unless the
rights decisions have been asserted — including locally, because `docs/` is committed and a local
publish is one push away from a permanent one.

- `PUBLISH_RIGHTS_CONFIRMED` — publishing at all.
- `FULL_TEXT_RIGHTS_CONFIRMED` — publishing the source document's own words. Required by
  `PUBLICATION_MODE=full`, and by publishing markdown at all, since markdown *is* the prose.

Both default to `false`, in `.env.example` and in the code. `.env.development` turns them on
because building the tree locally is how the publish step is exercised at all.

`PUBLICATION_MODE=metadata` publishes provision numbers, headings and the relationships between
them, with the text removed at the publication boundary. The redaction is a control that stays in
place whichever mode is configured, not a mode that deletes it.

## Configuration

Every setting lives in `.env`; `make env` creates one from `.env.development`. `.env.example`
documents all of them, and `src/billwatcher/config.py` is the authority — a value that cannot work
fails when configuration loads, not fifty minutes into a download.

`SITE_PREFIX` is worth singling out. It is where the tree is served — a bare domain
(`bills.example.my`), or `host/path` for a GitHub Pages project repository
(`cheeleong.dev/data-parlimen`) — and it is the base of every published FRBR IRI, so a citation in
the dataset dereferences to the page that serves it. At a domain apex it is also written verbatim
into `CNAME`; under a path no `CNAME` is written, and the path becomes the frontend's base URL.
It is one setting for all of that because a domain configured twice is a domain that will
eventually disagree with itself.

## Development

```sh
make check     # ruff, strict mypy, pytest, oxlint, tsc, vitest, oxfmt
make format    # ruff format and oxfmt
make verify    # re-hash the corpus against its own sidecars, provenance and gate verdicts
```

`make check` covers both toolchains and touches neither `corpus/` nor `docs/`: the test suite pins
every writable root into a temporary directory, because a test once wrote a full publication into
the working tree.

## Going further

| | |
| --- | --- |
| `documentation/operations.md` | Running the pipeline: the live crawl, the gates, what to do when a step fails. |
| `documentation/status.md` | Where the project actually stands, and what is open. |
| `documentation/data-model.md` | The corpus layout, FRBR identity, and what the published graph asserts. |
| `documentation/upstream.md` | What Parliament's site does, including the incomplete certificate chain. |
| `documentation/decisions/` | Architecture decision records, ADR-001 onward. |
