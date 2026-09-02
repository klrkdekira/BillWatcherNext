# TODO

Everything known to be outstanding, in one place. Written 2026-08-18, last updated 2026-08-22.

`docs/status.md` stays the ledger — the assumption register, the decision index, and the dated
evidence. This file is the **work list**: what is left, who can close it, and what closing it takes.
When an item is done, record the evidence in the `docs/status.md` gate log and delete the item here.
If the two ever disagree, `docs/status.md` is right, because it carries dates.

The last recorded green run is 2026-08-22 (`make check` 649 passed, 28 skipped, 2 deselected
offline), `make doctor` is clean, and the site serves 1,269 bills spanning 1990–2026 from live data
(via the Postgres-backed system, §0.7 — the file-first pipeline in §0.6 has its own store,
`pipeline-data/`, now holding the first pilot slice). `make test-pg` is green at the same date:
**654 passed, nothing skipped**, which matters
because the publication-readiness change did touch two modules the Postgres-backed system depends on
— the atomic-write helper in `storage/audit_tree.py` and the `SCHEDULE_ORDINALS` rename in
`legislation/vocabulary.py`.

Most of what follows is unfinished work rather than defect. **§2.4 is the exception**: three latent
defects found on 2026-08-19 while building the legislation pipeline, each harmless today and each
guaranteed to bite the next change in its area. A fourth was live rather than latent —
`make quickstart` could not run from a fresh clone — and is fixed, with the evidence in the
`docs/status.md` gate log.

---

## 0. Current priority — the milestone chain, each milestone shipping its own artefact (ADR-036)

Directed on 2026-08-23: **each stage is a milestone that produces a hostable artefact**, and the
intermediate goal is **the markdown, then the semantic knowledge graph**. ADR-036 aligned the code
to that; before it, a document reached the dataset only once it had a gate-passing graph, so the
corpus was publishable only at the speed of its slowest stage — 92 Expressions of 1,265 documents.

| # | Stage | Hostable artefact | State |
| --- | --- | --- | --- |
| 1 | Download | none, deliberately — never a source PDF (ADR-032) | **done**: 1,265 PDFs, 303 MB |
| 2 | **Markdown reading** | `.md` per Expression + `index.json` + `checksums.sha256` | **current — 1,192 Expressions (94%) build today** |
| 3 | **Semantic graph** | `.jsonld` + `.nq` per Expression, gate-passing only | 82 Expressions in; needs conversion at scale |
| 4 | Cross-reference | divergence report over the readings (ADR-035) | built, never run (~27,800 model calls) |

Both live milestones widen **one** site at one identity, differing only in extension
(`…/msa@.md`, `…/msa@.jsonld`, `…/msa@.nq`) — the widening mechanism ADR-032 described, used as
intended. `make build PIPELINE_SITE_REPRESENTATIONS=markdown-semantic` publishes both; `markdown`
alone publishes milestone 2 by itself.

### 0.0 The earlier framing, kept because the decisions in it still hold

Directed by the commissioner on 2026-08-22: "my priority right now is serving the schema and
dataset statically, second part would only be the backend serving, db integration and etc. the data
pipeline should be solely local file for now, not committed, only the static semantic files or
definition," then "My prioritise is a public cache of files, only then we do the teooling," then —
after the exporter was built and verified — **"prioritise static published dataset,"** then
**"don't commit the pdf, prioritise the jsonld for now,"** then **"create a directory called dist
that I can commit to another repo as github page… the build script should allow me to set prefix such
as 'bills.engineers.my'."**

The last direction changed the deliverable. ADR-029's boundary was a cache *produced locally and
deliberately not published*; the word **published** moves publication into scope and forces the
three decisions ADR-029 left to the owner. All three are now answered (ADR-031):

1. ~~**The dataset is committed to this repository.**~~ **Superseded the same day by ADR-033:** the
   published dataset is a **GitHub Pages site in a separate repository**, on `bills.engineers.my`.
   `make build` writes the tree to `dist/`; `dist/` and `public-cache/` are both gitignored here,
   and nothing in this repository carries the dataset. Both answers are in the `docs/status.md`
   ledger with dates rather than the first being quietly overwritten.
2. **It publishes in `full` mode** — real legislative text, resting on the A14 determination. A
   metadata-only tree carries no provision text at all, which is a catalogue, not a dataset.
3. **It is published only once the corpus run widens past the pilot.** 92 Expressions of ~1,269
   bills is a 7% sample; publishing it under a name implying the corpus is the failure ADR-031
   exists to prevent.
4. **The site publishes the semantic files — JSON-LD and RDF N-Quads — and never a source PDF**
   (ADR-032, widened for this surface by ADR-033).
   `PIPELINE_EXPORT_REPRESENTATIONS` defaults to `jsonld`; the Akoma Ntoso XML and N-Quads stay
   generated, stay in the store, keep their reserved extensions on the same §28.7 identifier, and
   widening later is one setting with no pipeline rerun. The exporter now refuses any payload that
   is a PDF by path or by magic bytes — "no PDFs" was already true, and is now enforced, because a
   committed tree turns a future mistake into a permanent publication.

Unchanged, and not to be quietly relaxed while executing the above: rights-flag defaults stay
`false` in `billwatcher.config`, `.env.example` and `.env.development` (a fresh clone must not be
able to publish by accident — assert them in the deployment `.env`); `pipeline.redact` stays in
place and stays tested, because `full` is a reversible posture and not the removal of the control;
`pipeline-data/` is still never committed; and nothing from Stages L3–L4 may enter the dataset,
which is §1.7's legal sign-off and is not satisfied by A14.

**Done, and closed:** the exporter itself. `pipeline/export.py`, `billwatcher pipeline
export-static`, `make pipeline-export-static`, `PIPELINE_EXPORT_ROOT`, definitions, Works/Expressions
catalogue, checksums, both rights refusals, boundary redaction, idempotence, and the scoped
reconciliation fix are complete and evidenced in two 2026-08-22 gate-log entries — the second
verifying every acceptance criterion independently against the real pilot. Nothing in §0.1 blocks
what remains here.

