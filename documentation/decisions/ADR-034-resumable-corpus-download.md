# ADR-034: The corpus download is resumable, and only closed archive years may be skipped

Status: accepted
Date: 2026-08-22

## Context

Directed by the commissioner on 2026-08-22: **"the pipeline should download all the bills, skip if
exists locally."** This is the gating item of `TODO.md §0` — the published dataset cannot represent
the corpus until the pipeline has read more than the pilot's 123 bills of ~1,269.

Half of it was already true. Step 3 (`fetch_documents`) iterates every bill in the store and skips
any document where `store.has_document(...)` holds, so a re-run downloads only what is missing; that
is where the cost is (1,264 PDFs at one request every two seconds). Step 1 (`fetch_listings`) fetches
all archive years when given no `--archive-years` limit, so "all the bills" needed no change either.

What was missing is that step 1 had **no skip at all**: every run re-fetched `robots.txt`, both
current listings, both archive indices, and all ~67 archive year documents. A crawl interrupted
partway had to start over.

The reason it had no skip is worth stating, because it is the trap: **listings are mutable, and they
are the only way anything new is discovered.** A naive "skip if it exists locally" applied to a
current listing means the crawl never sees a bill Parliament added after the first run. That is not a
saved request; it is a silent coverage hole, and it would be invisible — the run would report success
while quietly having stopped tracking Parliament.

## Decision

1. **`fetch_listings` skips by default (`skip_existing=True`), but only closed archive years.** An
   archived year strictly before the current calendar year cannot gain rows, so a stored successful
   snapshot is the whole answer for it.

2. **Four things are never skipped**, and this is the load-bearing half of the decision:
   - `robots.txt` — crawl policy can change, and A13's "there is no policy" finding is a fact about
     a moment in time.
   - both **current** listings — where a newly introduced bill first appears.
   - both **archive indices** — where a newly closed year first appears.
   - the **current calendar year's** archive — Parliament is still adding rows to it.

3. **A stored non-200 does not count as "exists locally".** `store.has_listing` requires a stored
   `status_code == 200` and a body. Skipping exists to avoid redundant work, not to freeze a bad
   response into the record: a re-run must retry a failure, not cement it.

4. **`--refetch-archive` forces the closed years to be re-read**, for the case where a parser fix or
   a suspected upstream correction makes re-reading the archive the point of the run.

5. **`make pipeline-download` is the whole-corpus command**: `fetch-listings` (no year limit) →
   `parse-listings` → `fetch-documents`. Both live steps skip what is already stored, so the target
   is safe to re-run and safe to interrupt — running it again resumes rather than restarts.

## Consequences

- **An interrupted full crawl now costs only what it had not yet fetched.** Over the archive that is
  ~67 year documents per chamber and, far more importantly, whatever slice of the 1,264 PDFs already
  landed.
- **Politeness is unchanged.** Skipping reduces the number of requests; it never shortens the delay
  between the ones that are made (§5's crawl policy, one request every two seconds).
- **Discovery keeps working on every run**, by construction rather than by remembering to force a
  refresh. A test pins it: a bill added to the current listing between two runs is found by the
  second, while the closed years are still skipped.
- **A permanently dead document URL is retried on every run.** ~31 links answer HTTP 200 with a
  23-byte `File does not exist (1)` body (A10), so they never store and never count as present. At
  two seconds each that is about a minute per run — accepted rather than fixed, because recording a
  negative result raises a question this ADR does not need to answer (when should a dead link be
  retried?). If it becomes annoying, that is the design to have deliberately.
- **Step 1's counts gain `skipped`**, so a run's output shows how much was resumed rather than
  fetched. Step 3 already had it.
