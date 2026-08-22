# Operations

## Getting a local instance running

```bash
make quickstart
```

That is `setup` → `env` → `db-up` → `migrate` → `seed` → `serve`, and it needs no network access
to Parliament. `make env` writes `.env` from `.env.development` only if `.env` is absent, so it
never overwrites a configured environment. `make db-up` starts `compose.dev.yaml`, which is a
development-only PostgreSQL published on `127.0.0.1:55432` and is not the production stack; it
also creates the `billwatcher_test` database that `make test-pg` uses.

`make seed` runs `billwatcher load-fixtures`: the committed listing fixtures are ingested as a
`fixture`-mode scrape run with real snapshot, blob, and coverage provenance, so browse, search,
bill detail, chamber timelines, `/changes`, and `/status` all have truthful content. It is
idempotent — a second load inserts nothing and records no changes — and it refuses to run against
`ENVIRONMENT=production` without `--confirm-production`.

`CONFIRM_RESET=yes make db-reset` deletes the development database and its volume.

Every operator action is a Make target. `make help` lists them. No default target crawls the live
Parliament site or deletes data, and every mutating backfill is a dry run unless `ARGS=--apply`
is passed.

Outstanding work is tracked in [`TODO.md`](../TODO.md).

## Daily and release gates

| Command | What it proves |
| --- | --- |
| `make check` | lint, strict type check, and the whole offline suite |
| `make doctor` | non-zero while any unresolved critical anomaly exists, a current document version is not accepted, or a recorded blob is missing or corrupt |
| `make status` | per-target freshness, queue depth, latest run, pipeline versions |
| `make verify-storage` | every database blob reference exists on disk, and no orphan bytes exist |
| `billwatcher pipeline verify` | the file-first pipeline's own store: every artifact matches the record of what produced it, nothing is stale, nothing unexplained is on disk. Independent of the database, so it says nothing about the four rows above |

`make doctor` is the release and daily-operations gate that stands in for CI. There is no GitHub
workflow in this repository by design.

## PostgreSQL-only tests

The offline suite runs on SQLite. Behaviour that only exists on PostgreSQL — the weighted
`tsvector`, `websearch_to_tsquery` ranking, `ts_headline` snippets, and pgvector cosine retrieval
— runs only when a disposable database is supplied:

```
BILLWATCHER_TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/billwatcher_test \
  uv run pytest tests/integration/test_postgres_search.py tests/integration/test_postgres_semantic.py
```

The fixture drops and recreates the `public` schema and migrates to head, so never point it at a
database you care about. Without the variable the tests skip with a message.

## Migrations

`make migrate` upgrades to head. A fresh, empty database reaching head is proven automatically by
the PostgreSQL fixture above, which drops and recreates the schema before every session.

Downgrade policy: downgrades are for disposable development databases only. Migration 0001's
downgrade drops every table, and no downgrade path is supported against a database holding real
archive data — recovering from a bad migration in production means restoring the database and the
blob store together, not stepping backwards.

## Crawling

Live crawling is off by default and gated behind `SCRAPE_ENABLED` plus an explicit
`--approve-live` flag. Before the first crawl, complete the discovery gates in `docs/upstream.md`:
robots.txt and its hash, the archive request contract, the bilingual label and status sweep, TLS
verification from the deployment host, and the configured contact identity.

- `make scrape` — one approved incremental run. Current listings only; it does not touch the
  archive, because re-reading 67 documents of closed history every twelve hours is impolite and
  pointless.
- `make scrape-archive` — one approved archive run: the year index for each chamber, then every
  year it offers (ADR-014). `ARGS=--archive-years=3` reads only the newest years, which is the
  only cheap archive refresh that means anything.
- `make scrape-full` — current listings and the whole archive in one run, with the archive's own
  larger budget. The first such run introduces about 2,000 documents into the queue at once,
  which is why `ARCHIVE_MAX_NEW_DOCUMENTS` exists; under the incremental limit the run would end
  `partial` and withhold every year it had just read.
- `make reparse` — replay stored snapshots offline at the current parser version; dry run by
  default. At an unchanged parser version this must report zero changes.
