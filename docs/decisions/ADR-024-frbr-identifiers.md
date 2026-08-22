# ADR-024: Permanent FRBR identifiers, built from published facts; the URL-hash scheme is withdrawn

Status: accepted
Date: 2026-08-22

## Context

ADR-021 gave a document its identity by hashing its URL (`doc-<sha256(url)[:8]>`), because a
file-first pipeline has no database to assign an id. As a *store key* that is fine and remains in
use. Step 4 (ADR-022) then reused it as a *public identifier*, minting FRBR URIs of the shape
`/akn/my/{type}/{year}/doc-<sha256(url)[:8]>`, and that is a different job with different rules.
Three defects, in increasing order of seriousness:

- **It is opaque.** Nothing in `doc-3f9a1c2b` names a bill. A citation cannot be read by a person or
  resolved by a machine that holds only `D.R.15/2026`, which is the only identifier Parliament
  actually publishes.
- **It is unstable across a URL change.** The identifier is a hash of a location, so the same
  document republished at a second URL is a second Work. This is not hypothetical: 62 sets of
  byte-identical documents are already published at two or more URLs (ADR-003, §25.6 item 13), and
  content-hash identity exists precisely because URL identity double-counts this archive.
- **It splits one bill's two language readings into two unrelated Works**, which is the exact
  relationship the FRBR model exists to express. The same renderer also hard-coded `msa` on every
  document, so an English reading was published as Malay, under a Work no Malay reading shared.

There was one further defect of the same kind: a missing year or number fell back to a placeholder,
so the pipeline would happily publish a citable identifier for a document nobody could identify.

The IRI scheme is confirmed by the project owner. What is recorded here is the reasoning, the
rejected alternative, and the costs — not a proposal.

## Decision

1. **One module owns every published IRI: `pipeline.frbr`.** A renderer, a graph builder and a
   router all need the same strings, and three copies of a scheme drift. `WorkIdentity` carries the
   four facts that name a Work — document type, originating chamber, year, number — and every IRI is
   a method on it.

2. **The scheme is the AKN naming convention with the chamber in the subtype slot:**

   | Level | Example |
   | --- | --- |
   | Work | `/akn/my/bill/dr/2026/15` |
   | Expression | `/akn/my/bill/dr/2026/15/msa@` |
   | Manifestation | `/akn/my/bill/dr/2026/15/msa@.xml` (also `.jsonld`, `.nq`, `.html`) |
   | Provision | `/akn/my/bill/dr/2026/15/msa@/~cl_5__subsec_1` |

   Every component is a fact the upstream document published: the country is fixed, the type comes
   from the document's own Arrangement heading (clauses → `bill`, sections → `act`, HANDOFF 26.2),
   and the chamber is the **originating** chamber per ADR-002 — a `D.R.` bill keeps `dr` on the
   Dewan Negara's listing, which is the same reading that made ADR-002's bill/chamber split right.

3. **Nothing mutable appears in an IRI.** No URL, no byte hash, no retrieval time. All three change
   when we re-fetch, and a permanent identifier must not. The Expression's version date is
   deliberately empty — `msa@`, which in the AKN convention reads as "the only version we have", the
   honest statement for a bill we hold no expression date for. `@YYYY-MM-DD` is reserved for a real
   document date. Putting `retrieved_at` there would mint a new permanent identifier every time the
   same bytes were fetched again.

4. **Malay and English are two Expressions of one Work**, and the language comes from a declared
   fact rather than a guess. `resolve_language` prefers the language recorded in the markdown's
   provenance — the operator knows which PDF they extracted — and cross-checks it against the
   document's own Arrangement heading (`Susunan Fasal` / `Arrangement of Clauses`), the same
   evidence ADR-017 chose for Gate L1 and better than either a listing column or a filename.
   Disagreement is not silently resolved: the declared value wins and the disagreement is written
   into the gate verdict, because a silent overrule is how a wrong Expression IRI becomes permanent.
   **A document with no language from either source fails.** It does not default to Malay, which is
   what the old renderer did to every document it converted.

5. **Two spellings of a language, mapped in exactly one place.** ISO 639-3 (`msa`/`eng`) in the AKN
   name, because the AKN convention requires it; BCP 47 (`ms`/`en`) on RDF literals and HTML `lang`
   attributes, because RDF requires well-formed BCP 47 and HANDOFF 15 mandates it for structured
   output. `frbr.AKN_LANGUAGES` is the only mapping between them; nothing else spells either code.

