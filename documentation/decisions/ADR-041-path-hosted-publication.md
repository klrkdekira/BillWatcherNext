# ADR-041: The tree is published under a path, and SITE_PREFIX carries it

Status: accepted
Date: 2026-08-29

## Context

Directed by the commissioner on 2026-08-29: **"I'm changing my approach, the docs would be
published under another repository called https://cheeleong.dev/data-parlimen/"** — and, on the
follow-up, that the publishing itself (copying the tree into that repository and pushing) is done
by hand.

Until now the published tree assumed a domain apex: `SITE_PREFIX` was validated down to a bare
hostname, written verbatim into `CNAME`, and used as the base of every published FRBR IRI; the
frontend was built with Vite's default base of `/`, and every fetch and file link in it was
root-relative. Served under `https://cheeleong.dev/data-parlimen/`, every one of those assumptions
breaks at once: the `CNAME` would try to claim `cheeleong.dev` for the data repository and detach
whatever serves the root; the IRIs would cite pages under a path the dataset does not mention; and
the app's assets and dataset fetches would resolve against the root and 404.

## Decision

**`SITE_PREFIX` accepts `host` or `host/path`, and stays the single authority.** The host part is
validated as before; a path part marks a tree served by a GitHub Pages *project* repository. Every
consequence is derived from this one setting rather than configured again elsewhere:

- `site_base_url` (`https://cheeleong.dev/data-parlimen`) is the base of every published FRBR IRI.
  It already sat in the semantic files' provenance inputs, so changing the prefix re-derives every
  JSON-LD and N-Quads file rather than leaving citations pointing at the old home.
- `cname_host` is the hostname `CNAME` should claim — and `None` when the prefix carries a path,
  because Pages reads `CNAME` only on the repository serving the domain's root. `publish` already
  treated a `None` prefix as "claim no domain"; it now receives exactly that for a path-hosted
  tree.
- `site_base_path` (`/data-parlimen/`) is the frontend's base. `vite.config.ts` reads `SITE_PREFIX`
  (and `SITE_ROOT`) from the pipeline's own `.env`, the router takes the base as its `basename` so
  `/akn/...` identifiers keep resolving, and `publishedUrl()` carries it into every dataset fetch
  and file link. The dev and preview servers strip the same base, so development serves the tree
  exactly as production does.

**Publishing is a manual copy.** The build keeps writing a complete, self-contained tree into
`SITE_ROOT` (`docs/` by default); moving it into the `data-parlimen` repository and pushing is a
deliberate human act, consistent with ADR-029's stance that publication cannot be withdrawn and so
must never be a side effect.

## Consequences

- A tree built for one home cites that home in every IRI. Moving the site again means changing
  `SITE_PREFIX` and rebuilding — `make graph publish site` — not copying the old tree.
- `docs/CNAME` no longer exists for this configuration; a stale one from the apex era must not be
  copied into the new repository. An apex-hosted deployment still gets one written from the same
  setting.
- The frontend cannot be built without the pipeline's `.env`, which is already true of the dataset
  it ships beside — the two halves of the tree now agree on where they live by construction.
