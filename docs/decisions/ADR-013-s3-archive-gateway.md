# ADR-013: VersityGW as the archive's S3 gateway, and serving archived documents

Status: accepted (storage) / proposed (public serving)
Date: 2026-08-18

## Context

The blob store is the archive: it is what makes versioning, replay, and post-hoc re-extraction
possible (HANDOFF 6), and it must be backed up independently of the database (HANDOFF 16.5).
Until now it was a local directory only, reachable by nothing but the application, which made
off-host backup and standard object tooling awkward.

Separately, HANDOFF 9.5 anticipates serving `/documents/{id}/versions/{n}` from the blob store
"if the review permits republication" — but assumption A14 is open, ADR-004 restricts the public
service to official links plus metadata and excerpts, and HANDOFF 2 lists publicly serving
mirrored bytes as a non-goal until that review concludes.

## Decision

**Storage.** `BlobStore` is now a protocol with two implementations: `FilesystemBlobStore` (the
default, unchanged behaviour) and `S3BlobStore` for any S3-compatible service. The deployment
runs VersityGW v1.7.0 with its POSIX backend pointed at the same archive volume, so:

- the bytes stay on an ordinary filesystem in the same content-addressed layout, and the gateway
  can be added or removed without migrating anything;
- standard S3 tooling and off-host backup have a supported interface;
- the application talks to one contract either way, so the scraper, the replay jobs, and the web
  layer do not know which backend is in use.

The gateway is internal to the Compose network and is never published to the host or the
internet. `boto3` is an optional `s3` dependency group: a filesystem deployment installs nothing
extra.

**Serving.** `GET /documents/{document_id}/versions/{version_no}` streams an archived version,
behind `SERVE_ARCHIVED_DOCUMENTS`, **off by default**. When off it returns 404 and the bill page
offers no download; the official link is always present either way and never depends on this
route. Only `accepted` versions are ever served — a quarantined version is kept for the record
and withheld.

The blob is located by a digest read from the database, never from anything in the request path
(HANDOFF 17). Responses carry the content hash as an `ETag`, an immutable `Cache-Control`, a
`Link: rel=canonical` to Parliament's URL, and `X-Robots-Tag: noindex`, because our copy is a
preservation artifact and not the authoritative record.

**Turning serving on is a rights decision, not a configuration change.** It requires the A14
review to conclude, ADR-004 to be superseded, and the outcome recorded in the manual gate log.

## Consequences

Storing bytes privately was always required; this only changes how they are reached. The public
serving path is complete and tested but inert, which is what HANDOFF 9.5 describes: the model was
built so that permission, if granted, needs no schema change.

Two defects surfaced while proving this against the live site and are fixed here:

- The document worker passed a literal string as `run_id`, violating the foreign key to
  `scrape_runs`. It had only ever run against SQLite, which does not enforce foreign keys.
- Validation quarantined every real bill PDF because Parliament serves them as
  `application/octet-stream`. HANDOFF 9.3 quarantines a response that is not the document — its
  example is an HTML session-expiry page — so the magic bytes now decide, and a lazy
  Content-Type no longer discards a genuine PDF.
