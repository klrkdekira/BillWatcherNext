# Vendored Akoma Ntoso 3.0 schema

The OASIS LegalDocML (Akoma Ntoso) 3.0 XML Schema, vendored so `pipeline.akn_schema.validate_akn`
validates against the published standard with no network access — in a validation run, in a test
run, and inside a container that has no egress.

Both files are byte-for-byte as published. They are not edited, including the relative
`schemaLocation="./xml.xsd"` import, because "identical to upstream" is the property the digests
below certify; rewriting a path would break it.

| File | Version | Source | SHA-256 |
| --- | --- | --- | --- |
| `akomantoso30.xsd` | AKN-Core v1.0 OASIS Standard, Part 2 (2018-08-29) | <https://docs.oasis-open.org/legaldocml/akn-core/v1.0/os/part2-specs/schemas/akomantoso30.xsd> | `6f61fe84cbb6f8cb0e8418cd67b74a63da9990e6573b5a3491f623184f45c4fd` |
| `xml.xsd` | W3C XML namespace schema, as redistributed by OASIS with the above | <https://docs.oasis-open.org/legaldocml/akn-core/v1.0/os/part2-specs/schemas/xml.xsd> | `61960fb3131e38022caad5360e2f33a3382578ab3c80cd58bd74320ede61b20c` |

Retrieved 2026-08-22.

`akomantoso30.xsd` has no `xs:include` and exactly one `xs:import`, for the XML namespace, resolved
by the relative path to `xml.xsd` beside it. `xml.xsd` imports nothing. The transitive closure is
therefore these two files and nothing else, which is why validation never reaches the network — but
it also means the two must stay in the same directory, and the schema must be loaded by filesystem
path rather than from a string, or the import falls back to the absolute W3C URL.

## Verifying

```sh
sha256sum src/billwatcher/pipeline/schemas/*.xsd
```

## Refreshing

Manual, and deliberately so: a schema change can invalidate the whole published corpus, so it is a
decision, not an update.

```sh
BASE=https://docs.oasis-open.org/legaldocml/akn-core/v1.0/os/part2-specs/schemas
curl -sfSL -o src/billwatcher/pipeline/schemas/akomantoso30.xsd "$BASE/akomantoso30.xsd"
curl -sfSL -o src/billwatcher/pipeline/schemas/xml.xsd "$BASE/xml.xsd"
```

Then update the digests in this table, run `make test`, and record the refresh in
`docs/status.md`. If any already-published document stops validating, that is a corpus migration to
plan rather than a test to relax.
