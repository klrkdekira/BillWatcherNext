# First corpus run

The runbook for putting the first real Parliament documents through the file-first pipeline
(HANDOFF §28), reading what Gate P1 says about them, and recording the evidence. Written as a
handoff: everything needed to execute it is in this file, and nothing here assumes the session that
built the pipeline.

**Why this run matters more than an ordinary smoke test.** Every part of the pipeline is green
against fixtures — 626 offline tests, 654 with PostgreSQL — and none of it has ever seen a real
document. That gap has already bitten twice: two coverage defects in Gate P1 were invisible to a
passing suite because the fixtures were provision-only markdown, and each would have rejected a
*faithful* reading of a real bill (see the 2026-08-22 gate-log entry in `docs/status.md`). The
threshold has been reasoned about carefully twice and been wrong twice. The third check has to be
real documents, and this run is it.

**What this run produces:** a pilot corpus under `pipeline-data/`, a Gate P1 verdict for every
converted document, a measured pass/reject distribution recorded in the `docs/status.md` gate log
(closing the first two boxes of TODO §1.10), and the evidence the owner needs for the publication
decision in TODO §1.9. It publishes nothing: `SERVE_LEGISLATION_CORPUS` stays `false` throughout,
except for one local-only smoke test in Phase 6.

**Who does what.** Phases 1, 3, 4, 5 and 6 are a developer or operator at a terminal. Phase 2 needs
the operator specifically, because it uses their vLLM endpoint and their knowledge of which PDF is
which language. The decisions in Phase 7 are the service owner's alone.

---

## Phase 0 — prerequisites

Work through these in order; each later phase assumes them.

1. **The tree is green.** `make check` passes. If it does not, stop — this runbook validates the
   pipeline, not the other way round.
2. **The upstream trust bundle exists.** Parliament's site serves an incomplete certificate chain
   (`docs/upstream.md`), so a live crawl fails TLS verification without the repaired bundle:

   ```sh
   make ca-bundle
   # then in .env:
   UPSTREAM_CA_BUNDLE=/absolute/path/to/var/upstream-ca.pem
   ```

3. **The vLLM endpoint is configured**, for step 5 (Akoma Ntoso conversion):

   ```sh
   # in .env:
   AKN_LLM_ENABLED=true
   AKN_LLM_BASE_URL=https://llm.loqasi.io/v1
   AKN_LLM_MODEL_ID=qwen-3.8-27b        # or whatever the endpoint serves
   ```

   Leave `AKN_GATE_MIN_TEXT_COVERAGE` at its default (0.95) for this run — measuring whether that
   default is right is one of the run's purposes, and moving it first would spoil the measurement.
4. **Rights are decided; readiness is not — keep the publication flags off during this run.** The
   owner determined on 2026-08-22 that bills are public information (the `docs/status.md` gate log
   entry is the authority), so setting the confirmation flags is legitimate. It is still wrong to
   set them *before* this run: publication being permitted does not make an unmeasured corpus fit
   to publish, and Gate P1 has never seen a real document. Phase 6 flips the serve flag locally,
   briefly; Phase 7 is where production goes live.
