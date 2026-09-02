# Operations

Running the pipeline. `README.md` describes what the stages are; this is what to do with them.

The runbook for the previous Postgres-backed stack — migrations, backups, compose, nginx, the
2026-08-18 security review — is preserved at `history/operations-postgres-stack.md`.

## The one live step

`make download` is the only thing here that contacts Parliament. It is slow on purpose: requests
are spaced by `DOWNLOAD_DELAY_SECONDS`, floored at two seconds in code, and nothing fetches in
parallel. The crawl reads every listing in both published languages (ADR-040), so a cold run is
~137 listing documents and an expected ~2,400 document requests — roughly an hour and a half. A
corpus that already holds the Malay half pays only for the English one: closed Malay archive years
and stored PDFs are skipped.

```sh
make download                      # listings, bills, then every document PDF
make download-listings             # just the listings and the archive tree
make download-documents            # just the PDFs already named in the bills
make download ARGS=--archive-years=3   # only the newest N archived years
```

Live steps refuse to run unless an operator says so in the same breath: `DOWNLOAD_ENABLED=true` in
`.env`, or `--approve-live`, which the Makefile passes for you.

**It is resumable, and interrupting it is safe.** A closed archive year already stored is skipped;
a document already in the corpus is not fetched again. The current listings, the archive indices
and the current year are always re-fetched, because they are how new bills are discovered. Every
step narrates itself on stderr — without that, a fifty-minute run's first output arrived fifty
minutes in, which is indistinguishable from a hung process.

**`parse-listings` can report `listings_wrong_language`.** Parliament's language follows the session
that serves the request, so a `lang=en` request is occasionally answered with a Malay page. Such a
snapshot is named with its URL and merged from not at all, rather than filing Malay titles as
English (ADR-040). The fix is to re-run `make download-listings`; the count staying non-zero across
runs means upstream has changed how it selects a language, and the English targets in
`download/targets.py` are where to look.

If the run fails on certificate verification, see `upstream.md`: Parliament serves an incomplete
chain, and `make ca-bundle` builds a trust store containing the intermediate it omits. Point
`UPSTREAM_CA_BUNDLE` in `.env` at what it writes — the crawl reads `.env`, so leaving the setting
blank there fails every target while `.env.development` looks correctly configured.

**A live step that reached nothing at all exits non-zero.** A partial failure does not: a handful of
unreachable targets in a 2,400-document crawl is expected, and the next run picks them up. But
`make download` runs the listings step and then the documents step, so a step that stored nothing —
which in practice means a trust store or a network that is not set up — has to stop the chain rather
than send the next step out over the same broken setup.

## The offline build

```sh
make build      # markdown → akn → graph → publish → site
```

Each step is separately runnable and re-runnable, and each skips work that is already current:

| | |
| --- | --- |
| `make markdown` | Read every stored PDF into markdown. Each document is read in the language of the listing that named it; `LANG_CODE` (default `ms`) is only the fallback for what that leaves unsettled, and the step counts how much of the run leaned on it (ADR-040). |
| `make akn` | Read a provision structure and render Akoma Ntoso, gated. |
| `make graph` | Akoma Ntoso to ELI JSON-LD and RDF N-Quads. |
| `make publish` | The gate-passing corpus into `docs/`. |
| `make site` | The React frontend into `docs/`. |

Every step prints one JSON object on stdout — pipe it into `jq` — and names each failure on
stderr. Every step also leaves a manifest under `corpus/manifests/<step>/` recording what it did
and which code versions did it.

## Coverage

```sh
make coverage      # or: billwatcher coverage --markdown documentation/coverage.md
```

Runs automatically at the end of `make download` and `make build`, and is safe to run at any time:
it is offline, writes nothing into the corpus, leaves no manifest and **always exits 0**. A report
is not a gate — "the English half is unread" is a finding to act on, not a reason to fail a build
that described itself accurately.

Counts are per stage and per language, never rolled into one figure. A corpus 97% downloaded and
50% read is not 73% anything, and the three reasons a document is not where you want it need
different responses:

