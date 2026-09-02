# Documentation

| Path | What it is |
| --- | --- |
| `decisions/` | Architecture decision records, ADR-001 onward. The reasoning behind the shape the project has. |
| `status.md` | Where the project actually stands: what is built, what is measured, what is open. |
| `data-model.md` | The corpus layout, FRBR identity, and what the published graph asserts. |
| `operations.md` | Running the pipeline: the live crawl, the gates, what to do when a step fails. |
| `upstream.md` | What Parliament's site does, including the incomplete certificate chain. |
| `history/` | The project's working record, kept unedited. |

`history/` holds the specification the build was driven from (`HANDOFF.md`, ~244 KB), `TODO.md`,
the previous `status.md`, the first corpus run's runbook, and the operations and data-model notes
for the Postgres-backed stack now in `legacy/` — including its 2026-08-18 security review and the
retrieval evaluation sets its search path used.

They are archived rather than deleted: much of the reasoning in the code cites them by section, and
those citations should keep resolving. They describe the project as it was, and are not maintained.