### 0.1 Milestone 2 — publish the markdown reading

The corpus run is **done** and the reading is **no longer operator work**: `make pipeline-download`
fetched 1,265 PDFs (27,833 pages, 31 dead upstream links, ADR-034), and
`make pipeline-extract-markdown` reads all of them locally in **11.4 minutes** with no model and no
network (ADR-035). 1,253 readings are stored; 270 carry a quality signal and are published labelled
rather than withheld (ADR-036).

Nothing in this milestone is blocked by the semantic work below. Its bytes were checked for it: the
localhost-IRI defect in §0.2 is present in **all 164** published semantic files and in **none** of
the 1,192 markdown files or `index.json`, which use relative paths.

- [ ] **Review a sample of the 270 suspect readings** before releasing them, and decide whether
      heading inflation is a fixable threshold in `layout._classify` or genuinely ambiguous
      typesetting. A threshold fix is far cheaper than a labelled release that a reader has to
      distrust, and it is the one change that would move the numbers before publication.
- [ ] **Settle the four release prerequisites in §0.3** — publication contract, licence,
      history-growth policy, the irreversible commit. They gate *any* first release, this milestone
      included, and none of them is code.

### 0.2 Milestone 3 — publish the semantic graph

82 Expressions of 1,265 documents. This is a conversion-throughput problem, not a publication one:
`convert-to-akn` is one vLLM call per document and Gate P1 rejects what it cannot verify.

- [ ] **Convert and generate at corpus scale.** ~1,183 documents have a reading and no graph.
      Per-document vLLM cost; record the real cost and wall-clock in the gate log — it is the input
      to deciding whether ADR-030's anchored extractor should land *before* the second full pass
      rather than after.
- [ ] **Regenerate the semantic files against the published domain.** Every `@id` in the pilot's
      stored JSON-LD and N-Quads reads `http://127.0.0.1:8000/...`, because step 5 takes its base
      IRI from `PUBLIC_BASE_URL` and the pilot ran with the development default. §28.7 says the path
      *is* the identifier, so publishing localhost IRIs contradicts the corpus's own contract. Set
      `PUBLIC_BASE_URL=https://bills.engineers.my` and re-run `make pipeline-generate-semantic`;
      ADR-026 records `base_iri` in the provenance, so the change regenerates every artifact rather
      than leaving the stale graph in place. Cheap and offline — but it must happen before the first
      release, and re-exporting is what carries it into the published tree.
- [ ] **Review every Gate P1 rejection before the first release (A15).** *(Milestone 3.)* 53 of 181 readings were
      rejected and none has been read by a human. This was a measurement question while nothing was
      published; now a false rejection is a bill silently missing from the published dataset. The
      output is a judgement on the 0.95 threshold and a list of rejections that are genuinely bad
      readings versus genuinely bad thresholds.
### 0.3 Prerequisites for any first release, whichever milestone goes first

- [ ] **Write the publication contract into the tree**, the four things a committed dataset owes
      that a local cache did not: a stated **scope** (which bills, languages, gate threshold, and
      what is absent and why); a **licence for the project's own output**, distinct from the source
      material's position; the **attribution and disclaimer** the A14 determination rests on,
      including that these are *readings* of published bills and not authoritative text; and what
      the §28.7 identifiers **guarantee** — a permanent path, content-addressed by
      `checksums.sha256`, whose bytes a re-export may change.
- [ ] **Decide the history-growth policy before tracking the tree.** Measured on the pilot in
      `full` mode, a JSON-LD-only release is 38.3 kB per Expression — ~33–46 MB at corpus scale over
      ~870–1,200 files for JSON-LD alone, roughly double that for the site's JSON-LD + N-Quads, and
      ~115–160 MB over ~2,600–3,600 with all three (ADR-032 is what bought the reduction). Note the
      history now grows in the **Pages repository**, not this one (ADR-033), which makes squashing or
      orphaning it cheaper. Fine once, either way. The cost that compounds is ADR-026
      regeneration: an `AKN_VERSION` or renderer bump rewrites *every* document, and each such
      commit adds another full copy of the tree to history, permanently. Accept it, squash it, or
      publish from an orphan branch. Decide before the first commit of the tree, because git history
      is the one publication channel where withdrawal requires a history rewrite.
- [ ] **Choose the dataset licence before the first commit to the public repository.** `index.html`
      currently publishes an explicit *"Licence: not yet stated … treat it as unlicensed for
      redistribution"* note, which is honest but is not a releasable answer. A published page that
      misstates reuse terms is worse than one admitting they are pending, so this is the last thing
      that must be settled. No code change is needed: set `PIPELINE_SITE_LICENCE` and
      `PIPELINE_SITE_LICENCE_URL` (they are empty by default and deliberately never guessed) and the
      page states the grant, adds `<link rel="license">` and badges it in the header. The sibling
      corpus at `cheeleong.dev/graph20` publishes as CC BY 4.0, which is the obvious candidate — but
      it is the owner's call, not a default.
- [ ] **Publish: `make build`, verify, then commit the tree to the Pages repository.** Assert
      `LEGISLATION_CORPUS_RIGHTS_CONFIRMED=true` and `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true` in
      the deployment `.env` only, run `make build` (optionally `PREFIX=`), verify
      `checksums.sha256` from the tree root, confirm a second `make build` reports `written: 0`,
      confirm `index.json` names the published representations and that no file is a PDF, then
      create/point the Pages repository at `bills.engineers.my` with DNS, and commit. Record the
      released scope and counts in the gate log. **This is the irreversible step** — every committed
      revision is a permanent publication of that revision.
- [ ] **Optional, and only when asked for:** widen `PIPELINE_SITE_REPRESENTATIONS` (or
      `PIPELINE_EXPORT_REPRESENTATIONS`) to `all` to publish the Akoma Ntoso XML alongside the
      markdown and the semantic files. Deliberately last: ADR-032 narrowed the release on purpose.
      Additive, one setting, no pipeline rerun.

### 0.4 Milestone 4 — the cross-reference (ADR-035)

