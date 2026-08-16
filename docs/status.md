# Implementation status

Last reconciled: 2026-08-17 (Asia/Kuala_Lumpur).

## Package ledger

| Package | State | Owner/agent | Branch | Started | Last update | Evidence | Blockers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A scaffold/runtime | done | Codex | worktree | 2026-08-16 | 2026-08-17 | make check; locked image build; fresh Compose health; UID 10001; read-only app blob mount | — |
| B discovery/model | in_progress | Codex | worktree | 2026-08-16 | 2026-08-17 | schema invariants; five parser fixtures | Reviewed live discovery pending |
| C scraper/versioning | in_review | Codex | worktree | 2026-08-16 | 2026-08-17 | 67 tests: document worker, extraction history, orchestration, robots, replay, queue and versioning | Reviewed live full crawl and real parser-bump replay pending |
| D web/search | done | Codex | worktree | 2026-08-17 | 2026-08-17 | 69 tests plus PostgreSQL simple-dictionary smoke; document scale/supersession; SSR/API | — |
| E operations/deploy | in_review | Codex | worktree | 2026-08-17 | 2026-08-17 | image/Compose health, PostgreSQL search, database+blob restore drill, UID/mount checks, Make check | external HTTPS and vulnerability review pending |
| F JSON-LD/discovery | done | Codex | worktree | 2026-08-17 | 2026-08-17 | current, passed, bilingual and malicious JSON-LD tests; canonical and sitemap | — |
| G semantic search | not_started | — | — | — | — | — | Release 1 |
| H RAG | not_started | — | — | — | — | — | Package G evaluation |

## Assumption status

| ID | Status | Verified on | Evidence |
| --- | --- | --- | --- |
| A1 | open | — | Live discovery not yet approved/run |
| A2 | open | — | Fixture required |
| A3 | open | — | Archive discovery ADR proposed |
| A4 | open | — | Cross-chamber fixture required |
| A5 | open | — | ADR-002 proposed; fail-loud parser implemented |
| A6 | open | — | Parser supports claim; upstream fixture required |
| A7 | open | — | Parser/tests cover formats; upstream fixture required |
| A8 | open | — | Archive discovery required |
| A9 | open | — | Status map remains provisional pending full sweep |
| A10 | open | — | Document sample required |
| A11 | open | — | ADR-003 proposed |
| A12 | open | — | First reviewed full crawl required |
| A13 | open | — | robots.txt must be fetched before crawling |
| A14 | open | — | Rights review required |

## Decision index

| ID | Title | State | Date |
| --- | --- | --- | --- |
| ADR-001 | Mypy and semantic parser selection | accepted | 2026-08-16 |
| ADR-002 | Bill identifier rules | proposed | 2026-08-16 |
| ADR-003 | Document identity and versioning | accepted | 2026-08-16 |
| ADR-004 | Official-link-only publication | proposed | 2026-08-16 |
| ADR-005 | Rollback version uniqueness | accepted | 2026-08-17 |
| ADR-006 | Runtime operations | accepted | 2026-08-17 |

## Open questions

| Question | Raised by | Raised on | Owner | Needed by |
| --- | --- | --- | --- | --- |
| What exact request contract serves archived listings? | HANDOFF A3 | 2026-08-16 | Discovery owner | B/C |
| What is the complete bilingual status vocabulary? | HANDOFF A9 | 2026-08-16 | Discovery owner | B/C |
| Does a revised document normally retain its URL? | HANDOFF A11 | 2026-08-16 | Discovery owner | C |
| May stored official PDF bytes be republished? | HANDOFF A14 | 2026-08-16 | Service owner | E |

## Manual gate log

- 2026-08-17 — Codex — Fresh Compose rehearsal passed for database health, one-shot migration, app readiness, non-root UID, and read-only app blob mount; external TLS and restore were not covered.
- 2026-08-17 — Codex — Isolated restore drill passed: PostgreSQL custom dump restored into a new database, seeded bill and blob reference verified, blob bytes restored and SHA-256 verified, and UID-10001 ownership confirmed. In-place destructive restore was not run.

The isolated database-plus-blob restore drill has passed. Dependency review, container vulnerability review,
external HTTPS validation, live crawl approval, and rights review remain required before release.

## Requirement evidence

Current evidence is developmental only. No release requirement is marked complete until the
HANDOFF section 18 acceptance walkthrough and section 22 evidence matrix are satisfied.