5. **Know where the store is.** Everything lands under `PIPELINE_DATA_ROOT` (default
   `pipeline-data/`, gitignored). The commands below assume the default; substitute if yours
   differs. This directory is *the record* for this pipeline — not a rebuildable projection — so
   from this run onward it belongs in whatever backup you operate (`docs/operations.md`, "Backups
   and restore").
6. **Budget.** The full corpus is ~1,264 PDFs at 0.24 GB, and step 5 costs one LLM call per
   document. The pilot below deliberately fetches far less. Politeness is enforced at 2 seconds per
   request and must not be tuned down: the pilot crawl takes minutes, a full crawl takes hours, and
   that is the correct price.

---

## Phase 1 — pilot crawl

Fetch a bounded slice: both current listings plus the newest archived year.

```sh
make pipeline-fetch-listings ARGS="--archive-years=1"
make pipeline-parse-listings
make pipeline-fetch-documents
```

> **Trap, recorded because it is easy to hit:** `--archive-years=0` does not mean "no archive
> years" — zero is falsy in the limit check, so it fetches **all** of them. Use `1` for the
> smallest live slice.

Each command prints one JSON line of counts. After each step, look before moving on:

- **After fetch-listings** — expect `{"fetched": N, "failed": 0}`. Any `failed` above zero on a
  pilot is worth understanding before continuing (usually TLS without the CA bundle, or the site
  being down).
- **After parse-listings** — expect `bills_touched` in the tens-to-low-hundreds for one archive
  year plus current listings. Open one record and check it carries what the identifiers need:

  ```sh
  jq '.identifier' pipeline-data/bills/*/bill.json | head -30
  ```

  Every record must have `originating_chamber`, `year` and `number` — a bill missing any of these
  will (correctly) fail conversion later rather than mint a placeholder identifier.
- **After fetch-documents** — expect `downloaded` ≈ `considered` and `failed` near zero. Spot-check
  that the bytes are really PDFs and the sidecars carry their digests:

  ```sh
  file pipeline-data/documents/*/*/v001/document.pdf | head -5
  jq '{sha256, byte_size, source_url}' pipeline-data/documents/*/*/v001/metadata.json | head -20
  ```

---

## Phase 2 — markdown production *(operator)*

PDF-to-markdown is deliberately outside this pipeline (ADR-021): the operator runs their own
endpoint against each stored PDF and brings the markdown back. Two ways in, both capturing the
provenance the rest of the pipeline depends on.

**The language declared here is load-bearing.** It becomes a permanent component of the Expression
IRI (`…/msa@` vs `…/eng@`), and the conversion step cross-checks it against the document's own
Arrangement heading — a disagreement is recorded in the gate verdict, and a document with no
language from either source fails rather than being guessed. Do not infer language from the
filename; upstream spells it inconsistently, which is exactly why declaration exists.

**Single document** (good for the first few, to see the shape):

```sh
uv run billwatcher pipeline import-markdown \
  --source /path/to/extracted.md \
  --language ms \
  --tool mineru --model MinerU2.5-2509-1.2B \
  --bill dr-15-2026 \
  --document-url "https://www.parlimen.gov.my/files/billindex/pdf/DR152026.pdf"
```

`--document-url` is the same URL the fetch step downloaded; the command derives the document key
from it, so the two can never disagree about which directory a document lives in. The stderr line
`WARNING … declared 'ms', document reads 'en'` means the declaration and the document disagree —
resolve it before converting, because the declared value wins.

**Bulk tree** (the shape for a real batch): lay the markdown out mirroring the store's own
`documents/` layout — `<bill-slug>/<doc-key>/v001/document.md` — and import the whole tree in one
command, one language per run:

```sh
make pipeline-import-markdown SRC=/path/to/markdown-tree LANG=ms TOOL=mineru \
  ARGS="--model MinerU2.5-2509-1.2B"
```

The bill slugs and document keys to mirror are simply the directory names already under
`pipeline-data/documents/`. A working loop shape, with your extractor where the comment is:

```sh
for meta in pipeline-data/documents/*/*/v001/metadata.json; do
  dir=$(dirname "$meta")
  rel=${dir#pipeline-data/documents/}          # <bill-slug>/<doc-key>/v001
  mkdir -p "md-tree/$rel"
  # --- your endpoint here: read "$dir/document.pdf", write "md-tree/$rel/document.md" ---
done
```

Files the tree import cannot match to a stored document are listed as
`WARNING source file matched no stored document` — a mis-shaped tree reports itself rather than
silently importing nothing. Re-importing identical markdown writes nothing; re-importing *changed*
markdown automatically restages every artifact derived from it.

---

## Phase 3 — conversion

```sh
make pipeline-convert-to-akn        # one vLLM call per eligible document
make pipeline-generate-semantic     # offline, no network
```

What the counts mean, and what to expect from a first real batch:

- `converted` — passed Gate P1, schema-validated against the vendored OASIS AKN 3.0 XSD, and
  published into the store with its provenance.
- `rejected` — the reading could not account for its source. **Not an error state of the run.** The
  verdict is in `document.akn.gate.json` and the failing render in `document.akn.rejected.xml`;
  nothing downstream picks either up. Some rejections on a first real batch are the gate working.
- `failed` — the step itself failed for that document (endpoint error, missing language, incomplete
  bill record). Each is named on stderr with its reason, and the run's manifest under
  `pipeline-data/manifests/convert-to-akn/` keeps the list.

Do not chase individual documents yet — Phase 4 reads the whole distribution first, which is the
point of the run.

---

## Phase 4 — read the gate *(the actual purpose)*

Aggregate every verdict before looking at any single one:

```sh
GATES=$(find pipeline-data/documents -name document.akn.gate.json)

# 1. Status histogram — the headline number
cat $GATES | jq -s 'group_by(.status) | map({status: .[0].status, n: length})'

# 2. Coverage distribution — is 0.95 the right line?
cat $GATES | jq -s '[.[] | select(.coverage != null) | .coverage] | sort |
  {n: length, min: .[0], p25: .[length/4|floor], median: .[length/2|floor],
   p75: .[length*3/4|floor], max: .[-1]}'

# 3. Which findings actually fire
cat $GATES | jq -s '[.[].findings[]? | .kind] | group_by(.) |
  map({kind: .[0], n: length}) | sort_by(-.n)'

# 4. Language disagreements — each one is a possible wrong permanent IRI, caught in time
cat $GATES | jq -s '[.[] | select(.language_disagreement != null) |
  .language_disagreement] | group_by(.) | map({case: .[0], n: length})'
```

**Reading the histogram** (from TODO §1.10, restated here so this file stands alone):

- **Rejection near 100%** → the threshold or the measurement is wrong, not the corpus. This exact
  signature has appeared twice pre-launch (front matter in the denominator; structural keywords in
  the denominator). Look at the coverage distribution: a tight cluster just *below* 0.95 across
  faithful-looking documents means the denominator still counts something no tree can carry —
  that is a code fix, not a threshold change.
- **Rejection near 0% is not automatically good.** Check finding kinds fire at all on documents
  known to be hard. A gate that never fires is not doing anything.
- **A healthy result** is most documents passing with coverage well above threshold, and a
  reviewable tail of rejections whose verdicts name real problems.

**What each finding kind means when you drill into one document:**

| Finding | What it says | Usual cause on real documents |
| --- | --- | --- |
| `duplicate_eid` | two provisions got one identifier | Arrangement bled into the body (the model failed at its one hard job) |
| `missing_num` | a provision has no printed number | model emitted an unnumbered node; would silently merge into its parent |
| `sequence_gap` / `sequence_order` | skipped or backwards numbering | TOC bleed (backwards) or a dropped provision (gap) |
| `unanchored_run` | the run doesn't start at 1 or 2 | reading lost the document's opening provisions |
| `no_source_text` | nothing scoreable in the source | extraction recovered nothing from a scan — the *markdown* is the problem |
| `low_text_coverage` | source words absent from the tree | dropped page/schedule — or, if widespread on good documents, a denominator bug |

To inspect one rejection: the verdict, the rejected render, and the source, side by side —

```sh
D=pipeline-data/documents/<slug>/<doc-key>/v001
jq . "$D/document.akn.gate.json"
less "$D/document.akn.rejected.xml" "$D/document.md"
```

**Evaluating a different threshold costs nothing — changing it costs a full re-extraction.**
`pipeline verify --strict` re-judges every stored verdict offline at the currently configured
threshold, with no model calls:

```sh
AKN_GATE_MIN_TEXT_COVERAGE=0.90 uv run billwatcher pipeline verify --strict
```

Every `gate p1 now reads …` line is a document whose verdict would change. Use this to find the
number, and only commit it to `.env` when you are prepared for the consequence: the threshold is
part of each artifact's provenance, so changing it restages **every** converted document, and the
next `pipeline-convert-to-akn` re-runs the LLM extraction for all of them. Read the verdicts before
moving the number — that instruction is TODO §1.10's, and it exists because the number has been
wrong for reasons a threshold change would not have fixed.

---

## Phase 5 — integrity and idempotence

```sh
make pipeline-verify          # expect: {"issues": 0}, exit 0
```

Then prove the run is a fixed point — the property the whole store design rests on (ADR-019,
ADR-026):

```sh
find pipeline-data -type f -newer /tmp/marker 2>/dev/null  # after: touch /tmp/marker
make pipeline-convert-to-akn      # expect eligible: 0
make pipeline-generate-semantic   # expect eligible: 0
find pipeline-data -type f -newer /tmp/marker              # expect: nothing
```

A second run that writes anything (manifests aside — those are per-run by design) is a defect;
report it rather than shrugging.

If `pipeline verify` reports issues, the message prefix says which kind of problem you have:
`content differs …` is damage (bytes no longer match their own record); `stale: …` (only under
`--strict`) means re-run the producing step; `present in the store with no step that writes it`
is a stray file; `two documents claim one expression iri` means one bill has two published
readings in one language — the version-chain limitation ADR-024 records, detected rather than
silent, and a case to bring to the owner.

---

## Phase 6 — local serving smoke test

```sh
make db-up                          # the app boots against the dev database
# in .env, temporarily:
SERVE_LEGISLATION_CORPUS=true
make serve
```

Visit, substituting a bill the pilot actually converted:

- `http://127.0.0.1:8000/akn/my` — and click down through every level; each must resolve.
- `…/akn/my/bill/dr/<year>/<number>/msa@` — the reading, structure only.
- the `.xml`, `.jsonld`, `.nq` variants — right content types, `Link: rel="alternate"` headers.

**The leak check, which is the part that matters.** Pick a full sentence from a stored
`document.md` — a drafted sentence, not a heading — and confirm no served representation contains
it:

```sh
S="Akta ini bolehlah dinamakan"            # use a real sentence from your corpus
B="http://127.0.0.1:8000/akn/my/bill/dr/<year>/<number>"
for p in "" "/msa@" "/msa@.xml" "/msa@.jsonld" "/msa@.nq"; do
  printf '%-14s %s\n' "${p:-work}" "$(curl -s "$B$p" | grep -c "$S")"
done                                        # every count must be 0
```

This checks that the *mode switch* does what it claims, which matters even though production will
run in full mode: `LEGISLATION_PUBLICATION_MODE` is the mechanism that would withdraw text again if
the rights determination were ever revisited, and a reversibility mechanism that has never been
exercised is a promise, not a control. In the default `metadata` mode every count must be 0 while
provision numbers and short headings still appear; set `LEGISLATION_PUBLICATION_MODE=full` and
re-run the same loop, and the counts must become non-zero. A leak in metadata mode is a release
blocker — file it, do not rationalise it. Then reset both flags: Phase 7 is where production
configuration happens deliberately.

---

## Phase 7 — record, then decide

**Record** (developer/operator): a dated entry in the `docs/status.md` gate log, in its usual
voice. What it must contain, per TODO §1.10:

```markdown
- **YYYY-MM-DD — first real-corpus run (Gate P1 calibration).** N documents crawled
  (--archive-years=1 plus current listings), N imported (ms: N, en: N), converted N /
  rejected N / failed N at threshold 0.95. Coverage distribution: min …, median …, p25 … .
  Blocking findings: <kind: n, …>. Language disagreements: N, resolved by … .
  `pipeline verify`: 0 issues; second run wrote nothing. Local serving smoke test: every
  truncatable level resolves; leak check 0 hits across all representations for "<sentence>".
  Verdict on the 0.95 default: <keep / move to X because …>. Rejected documents reviewed: <…>.
```

Tick the boxes this closes in TODO §1.10, and update the item if the threshold conclusion changes
its remaining work.

**Decide** (service owner — nothing below is a developer's call):

1. **The threshold** — keep 0.95 or move it, on the measured distribution, knowing a change
   restages the corpus (Phase 4).
2. **The full crawl** — if the pilot is healthy, the same phases at full scale
   (`make pipeline-fetch-listings` with no ARGS). Same politeness, more hours, ~1,264 more LLM
   calls in step 5.

**Go live** (operator, once the pilot is healthy and recorded). The rights determination is already
made and recorded (gate log, 2026-08-22), so this is configuration, in this order:

```sh
# in the production .env:
ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true    # asserts the recorded A14 determination
LEGISLATION_CORPUS_RIGHTS_CONFIRMED=true   # asserts the recorded corpus determination
SERVE_LEGISLATION_CORPUS=true              # the corpus, on truncatable /akn/... paths
LEGISLATION_PUBLICATION_MODE=full          # provision text included, per the determination
SERVE_ARCHIVED_DOCUMENTS=true              # optional: the stored PDFs themselves (ADR-013)
```

Production refuses each serving flag without its confirmation — that pairing is the design, so
turning a surface on is always the recorded decision rather than a stray flag. The deployment also
needs `pipeline-data/` mounted where the app can read it (`compose.yaml` mounts the `pipeline_data`
volume read-only into `app`; the pipeline steps run outside the stack and write it). What stays
off regardless: the N-Quads mirror dump, which is unbuilt and separately gated (TODO §1.7), because
a served page can be withdrawn and a mirror cannot.

---

## Troubleshooting

| Symptom | Meaning | Fix |
| --- | --- | --- |
| TLS failure on fetch | missing intermediate cert | `make ca-bundle`, set `UPSTREAM_CA_BUNDLE` |
| `live fetch is disabled` | live-crawl gate | Make targets pass `--approve-live`; direct CLI calls need it explicitly |
| `FAIL: no AKN structure extractor is configured` | step 5 config | set the three `AKN_LLM_*` variables |
| `FAILED …: FrbrIdentityError: no language on the record …` | no declared language, no Arrangement heading | re-import that document with `--language` |
| `FAILED …: FrbrIdentityError: no originating chamber …` | incomplete bill record | inspect `bills/<slug>/bill.json`; a parse problem, not a conversion one |
| `FAILED …: AknSchemaError: …` | our renderer emitted invalid AKN | a code defect — file it with the document; never relax the validator |
| `gate P1 mismatch: …` on most documents | measurement or threshold wrong | Phase 4's histogram logic; look for a denominator bug before touching the number |
| verify: `two documents claim one expression iri` | one bill, two readings, one language | ADR-024's version-chain limit, detected; owner decision |
| a served page 503s `Our reading … unavailable` | artifact missing/corrupt for that document | `make pipeline-verify`, then re-run the producing step |

**Resetting.** Deleting any derived file (`document.akn.xml`, the semantic pair, their provenance
sidecars, `document.akn.gate.json`) is always safe — the staleness gate regenerates on the next
step run. Deleting listings, `bill.json`, PDFs or `document.md` destroys the record and means
re-crawling or re-importing. Never hand-edit a sidecar: `verify` will (correctly) report it as
damage.

**Hard boundaries, restated so they travel with this file:** no N-Quads dump (ADR-018 — a mirror
cannot be withdrawn; unbuilt and separately gated, TODO §1.7); no politeness tuning; nothing from
`lom.agc.gov.my` (a different publisher whose rights questions are not inherited, HANDOFF 26.7);
and no consolidated law (a higher bar than A14, needing legal sign-off, TODO §1.7). The A14
determination for Parliament's bills is made and recorded (gate log, 2026-08-22) — the flags in
Phase 7 assert that record, they do not substitute for it.