- [ ] **Run `make pipeline-cross-reference`** once milestone 2 is out. ~27,800 model calls, upwards
      of fifteen hours, resumable. It is the only check on the readings themselves — Gate P1 scores
      a tree against the markdown, never the markdown against the page — so it is what eventually
      puts evidence behind the `reading.suspect` labels the dataset now carries.

### 0.5 Second — the tooling (HANDOFF §28.5 as amended, ADR-030; then §28.10)

Explicitly after §0: "only then we do the teooling." In order:

- [ ] **Split step 4 (ADR-030).** `extract-structure` persists `document.structure.json` (+
      provenance, + `document.structure.gate.json`, + `document.structure.rejected.json` on
      rejection; `has_structure` becomes the promotion flag; Gate P1 moves here unchanged);
      `render-akn` renders deterministically from the stored tree. Retire
      `document.akn.gate.json`/`document.akn.rejected.xml`; grow `KNOWN_FILENAMES`,
      `PipelineStore`, CLI, Make. Acceptance is in Package M (HANDOFF §19).
- [ ] **The anchored extractor contract (ADR-030).** Send line-numbered markdown; the model
      returns node type / printed num / heading / start line, never body text; paragraphs are
      sliced from `document.md` between anchors. This is the actual fix for per-document LLM cost
      — output drops from O(document) to O(provisions) — and it makes paraphrase structurally
      impossible. A wrong anchor must fail Gate P1, not publish mis-sliced text.
- [ ] **Backend serving (§28.10)** — the served surface on truncatable paths with content
      negotiation. Unchanged contract, now phase two behind the cache.
- [ ] **A database or object-store `PipelineStore` implementation** — correctly unbuilt, per
      standing direction. When it lands, no step function should need to change. Note it now has
      more to implement than it did: the provenance, manifest, gate-verdict, unexpected-file — and,
      post-split, structure — methods are part of the protocol.
- [ ] Optional, after the split proves itself: a tiered extractor (regex first, LLM only for the
      Arrangement/body split or on Gate P1 rejection). Deliberately not decided in ADR-030.

### 0.6 The file-first pipeline as built (HANDOFF §28, ADR-021)

Directed by the commissioner on 2026-08-21, the priority before §0 above: "we are revisiting from
scratch, database and object store are for later, we want the pipeline to work fully with file
first," then "it can work from db, but it would be an extension, the pipeline should work with
interface of input, such as file and also from db or object store," then "do not attempt to parse
the pdf for me too, I have vllm openai compatible endpoint https://llm.loqasi.io/v1/ for that."

Everything in §0.7 (the Postgres-backed audit tree, `fetch-documents`, `mineru-extract`) is left
in place, untouched, dormant. `billwatcher.pipeline` is a new, separate package that imports none
of it. Kept here as the build record; the open work moved to §0 and §0.1.

- [x] **`PipelineStore` interface + `FileStore` implementation**
      (`src/billwatcher/pipeline/store.py`): `save_listing`/`iter_listings`,
      `load_bill`/`save_bill`/`iter_bill_slugs`, `has_document`/`save_document`/`iter_documents`,
      write-if-changed idempotence reusing the audit tree's deterministic sidecar serializer.
- [x] **Step 1, fetch listings** (`pipeline/listings.py::fetch_listings`, `pipeline/targets.py`):
      robots.txt, both current listings, both archive indices, every archived year. Reuses
      `scraper.fetch.Fetcher`/`scraper.policy.CrawlPolicy`/`scraper.robots` as-is — none of them
      ever touched a database.
- [x] **Step 2, parse listings** (`pipeline/listings.py::parse_listings`,
      `pipeline/bills.py::merge_listing_into_bill`): fully offline, reuses
      `scraper.parse_listing`/`scraper.parse_archive` as-is. One JSON record per bill
      (`bills/<slug>/bill.json`), deliberately simple — no field-level change history.
- [x] **Step 3, fetch documents** (`pipeline/documents.py::fetch_documents`): downloads every
      document URL found across bill records, skipping what's already present. Document identity
      is `doc-<sha256(url)[:8]>` — no database id to derive one from.
- [x] **CLI + Make targets**: `billwatcher pipeline fetch-listings|parse-listings|fetch-documents`
      (a sub-app, nested under the existing `billwatcher` command without touching it) and
      `make pipeline-fetch-listings`/`pipeline-parse-listings`/`pipeline-fetch-documents`. The two
      live steps are gated behind `SCRAPE_ENABLED`/`--approve-live`, checked directly against the
      CLI, same as the Postgres-backed commands.
- [x] **Tests**: 19 new tests (`tests/unit/test_pipeline_store.py`,
      `tests/unit/test_pipeline_bills.py`, `tests/integration/test_pipeline_listings.py`,
      `tests/integration/test_pipeline_documents.py`), all offline/mocked, using real fixture
      HTML/XML for the listings tests. One real bug found and pinned: `last_seen_at` could move
      backwards because listings are parsed in storage-key order, not fetch order, when a bill
      (D.R.15/2026, per A4) is referenced by both chambers — fixed with a monotonic max, pinned
      by `test_last_seen_at_is_monotonic_regardless_of_processing_order`.
- [x] **PDF-to-markdown is explicitly out of scope; markdown-to-Akoma-Ntoso is step 4.**
      Directed 2026-08-21: "next up for pipeline after markdown conversion is conversion to the
      oasis format," then "Akoma Ntoso XML parsing should use the help of the vllm server."
      `pipeline/akn.py` (`Node`, `assign_eids`, `render_akn`, `MarkdownStructureExtractor`
      protocol, `RegexMarkdownStructureExtractor`) and `pipeline/akn_llm.py`
      (`VllmMarkdownStructureExtractor`, `build_structure_extractor`) implement it; PDF-to-markdown
      itself remains the operator's own vLLM endpoint (`https://llm.loqasi.io/v1/`), producing
      `document.md` for this step to read. `store.py` gained `has_markdown`/`load_markdown`/
      `save_markdown`/`has_akn`/`save_akn`. CLI: `billwatcher pipeline convert-to-akn`, Make:
      `pipeline-convert-to-akn`, gated behind `AKN_LLM_ENABLED`/`AKN_LLM_BASE_URL`/
      `AKN_LLM_MODEL_ID`. 23 new tests; a live smoke test against the real endpoint
      (`https://llm.loqasi.io/v1`, model `qwen-3.8-27b`) found and fixed one real bug — see the
      `docs/status.md` gate log (ADR-022).
