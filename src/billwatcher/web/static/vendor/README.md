# Vendored assets

Third-party code is committed here rather than loaded from a CDN. The site must make no
third-party requests (HANDOFF 14) and the Content-Security-Policy is `default-src 'self'`,
so an external script would be both a policy violation and a blocked request.

| File | Version | Source | SHA-256 |
| --- | --- | --- | --- |
| `datastar-1.0.2.js` | v1.0.2 | https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.2/bundles/datastar.js | `2837d87acf6ee0ba8e4e63765926c25a98d63883b02f88be194a86b81d3fd24a` |

Retrieved 2026-08-18. Verify with:

```bash
sha256sum src/billwatcher/web/static/vendor/datastar-1.0.2.js
```

Upgrading is a deliberate step: fetch the new bundle, record its version and digest here, and
re-run `make check`. The filename carries the version so a stale copy cannot be served from a
cache after an upgrade.
