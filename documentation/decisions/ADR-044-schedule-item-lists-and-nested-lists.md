# ADR-044: A Schedule's restarting items are lists, and a list introduced by an item's own dash nests beneath it

Status: accepted
Date: 2026-09-02

## Context

ADR-043 gave the tree a `list` node for one printed shape: a lettered list that restarts under
one parent, each defined term's own `(a)`, `(b)` in an interpretation clause. The second audit of
the structure parser (same day, `documentation/status.md`) met two more shapes the tree still had
no place for, and both are the same shape one level away.

A Schedule numbers its items once — except where it does not. A worked *Illustration* beneath
paragraph 5 numbers its steps 1, 2, 3; a table of rates numbers its rows from 1 again; a Schedule
that sets out forms numbers each form's paragraphs from 1. With one `para_1` per Schedule the
second run duplicates every eId of the first, and Gate P1 rightly rejects the reading (measured:
nine readings, every one a Schedule with a second `1.`).

A lettered item that introduces a list of its own — `(d) dalam subseksyen (3)—` followed by
`(a) dalam perenggan (a), ...`, `(b) dalam perenggan (b)—` — restarts the letters under the parent
that already holds `(a)` to `(d)`. ADR-043 read that as the next of several sibling lists, so the
`(e)` that follows landed in the second list after its `(b)` and was reported as a gap. The
drafting is unambiguous: the list is `(d)`'s, and `(e)` continues `(d)`.

## Decision

1. **A Schedule's numbered items are held as ADR-043 holds lettered ones.** A second `1.` under a
   Schedule that already holds a `1.` — or an item whose number the Schedule already carries —
   makes the items already there `list_1`, opens `list_2` for the new one, and each list numbers
   its own items (`sched_1__list_2__para_3`). A Schedule with one run of items is unchanged, so no
   existing identifier moves. Inside a Schedule's Part the Part is the parent, as it already was.
2. **A restarting lettered list nests beneath the item that introduces it** when that item's own
   opening line — and nothing after it — ends on the dash or colon that introduces a list
   (`cl_10__para_d__para_a`). A restart after further prose, a defined term's `"term" means—`
   appended to the item before, is still the next of several sibling lists, as ADR-043 decided.
   The two shapes are told apart by that one fact about the item's text, and nothing else.

## Consequences

- No vocabulary, renderer or schema change: `list` and `paragraph` already exist, and a
  `paragraph` beneath a `paragraph` is an ordinary hierarchy nesting. `AKN_VERSION` 1.6.0 and
  `STRUCTURE_GATE_VERSION` 1.4.0 regenerate the corpus once, together with the parser rules of the
  same audit.
- A table of rates whose rows are numbered is read as a list of paragraphs, which is what the
  gate can check and not what the table is. The words are all kept and each row's number is
  checked within its list; what is not modelled is that the row is a row. A table node is a
  decision for the vocabulary, the renderer and the published schema together, and is not made
  here — the same boundary ADR-043 drew for `blockList`.
- Still not modelled, as ADR-043 recorded: an Act consolidated whole inside a Schedule, whose
  sections run across the Schedule's Parts.