- [x] **Step 5, semantic files (JSON-LD + RDF N-Quads)** (`pipeline/semantic.py`). Directed
      2026-08-21: "after akn, then it should be to the semantic files such as jsonld and rfg" —
      read as RDF, flagged as an interpretation (ADR-023). `parse_akn` reads `document.akn.xml`
      back into a tree rather than reusing step 4's in-memory one, so the two steps stay
      independently replayable; one graph construction serves both files, so they can never
      disagree — since 2026-08-22 that graph is an `rdflib.Dataset` serialised twice rather than a
      hand-rolled dict and a flattener over it (ADR-028). `store.py` gained
      `has_semantic`/`save_jsonld`/`save_rdf`. Fully offline — no LLM, no network, reuses
      `public_base_url` rather than a new setting. CLI: `billwatcher pipeline generate-semantic`,
      Make: `pipeline-generate-semantic`. 10 new tests, including one pinning that a malformed AKN
      file is counted `failed` rather than raised, and one pinning that JSON-LD and N-Quads agree.
- [x] **Made publication-ready, 2026-08-22** (ADR-024 through ADR-028, HANDOFF 28.7–28.10). Nine
      defects fixed; the three that mattered were all about putting wrong facts on a permanent
      record. `pipeline/frbr.py` replaces the URL-hash public identifier with a real FRBR triple
      built from published facts, and language is now a declared fact rather than a hard-coded
      `msa`; `pipeline/fidelity.py` adds Gate P1 and `pipeline/akn_schema.py` validates the render
      against a vendored OASIS XSD; `pipeline/provenance.py` makes regeneration depend on input
      hashes rather than on a file existing, with volatile facts confined to per-run manifests
      (`pipeline/reporting.py`); `pipeline/redact.py` plus four settings give the corpus a
      publication posture that is off by default. Evidence and the full defect list are in the
      `docs/status.md` gate log.
The two items formerly open here moved: the database/object-store `PipelineStore` to §0.1 (it is
"the tooling"), and "run it against real data" into §0's fill-the-store item — the pilot has
begun, and §1.10 still owns the measurement.

### 0.7 Auditable step pipeline (superseded as current priority, HANDOFF §27, ADR-019, Package K)

Directed by the commissioner on 2026-08-21 and prioritised ahead of everything below at the time; every
pipeline step auditable from the filesystem, every step one Make target, every step storing its
output in a local directory tree — the raw downloaded PDF beside a JSON sidecar carrying source,
raw file, language, URL, and provenance. The contract is HANDOFF §27; the design decision (the
tree is a byte-reproducible *projection* of the database, not a replacement for it) is ADR-019.

All of this is developer work; none of it is blocked on anyone. **2026-08-21 update: the PDF
download step (S3) is built and tested; the listing steps (S1/S2) are deliberately deferred** —
the commissioner's follow-up direction was "work on the PDF download pipeline… do not begin the
processing yet", read as: build the document-download half now, leave `make scrape`'s fused
listing fetch+parse and the S4–S7 processing tiers (`reextract`/`restructure`/`rechunk`/`reembed`
tree output) for later, separately confirmed work.

- [x] **Build the audit-tree writer** (`storage/audit_tree.py`): the §27.2 layout, paths from our
      own identifiers only (never upstream filenames — §17), and the §27.3 deterministic sidecar
      serializer (sorted keys, two-space indent, UTF-8, LF, trailing newline), versioned by
      `metadata_schema_version`. Write-if-changed idempotence is a unit test
      (`tests/unit/test_audit_tree.py`), not an assumption.
- [x] **Wire tree output into step S3.** `process_one_document` writes `document.pdf` +
      `metadata.json` under every bill the document is linked from for every accepted *or*
      quarantined download (a bad download is still a raw-bytes-on-the-wire fact worth an
      auditable record, tagged by its own `validation_status`); `run_fetch_documents_step` drains
      the whole queue as one Make target (`fetch-documents`, gated behind
      `SCRAPE_ENABLED`/`--approve-live` exactly like `scrape`, since it hits the same live host)
      and writes one `manifests/fetch-documents/<run-id>.json` per run.
- [ ] **S1 (`fetch-listings`) and S2 (`parse-listings`).** `make scrape` still fuses fetch, parse,
      and ingest in one `ScrapeOrchestrator.run()`, including the §11.6 guardrails (zero-records,
      count-drop, structure-drift) that currently gate publication inline at fetch time. Splitting
      requires moving those checks into a from-stored-snapshots S2, on the same shape `reparse`
      already proves works. Deferred, not abandoned — `make pipeline` (S1→S6) and the listing tier
      of the audit tree (`01-listings/`, `02-bills/`) wait on it.
- [x] **Build `make verify-audit`** (`jobs/audit_rebuild.py`, document tier only): rebuilds into a
      scratch directory and diffs it against the real tree file by file, so a tampered byte, a
      missing artifact, and a stray file with no backing record all surface as a named issue and
      raise the critical `audit_tree_divergence` anomaly `make doctor` already reads generically.
- [x] **Build `make audit-rebuild`** (document tier only): regenerates every accepted or
      quarantined document version's directory; zero writes over an already-correct tree, proven
      by a test (`test_second_version_gets_its_own_directory_and_the_first_survives`).
- [x] **Tests**: a tampered byte fails `verify-audit`
      (`test_verify_catches_a_tampered_byte`); a superseded version's stale `is_current` sidecar is
      caught by verify and fixed by rebuild; the step drains a seeded queue and writes one manifest
      (`test_fetch_documents_step.py`); `fetch-documents` refuses without
      `SCRAPE_ENABLED`/`--approve-live`, checked directly against the CLI. `make check`
      (331 passed offline, 28 PostgreSQL-only skipped) and `make test-pg` (359 passed against a
      real PostgreSQL 16 + pgvector + VersityGW, nothing skipped) both green.
