# ADR-012: Datastar for progressive enhancement, and the CSP cost of it

Status: accepted
Date: 2026-08-18

## Context

HANDOFF 6 permits "small progressive-enhancement JavaScript only where it materially improves
usability". HANDOFF 1 principle 5 and HANDOFF 14 require the site to remain useful with
JavaScript disabled, and HANDOFF 14 forbids third-party fonts, trackers, and analytics.
HANDOFF 17 requires a tested Content Security Policy.

Two interactions on this site cannot be expressed in HTML alone: searching without a full page
reload, and watching the crawl status change while a run is in progress. Everything else that
looked like a candidate — expanding a document's version history, for instance — is better served
by plain HTML, and no script was added for it.

## Decision

Use Datastar v1.0.2, **vendored** into `web/static/vendor/` with its version and SHA-256 recorded
in a README beside it. It is never loaded from a CDN: the site makes no third-party requests, and
`default-src 'self'` would block one anyway.

It is used for exactly two things:

1. `/bills` search-as-you-type, debounced, patching only the results region.
2. `/status` subscribing to a bounded server-sent event stream that re-renders the panel.

Both are strictly additive. The search form is a plain `GET` that works when submitted normally,
and `/status` renders a complete, correct panel server-side before any script runs. Each fragment
endpoint renders the *same* partial the full page includes, so the two cannot drift.

## The cost, stated plainly

Datastar compiles `data-*` expressions with the `Function` constructor, so
`script-src 'self' 'unsafe-eval'` is required. That is a real reduction in defence depth: if an
injection existed, `unsafe-eval` removes one barrier against exploiting it.

It was accepted because the exposure is bounded and the alternative was worse:

- Every template is Jinja-autoescaped. The single place we emit unescaped markup is the search
  passage, which is escaped first and then has only `<mark>` reinserted, and that is tested.
- `unsafe-eval` does not itself create an injection; it weakens a mitigation for one.
- Everything else in the policy stays closed, and `unsafe-inline` is **not** granted, so an
  injected `<script>` tag or inline handler is still refused.

A CSP-safe Datastar build using an AST interpreter instead of `Function` exists only in a
third-party fork, not in the official project, so adopting it would mean depending on a fork for
a security property. That was rejected. If upstream ships such a bundle, drop `'unsafe-eval'` and
supersede this ADR.

## Consequences

The no-JavaScript guarantee is now a tested property rather than an assumption: the suite asserts
that the pages render their content and that the forms remain plain `GET` submissions, and that
the fragment endpoints are additive rather than load-bearing.

Upgrading Datastar is a deliberate act — fetch the bundle, record the new version and digest,
re-run `make check` — because the filename carries the version and nothing resolves "latest".