| | |
| --- | --- |
| **stored** | the steps already report this |
| **absent upstream** | not recoverable by running anything again; re-attempting it costs a politeness slot per document on every future crawl |
| **not yet run** | the only part anybody can act on |
| **no text layer** | an image-only scan; the local reader found nothing and correctly wrote nothing, so re-running it will never help |

That last row is the one a corpus cannot answer on its own: nothing is written for a reading that
produced nothing, so `coverage` reads the newest `extract-markdown` manifest to recover the verdict
(ADR-019). It is applied only to a document that is *still* unread, so a stale manifest naming a
document since read changes nothing.

`documentation/coverage.md` is the written report and is tracked, so `git diff` after a build shows
coverage moving. Everything above the horizontal rule is byte-identical between two runs over the
same corpus — the timestamp sits in the footer for exactly that reason, and named example URLs live
in the report rather than in the JSON so stdout stays one pipeable object.

Two findings it reports that no per-step count can: an archive **year** one language's tree lists
and the other's does not (those bills were never listed, so nothing in the corpus knows to miss
them), and two promoted documents of one bill claiming a single Expression IRI.

## When the gate rejects a document

Gate P1 asks whether a provision tree accounts for the markdown it was read from. A rejection is
not a bug to route around: the rejected render is written to `document.akn.rejected.xml` beside a
verdict in `document.akn.gate.json`, and no `document.akn.xml` appears for later steps to pick up,
so a reading nobody has checked cannot reach the published dataset.

The common rejection reasons, and what they mean:

| Reason | What the reader did |
| --- | --- |
| `duplicate_eid` | Read the same provision twice — usually the Arrangement of Clauses *and* the body. |
| `sequence_gap` | Missed provisions between two it found. |
| `sequence_order` | Emitted provisions out of their printed order. |
| `unanchored_run` | Produced a run of provisions with nothing tying them to the document's structure. |
| `mismatch` (coverage) | The tree accounts for less of the markdown's vocabulary than `AKN_GATE_MIN_TEXT_COVERAGE`. |

The first four are the signature of the deterministic parser meeting a document whose Arrangement
it cannot separate from its body. The route through is a handoff:

```sh
make handoff OUT=var/handoff      # one work packet per document
# answer the packets: each holds the markdown and an INSTRUCTION.md naming the JSON to write
make akn FROM=var/handoff         # read the answers back through the identical gate
make graph && make publish
```

Answers are matched to documents **by the hash of the markdown they were read from**, never by
filename. An answer written against edited text is refused rather than misattributed. Existing
answers are preserved across re-runs unless `--overwrite-answers`: the answer is the expensive
part.

## Checking the corpus

```sh
make verify              # re-hash everything against its own sidecars and provenance
make verify ARGS=--strict   # also report artifacts that are stale rather than damaged
```

Offline, writes nothing, exits non-zero on any issue — which is what makes it safe to run between
two steps that do. A clean run certifies only what it can recompute from stored files. It says
nothing about whether a reading is a *correct* reading of the printed page; that is Gate P1's
separate and weaker judgement, and the cross-check that could answer it properly was dropped in
ADR-039.

## Publishing

`make publish` refuses unless the rights confirmations are set — in every environment, because
`docs/` is committed and a local publish is one push from a permanent one. See the README.

**A build is additive.** Files the build no longer publishes are reported by name and left in
place. `make rebuild` deletes them, and that is the only way they go:

```sh
make rebuild    # markdown → akn → graph → publish --prune → site
```

The default exists because a build run while the corpus was mid-repair found nothing to emit, and
would have deleted the published tree that was by then the only surviving copy of it.

To publish, commit `docs/` and push; GitHub Pages serves it from this repository. Before doing so,
confirm the tree is what you think it is:

```sh
git status --short docs
python3 -c "import json; d=json.load(open('docs/index.json')); \
  print(d['publication_mode'], d['representations'], len(d['works']), 'works')"
cat docs/CNAME
```

## Quality gates

```sh
make check    # ruff, strict mypy, pytest, oxlint, tsc, vitest, oxfmt
make format   # ruff format and oxfmt
```

`make check` covers both toolchains and touches neither `corpus/` nor `docs/` — the test suite
pins every writable root into a temporary directory, because a test once wrote a full publication
into the working tree.