- [ ] **Materialise the stored corpus** (1,264 PDFs) by running `make audit-rebuild` where the
      blob store lives — the deployment host or the S3 gateway — and record the counts in the
      `docs/status.md` gate log. Note this is the same corpus access §1.8 needs; one trip can
      serve both. Not done from here: this session's dev database has fixture-seeded bills and a
      queue but zero real document versions, so there is nothing yet to materialise locally.
- [x] Add `AUDIT_TREE_ROOT` to config, `.env.development`, `.env.example`, `compose.yaml` (worker
      read-write volume), and gitignore `data/`; `docs/operations.md` and `docs/data-model.md`
      updated.
- [x] **2026-08-21, a second direction: "use MinerU instant to parse the PDFs, still local file
      based, but this time as the markdown artefacts."** One slice of the S4 processing tier
      landed — the MinerU vision-language reading, written to `04-text/.../mineru@<version>/`
      exactly as §27.2 specified but nothing had yet built (HANDOFF 27.7, ADR-020,
      `billwatcher.mineru`, `jobs/mineru_extract.py`, `make mineru-extract`). The **`pypdf`-based
      S4 tree output is still not built** — `reextract`/`persist_current_extraction` still write
      only to `document_extractions`, never to the tree — so `04-text/` today holds MinerU output
      only. Verified end to end against the real hosted endpoint
      (`https://mineru.loqasi.io`), not just mocked tests; found and fixed one real bug that no
      mock could have caught (see the `docs/status.md` gate log). S1/S2 and the remaining S4–S7
      tree wiring (`restructure`/`rechunk`/`reembed`) remain deferred.

---

## 1. Blocked on someone other than a developer

No amount of code closes these. Each names what it needs.

### 1.1 Deploy it: certificate, DNS, and the nginx in front — *service owner*

TLS is terminated by an nginx deployed separately (ADR-015), so the proxy half of the path cannot be
tested from here. Verify **once**, by hand, against the real deployment:

- [ ] A publicly trusted certificate and public DNS; an external client on another network loads the
      site over valid HTTPS. A localhost check is not evidence.
- [ ] HTTP redirects to HTTPS.
- [ ] `proxy_buffering off` is in place — **the one that silently breaks things**. Without it
      `/status` looks like it has hung instead of streaming. Confirm by watching
      `curl -N https://<host>/fragments/status` emit events.
- [ ] `Strict-Transport-Security` is sent exactly once, by nginx **or** by
      `HSTS_MAX_AGE_SECONDS`, never both — and only after the certificate is known good, because a
      year-long `max-age` published too early takes the domain down for every browser that saw it.
- [ ] nginx does **not** set `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`,
      `X-Frame-Options`, or `Cross-Origin-Opener-Policy`. The app sets them and the suite asserts
      them; a second, stale copy of a CSP breaks the site rather than protecting it.
- [ ] Certificate renewal is monitored. Caddy used to make this a property of the stack; it is now
      outside anything this repository can see.

Configuration to copy: `docs/operations.md` → "The nginx configuration this app needs".

### 1.2 Decide whether stored PDFs may be republished (A14) — *decided 2026-08-22*

**Decided by the service owner: bills are public information; no copyright restriction applies to
republishing them.** The determination and its scope (and what it deliberately does not cover —
§1.7 stands apart) are recorded in the `docs/status.md` gate log, which is the authority.

What remains is the operator action, per deployment:

- [ ] `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true`, then `SERVE_ARCHIVED_DOCUMENTS=true` — stored PDF
      bytes served (ADR-004, ADR-013).
- [ ] The same confirmation permits `LEGISLATION_PUBLICATION_MODE=full` (§1.9, also decided).

### 1.3 Choose an embedding model (ADR-008) — *service owner, then a developer*

Shortlisted to models already matching the 1024-wide schema, so no migration is needed.
**BGE-M3 self-hosted is recommended**: MIT licensed, no per-query cost, and no third-party egress,
which is the only option consistent with a site that makes no third-party requests.

