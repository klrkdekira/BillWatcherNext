"""A second, independently versioned reading of stored PDFs via a hosted MinerU
vision-language model (HANDOFF 27.7, ADR-020).

`billwatcher.scraper.parse_document` continues to produce flat page text for lexical search and
must not change. This package is additive: it renders stored PDF bytes to page images, sends
each page to a MinerU-serving endpoint, and assembles the returned content blocks into markdown,
written only as a local file artifact under the audit tree (HANDOFF 27.2) — never into
`document_extractions`, which today assumes exactly one writer (TODO 2.4).
"""
