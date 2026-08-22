"""What each derived artifact was built from, and whether it still matches.

Every step in this pipeline used to decide "is there work to do?" by asking whether its output file
existed. That is wrong in a way that only shows up later: correcting the FRBR IRI scheme, fixing
the AKN serialiser, or improving the extraction prompt leaves every already-converted document
exactly as it was, because the file is still there. The corpus then disagrees with the code that
claims to have produced it, and nothing detects that.

A provenance record fixes it by making the *inputs* the gate. `inputs` names every source file with
its hash plus the code, model and prompt versions involved; `output` records what was written, for
`pipeline verify` to re-check. Comparing a freshly computed `inputs` against the stored one answers
"is this artifact still what this code would produce from this source?" — so a version bump
regenerates the corpus once and then settles.

Deliberately absent: timestamps and run ids. Both are volatile, and either one inside a
per-artifact sidecar would make every re-run rewrite it, destroying the "a repeat run writes
nothing" guarantee that is the whole point of the deterministic writer (ADR-019). They belong in the
per-run manifest, whose path is already unique per run.
"""

from typing import Any

from billwatcher.pipeline.store import PipelineStore, StoredDocumentRef, sha256_of
from billwatcher.storage.audit_tree import METADATA_SCHEMA_VERSION

RAW_FILES = {
    "markdown": "document.md",
    "akn": "document.akn.xml",
    "semantic": "document.jsonld",
}


def build_record(
    *, artifact: str, inputs: dict[str, Any], outputs: dict[str, bytes]
) -> dict[str, Any]:
    """One provenance record: the staleness key (`inputs`) and the integrity key (`output`)."""
    return {
        "metadata_schema_version": METADATA_SCHEMA_VERSION,
        "artifact": artifact,
        "raw_file": RAW_FILES[artifact],
        "inputs": dict(inputs),
        "output": {
            name: {"sha256": sha256_of(payload), "byte_size": len(payload)}
            for name, payload in sorted(outputs.items())
        },
    }


def needs_rebuild(
    store: PipelineStore,
    ref: StoredDocumentRef,
    *,
    artifact: str,
    inputs: dict[str, Any],
    present: bool,
) -> bool:
    """True when the artifact is absent, unprovenanced, or built from something else.

    A missing provenance record beside a present artifact means "built before provenance existed"
    and counts as stale: that regenerates the pre-provenance corpus once, and it settles.
    """
    if not present:
        return True
    recorded = store.load_provenance(
        bill_slug=ref.bill_slug, doc_key=ref.doc_key, version=ref.version, artifact=artifact
    )
    if recorded is None:
        return True
    return recorded.get("inputs") != inputs