- [ ] Accept the hosting cost (or a hosted vendor's licence and per-query cost).
- [ ] Implement the provider behind the existing `EmbeddingProvider` protocol. A dimension mismatch
      is refused at construction, so this cannot go in silently wrong.
- [ ] Run `make evaluate` against it and paste the gate-log line it prints into `docs/status.md`.
      Malay coverage is a vendor claim until this passes; the evaluation set is bilingual for
      exactly this reason.
- [ ] Only then `SEMANTIC_SEARCH_ENABLED=true`.

### 1.4 Select and evaluate the vLLM answer model, if `/ask` ships (ADR-009) — *service owner*

The provider decision is made: a self-hosted vLLM OpenAI-compatible endpoint. There is no
third-party retention arrangement or provider SDK.

- [ ] Choose the answer model and run `make evaluate` against it.
- [ ] Record the evaluation in the gate log.
- [ ] Set `RAG_MODEL_ID`, `RAG_BASE_URL`, and an optional `RAG_API_KEY`, then enable
      `RAG_ENABLED`. Keep the endpoint private and disable request-body logging at vLLM's proxy.

### 1.5 Decide whether the 22 scanned bills should be searchable — *service owner*

22 documents (1.7%) yield no text: scans concentrated in 2010, 2013 and 2018, plus ten malformed
PDFs. They are findable today by their listing metadata, but not by their contents.

- [ ] Decide whether that matters enough to build the optional OCR worker (§2.1).

### 1.6 Decide whether Acts can be obtained at all (HANDOFF 26.7) — *discovery owner, then service owner*

The legislation pipeline's whole point is consolidated law, and **without Acts there is neither
consolidation nor a correctness oracle**: Gate L3 diffs a consolidation against a published AGC
reprint, and every reprint is on `lom.agc.gov.my`.

- [x] Run a first discovery pass: `robots.txt`, TLS chain, terms of use. Done 2026-08-20, read-only,
      recorded in `docs/upstream.md` (A16). TLS chain is complete — no `UPSTREAM_CA_BUNDLE`
      equivalent needed. `robots.txt` returns HTTP 500, not a clean 404: **that is its own
      condition and needs its own decision**, not `ROBOTS_MISSING_POLICY`'s absent-policy reasoning
      reused by analogy — a 500 does not read as RFC 9309 "no restrictions" the way a 4xx does.
- [ ] Decide what a `robots.txt` that errors rather than answers means for crawl policy, and record
      the decision — it is not the same fact as A13's and should not inherit A13's resolution.
- [ ] Fetch an actual listing or reprint page (not done in the discovery pass, deliberately, to
      keep it read-only reconnaissance rather than the start of a crawl) and confirm whether
      reprints state the date to which amendments are incorporated. This is what Gate L3 needs and
      is still unconfirmed.
- [ ] Decide crawl policy and rights for AGC as its own question, recorded in an ADR. A13 and A14
      are answers about Parliament, not about the Attorney General's Chambers. The FAQ's "can be
      downloaded and printed... for purposes of reference" is a fact on the record (`docs/upstream.md`),
      not a licence this project has granted itself — whether it covers building a structured,
      mirrored corpus is exactly the judgement this decision is for.
- [ ] Have the eventual legal reviewer read the FAQ's subsection-18(4) point alongside the s.61
      disclaimer (`docs/upstream.md`, 2026-08-20): the online portal is stated to be "the first
      official Gazette published to the public" from 26 April 2011, which may give the *online*
      publication different evidentiary standing from a *printout* of it. Not something this
      project is qualified to resolve.
- [ ] Keep `lawnet.com.my` out of that ADR. It is a paid PNMB subscription governed by a contract,
      so it carries terms-of-use and unauthorised-access exposure that a public site does not. It
      needs its own decision or an explicit decision not to use it. AGC's own FAQ (2026-08-20)
      confirms pre-2011 Acts are only obtainable from `www.agc.gov.my` or `www.lawnet.com.my`,
      never from `lom.agc.gov.my`.

### 1.7 Get legal sign-off before anything consolidated is public (HANDOFF 26.7) — *service owner, legal*

This is a **higher bar than A14** and must not be folded into it. A14 asks whether stored bytes may
be republished. This asks whether we may state what the law *is* — a claim about the world that no
upstream source published in that form, and one this site's existing disclaimers actively
contradict, since "Parliament is the authority" is false for a consolidated Act whose authority is
the Gazette.

- [ ] Have a Malaysian-qualified lawyer review the consolidation methodology and the disclaimers.
- [ ] Extend the disclaimer regime rather than reusing it: carry the AGC statement that its copies
      are not Gazette copies for the purposes of section 61 of the Interpretation Acts 1948 and
      1967 through to every document derived from them.
- [ ] Before any N-Quads dump ships, give it the same hard runtime control `SERVE_ARCHIVED_DOCUMENTS`
      has — default off, plus a production validator that refuses to boot without an explicit rights
      confirmation. **A mirrored dump cannot be withdrawn** (ADR-018), so protecting the lower-risk
      artifact while leaving the higher-risk one open would be exactly backwards.

### 1.8 Give Stage L1 access to the stored corpus — *service owner*

Gate L1 is proven correct in its logic and **unproven against Parliament's actual typesetting**.
Every fixture is constructed typography; the 1,264 stored PDFs live on the deployment host or in the
S3 gateway, not in a clean checkout.

- [ ] Point a `make restructure` run at the real blob store and record the corpus-wide pass rate,
      and the `no_arrangement` rate, in the `docs/status.md` gate log. That measurement also settles
      A15 — whether every Malaysian bill really does carry an Arrangement of Clauses.
- [ ] Decide who staffs the Gate L1 review queue and to what SLA. An unstaffed review queue silently
      becomes a coverage gap, which is the same question §1.5 raises; answer both once.
- [ ] While there, sweep the real filenames for language markers and record what actually
      appears — `BM`/`BI`, `bm`, `(BM)`, or nothing — with counts, in `docs/upstream.md`. That is
      the discovery `documents.language` classification needs and does not have yet (HANDOFF
      26.7): the four examples already on record (`docs/upstream.md`) are inconsistent enough
      that guessing a regex from them would repeat the mistake A9's status sweep corrected twice.

### 1.9 Decide whether the structural corpus may be published — *decided 2026-08-22*

**Decided by the service owner, as part of the A14 determination (gate log): the corpus may be
published, in full-text mode.** The metadata-only posture and the `KEEP_HEADINGS` residual recorded
here previously are moot under that determination; they remain in the code as the fallback posture
should the determination ever be revisited, which is the reversibility ADR-027 was built for.

Remaining operator actions, per deployment. Note the surface changed shape (ADR-029): the first
publication is the **static cache export** of §0, which the same rights flags gate at the command
level; `SERVE_LEGISLATION_CORPUS` only matters when the phase-two served surface (§0.1) arrives.

- [ ] `LEGISLATION_CORPUS_RIGHTS_CONFIRMED=true` — now gates `pipeline export-static` first, and
      `SERVE_LEGISLATION_CORPUS=true` later, in phase two.
- [ ] `LEGISLATION_PUBLICATION_MODE=full` (requires `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true`,
      which §1.2 now permits).
- [ ] Run the first-corpus runbook (`docs/first-corpus-run.md`) **before** flipping any of these in
      production: publication being permitted does not make an unmeasured corpus fit to publish —
      Gate P1 has never seen a real document (§1.10).
- [ ] The N-Quads mirror dump stays unbuilt and separately gated (§1.7): a served surface can be
      withdrawn, a mirror cannot, and the hard runtime control ADR-018 requires for it does not
      exist yet.

### 1.10 Measure Gate P1 against real documents — *service owner, then a developer*

**The step-by-step handoff for executing this item is `docs/first-corpus-run.md`** — pilot crawl,
markdown import, conversion, reading the verdicts, integrity checks, the local serving smoke test,
and the gate-log entry template. This section stays as the *why*; that file is the *how*. With the
rights decision now made (§1.9), this item is also the last thing standing between the corpus and
production: publication being permitted does not make an unmeasured corpus fit to publish.

Gate P1 is the deterministic check that a model's reading of a bill accounts for the words that were
on the page (ADR-025). Its logic is proven; its **one threshold still needs a reviewed judgement**.
`AKN_GATE_MIN_TEXT_COVERAGE` defaults to 0.95. The 2026-08-22 gate-log entry now records the pilot's
pass/reject/failed counts, coverage distribution and blocking findings over the first real slice.
What remains is human review of the rejected readings and ownership of that queue, not measurement.

**Treat this item as more urgent than it looks, on evidence.** Two coverage defects were found by
review rather than by testing, and both were invisible for the same reason: the fixtures were
provision-only markdown, so nothing exercised the shape of a real bill. Counting a bill's front
matter scored a *faithful* reading 0.71-0.81 against a 0.95 threshold, and the structural keywords
cost a further 5.2% on short documents. Both are fixed and a faithful reading now scores exactly 1.0
on a realistic fixture — but "realistic fixture" is still a fixture somebody wrote. The threshold
has been reasoned about carefully twice and been wrong twice; the third check has to be real
documents.

- [ ] Read the verdicts before changing the number. `low_text_coverage` alone can be structural
      furniture on a short document (the words `Susunan`, `Fasal` and `Bahagian` never appear inside
      a provision); `sequence_order` beside it is a real table-of-contents bleed.
- [ ] Resolve or explicitly accept the store's 32 same-Expression claims. They come from
      cross-chamber URL records for the same bill/language; the static exporter ranks the
      originating-chamber copy deterministically, but `pipeline verify` correctly remains non-zero
      because 21 pairs produced different promoted readings from identical source bytes. This is
      identity/version tooling, not a reason to hand-delete evidence from `pipeline-data/`.
- [ ] Decide who reads the Gate P1 review queue. It is the same unstaffed-queue question §1.5 and
      §1.8 already raise for OCR and Gate L1 — answer all three once, or accept that
      `document.akn.rejected.xml` is a directory nobody opens.

---

## 2. Not built yet

### 2.1 The OCR worker (HANDOFF 11.4 step 7)

Gated on §1.5. The contract already specifies the shape: an explicit optional queue, recorded as a
separate extractor with `mode = ocr`, never overwriting the native-text attempt.

- [ ] Implement it. The subset is identified and small; the extraction taxonomy already distinguishes
      `succeeded` / `empty` / `failed`, which is what makes the work addressable.
- [ ] Decide what happens to a scan OCR cannot read either — an anomaly, presumably, not silence.

### 2.2 Document relations beyond identical bytes (A11, ADR-003)

- [ ] Nothing to do yet, and that is the finding. After fetching all 1,295 documents **no document
      has a second version**, so revision behaviour is still unobserved and `document_relations`
      heuristics would be built on nothing. Revisit when a revision actually appears.
- [ ] What *is* settled: a document does not have one canonical URL — 62 sets of byte-identical
      documents are published at two or more URLs. Content-hash identity handles it.

### 2.3 A `D.N.` identifier has never been seen (A5)

- [ ] No action, recorded so it is not mistaken for tested behaviour. Not one `D.N.` code exists in
      35 years of archive, so half of ADR-002's originating-chamber rule is unexercised by real data.
      The first `D.N.` row to appear will be its first test.

### 2.4 Three latent defects, harmless today (found 2026-08-19)

None is live. Each is correct under today's single-extractor, single-reading assumptions and each
becomes wrong the moment the next planned change in its area lands. They are recorded rather than
fixed because fixing them now would change behaviour that is currently right.

- [ ] **A second extraction tier will be silently destroyed.** `scraper/service.py`'s
      `persist_current_extraction` demotes *every* `is_current` extraction for a document version
      regardless of `extractor_name`, and `jobs/retention.py`'s `_prune_extractions` keeps two rows
      per version ordered by creation time without partitioning by extractor either. The OCR worker
      (§2.1) is exactly the change that trips both: its output would demote the native extraction,
      `rechunk` filters on `is_current`, and the chunk and embedding pipeline would flip to whichever
      extractor wrote last. **Partition both by `extractor_name` before landing OCR.** Stage L1
      avoids this today only by writing to its own tables (ADR-016).
- [ ] **`documents.document_kind` and `documents.language` are dead fields.** `scraper/ingest.py`
      writes both as `"unknown"` at creation and nothing ever updates them, so the corpus cannot be
      partitioned into BM/EN pairs. Gate L1 does not care — it reads the language from the document's
      own Arrangement heading, which is better evidence — but **Gate L4, the bilingual cross-check,
      is blocked on this** (HANDOFF 26.4).
- [ ] **Provision-aware chunking is inert.** `search/chunking.py`'s `_PROVISION` regex anchors on
      line starts, but `normalize_text` collapses newlines before an extraction is stored, so each
      page arrives as a single line, `_blocks()` returns one block per page, and every chunk is
      page-shaped rather than provision-shaped. Verify with
      `normalize_text("1. Tajuk\n2. Tafsiran")`, which returns `"1. Tajuk 2. Tafsiran"`. This is not
      what HANDOFF 12.3 describes. The layout reading added for Stage L1 is a better source of
      provision boundaries than a regex over flattened text, so the fix and Stage L2 want the same
      input.

### 2.5 Gate L5 (SHACL validation of the ELI graph) is deferred, with a reason

Not an omission and not blocked on a person — blocked on the stages that would give it something to
check. Gate L5's shapes (HANDOFF 26.4, 26.6) test for dangling `amends` targets, missing `validFrom`
on an expression, and overlapping expression intervals for one `wId`+language. **Every one of those
facts is produced by Stage L3 (amendment extraction) or Stage L4 (consolidation)**, neither of which
exists, so pySHACL today would validate an empty half of the shape set and report success — worse
than not running it, because it would read as evidence.

- [ ] Add pySHACL and the shapes when L3/L4 produce `amends` and `validFrom`. The graph is already an
      `rdflib.Dataset` (ADR-028) precisely so this drops in rather than requiring a rewrite.
- [ ] Until then, cite the ELI predicates as **this project's reading of ELI**, not a validated one.
      `eli:has_part`/`eli:is_part_of`/`eli:number`/`eli:language`/`eli:jurisdiction` are asserted by
      our own tests agreeing with our own builder, which is the weakest kind of evidence this
      codebase accepts anywhere.
- [ ] Note what Gate P1 does **not** cover while that is true: it measures source words reaching the
      tree, so a model that *invents* a provision while preserving every real word passes (ADR-025).
      A reverse measure is the obvious next check and is unbuilt; its false-positive behaviour on
      legitimately normalised text is unknown.

---

## 3. Verification gaps

Things that work but whose evidence is thinner than it looks.

- [ ] **Versioning is exercised only by fixtures.** No real document has a second version, so the
      version state machine, supersession notices, and `document_relations` have never run on live
      data. This is the archive being young, not the code being untested — but it is not the same as
      proven.
- [ ] **The slug alias path has never run.** Slugs are derived and none has needed correcting, so
      HANDOFF 10.2's alias mechanism is tested by fixtures only.
- [ ] **The corpus is indexable but never advertised.** ADR-018 chose serving over a static build on
      the strength of indexing the corpus "with the existing search machinery", and the corpus HTML
      pages deliberately carry no `noindex` — but `/sitemap.xml` still lists only `/bills/<slug>`, so
      nothing points a crawler at any `/akn/...` page. Closing it means enumerating Works in the
      sitemap route, which is a per-request walk of the store unless it is cached, and it must stay
      empty while `SERVE_LEGISLATION_CORPUS` is off. Left as a deliberate follow-up rather than
      bolted onto the serving work: the pages resolve and are citable today, which is the property
      that mattered, and discovery is a separate decision with its own cost.
- [ ] **`fixtures-refresh` regenerates, but a human still reduces.** It slices rows and tree nodes
      verbatim from stored snapshots; it does not reproduce the hand-editing in the committed
      fixtures (stripped styling, a row chosen for its status). Output lands in
      `tests/fixtures/parliament/regenerated/` for review, which is deliberate.
- [ ] **The scheduled worker never crawls the archive.** By contract — HANDOFF 11.7 makes the archive
      explicitly triggered. Consequence: nothing refreshes it automatically. Schedule
      `make scrape-archive` on the host if it should be refreshed; monthly is generous, since a
      closed year cannot change.
- [ ] **The legislation corpus has never been served or exported publicly.** Both publication
      flags are off (§1.9). `PIPELINE_DATA_ROOT` now holds the first pilot slice (§1.10), and the
      pilot has already justified the caution once: real drafting exposed a preamble text leak
      past the redactor's wrapper walk (fixed in the 2026-08-22 working tree). What remains
      untested is the combination that matters: real Malaysian drafting, at corpus scale, through
      the publication path — now the §0 export first, the serving path second. Verify
      `contains_provision_text` on a sample of the first real export, not the last.
- [ ] **`make completeness` (bill-numbering gap check, added 2026-08-21) has only run against
      synthetic test data.** The logic is proven — a detected gap, a clean year, an open year's
      gap correctly ignored, chamber isolation, a bill with no parsed number correctly excluded —
      but it has never been run against a chamber-year from the real archive, because that needs
      the same corpus access §1.8 is already waiting on. Run it after the next full archive crawl
      and record whatever it finds (or doesn't) in the gate log; a first real result is also the
      first evidence on whether Malaysian bill numbering has gaps at all, which nothing currently
      confirms either way.

---

## 4. Live-data facts worth re-checking before each release

Upstream is not stable, and each of these is a thing that will break quietly.

- [ ] **The pinned TLS intermediate.** The site serves an incomplete chain, so `UPSTREAM_CA_BUNDLE`
      carries the Sectigo intermediate it omits. That certificate expires. If Parliament fixes its
      chain, drop the setting rather than carrying a pinned intermediate for ever.
- [ ] **`robots.txt` is still absent.** If one appears, the first hash stored becomes the baseline and
      any restriction in it must be obeyed immediately. Every run raises `robots_absent` so the
      decision stays visible.
- [ ] **31 archive links are dead** and answered with `HTTP 200` plus `File does not exist (1)`. All 31
      are acknowledged. Re-check whether any have been fixed upstream; a fixed one will download
      normally on the next crawl.
- [ ] **The status vocabulary will grow.** It is complete for everything published as of
      2026-08-18, and an unmapped phrase raises `unmapped_status` rather than guessing.
- [ ] **Re-run the security review** — `docs/operations.md` → "Security review" has the commands. Nine
      OS packages carry advisories Debian 12 has no fix for; that set changes.
- [ ] **A dedicated image scanner has never been run.** `trivy image` or `grype` should run wherever
      the release image is built. The OSV query in the review stood in for one because no scanner was
      available.

---

## 5. Known-and-accepted, not to be "fixed"

Recorded so nobody spends a day rediscovering the reasoning.

- **`'unsafe-eval'` in the CSP.** Datastar compiles `data-*` expressions with `Function` (ADR-012).
  Accepted, with the injection surface audited down to one escaped expression. The exit is upstream
  shipping a CSP-safe bundle — not adopting a third-party fork for a security property.
- **Deep-ranked pagination is capped** (ADR-007).
- **Three bills carry conflicting titles across chambers**, including D.R.11/2013, where the two
  chambers publish genuinely different bills under one code. They raise
  `duplicate_identifier_conflict` and the first-recorded title stands, rather than flip-flopping on
  every crawl.
- **13 archived readings are dated `30/11/-0001`**, a zero date from the upstream database. Retained
  raw, reported, never guessed into a real date.
- **One bill code is published as `D.R.40/2017 ARKIB`.** A stray token is not punctuation, so it
  fails loudly; the same bill is also published cleanly.
- **The image applies apt security updates at build time**, so the build is deliberately not
  byte-reproducible. Shipping a known-stale trust store to keep a rebuild identical would be
  backwards, given the crawler verifies upstream TLS against it.
