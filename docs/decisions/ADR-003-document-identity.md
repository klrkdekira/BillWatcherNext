# ADR-003: Document identity and versioning

Status: accepted
Date: 2026-08-16

A canonical URL identifies a logical document. Different accepted bytes at that URL create a new
monotonic version. A different URL creates a distinct document even when its bytes deduplicate to
the same blob. URL normalization removes only documented tracking/session parameters. Rollbacks
create a new version pointing at the old blob and raise an anomaly. Invalid PDF responses are
archived as quarantined versions and never promoted.