- `make fixtures-refresh` — regenerate the committed fixtures from stored snapshots, offline.
  Writes to `tests/fixtures/parliament/regenerated/` for review; `ARGS=--apply` overwrites the
  committed files. It never contacts Parliament: the only input is a snapshot already stored.
- `make fetch-documents` — step S3 of the auditable pipeline (HANDOFF 27): drains the document
  fetch queue, gated behind the same `SCRAPE_ENABLED`/`--approve-live` rule as the listing crawls
  because it issues live requests to the same allowlisted host. Every accepted or quarantined
  download is written into the audit tree as it happens, one manifest per run.
- `make audit-rebuild` — offline. Regenerates the document tier of the audit tree from the
  database and blob store; a no-op over an already-correct tree, so it is also the recovery path
  after deleting `AUDIT_TREE_ROOT` and the backfill path after a sidecar schema bump.
- `make verify-audit` — offline. Re-hashes the audit tree against the database and exits non-zero
  on any divergence, raising the `audit_tree_divergence` anomaly `make doctor` reads.
- `make reextract` — additive re-extraction of current document versions.
- `make mineru-extract` — a second, independently versioned markdown reading via a hosted MinerU
  vision-language model, written only as a local file artifact under `data/04-text/`; dry run by
  default. Needs `MINERU_ENABLED=true` and `MINERU_BASE_URL` set, since it sends page images to a
  configured third-party endpoint over the network — that is a data-handling decision (ADR-020),
  so nothing here defaults it on. Eligibility is whatever markdown does not already exist on disk,
  so a repeat run costs nothing for a document already processed.
- `make restructure` — additive Gate L1 structural reading of current, accepted document
  versions, offline from stored bytes; dry run by default. A reading that fails the gate is
  stored for review and is never promoted; a failing re-read never withdraws one that passed
  (§26.3). `/status` reports the corpus-wide outcome histogram.

### The file-first pipeline and the legislation corpus

A second, independent pipeline (HANDOFF 28, ADR-021) keeps its whole record in `PIPELINE_DATA_ROOT`
— no database, no blob store — and produces the legislation corpus: Akoma Ntoso XML, ELI JSON-LD and
RDF N-Quads per document. Nothing in it touches the Postgres-backed system above, and nothing above
touches it.

| Command | What it does | Network |
| --- | --- | --- |
| `make pipeline-fetch-listings` | step 1: listings into the file store; gated behind `SCRAPE_ENABLED`/`--approve-live` like `scrape`, because it hits the same live host | live |
| `make pipeline-parse-listings` | step 2: stored listings into `bills/<slug>/bill.json` | none |
| `make pipeline-fetch-documents` | step 3: download every document URL found in those bill records; same live gate | live |
| `billwatcher pipeline import-markdown` | step 3b: put a markdown file produced by your own extraction into the store, **with its language declared** (`--language ms\|en`). The language becomes a permanent part of every published identifier (ADR-024), so it is an argument rather than a guess | none |
| `make pipeline-convert-to-akn` | step 4: markdown → Akoma Ntoso, behind Gate P1 and schema validation. Needs `AKN_LLM_ENABLED=true`, `AKN_LLM_BASE_URL`, `AKN_LLM_MODEL_ID` | live (vLLM) |
| `make pipeline-generate-semantic` | step 5: Akoma Ntoso → ELI JSON-LD + RDF N-Quads | none |
| `billwatcher pipeline verify` | offline integrity pass: every artifact re-hashed against the provenance record of what it was built from, every stale artifact named, and every file no step writes reported | none |

Two properties worth knowing before running any of them. **A repeat run writes nothing** — each
derived artifact carries a provenance record naming its inputs, and a step rebuilds only when those
inputs changed (ADR-026), so re-running a step after a code upgrade regenerates exactly what the
upgrade affected and leaves the rest alone, including its mtimes. And **a document that fails Gate
P1 is kept, not discarded**: its verdict lands in `document.akn.gate.json` and the rejected render in
`document.akn.rejected.xml`, and no `document.akn.xml` is written, so nothing downstream can pick it
up (ADR-025). `billwatcher pipeline convert-to-akn` prints the counts and names every failure on
stderr; the same is on disk in `manifests/<step>/<run-id>.json`.

