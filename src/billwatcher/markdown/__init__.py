"""Stage 2: read every stored PDF into markdown locally, with no model in the loop.

`layout` reads a PDF into classified, geometry-bearing lines — which is what makes it safe, because
a marginal note is typeset on the same baseline as the provision it annotates and a naive reader
splices the annotation into the legal text. `reading` assembles those roles into markdown, and
`imports` is the same recording path for a reading produced anywhere else, so an externally
produced markdown is stored and versioned exactly like a local one rather than blended into it.
"""
