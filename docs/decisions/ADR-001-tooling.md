# ADR-001: Mypy and semantic HTML parsing

Status: accepted
Date: 2026-08-16

Use mypy in strict mode as the required type checker. Use a small semantic parser adapter built on
the standard library initially; Selectolax may be introduced after real fixtures demonstrate a
need. Parsers accept stored bytes/text and metadata and never fetch.
