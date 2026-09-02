# ADR-038: A build does not delete; withdrawal is an explicit action

Status: accepted
Date: 2026-08-24

## Context

Directed on 2026-08-24, after an incident: "the build should not be destructive."

`write_tree` reconciled the tree it wrote. Anything under a namespace the step owns (`akn/`,
`definitions/`, `index.json`, `checksums.sha256`) that the current build did not emit was unlinked,
every run, silently. The scoping was careful and correct as far as it went — `.git/`, a
hand-written `README.md`, `CNAME` and `LICENSE` were never ours to touch (ADR-029) — but *within*
those namespaces deletion was unconditional.

The reason it existed is real and is not in dispute: a reading the gate has stopped passing must
stop being published, or the tree serves a rejected reading forever. "The gate decides whether the
file exists" (ADR-025).

What the incident showed is that the same rule, applied automatically, makes a build destructive
exactly when the operator can least afford it. A bug elsewhere in the pipeline had emptied the store
of its derived Akoma Ntoso and semantic artifacts. `dist/` still held the 92 published Expressions —
by that point the **only** surviving copy of them. A build run in that state would have found
nothing to emit for them, classified all 184 files as no-longer-published, and deleted them. The
reconciliation would have been working exactly as designed.

The premise underneath the old behaviour is that a published tree is disposable because it is
derived. That premise holds right up until the source is incomplete, and then it inverts: the
derived tree is the last backup. A build cannot tell which case it is in — "the store has no
artifacts for this Expression" reads identically whether the reading was withdrawn or the store is
mid-repair — so it must not be the thing that decides.

## Decision

1. **`prune=False` is the default.** A build writes and never unlinks. `write_tree` returns
   `(written, removed, stale)`; with `prune=False`, `removed` is 0 and `stale` names what a prune
   would have taken.

2. **Withdrawal becomes an explicit action, not a side effect.** `--prune` on
   `pipeline export-static` and `pipeline build-site` performs the deletion. The property ADR-025
   wants is preserved; what changes is that a human asks for it.

3. **Every leftover is named, through `failures`.** Safe is not sufficient: a build that quietly
   leaves a withdrawn Expression in the tree has published it. Leftovers are reported on the channel
   `_report` already prints to stderr and writes into the run manifest, with the remedy in the
   message. An additive build is therefore auditable, not merely harmless.

4. **`checksums.sha256` describes what this build publishes**, not what happens to be in the
   directory. A leftover stays detectable as a file present in the tree and absent from the digest
   list, which is what lets a consumer — or a reviewer of the Pages repository diff — see it.

5. **Empty-directory cleanup only runs under `prune`.** Removing a directory whose files were
   deliberately left in place would be the same deletion by another route.

## Consequences

Verified against the incident itself, on a replica of the real `dist/`: a store holding no semantic
artifacts, built into a tree holding 92 JSON-LD and 92 N-Quads. Result: `written: 1195`,
`removed: 0`, `stale: 184`, all 184 files still present, 1,192 markdown Manifestations added beside
them, and every leftover named. Under the previous behaviour the same command deleted all 184.

**The cost, stated plainly.** A tree can now accumulate files no build publishes, and the operator
carries the judgement about when to prune. That is the intended trade: an accidental deletion of a
published tree can be unrecoverable, while a leftover file is visible in the manifest, absent from
the checksums, and removable at any time by a command that says what it is doing.

`--prune` is still capable of destroying a tree that a broken store cannot rebuild. It is a sharp
tool by design; the change is that a build is no longer one.
