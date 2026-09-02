# ADR-033: The published dataset is a GitHub Pages site in a separate repository, built into `dist/`

Status: accepted
Date: 2026-08-22

**Reverses ADR-031 decision 1**, which had this repository carry the published tree. Keeps ADR-031's
other decisions (`full` mode, publish after the corpus widens) and ADR-032's (JSON-LD first, no
source PDFs) intact, and extends ADR-032's representation set for this surface.

## Context

Directed by the commissioner on 2026-08-22: **"create a directory called dist that I can commit to
another repo as github page. This contains the index.html and the semantic files such as jsonld and
rdf, the build script should allow me to set prefix such as 'bills.engineers.my' (this should be the
default)."** Then, on the build: **"dist should be part of the make target build, do not create
youself."**

Three things change from ADR-031, and one is a reversal:

1. **Where the dataset lives.** ADR-031 answered the ADR-029 hosting question with "committed to
   this repository". This direction names a different answer: *another* repository, served by GitHub
   Pages, on the custom domain `bills.engineers.my`. This is the option ADR-029 listed as "a
   separate repository" and ADR-031 declined.
2. **The tree gains a human entry point.** A cache of files needs no landing page; a domain does.
   `index.html` is what a person gets when they open `https://bills.engineers.my/`, and it is the
   natural home for the publication contract ADR-031 required before release — scope, provenance,
   disclaimer, and what the identifiers guarantee.
3. **The published representations widen from JSON-LD alone to "the semantic files such as jsonld
   and rdf".** In this project's own vocabulary (§28.6) that pairing is the ELI-style JSON-LD and
   the RDF N-Quads. The Akoma Ntoso XML is still not published.

The "do not create youself" instruction is a constraint on *this* work, and a sound one: the
publishable tree is an operator artifact produced by a reviewed command, not something an agent
leaves in a working tree. It also keeps the irreversible act — building, then committing to a public
repository — in the operator's hands, consistent with how every rights flag in this system behaves.

## Decision

1. **`billwatcher pipeline build-site` (Make: `build`) writes a GitHub Pages tree** into
   `PIPELINE_SITE_ROOT`, default `dist/`. It is step 7, offline, and it is the second step that
   writes outside `PIPELINE_DATA_ROOT`.

2. **The tree is the dataset plus exactly three host files:**

   | Path | Content |
   | --- | --- |
   | `index.html` | the landing page: counts, how to fetch and verify, what the identifiers guarantee, provenance and disclaimer, and a table of every published Work |
   | `CNAME` | the bare hostname, which is how Pages learns the custom domain |
   | `.nojekyll` | so Pages serves the tree verbatim instead of running Jekyll over it |
   | `akn/…/<lang>@.jsonld`, `…@.nq` | the semantic files, on their permanent §28.7 paths |
   | `definitions/`, `index.json`, `checksums.sha256` | unchanged from §28.12 |

3. **The site cannot publish anything the dataset export would withhold.** Both call the same
   `export.build_projection`, so gate selection, FRBR identity, deduplication, `pipeline.redact`
   at the publication boundary, and the source-bytes refusal are one implementation, not two.
   `build-site` enforces the same rights confirmations at the same hardness.

4. **The prefix is configuration with a default.** `PIPELINE_SITE_PREFIX` defaults to
   `bills.engineers.my`; `--prefix` (Make: `PREFIX=`) overrides it. It is normalised to a bare
   hostname — a pasted scheme or trailing slash is stripped — and anything still not a hostname is
   **refused**, because it would otherwise be written verbatim into `CNAME` and silently break the
   domain. It sets `CNAME`, the canonical link, and the copy-pasteable examples on the page.

5. **`PIPELINE_SITE_REPRESENTATIONS` defaults to `semantic`** (`jsonld` + `nq`), against `jsonld`
   for the bare dataset export. `all` adds the Akoma Ntoso XML. The store still keeps every
   representation regardless (ADR-032 decision 5).

6. **`dist/` is gitignored *here*.** It is generated, and it is committed to the *other*
   repository — the one Pages serves. `public-cache/` stays gitignored too: with the site as the
   publication channel, nothing in this repository needs to carry the dataset.

7. **The page is deterministic.** No build timestamp, and the catalogue is already sorted, so a
   rebuild over an unchanged corpus rewrites nothing — §28.9's discipline applied to a file whose
   content is derived rather than stored. Without this, every rebuild would be a commit.

8. **Reconciliation stays scoped, and this is now load-bearing rather than defensive.** The site
   root may be a checkout of the publishing repository, so `.git/`, its `README.md`, its `LICENSE`
   and any workflow files are files the step must not touch. It prunes only within `akn/`,
   `definitions/`, `index.json`, `checksums.sha256`, `index.html`, `CNAME` and `.nojekyll`.

9. **No GitHub Actions, ever.** The standing constraint holds: the tree is built locally by the
   Make target and the built files are committed. Pages serves them directly; nothing runs in CI.

## Consequences

- **ADR-031 decision 1 is withdrawn.** The rest of ADR-031 stands: `full` mode, and publication only
  once the corpus run widens past the pilot. ADR-032 stands, with its representation default
  extended for this surface only. The open question ADR-029 raised — where the cache lives — is
  answered differently than it was this morning, and the ledger records both answers with dates
  rather than overwriting the first.
- **Publication is still irreversible, and now the git-history argument moves to the other
  repository.** ADR-031's history-growth question (an `AKN_VERSION` bump rewrites every file, and
  each rebuild commits another copy) applies to the publishing repository instead of this one. It
  remains undecided and remains a `TODO.md §0` item; it is now somewhat easier, because that
  repository's history can be squashed or orphaned without touching the code history.
- **The site is a second surface carrying the same content, so the redaction and gating guarantees
  had to become shared code rather than parallel code.** That refactor is the substantive
  engineering in this ADR; the landing page is the visible part.
- **`.jsonld` and `.nq` MIME types are whatever Pages serves.** Content type cannot be configured
  on Pages, so consumers should not rely on it; `index.json` names the formats, and the extension
  is the contract. Recorded as a known limitation, not a defect to fix here.
- **The licence is still unstated, and the page says so.** ADR-031 listed a licence for the
  project's own output as a release prerequisite and it has not been chosen. `index.html` therefore
  carries an explicit "not yet stated … treat it as unlicensed for redistribution" note rather than
  implying terms. **This is the item to settle before the first commit to the public repository**,
  because a published page that misstates reuse terms is worse than one that admits they are
  pending.
