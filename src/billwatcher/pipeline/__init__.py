"""A file-first pipeline: listings -> bills -> documents, no database, no object store.

Every step depends only on `billwatcher.pipeline.store.PipelineStore`, an interface, never on a
concrete backend. `FileStore` (local directories and JSON) is the only implementation built so
far. A database or object-store backend is a later, additive extension: implement the same
protocol and every step in this package works against it unchanged, with no step logic to touch.

This package does not import `billwatcher.models`, `billwatcher.db`, or any of the
Postgres-backed scraper/jobs modules (`scraper.service`, `scraper.ingest`, `scraper.versioning`,
`scraper.queue`, `scraper.worker`, `scraper.document_worker`, `operations`). Those remain in
place, dormant, for later reintegration. It does reuse the parts of `billwatcher.scraper` that
were already pure — `fetch`, `policy`, `robots`, `normalize`, `parse_listing`, `parse_archive` —
none of which ever touched a database.

PDF parsing/extraction is out of scope here by direction: the operator has a vLLM
OpenAI-compatible endpoint for that, separately from this pipeline.
"""
