# ADR-031: The published dataset lives in this repository, in full text, after the corpus run widens

Status: accepted
Date: 2026-08-22

Amends ADR-029, which deliberately left decision 1's hosting question open ("publishable by any
static file host — or committed, if the operator so chooses"). This ADR closes it, and settles the
two questions that decide what is actually published.

## Context

Directed by the commissioner on 2026-08-22, after the export step was built, verified against the
real pilot, and recorded in the gate log: **"prioritise static published dataset."**

ADR-029 made the static cache the first publication *surface* and left three things unresolved,
each of which had to be answered by the service owner rather than in code:

1. **Where the cache lives** — this repository, a separate repository, or a sync to a static host
   behind the external nginx (ADR-015). Recorded as an open question in `docs/status.md` since
   2026-08-22.
2. **Which publication mode it ships in.** The exporter supports both. The A14 determination of
   2026-08-22 found that bills are public information, which made `full` legitimate; nothing had
   yet chosen between `metadata` and `full`.
3. **What counts as "the dataset."** The pipeline had processed a pilot only: 123 bill records and
   181 URL-addressed document records, yielding **92 publishable Expressions** — against ~1,269
   bills and 1,264 stored PDFs known to the Postgres-backed system. Publishing the pilot would
   have published roughly 7% of the corpus under a name that implies the whole of it.

The word that changed in the direction is **published**. ADR-029's deliverable was a cache
*produced locally* and deliberately not published; the boundary of that task was "producing it
locally and recording the evidence." This direction moves publication itself into scope, so the
three questions can no longer be deferred.

Measured sizing, taken from the real pilot rather than estimated (gate log, 2026-08-22):

| Mode | Per Expression (3 files) | Pilot dataset (92 Expressions) |
| --- | --- | --- |
| `metadata` | 74.4 kB | 6.84 MB over 276 files |
| `full` | 132.1 kB | 12.15 MB over 276 files |

## Decision

1. **The published dataset is committed to this repository.** `public-cache/` stops being
   gitignored and becomes tracked content. The dataset and the code that produces it share one
   history, one set of tags, and one review path; a consumer who clones the repository gets the
   corpus without a second fetch, and `checksums.sha256` is verifiable against the same commit
   that produced it. This resolves the open question of 2026-08-22.

2. **The published mode is `full`.** `LEGISLATION_PUBLICATION_MODE=full`, which the exporter
   enforces additionally requires `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true`. Both confirmations
   rest on the A14 determination. A metadata-only tree carries no legislative text — 0 of the
   pilot's 276 representations contain a provision — which makes it a catalogue rather than a
   dataset, and a dataset is what was directed.

   `pipeline.redact` is **not** removed or weakened. It remains the publication-boundary control
   and remains exercised by the test suite; `full` is a configured posture, reversible in one
   setting, not a deletion of the mechanism.

3. **Publication waits for the corpus run to widen.** The pilot slice is not published. The
   pipeline runs over the rest of the stored corpus first, and the dataset is published when it
   represents the corpus rather than a sample of it. Two consequences follow:
   - The first published release is a **deliberate, dated release of a known scope**, with the
     scope stated in the repository — not an unlabelled partial tree.
   - Gate P1's rejected readings (A15: 53 of 181 rejected, none yet read by a human) become
     load-bearing, because a rejection is now the difference between a bill being in the published
     dataset and silently absent from it.

4. **Defaults stay safe.** `LEGISLATION_CORPUS_RIGHTS_CONFIRMED` and
   `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED` remain `false` in `billwatcher.config`, `.env.example`,
   and `.env.development`. A fresh clone must not be able to publish by accident; asserting the
   confirmations stays a deliberate operator action in the deployment environment's own `.env`.
   Decision 2 records *which posture is authorised*, not a new default.

5. **The store is still never committed.** ADR-029 decision 5 is unchanged and unweakened.
   `pipeline-data/` — PDFs, markdown, structures, provenance, rejected renders, manifests — stays
   local and gitignored. Only the export tree and the definitions enter version control. The
   exporter's reconciliation is scoped to the namespaces it owns (`akn/`, `definitions/`,
   `index.json`, `checksums.sha256`), so tracking `public-cache/` in git does not put `.git` or
   any other repository file at risk of deletion by a re-export.

## Consequences

- **Publication becomes irreversible in the strongest available sense.** ADR-029 already noted
  that a mirrored cache cannot be withdrawn. Committing it is stricter still: a static host lets
  you delete a file, whereas git history retains every published revision unless the history is
  rewritten. Every commit of the dataset is a permanent publication of that revision.

- **Repository growth is now a real constraint, and it is a function of re-export churn rather
  than of dataset size.** At the measured 132.1 kB per Expression, a corpus-scale full-text
  dataset is roughly **115–160 MB across ~2,600–3,600 files** (~870 Expressions at the pilot's
  68.5% Gate P1 pass rate, up to ~1,200 if the rate improves). That is an acceptable one-time
  size. The cost that compounds is regeneration: under ADR-026 a bump to `AKN_VERSION` or the
  renderer regenerates **every** document, so each such bump is a commit that rewrites the whole
  tree and adds another full copy to history. Whether to accept that growth, squash it, or publish
  from an orphan branch is a follow-up decision recorded in `TODO.md §0`; it is not settled here,
  because it depends on how often those versions actually move.

- **The release needs the things a dataset needs and a cache did not.** A tree of files on a host
  is self-describing enough; a committed, citable dataset carried in a repository needs a stated
  scope, a licence for the project's own output, attribution and disclaimers for the source
  material, and a statement of what the identifiers guarantee. These are enumerated as work in
  `TODO.md §0` rather than invented here.

- **ADR-018 and ADR-027 are untouched.** They govern the Postgres-backed system's served surface.
  This ADR moves only the file-first corpus, exactly as ADR-029 did.

- **Nothing consolidated may enter the published dataset.** Stages L3–L4 output remains under
  TODO 1.7's legal sign-off, a higher bar than A14 and not satisfied by it. Going to full text for
  *bills* does not touch that boundary.
