# ADR-015: TLS is terminated by an nginx deployed outside this repository

Status: accepted
Date: 2026-08-18

Supersedes the Caddy half of ADR-006 and the `caddy` service in HANDOFF §16.2. Everything else in
ADR-006 stands.

## Context

HANDOFF §7 and §16.2 specify Caddy as the public entry point: the only service publishing 80 and
443, holding the certificate volumes, and adding the response security headers. The repository
shipped a `Caddyfile` and a `caddy` service to match.

The service owner deploys nginx separately, as shared infrastructure that already terminates TLS for
other sites on the host. Two reverse proxies in front of one app is not a configuration — it is a
second place for the same rules to drift, and the one in this repository would be the copy nobody
looks at.

## Decision

**Caddy is removed.** The `Caddyfile` is deleted and the `caddy` service, its two certificate
volumes, and the `public` network are gone from `compose.yaml`. Nothing in this repository terminates
TLS, obtains certificates, or redirects HTTP to HTTPS.

**The app publishes an origin for the external proxy** on `127.0.0.1:8000`. Loopback is deliberate:
binding an unencrypted origin to `0.0.0.0` is how a reverse-proxy deployment ends up serving
plaintext to the network. A proxy on a different host needs that bind changed and the port firewalled
as a deliberate act.

**The response security headers stay in the application** — `web/security_headers.py`, asserted by
the suite. That was already true before this ADR and matters more now: the proxy is outside the
repository, so the application is the only place that can guarantee them. The nginx configuration
must **not** set its own copies; a browser enforces the intersection of two
Content-Security-Policies, so a second, stale copy breaks the site rather than protecting it.

**HSTS moves into the application as a setting, defaulted off.** It is the one header that belongs
with the transport, and the application cannot see the transport from behind a proxy. It is also the
one header that does real damage when it is wrong: a year-long `max-age` published before a
certificate works takes the site down for every browser that saw it. HANDOFF §17 says to add it
"only after HTTPS/domain correctness is established", so `HSTS_MAX_AGE_SECONDS` is `0` until an
operator has established that. `preload` is never emitted — that submission has a slow exit and is
not a default's decision to make. Setting it on the nginx side instead is equally fine; setting it in
both places is not.

**The container network split changes with it.** `backend` stays `internal: true`, so the database
and the blob gateway remain unreachable from the host and the internet. A new non-internal `egress`
network carries the app and the worker.

## Consequences

The deployment runbook in HANDOFF §16.5 no longer matches, and `docs/operations.md` carries the
replacement, including the nginx configuration this app actually needs — most importantly
`proxy_buffering off` for the `/fragments/status` event stream, which Caddy handled with
`flush_interval -1`. Without it the status page appears to hang rather than stream.

Two things this ADR gives up, and they should be recorded as costs rather than glossed over:

1. **Certificate automation is now someone else's problem.** Caddy obtained and renewed
   certificates as a property of the stack. An expiring certificate is now an operational
   responsibility outside anything this repository can test or monitor.
2. **The TLS path can no longer be rehearsed from this repository.** The 2026-08-18 rehearsal in
   `docs/operations.md` brought up the real stack and verified the redirect, the chain, HSTS, and
   every header surviving a proxy. That rehearsal is no longer reproducible here, because the proxy
   it exercised is gone. What survives is the application half — the headers are asserted by tests
   that need no proxy at all — and the nginx half becomes something to verify once, by hand, against
   the real deployment. `TODO.md` tracks it.

A fixed defect worth recording, because removing Caddy is what surfaced it: the `worker` sat on the
`internal: true` network alone, so the containerised crawler had **no outbound access at all**. It
would have started, reported healthy, and failed every fetch. Live crawling had only ever been run
from the host, so nothing caught it. The worker is now on `egress`, and a test asserts it stays
there.
