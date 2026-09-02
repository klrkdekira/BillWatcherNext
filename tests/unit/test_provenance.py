"""What each derived artifact was built from, and whether it still matches.

The behaviour under test is a staleness decision, so every test is framed as one: given a stored
record and a freshly computed `inputs`, does the step have work to do? The cases that matter are the
ones an existence check gets wrong — a corrected IRI scheme, a fixed serialiser, an improved prompt
all leave the output file exactly where it was.

The last test is the one that protects everything else in this pipeline: a provenance record must
carry no timestamp and no run id, or a repeat run rewrites every sidecar and "a repeat run writes
nothing" stops being true.
"""

import json
from pathlib import Path
from typing import Any

from billwatcher.provenance import RAW_FILES, build_record, needs_rebuild
from billwatcher.store import FileStore, StoredDocumentRef, sha256_of

MARKDOWN = "1. Tajuk ringkas.\n\nAkta ini bolehlah dinamakan Akta Contoh 2026.\n"

REF = StoredDocumentRef(bill_slug="dr-15-2026", doc_key="doc-abc12345", version=1, metadata={})

# What step 4 records: the source markdown by hash, plus every version that decided the output —
# the serialiser, the gate, the threshold, and the extractor's own identity.
AKN_INPUTS: dict[str, Any] = {
    "source_files": [{"file": "document.md", "sha256": sha256_of(MARKDOWN)}],
    "code_version": "1.0.0",
    "gate_version": "1.0.0",
    "min_text_coverage": 0.95,
    "producer": "vllm",
    "model_id": "Qwen/Qwen3-30B",
    "prompt_sha256": "a" * 64,
}


def store_with_akn(root: Path) -> FileStore:
    """A store holding one document with a `document.akn.xml` and no provenance beside it."""
    store = FileStore(root)
    store.save_document(
        bill_slug=REF.bill_slug,
        doc_key=REF.doc_key,
        version=REF.version,
        content=b"%PDF-1.4 fake",
        metadata={"source_url": "https://example.org/a.pdf"},
    )
    store.save_akn(
        bill_slug=REF.bill_slug,
        doc_key=REF.doc_key,
        version=REF.version,
        content=b"<akomaNtoso/>",
    )
    return store


def record_akn(store: FileStore, inputs: dict[str, Any]) -> None:
    store.save_provenance(
        bill_slug=REF.bill_slug,
        doc_key=REF.doc_key,
        version=REF.version,
        artifact="akn",
        record=build_record(
            artifact="akn", inputs=inputs, outputs={"document.akn.xml": b"<akomaNtoso/>"}
        ),
    )


def test_build_record_names_the_artifact_its_raw_file_its_inputs_and_its_output() -> None:
    record = build_record(
        artifact="akn",
        inputs=AKN_INPUTS,
        outputs={"document.akn.xml": b"<akomaNtoso/>"},
    )
    assert record == {
        "metadata_schema_version": 1,
        "artifact": "akn",
        "raw_file": "document.akn.xml",
        "inputs": AKN_INPUTS,
        "output": {
            "document.akn.xml": {
                "sha256": sha256_of(b"<akomaNtoso/>"),
                "byte_size": len(b"<akomaNtoso/>"),
            }
        },
    }


def test_build_record_records_every_output_a_step_writes() -> None:
    """Step 5 writes two files from one graph, so one record has to account for both."""
    record = build_record(
        artifact="semantic",
        inputs={"code_version": "1.0.0"},
        outputs={"document.jsonld": b'{"@graph": []}', "document.nq": b""},
    )
    assert record["raw_file"] == "document.jsonld"
    assert sorted(record["output"]) == ["document.jsonld", "document.nq"]
    assert record["output"]["document.nq"] == {"sha256": sha256_of(b""), "byte_size": 0}


def test_the_raw_file_of_every_artifact_is_named_in_one_place() -> None:
    assert RAW_FILES == {
        "markdown": "document.md",
        "crosscheck": "document.crosscheck.md",
        "akn": "document.akn.xml",
        "semantic": "document.jsonld",
    }


def test_build_record_copies_its_inputs_rather_than_aliasing_them() -> None:
    """A step reuses one `inputs` dict per document; a record that aliased it would drift."""
    inputs = dict(AKN_INPUTS)
    record = build_record(artifact="akn", inputs=inputs, outputs={"document.akn.xml": b"x"})
    inputs["code_version"] = "9.9.9"
    assert record["inputs"]["code_version"] == "1.0.0"


