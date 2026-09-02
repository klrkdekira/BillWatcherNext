"""Stage 3: markdown to a semantic knowledge graph, through Akoma Ntoso.

`akn` reads a provision structure out of the markdown and renders Akoma Ntoso XML on stable FRBR
identifiers; `fidelity` is the gate that judges the tree against the markdown it was read from,
and no document reaches the published dataset without passing it. `semantic` then serialises the
gate-passing XML into ELI JSON-LD and RDF N-Quads from a single graph, so the two serialisations
cannot disagree.

`handoff` is the model-free route into the structure step: it writes one self-contained work
packet per document and reads the answers back through the same conversion, gate and provenance
path as any other reading.
"""
