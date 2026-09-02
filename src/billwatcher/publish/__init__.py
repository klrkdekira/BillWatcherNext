"""The publication boundary: the corpus in, the static site tree out.

`dataset` selects only complete, gate-passing Expressions, renders them on their permanent FRBR
manifestation paths, and writes them into the site root the React frontend is built into. It
manages only the entries it owns (`akn/`, `definitions/`, `index.json`, `checksums.sha256`,
`CNAME`), so it can be pointed straight at a tree it shares with the frontend build without either
deleting the other's files.

`redact` is the control that makes a metadata-only publication real rather than nominal, and it
stays in place whichever publication mode is configured.
"""