The gate's one threshold, `AKN_GATE_MIN_TEXT_COVERAGE` (default 0.95), is **uncalibrated**: it has
never run against Parliament's real typesetting. If a first real batch rejects a large fraction of
documents, read the verdicts before changing the number — `low_text_coverage` alone on a short
document may be structural furniture, while `sequence_order` beside it is the table-of-contents bleed
the gate exists to catch.

#### Publishing the corpus

`SERVE_LEGISLATION_CORPUS` is `false` by default, and every corpus path returns 404 while it is.
Turning it on is a sequence of recorded decisions, not a flag flip (ADR-027):

1. Build the corpus and run `billwatcher pipeline verify` clean. For the first real corpus, the
   whole sequence — including reading Gate P1's verdicts before trusting them — is the runbook in
   `docs/first-corpus-run.md`.
2. The rights decision is **made and recorded** (gate log, 2026-08-22): the owner determined that
   Parliament bills are public information, covering both the structural corpus and provision text.
   The confirmation flags below assert that record; they never substitute for it.
3. Set `SERVE_LEGISLATION_CORPUS=true` **and** `LEGISLATION_CORPUS_RIGHTS_CONFIRMED=true`.
   Production refuses to boot with the first and not the second.
4. For provision text, set `LEGISLATION_PUBLICATION_MODE=full`, which additionally requires
   `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true` — the A14 confirmation that also gates
   `SERVE_ARCHIVED_DOCUMENTS`, now likewise covered by the recorded determination. `metadata`
   remains the shipped default and the posture the deployment falls back to if the determination is
   ever revisited.
5. Neither flag needs a rebuild. Redaction happens when a response is rendered, so both directions
   are reversible and neither costs a re-extraction.

The `app` container mounts `PIPELINE_DATA_ROOT` **read-only**: the pipeline steps write it and are
run deliberately, and the serving process only reads. Do not treat it like the audit tree below just
because both are directory trees — the audit tree is a projection and `make audit-rebuild`
regenerates it, while this store **is the record** and nothing can rebuild it. Losing it means
re-crawling Parliament and re-running the extraction. Back it up as data if the corpus matters to
you; HANDOFF 16.4 leaves that a deployment decision rather than a contract, because the corpus is
not yet built anywhere.

### The audit tree

`AUDIT_TREE_ROOT` (default `data/` in development, `/var/lib/billwatcher/audit` in the container
image) holds a human-legible projection of the archive: every downloaded document version's raw
PDF beside a `metadata.json` naming its source URL, language, retrieval time, hashes, and the bill
it belongs to (HANDOFF 27). It is scoped to `03-documents/` today — Package K covers the PDF
download step only; the listing and processing tiers are specified but not built.

It is **not** part of the backup contract. It is a derived, rebuildable projection of the database
and blob store — `make audit-rebuild` regenerates it byte-for-byte — so deleting it, or losing the
volume, loses nothing the database and blob-store backups do not already cover. Run
`make verify-audit` after a restore drill or a suspected disk issue; a clean result only certifies
the document tier it checks.

The scheduled worker (`billwatcher worker`, the `worker` service in Compose) runs incremental
crawls only, because HANDOFF 11.7 makes the archive an explicitly triggered mode. Nothing refreshes
the archive automatically; if you want it refreshed, schedule `make scrape-archive` on the host —
monthly is generous, since a year that has closed cannot change.

That is also why a closed archived year has no freshness expectation at all: its coverage row
carries `expected_interval_hours = 0`, which `/status` treats as "not expected to be read again".
Only the newest archived year, which can still gain bills, can go stale — one meaningful alert per
chamber instead of sixty-six meaningless ones. The orchestrator re-sets this on every archive run,
so last year's newest year closes when the index gains a node.

