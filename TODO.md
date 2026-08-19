# TODO

Everything known to be outstanding, in one place. Written 2026-08-18.

`docs/status.md` stays the ledger — the assumption register, the decision index, and the dated
evidence. This file is the **work list**: what is left, who can close it, and what closing it takes.
When an item is done, record the evidence in the `docs/status.md` gate log and delete the item here.
If the two ever disagree, `docs/status.md` is right, because it carries dates.

Nothing below is a known defect. The suite is green (`make check`, and `make test-pg` at 296 tests
with nothing skipped), `make doctor` is clean, and the site serves 1,269 bills spanning 1990–2026
from live data. These are the things that are genuinely not finished.

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

### 1.2 Decide whether stored PDFs may be republished (A14) — *service owner, legal judgement*

The evidence is gathered and points one way: the site publishes **no licence and no terms of use**,
and the only copyright statement anywhere is `© Hakcipta Terpelihara Parlimen Malaysia` — all rights
reserved. See `docs/upstream.md` → "the site's published policies, read in full".

- [ ] Decide: rely on a statutory exception, ask Parliament for permission, or keep serving links
      only. Record the outcome in the `docs/status.md` gate log.
- [ ] Only then `SERVE_ARCHIVED_DOCUMENTS=true` **and** `ARCHIVED_DOCUMENT_RIGHTS_CONFIRMED=true`.
      Production refuses the first without the second, so that turning serving on is the recorded
      decision rather than a flag flip (ADR-013, ADR-004).

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

---

## 3. Verification gaps

Things that work but whose evidence is thinner than it looks.

- [ ] **Versioning is exercised only by fixtures.** No real document has a second version, so the
      version state machine, supersession notices, and `document_relations` have never run on live
      data. This is the archive being young, not the code being untested — but it is not the same as
      proven.
- [ ] **The slug alias path has never run.** Slugs are derived and none has needed correcting, so
      HANDOFF 10.2's alias mechanism is tested by fixtures only.
- [ ] **`fixtures-refresh` regenerates, but a human still reduces.** It slices rows and tree nodes
      verbatim from stored snapshots; it does not reproduce the hand-editing in the committed
      fixtures (stripped styling, a row chosen for its status). Output lands in
      `tests/fixtures/parliament/regenerated/` for review, which is deliberate.
- [ ] **The scheduled worker never crawls the archive.** By contract — HANDOFF 11.7 makes the archive
      explicitly triggered. Consequence: nothing refreshes it automatically. Schedule
      `make scrape-archive` on the host if it should be refreshed; monthly is generous, since a
      closed year cannot change.

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
