# Data model

Two trees, and the identifiers that connect them: `corpus/`, which is the pipeline's own record,
and `docs/`, which is the published projection of it.

The Postgres schema notes for the previous stack — search units, chunks, embeddings, anomalies,
event fingerprints, the audit tree — are preserved at `history/data-model-postgres-schema.md`.

## The corpus

```
corpus/
├── listings/<chamber>-<kind>-<year>-<lang>/     one stored HTTP response, verbatim, plus a sidecar
├── bills/<slug>/bill.json                       one record per bill, parsed from those listings
├── documents/<slug>/<doc-key>/v<NNN>/           one directory per document version
└── manifests/<step>/<run-id>.json               what each step run read, wrote, and failed on
```

A bill slug is `dr-11-2024` — chamber, number, year. A `doc-key` is derived from the document's own
URL rather than from its upstream filename, so two documents cannot collide by being published
under the same name. Versions are `v001` upward: a document version is immutable, and a
re-download that differs becomes `v002` rather than overwriting `v001`.

Inside a document version:

| File | Written by | What it is |
| --- | --- | --- |
| `document.pdf` | download | The published bytes, verbatim. |
| `metadata.json` | download | Where it came from, when, what the server said. |
| `document.md` | markdown | The local reading. |
| `document.markdown.provenance.json` | markdown | What produced the reading, from what, at which code version. |
| `document.akn.xml` | graph | Akoma Ntoso, **only if it passed the gate**. |
| `document.akn.rejected.xml` | graph | The render that did not pass, kept so it can be looked at. |
| `document.akn.gate.json` | graph | The gate's verdict, written either way. |
| `document.jsonld`, `document.nq` | graph | The semantic graph, from one `rdflib.Dataset`. |

The presence of `document.akn.xml` *is* the promotion. Nothing else records whether a document is
publishable, so a rejected reading cannot be published by a downstream step that forgot to check.

## Provenance and re-derivation

Every derived artifact records the hash of what it was derived *from* and the versions of the code
that derived it. A step re-runs a document when either has moved and skips it otherwise, so a
re-run over an unchanged corpus writes nothing at all.

This is also what makes a version bump meaningful: raising `AKN_VERSION` re-derives every Akoma
Ntoso render and leaves the markdown alone, while raising `AKN_FIDELITY_GATE_VERSION` re-judges
every document without re-rendering any of them. They are separate constants for exactly that
reason — see `src/billwatcher/version.py`.

## FRBR identity

Three levels, and the identifier grows at each:

| Level | Example | What varies |
| --- | --- | --- |
| Work | `/akn/my/bill/dr/2024/11` | The bill itself, independent of language or format. |
| Expression | `/akn/my/bill/dr/2024/11/msa@` | The language it was read in. |
| Manifestation | `/akn/my/bill/dr/2024/11/msa@.jsonld` | The serialisation. |

The language component is ISO 639-3 (`msa`, `eng`), mapped in exactly one place —
`AKN_LANGUAGES` in `src/billwatcher/frbr.py`. The trailing `@` is Akoma Ntoso's marker for an
expression at no particular point in time.

**The language is declared, never sniffed.** It becomes a permanent part of the Expression IRI, so
it is taken from the reading's provenance; detection disagreeing with it is recorded as a finding,
not treated as licence to mint a second identifier.

What declares it is the listing that named the document: Parliament publishes each bill in both
languages, and the Malay and English pages name *different files* (`DR 17 BM.pdf`, `DR 17 BI.pdf`),
so `bills/<slug>/bill.json` records which listing languages named each document and the reading step
reads it from there (ADR-040). `extract-markdown --language` is only the fallback for what that
leaves unsettled — a file both languages link, or a document stored before the field existed.

An identifier that cannot be minted is not approximated. A bill whose number or year cannot be
read is absent from the published dataset rather than published under a placeholder that asserts
something nobody established.

## The published tree

```
docs/
├── index.json              the catalogue: every work, its expressions, and their files
├── checksums.sha256        a digest for every file this build publishes
├── akn/my/bill/…           the manifestations, on their permanent paths
├── definitions/            the JSON-LD context, the AKN schemas, the structural vocabulary
├── CNAME                   the custom domain, from SITE_PREFIX
└── index.html, 404.html, assets/, .nojekyll     the frontend
```

`index.json` carries one entry per work, each with its expressions, each with the root-relative
paths of its published files and — where there is a reading — the measured quality of that reading,
including whether the pipeline flagged it `suspect`. A consumer can filter on that without
re-deriving anything, and one who ignores it gets the whole corpus rather than a silently trimmed
part of it.

`checksums.sha256` describes what *this build* publishes and deliberately does not checksum itself.
A leftover from an earlier build is therefore detectable as a file present in the tree and absent
from the digest list.

## What the graph asserts

The JSON-LD and the N-Quads are serialised from one `rdflib.Dataset`, so they cannot disagree.
Provisions relate by `eli:has_part` / `eli:is_part_of`, carry `eli:number` and, where the document
printed one, a `schema:name` heading tagged with its language. The expression node carries
`eli:is_realized_by` back to the work, `eli:language`, and `eli:jurisdiction`.

A provision's identifier is its path through the tree, and the tree has a place for every printed
shape the gate can check. Beyond the usual hierarchy — Part, Chapter, clause, subsection,
paragraph, subparagraph, Schedule — two node types exist for drafting that restarts its own
numbering (ADR-043, ADR-044). A `list` holds one of several runs under a single parent: each
defined term's own `(a)`, `(b)` in an interpretation clause, or a Schedule's items that begin
again at `1.` (`sched_1__list_2__para_3`). An `article` is `ARTICLE N` / `PERKARA N` of a treaty
set out in a Schedule. A lettered list introduced by an item's own closing dash is not a `list`
but nests beneath that item (`cl_10__para_d__para_a`). A Schedule or parent with a single run is
identified exactly as it was before either decision, so no identifier moved. Not modelled: a table
as a table (its numbered rows are read as a list), and an Act consolidated whole inside a Schedule.

The graph asserts structure and identity. It does not assert that a reading is a correct reading of
the printed page — that is Gate P1's separate and weaker judgement, and `index.json`'s `reading`
block is where the pipeline says how much it trusts its own work.