`make completeness` reuses that same "closed" signal to check something different: whether a
chamber-year's bill numbers run without a hole (`DR-1`, `DR-2`, `DR-3`, …). It only looks at years
whose archive coverage target is closed, because an open year is still growing and a "gap" in it
is just a bill nobody has fetched yet, not evidence of anything missing. It is a heuristic report
for a human to check against the archive — it raises no anomaly and does not affect `make doctor`
— because nothing in the assumption register claims Parliament's numbering has no legitimate
gaps. Run it after a full archive crawl of years you have not checked before; it has not yet been
run against the real corpus, only against synthetic data in tests, because the real corpus is not
reachable from a clean checkout (the same limitation as the Gate L1 pass-rate measurement,
`TODO.md` §1.8).

An archive run reads about 70 documents over several minutes, so a dropped connection is ordinary
rather than exceptional. Transport failures are retried, and a year that still cannot be read
degrades that one year on `/status` while the rest publish. If a run reports `partial`, read
`make anomalies --severity warn` for the `listing_unavailable` rows: each names the year.

## Working through anomalies

`make doctor` fails while any unresolved critical anomaly exists, so anomalies are a work list
rather than a log.

| Command | Use |
| --- | --- |
| `make anomalies` | list unresolved anomalies with their ids; `ARGS="--severity critical"` to triage |
| `make resolve-anomaly ID=… BY=… NOTE=…` | the cause has been dealt with. It reappears if it recurs |
| `make acknowledge-anomaly ID=… BY=… NOTE=…` | reviewed, upstream is at fault, nothing to fix here. It stops failing `doctor`, stays visible on `/status`, and keeps counting occurrences |

Both require a name and a note, and both append the decision to the anomaly. Acknowledging is not
deleting: the condition remains on the page with its full history, because a gate nobody can clear
is a gate everybody learns to ignore.

Several anomalies on this site are permanent upstream defects rather than work — thirteen archived
readings dated `30/11/-0001`, one bill code with a stray `ARKIB` suffix, three bills the two
chambers title differently. `docs/upstream.md` lists them. Acknowledge those rather than chasing
them.

## Retention

`make retention` is a dry run. `make retention ARGS=--apply` aggregates expiring `fetch_attempts`
into `daily_fetch_metrics` and deletes them, prunes extractions to the current extractor version
plus the previous one, and releases blob references held by old failed page snapshots. It never
deletes bytes and never touches document versions, record changes, bill events, or presence
observations (ADR-010).

`make prune-blobs` deletes only blobs with no references and orphan files with no database row.
It is a dry run unless `ARGS=--apply`.

## Backups and restore

- `make backup BACKUP_DIR=/srv/backups` — timestamped PostgreSQL custom-format dump
- `make backup-blobs BLOB_BACKUP_DEST=/srv/backups/blobs` — incremental blob-store copy
- `make restore RESTORE_PATH=… CONFIRM_RESTORE=yes`
- `make restore-blobs BLOB_RESTORE_PATH=… CONFIRM_RESTORE=yes`

A database restore without the blob store loses the archive and every future re-extraction. Drill
both together, and record each drill in the manual gate log in `docs/status.md`.

**`PIPELINE_DATA_ROOT` is inside the backup contract and has no target yet.** This is the one gap in
the list above, and it is a real one rather than an oversight of convenience. The audit tree is
excluded because `make audit-rebuild` regenerates it from the database; the file-first pipeline's
store is the opposite — it *is* the record for that pipeline (ADR-021), so nothing regenerates it.
Losing that volume loses every fetched listing, every downloaded PDF, every imported markdown
reading and every derived artifact, and the listings and PDFs can only be recovered by crawling
Parliament again. The derived tiers could be rebuilt from the markdown, but the Akoma Ntoso step
needs the vLLM endpoint and would produce a *different* reading, which is precisely what the
provenance records exist to make visible.

Until a `make backup-pipeline` target exists, copy the directory as part of any backup run and say
so in the drill record. Do not treat a clean `make pipeline-verify` as a substitute: it proves the
stored corpus is internally consistent, not that a copy of it exists anywhere else.

## Release 3 rollout

Semantic search and RAG are off by default and the site is complete without them. Turning either
on is a sequence of recorded decisions, not a configuration flip:

1. Choose an embedding model whose dimension is 1024 and record the decision, licence, cost, and
   multilingual evidence against ADR-008. A different width needs its own migration.