def test_a_record_carries_no_timestamp_and_no_run_id(tmp_path: Path) -> None:
    """The guarantee the whole deterministic writer rests on: a repeat run writes nothing.

    Either field inside a per-artifact sidecar would make every re-run rewrite it, because either
    changes on every run. Volatile facts belong in the per-run manifest, whose path is already
    unique per run — so this checks the record's keys *and* checks the file's mtime survives a
    second identical save.
    """
    record = build_record(
        artifact="akn", inputs=AKN_INPUTS, outputs={"document.akn.xml": b"<akomaNtoso/>"}
    )
    serialised = json.dumps(record).casefold()
    for volatile in ("timestamp", "run_id", "started_at", "finished_at", "generated", "_at"):
        assert volatile not in serialised
    assert sorted(record) == ["artifact", "inputs", "metadata_schema_version", "output", "raw_file"]

    store = store_with_akn(tmp_path)
    record_akn(store, AKN_INPUTS)
    path = tmp_path / "documents" / REF.bill_slug / REF.doc_key / "v001"
    sidecar = path / "document.akn.provenance.json"
    first_mtime = sidecar.stat().st_mtime_ns
    record_akn(store, AKN_INPUTS)
    assert sidecar.stat().st_mtime_ns == first_mtime


def test_needs_rebuild_is_true_when_the_artifact_is_absent(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    assert needs_rebuild(store, REF, artifact="akn", inputs=AKN_INPUTS, present=False) is True


def test_needs_rebuild_is_true_for_a_present_artifact_with_no_provenance(tmp_path: Path) -> None:
    """A missing record beside a present artifact means it was built before provenance existed.

    That regenerates the pre-provenance corpus once and then settles — the alternative is a corpus
    that disagrees with the code claiming to have produced it, with nothing able to detect it.
    """
    store = store_with_akn(tmp_path)
    assert store.has_akn(bill_slug=REF.bill_slug, doc_key=REF.doc_key, version=REF.version)
    assert (
        store.load_provenance(
            bill_slug=REF.bill_slug, doc_key=REF.doc_key, version=REF.version, artifact="akn"
        )
        is None
    )
    assert needs_rebuild(store, REF, artifact="akn", inputs=AKN_INPUTS, present=True) is True


def test_needs_rebuild_is_false_when_the_recorded_inputs_match(tmp_path: Path) -> None:
    store = store_with_akn(tmp_path)
    record_akn(store, AKN_INPUTS)
    assert needs_rebuild(store, REF, artifact="akn", inputs=AKN_INPUTS, present=True) is False
    # And a fresh dict of the same values, which is what a step actually recomputes.
    assert needs_rebuild(store, REF, artifact="akn", inputs=dict(AKN_INPUTS), present=True) is False


def test_needs_rebuild_is_true_when_the_source_bytes_changed(tmp_path: Path) -> None:
    store = store_with_akn(tmp_path)
    record_akn(store, AKN_INPUTS)
    reimported = dict(AKN_INPUTS)
    reimported["source_files"] = [
        {"file": "document.md", "sha256": sha256_of(MARKDOWN + "\n2. Tafsiran.\n")}
    ]
    assert needs_rebuild(store, REF, artifact="akn", inputs=reimported, present=True) is True


def test_needs_rebuild_is_true_when_a_code_version_moved(tmp_path: Path) -> None:
    """The case an existence check can never notice: same source, different producing code."""
    store = store_with_akn(tmp_path)
    record_akn(store, AKN_INPUTS)
    for field, value in (
        ("code_version", "1.1.0"),
        ("gate_version", "2.0.0"),
        ("min_text_coverage", 0.98),
    ):
        changed = dict(AKN_INPUTS) | {field: value}
        assert needs_rebuild(store, REF, artifact="akn", inputs=changed, present=True) is True


def test_needs_rebuild_is_true_when_the_extractor_identity_changed(tmp_path: Path) -> None:
    """A prompt improvement or a model swap must not leave every artifact looking current.

    Without this the corpus silently mixes readings from different producers with no way to tell
    which is which.
    """
    store = store_with_akn(tmp_path)
    record_akn(store, AKN_INPUTS)
    for field, value in (
        ("producer", "regex"),
        ("model_id", "Qwen/Qwen3-235B"),
        ("model_id", None),
        ("prompt_sha256", "b" * 64),
        ("prompt_sha256", None),
    ):
        changed = dict(AKN_INPUTS) | {field: value}
        assert needs_rebuild(store, REF, artifact="akn", inputs=changed, present=True) is True


def test_needs_rebuild_reads_the_provenance_of_the_artifact_it_was_asked_about(
    tmp_path: Path,
) -> None:
    """Each artifact has its own record, so an up-to-date AKN says nothing about the graph."""
    store = store_with_akn(tmp_path)
    record_akn(store, AKN_INPUTS)
    semantic_inputs = {
        "source_files": [{"file": "document.akn.xml", "sha256": sha256_of(b"<akomaNtoso/>")}],
        "code_version": "1.0.0",
        "producer": "rdflib",
        "base_iri": "https://bills.example",
    }
    assert needs_rebuild(store, REF, artifact="akn", inputs=AKN_INPUTS, present=True) is False
    assert (
        needs_rebuild(store, REF, artifact="semantic", inputs=semantic_inputs, present=True) is True
    )