6. **Refusal is a first-class outcome.** `FrbrIdentityError` is raised — never defaulted around —
   when a bill record lacks an originating chamber, a year, a number, or a language. One document
   failing loudly, by name, in the step's failure list is much cheaper than a citable identifier
   asserting a fact nobody established.

7. **A request segment is validated, never trusted.** `parse_work_path` and
   `parse_expression_segment` return `None` for anything malformed, so a caller turns every bad
   segment into a 404; and the store key is *recomputed* from the validated identity (`slug_for`),
   never assembled from the request string. That keeps HANDOFF 17's rule — storage paths are built
   only from our own identifiers — true on the serving side as well as the crawling side.

   Every segment is matched against an explicit ASCII pattern anchored with `\A`/`\Z`, and that
   precision is not pedantry. The number segment was first validated with `str.isdigit()`, which is
   true for every Unicode digit character: `٢` and `２` therefore resolved the *same* Work at HTTP
   200, giving a supposedly permanent identifier unboundedly many non-canonical spellings, while `²`
   passed `isdigit()` and then raised out of `int()` as an unauthenticated HTTP 500 from a function
   whose docstring promises it returns `None` rather than raising. There was also no length bound, so
   a long digit run hit CPython's integer-parse limit the same way. A permanent identifier gets
   exactly one spelling, and a malformed request gets a 404. Related: `$` in Python also matches
   before a trailing newline, which is why the guard on the URL that reaches the `Link` header uses
   `\Z` — a `source_url` ending in a newline was passing the check whose entire job is to stop a
   header being forged.

### Alternatives rejected

**The bill slug as a single path segment** (`/akn/my/bill/dr-15-2026/msa@`). Seriously considered,
and the reason it is worth recording: the slug already exists, is already stable, is already the
store key, and is already this site's own public identity for a bill (`/bills/dr-15-2026`). Reusing
it would have made the two identifier systems trivially interchangeable. Rejected on three counts.
It is not **truncatable**: ADR-018 adopted the ELI requirement that each level of a path resolve to
a listing, which means chamber, year and number have to be their own segments — `/akn/my/bill/dr/`
listing a chamber and `/akn/my/bill/dr/2026/` listing a year are exactly what the scheme is for, and
one fused segment cannot produce them. It hides the components AKN tooling expects in fixed slots,
so a consumer would have to learn our slug grammar to read a year out of a path. And it puts a
project-specific string at the centre of a standard identifier, which is the same mistake the URL
hash made in a different spelling. The slug survives where it belongs — as the store key — and
`slug_for` derives it from the identity, so the two cannot drift apart.

**Keeping a date in the Expression segment** (`msa@2026-08-21`, the retrieval date). Rejected for
the reason in decision 3: it is a fact about us, and it makes every re-fetch a new Work expression.

## Consequences

- **Every already-converted document's IRI changes.** That is a corpus regeneration, and it happens
  only because regeneration is now gated on input hashes rather than on a file existing (ADR-026).
  Under the old existence check this ADR would have changed the code and left the corpus alone,
  which is the failure mode ADR-026 exists to remove.
- **There is no version chain.** Two documents that share a Work, a language and a manifestation
  type resolve to one IRI, and this scheme carries no component to distinguish them. A bill revised
  and republished at a new URL is therefore not representable today. A11 records that no document in
  the whole corpus has ever had a second version, so nothing is being lost yet; when one appears, an
  Expression date or a version component is the change, and it is a change to this ADR rather than a
  detail to improvise. It is at least *detected*: `pipeline verify` reports two documents claiming
  one Expression IRI. An undetected collision would be the worst failure this scheme allows — a
  citable identifier silently resolving to whichever document sorted first, with the other reading
  unreachable and nothing saying so — and detection costs one dictionary, so "not representable"
  should never have meant "not noticed".
- **The `dn` branch is untested by real data.** ADR-002 records that no `D.N.` identifier exists
  anywhere in 35 years of archive (A5, partially verified), so half of the chamber mapping in this
  scheme is a rule the corpus has never exercised. The first `D.N.` bill published will be its first
  test, exactly as it will be ADR-002's.
- **A provision IRI is only as unique as its eId.** eIds are computed deterministically by
  `assign_eids` (ADR-022), and a duplicate eId would give two provisions one IRI — which is why
  `duplicate_eid` is a blocking finding in Gate P1 (ADR-025) rather than a warning.
- Nothing here depends on the store backend. A future database or object-store `PipelineStore`
  publishes the same IRIs, because they are derived from the bill record's own fields and not from
  where those fields are kept.