2. Set `EMBEDDING_PROVIDER` and `EMBEDDING_MODEL_ID`, then run `make rechunk ARGS=--apply` and
   `make reembed ARGS=--apply`. Both are dry runs otherwise, and both record a `backfill_jobs`
   row.
3. Run `make evaluate` against the real model. It must meet the thresholds in
   `docs/evals/README.md`. Record the run, the date, and the model ID in the manual gate log.
4. Once representative vectors exist, build the index: `make semantic-index ARGS=--apply`. It
   refuses to build before any vectors exist.
5. Set `SEMANTIC_SEARCH_ENABLED=true`. `/semantic-search` appears; `/search` is unchanged.
6. For answers, run a vLLM OpenAI-compatible server, set
   `RAG_PROVIDER=openai_compatible`, `RAG_MODEL_ID`, `RAG_BASE_URL`, and the optional
   `RAG_API_KEY`, then set `RAG_ENABLED=true`. The base URL includes `/v1`, for example
   `http://vllm:8000/v1`.

Switching models later: `make reembed ARGS=--apply` backfills the new model alongside the old
one, and `uv run billwatcher drop-embedding-model <old-id> --apply` removes the superseded vectors
only after the replacement is validated.

`RAG_ENABLED=false` and `SEMANTIC_SEARCH_ENABLED=false` are kill switches. With them off,
`/semantic-search`, `/ask`, and `/api/v1/ask` return 404 and everything else is unaffected.

## Deployment

One locked image runs migrations, the web service, and the worker. Containers run as UID 10001. The
web container mounts the blob volume read-only; the worker owns read-write access.

`make docker-build`, `make compose-up`, `make compose-down`, `make logs`.

### What this stack does and does not include

**TLS is terminated by an nginx deployed separately (ADR-015).** Nothing here obtains certificates,
redirects HTTP to HTTPS, or listens on 80 or 443. The stack publishes one thing:

| Service | Reachable from | Why |
| --- | --- | --- |
| `app` | `127.0.0.1:8000` on the host | the origin for the external proxy. Loopback on purpose — an unencrypted origin bound to `0.0.0.0` is how a reverse-proxy deployment ends up serving plaintext to the network |
| `db`, `blobs` | other containers only (`internal: true`) | the database and the blob gateway are never reachable from the host or the internet |
| `app`, `worker` | outbound, via `egress` | the worker crawls Parliament; the app needs it only when RAG is on |

If nginx runs on another host, change the published bind and firewall the port deliberately. Do not
leave it on `0.0.0.0` and rely on a network being private.

### The nginx configuration this app needs

