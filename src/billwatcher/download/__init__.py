"""Stage 1: fetch Parliament's listings, bills and document PDFs into the local corpus.

The one stage that makes network requests, and the only one that can fail for reasons outside this
repository. Every request goes through `policy.CrawlPolicy` (rate, budget, user agent, trust
store) and every response is stored verbatim beside a sidecar recording where it came from, so
each later stage reads files rather than the site.

Resumable by construction: a document already in the corpus is not re-fetched, so an interrupted
run continues where it stopped rather than starting over.
"""
