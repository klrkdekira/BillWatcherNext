# ADR-043: Two node types join the structural vocabulary — `list`, for a lettered list that restarts under one parent, and `article`

Status: accepted
Date: 2026-09-02

## Context

Two printed shapes had no node the tree could hold them in.

An interpretation clause gives each defined term its own `(a)`, `(b)` list, so one subsection
carries several lettered lists. With one `para_a` per parent the second list duplicates every eId
of the first, and Gate P1 rightly rejects the tree. The parser audit of 2026-09-02 met this in 514
rejected readings — the largest single remaining cause — and read the restart as the parent's
prose: every word kept, no identifier invented, and a sub-structure given up that the tree had no
element for. That was recorded as a concession, not a model.

A treaty set out in a Schedule is divided into Articles, each with its own numbered paragraphs.
With no `article` type the articles' paragraphs all fell under one chapter and duplicated each
other (19 readings, all rejected).

Akoma Ntoso has an element for each: `article` is a hierarchy element, and a list of items is
`blockList`. `blockList` is not a hierarchy element, and its `item` children are not the
`paragraph` elements the gate checks and the semantic graph publishes.

## Decision

1. **`list`** is a node type: a numbered container for one of several lettered lists under one
   parent. When a lettered list restarts under a parent that already holds one, the items already
   there become `list_1`, the new item opens `list_2`, and each list numbers its own items —
   `cl_2__list_2__para_c`. A parent holding a single list is unchanged, so no existing identifier
   moves. It renders as `<hcontainer name="list">`, which keeps its items hierarchy elements the
   gate and the graph already understand; the semantic reader reads the `name` back. Its own
   numbering restarts per parent, like the lists it holds.
2. **A restarting subsection list is not a `list`.** A clause has one `(1)`; a second one is an
   inserted section of another Act whose marks were lost, and the clause's subsections are read as
   its prose as before. ADR-042's depth reading is what recognises that case where geometry is
   available.
3. **`article`** is a node type, recognised from `ARTICLE N` / `PERKARA N`, rendered as
   `<article>`, with eId prefix `art`. Containers nest by rank — Part, Chapter, Article — inside a
   Schedule as well as in the body, and a Schedule stays the root of its own stack.
4. **Gate P1 scopes document-wide runs to the Schedule they sit in.** A Schedule's Parts number
   from I and a treaty's Articles from 1 whatever the body did, and two Schedules each begin again.
   The bill's own clause run is still anchored at the document's start.

## Consequences

- `NODE_TYPES`, `EID_PREFIXES`, `AKN_ELEMENTS` and `NODE_LABELS` grow together, and the published
  `definitions/structural-vocabulary.json` with them (`STATIC_EXPORT_VERSION` 1.1.0). The handoff
  contract accepts both types from a writer. `AKN_VERSION` 1.5.0 and `STRUCTURE_GATE_VERSION` 1.3.0
  regenerate the corpus once.
- What is still not modelled: an Act consolidated whole inside a Schedule, whose sections run
  continuously across the Schedule's Parts while the gate checks a Schedule's paragraphs per Part.
  It is a handful of readings and needs a decision about what such a Schedule *is*, not a parser
  rule.
