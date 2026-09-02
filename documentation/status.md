# Status

Written 2026-08-27, after the reorganisation.

## What the project is now

Three stages over local files — download, markdown, graph — and a static publication of the
result. No database, no application server, no model endpoint. `README.md` describes the shape;
this file records where it actually stands.

## Measured, on the real corpus

Numbers from a full `make build` on 2026-08-27:

| | |
| --- | --- |
| Bills downloaded | 1,269 |
| Document PDFs stored | 1,265 |
| Markdown readings | 1,253 |
| Readings flagged `suspect` | 252 (20%) |
| Structures passing Gate P1 | **146 of 1,253 (12%)** |
| Expressions published | 1,192 |
| — with a markdown reading | 1,192 |
| — with a JSON-LD/N-Quads graph | 139 |
| Files in `docs/` | 1,483 |

## Both languages: crawled in code, not yet in the corpus

ADR-040 (2026-08-27) added the four English entry points, the per-document language, and the
wrong-language guard. **The 1,269 bills measured above are still the Malay half of what Parliament
publishes**: the numbers in that table predate the change and no crawl has run since.

- `make download-listings` then `make download` fetches the English half. The listings roughly
  double (69 → ~137 documents) and the document queue is expected to grow by ~1,100 English PDFs,
  about fifty minutes at the crawl delay. Nothing already stored is refetched.
- `make download-listings`'s parse half alone migrates the existing records — `statuses_raw`,
  `source_urls`, `documents[].languages` — offline, from stored bytes, and rewrites all 1,269.
- Whether upstream honours `lang=en` for every target is verified only for the Dewan Rakyat's
  current listing and 2024 archive year (the 2026-08-18 sweep). The rest is expected to behave the
  same way and will report `listings_wrong_language` if it does not.

## Gate P1's pass rate: 28% to 52%, on 2026-08-30

The rejections were a property of the deterministic parser, not of the corpus, and three of the
causes turned out to be nameable and cheap. `AKN_VERSION` 1.3.0 addresses them, measured over all
2,479 stored readings:

| | before | after |
| --- | --- | --- |
| Passing Gate P1 | 690 (27.8%) | **1,292 (52.1%)** |
| `duplicate_eid` | 1,547 | 998 |
| `sequence_order` | 1,704 | 1,107 |
| `sequence_gap` | 1,434 | 737 |
| Published `.jsonld` | 648 | 1,202 |

603 documents gained, **one** lost (`dr-16-2023`, `sequence_gap`); its two stale published files
were left in place by ADR-038 rather than deleted. What the parser stopped doing:

- **Reading the Arrangement of Clauses as clauses.** A bill that prints a contents page prints its
  whole clause list twice, and the parser skipped only the *heading*. It now cuts to the bill's own
  opening — the title block or the enacting formula. `tree.body_start` is shared with the gate's
  coverage view, because the two must cut a document in the same place.
- **Reading quoted amendments as structure.** An amendment bill prints the sections it inserts in
  quotation marks, carrying the *principal Act's* numbering; those became a second clause 13 and a
  sequence leaping to 95 and back. They are now the introducing clause's prose, which is what they
  are, and so still count toward coverage.
- **Reading impossible numbers as clauses.** A cited year (`... Act 1955.`) and a section number
  far ahead of the bill's own sequence are refused. Only those two: a number that runs *backwards*,
  or a Part restarting at 1, is still recorded, because `sequence_order` and `unanchored_run` exist
  to name it and a parser that quietly absorbed it would leave the gate nothing to find.

**What is left is the harder half.** 1,187 readings still fail, and the remaining findings are no
longer one signature — they include genuinely damaged OCR, bills whose clause numbering the reading
lost, and structures a line-by-line reader cannot recover. This is where `structure-handoff` earns
its place: `make handoff OUT=…` writes one packet per document and `make akn FROM=…` reads the
answers back through the identical gate.

The published dataset is now a **corpus of readings** (2,352 markdown expressions) with a **graph
over half of it**.

## What the reorganisation changed

- The Postgres/FastAPI stack moved to `legacy/`, frozen. See `legacy/README.md`.
- Two model-backed steps were dropped: the MinerU cross-check, and LLM-assisted structure
  extraction. Both are recoverable from commit `b0bfb77`; the second one's prompt and parsing
  survive in `graph/handoff.py`.
- The published tree moved from `dist/` to `docs/`, which GitHub Pages serves from this repository,
  and is now shared between the dataset writer and a React frontend that reads the same files a
  `curl` user would.
- `SITE_PREFIX` became the single authority for both `CNAME` and the base of every published FRBR
  IRI. **This fixed a live defect**: the previously published graph carried
  `http://127.0.0.1:8000/...` as the base of its identifiers, which dereferenced to nothing.
- `make build` over an unchanged corpus went from ~11 minutes to 15 seconds: the markdown step now
  consults provenance before reading a PDF rather than after.
- Configuration dropped from ~50 settings to 16, and the runtime dependency set from 19 packages
  to 6. `src/` went from 180 files to 36.

## Open, and not decided here

- **A licence for the project's own output.** `SITE_LICENCE` is deliberately empty; the site says
  so plainly rather than implying terms nobody granted. A published dataset needs one.
- **`robots.txt` is fetched and stored as evidence, but not enforced.** Enforcement lived in the
  legacy crawler. The parser survives at `download/robots.py` and the live smoke test still
  exercises it, but no step in the pipeline consults it.
- **Repository growth.** `docs/` is committed, so every rebuild that changes bytes adds a revision
  to history. A version bump that re-derives the whole corpus rewrites the whole tree. Whether to
  accept that, squash it, or publish from an orphan branch is recorded in
  `history/TODO.md §0` and is still open.
- **`public-cache/` is left in the working tree deliberately, and should not be deleted casually.**
  It is the old export root of a step that no longer exists, so nothing writes it any more. It held
  84 files that could not be regenerated — JSON-LD for 2024–2026 bills whose structures were read by
  the LLM-assisted path dropped in ADR-039, and which the deterministic parser could not get past
  Gate P1. **`AKN_VERSION` 1.3.0 recovered most of them: 81 of its 99 files are now published from
  the corpus, and 18 remain absent** (2026-08-30).

  Those 18 are what a good extraction produced and this parser still cannot, which makes them the
  sharpest comparison target the project has for handoff answers — a small, named set rather than a
  directory-sized one. It is untracked and will
  show up in `git status`; keep it out of any `git add .` until it has been looked at.

- **`make verify` currently exits non-zero on 91 issues**, all one condition: 91 bills each have
  two stored documents that would mint the same Expression IRI. Publication selection is
  deterministic so the published tree is stable, but the underlying data has not been reviewed.
  This predates the reorganisation; it stood at 42 before `AKN_VERSION` 1.3.0 and grew only because
  more documents now pass the gate and so claim an IRI at all. It is ADR-024's recorded
  consequence — the scheme carries no version component — and detection is the designed behaviour,
  not a defect in the reading.

- **`skipped_duplicate_expression: 127` and `conflicting_expressions: 4`** (2026-08-30) — two bills
  competing for one Expression IRI. Selection is deterministic, so the published tree is stable, but the
  underlying data condition has not been reviewed.
