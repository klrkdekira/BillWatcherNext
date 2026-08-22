"""Central version identifiers for every derived artifact."""

__version__ = "0.1.0"
PARSER_VERSION = "1.0.0"
NORMALIZER_VERSION = "1.0.0"
EXTRACTOR_VERSION = "1.0.0"
# The geometric reading of a legislative PDF, versioned apart from the flat-text extractor
# so either can be replayed without invalidating the other (HANDOFF 26.1, ADR-016).
LAYOUT_EXTRACTOR_VERSION = "1.0.0"
# The Arrangement-of-Sections and body tree parser that Gate L1 compares (HANDOFF 26.3).
STRUCTURE_VERSION = "1.0.0"
CHUNKER_VERSION = "1.0.0"
# The MinerU vision-language markdown reading (§27.7): a second, independently versioned
# reading of the same stored bytes, recorded as a local file artifact rather than a
# `document_extractions` row (ADR-020).
MINERU_EXTRACTOR_VERSION = "1.0.0"
# The file-first pipeline's markdown -> Akoma Ntoso conversion (§28.5): eId assignment, FRBR
# identification, and AKN serialisation. Versioned apart from whichever extractor read the
# structure, so a serialisation fix does not invalidate every structural reading — and apart from
# the gate below, so tightening a threshold does not imply the XML changed.
AKN_VERSION = "1.0.0"
# Gate P1, the AKN fidelity gate (§28.5): the deterministic check that an LLM-read provision tree
# accounts for the markdown it was read from. Its own version because a threshold change re-judges
# every document without re-rendering any of them.
AKN_FIDELITY_GATE_VERSION = "1.0.0"
# The Akoma Ntoso -> ELI JSON-LD / RDF N-Quads graph construction (§28.6, ADR-023).
SEMANTIC_VERSION = "1.0.0"