Three things matter, and one of them is not obvious:

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name bills.example.org;

    # ssl_certificate / ssl_certificate_key are yours to manage — nothing in this
    # repository obtains or renews them any more.

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # The status page streams server-sent events from /fragments/status. nginx buffers
        # proxied responses by default, which does not fail — it just makes the page look
        # like it has hung. This is the line people forget.
        proxy_buffering off;
        proxy_read_timeout 1h;
    }
}
```

Two things it must **not** do:

- **Do not set `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`,
  `X-Frame-Options`, or `Cross-Origin-Opener-Policy`.** The application sets them and the test suite
  asserts them. A browser enforces the intersection of two Content-Security-Policies, so a second,
  stale copy breaks the site rather than protecting it.
- **Do not add HSTS in both places.** Either set `add_header Strict-Transport-Security` in nginx or
  set `HSTS_MAX_AGE_SECONDS=31536000` in the app — not both. It is off by default in the app
  because HANDOFF 17 says to enable it only once HTTPS and the domain are known good: a year-long
  `max-age` published before a certificate works takes the site down for every browser that saw it.

### Before calling it public

Do not call the service publicly accessible until an external client on another network loads it
over valid HTTPS. A localhost container check is not evidence. `TODO.md` tracks what specifically
remains unverified about the deployed path.

## Security review, 2026-08-18

This is the dependency, container, and Content-Security-Policy review HANDOFF 17 requires. Re-run
it before each release; the commands are here so the result is reproducible rather than asserted.

### Python dependencies

```bash
uv export --frozen --no-hashes --no-emit-project --all-extras --all-groups -o /tmp/locked.txt
uvx pip-audit -r /tmp/locked.txt                                  # PyPI advisories
uvx pip-audit -r /tmp/locked.txt --vulnerability-service osv      # OSV, as a second source
```

Result: **67 locked packages, no known vulnerabilities from either source.** The lockfile is
committed and the image installs from it with `uv sync --locked`, so what was audited is what
runs.

**Re-run 2026-08-19**, after Stage L1 added `pdfminer.six` (ADR-016): **67 locked requirements, no
known vulnerabilities** from PyPI advisories or OSV. That reads as unchanged from the 2026-08-18
count of 67, and it is not: between the two reviews, moving RAG to an OpenAI-compatible endpoint
removed five packages (`anthropic`, `distro`, `docstring-parser`, `jiter`, `sniffio`), taking the
locked set to 62 — a number this document never recorded, which is the gap being closed here.
Stage L1 then added five different packages — `pdfminer.six` itself plus `cryptography`, `cffi`,
`pycparser` and `charset-normalizer` — landing back at 67 by coincidence of count, not of contents.
Note `cryptography`: it is a native crypto library with an active advisory history, it arrives as a
hard dependency of `pdfminer.six` rather than by choice, and this project has no CI, so this review
is the only control on it. Record the count on every run, not just when it looks like it changed —
this gap is exactly why.

**This review is stale, and by more than one change.** It last ran on 2026-08-19 against 67 locked
requirements. The export command above returns **79** today, and the difference is not one
addition: the MinerU reading (ADR-020) added `mineru-vl-utils` and `pypdfium2` with their transitive
set — `aiofiles`, `httpx-retries`, `loguru`, `pillow`, `tqdm` among them — and the audit was not
re-run for them, and the legislation corpus then added `rdflib` and `xmlschema` with `pyparsing` and
`elementpath` (ADR-025, ADR-028). All four of the latter are pure Python; `pillow` is not, and it
arrives the same way `cryptography` did, as somebody else's hard dependency rather than a choice.

Re-running this is an **operator action**, not a code change, and it is the only control this
project has on that set:

```bash
uv export --frozen --no-hashes --no-emit-project --all-extras --all-groups -o /tmp/locked.txt
grep -cE '^[a-zA-Z0-9._-]+==' /tmp/locked.txt        # record this number
uvx pip-audit -r /tmp/locked.txt
uvx pip-audit -r /tmp/locked.txt --vulnerability-service osv
```

Record the count and both results here with a date, the way the entries above do, and note that a
count matching a previous one proves nothing about the contents — that is the mistake the 2026-08-19
entry had to reconstruct after the fact.

### Container image

```bash
make docker-build
docker run --rm billwatcher:latest id                      # must be uid=10001
docker run --rm --user 0:0 billwatcher:latest sh -c "apt-get update -qq && apt-get -s upgrade"
```

Three findings, all addressed:

1. **The base image was pinned by a mutable tag only.** A re-pushed tag would have changed the
   image without changing the repository. Now pinned by digest as well; bumping it is a deliberate
   step documented in the `Dockerfile`.
2. **Python was 3.12.5, nine patch releases behind.** Now 3.12.13 across `.python-version`,
   `pyproject.toml`, and both build stages, with the full suite green on it.
3. **The base image carried an outstanding Debian security update**, `ca-certificates`. The
   runtime stage now applies security upgrades. That is the one place the build is deliberately
   not byte-reproducible, and it is the right trade: the crawler verifies upstream TLS against
   this trust store, so shipping a known-stale one to keep a rebuild identical would be
   backwards.

After those changes the image reports `0 upgraded, 0 newly installed`. Nine OS packages still
carry 26 advisory ids between them (`apt`, `coreutils`, `diffutils`, `gzip`, `libgcrypt20`,
`libtasn1-6`, `openssl`, `tar`, `util-linux`) for which **Debian 12 offers no fix** — they are
either marked unimportant or not yet fixed upstream. There is nothing to apply; note them and
re-check at the next release. To enumerate them without installing a scanner, query OSV with the
image's own package list:

```bash
docker run --rm billwatcher:latest sh -c "dpkg-query -W -f='\${Package}\t\${Version}\n'" > /tmp/dpkg.tsv
# then POST each as {"package": {"name": …, "ecosystem": "Debian:12"}, "version": …}
# to https://api.osv.dev/v1/querybatch
```

A dedicated scanner (`trivy image`, `grype`) is still the better tool and should be run wherever
the release image is built; it was not available in the environment this review ran in, and the
OSV query above is what stood in for it.

### Content-Security-Policy

The policy grants `script-src 'self' 'unsafe-eval'` because Datastar compiles `data-*` expressions
with the `Function` constructor (ADR-012). The review of that grant:

* **The policy is the application's, not the proxy's.** It used to live only in the proxy config, so
  `make serve` and any deployment behind a different proxy sent no policy at all, and nothing
  tested it. It is now set by `web/security_headers.py` and asserted on every page by
  `tests/e2e/test_security_headers.py`. The reverse proxy must not set its own: a browser enforces
  the intersection of two policies, so a stale second copy would break the site rather than protect
  it.
* **`unsafe-eval` weakens a mitigation; it does not create an injection.** The exposure is
  therefore the injection surface, and that surface is one expression: the search passage, the
  only place the site emits unescaped markup. It is escaped first and then has `<mark>` reinserted
  by `_render_highlights`, and a test feeds it `<script>alert(1)</script>` and asserts that the
  only tags surviving are `<mark>` and `</mark>`. Every other template is Jinja-autoescaped, with
  no `|safe` and no `Markup` anywhere else.
* **`'unsafe-inline'` is not granted**, so an injected `<script>` tag or inline handler is still
  refused, and that is asserted too.
* **No third-party asset is loaded**, which is what makes `default-src 'self'` meaningful rather
  than decorative. A test walks the pages and fails on any off-origin `src` or `href` asset.
* **The vendored Datastar bundle is verified against its recorded SHA-256** by a test, and the
  test also fails if an unrecorded `.js` file appears in the vendor directory. A vendored script
  is only trustworthy while it is the file that was reviewed.

The residual risk is accepted and unchanged from ADR-012: if an injection is ever introduced,
`unsafe-eval` removes one barrier to exploiting it. The path to dropping it is upstream shipping a
CSP-safe bundle; adopting a third-party fork for a security property was rejected.

### TLS, rehearsed once against a proxy that is no longer here

On 2026-08-18 the whole path was rehearsed by running the production-shaped stack while it still
shipped Caddy, with `SITE_HOST=bills.localhost` so an internal CA was used and no ACME request
fired. It verified the HTTP→HTTPS redirect, TLS over HTTP/2, the certificate chain, HSTS, every
application security header surviving a proxy unchanged, seven routes returning 200, the SSE stream
arriving as `text/event-stream`, UID 10001 with a read-only root filesystem, and `/documents/...`
still 404 while serving is off.

**That rehearsal is no longer reproducible here**, because ADR-015 removed Caddy in favour of an
nginx deployed separately. What it proved is worth keeping straight:

- **The application half survives.** The security headers are set by the app and asserted by
  `tests/e2e/test_security_headers.py`, which needs no proxy at all. Nothing about that depended on
  Caddy.
- **The proxy half now has to be verified once by hand against the real nginx** — the redirect, the
  certificate chain, HSTS not being doubled, and above all `proxy_buffering off`, because the event
  stream is the one thing a default proxy configuration silently breaks. `TODO.md` tracks it.

Two findings came out of the rehearsal, and both were real:

1. **The image could not run its own documented configuration.** `uv sync` omitted the `s3` extra
   while `.env.example` and `compose.yaml` both select the VersityGW backend (ADR-013), so the app
   exited on start with "the S3 archive backend needs the 's3' dependency group installed" and the
   stack never became healthy. The Dockerfile now installs it, and
   `tests/unit/test_deployment_consistency.py` compares the documented configuration against the
   image's dependency set so it cannot drift again. `rag` is still left out — it is off by default
   and would put an answer-provider SDK in every image.
2. **HSTS was not being sent**, because Caddy adds it only for a publicly trusted certificate. It is
   now an application setting, `HSTS_MAX_AGE_SECONDS`, defaulted to off for the reason HANDOFF 17
   gives.
