import json
from datetime import UTC, datetime

import pytest

from billwatcher.reporting import run_id_for
from billwatcher.store import KNOWN_FILENAMES, FileStore, sha256_of

KEYS = {"bill_slug": "dr-15-2026", "doc_key": "doc-abc12345", "version": 1}


def version_dir(root):
    return root / "documents" / "dr-15-2026" / "doc-abc12345" / "v001"


def seed_document(store: FileStore) -> None:
    store.save_document(**KEYS, content=b"%PDF-1.4 fake", metadata={"source_url": "https://x"})


def test_listing_round_trips_body_and_metadata(tmp_path) -> None:
    store = FileStore(tmp_path)
    store.save_listing(
        key="dewan_rakyat-current-ms",
        extension="html",
        body=b"<html>hello</html>",
        metadata={"url": "https://example.org/a.html", "status_code": 200},
    )
    stored = list(store.iter_listings())
    assert len(stored) == 1
    assert stored[0].key == "dewan_rakyat-current-ms"
    assert stored[0].body == b"<html>hello</html>"
    assert stored[0].metadata["status_code"] == 200


def test_listing_write_is_idempotent(tmp_path) -> None:
    """An unchanged file keeps its mtime as well as its bytes, which is what makes "a repeat run
    writes nothing" observable from outside — atomic writes replace the file wholesale, so the
    comparison has to short-circuit before the write rather than after it."""
    store = FileStore(tmp_path)
    kwargs = dict(key="k", extension="html", body=b"same", metadata={"a": 1})
    store.save_listing(**kwargs)
    path = tmp_path / "listings" / "k" / "body.html"
    first_mtime = path.stat().st_mtime_ns
    store.save_listing(**kwargs)
    assert path.stat().st_mtime_ns == first_mtime


def test_a_changed_body_is_rewritten_over_the_same_path(tmp_path) -> None:
    store = FileStore(tmp_path)
    store.save_listing(key="k", extension="html", body=b"first", metadata={"a": 1})
    store.save_listing(key="k", extension="html", body=b"second", metadata={"a": 2})
    assert (tmp_path / "listings" / "k" / "body.html").read_bytes() == b"second"
    assert [stored.metadata["a"] for stored in store.iter_listings()] == [2]


def test_a_write_leaves_no_temp_file_behind(tmp_path) -> None:
    """Every write is a sibling-plus-rename, so a reader never sees a half-written artifact — but
    the sibling must not survive the write either, or `pipeline verify` reports it forever."""
    store = FileStore(tmp_path)
    store.save_bill("dr-15-2026", {"identifier": {"slug": "dr-15-2026"}})
    seed_document(store)
    store.save_markdown(**KEYS, content="1. Tajuk.\n")
    store.save_akn(**KEYS, content=b"<akomaNtoso/>")
    store.save_structure_gate(**KEYS, record={"gate": "P1", "status": "passed"})
    store.save_manifest(step="convert-to-akn", run_id="20260821T000000Z", payload={"counts": {}})

    leftovers = [str(path) for path in tmp_path.rglob("*") if path.name.endswith(".tmp")]
    assert leftovers == []
    assert list(store.iter_unexpected_files()) == []


def test_bill_round_trips_and_is_absent_before_saving(tmp_path) -> None:
    store = FileStore(tmp_path)
    assert store.load_bill("dr-15-2026") is None
    store.save_bill("dr-15-2026", {"identifier": {"slug": "dr-15-2026"}})
    assert store.load_bill("dr-15-2026") == {"identifier": {"slug": "dr-15-2026"}}
    assert list(store.iter_bill_slugs()) == ["dr-15-2026"]


def test_document_round_trips_and_has_document_reflects_reality(tmp_path) -> None:
    store = FileStore(tmp_path)
    assert not store.has_document(**KEYS)
    seed_document(store)
    assert store.has_document(**KEYS)
    assert store.load_document(**KEYS) == b"%PDF-1.4 fake"
    refs = list(store.iter_documents())
    assert len(refs) == 1
    assert refs[0].bill_slug == "dr-15-2026"
    assert refs[0].doc_key == "doc-abc12345"
    assert refs[0].version == 1
    assert refs[0].metadata["source_url"] == "https://x"


def test_iter_bill_documents_sees_one_bills_documents_and_no_others(tmp_path) -> None:
    """The serving surface resolves a request to one bill, so it must not pay for a scan of every
    other bill's directories to find one document."""
    store = FileStore(tmp_path)
    seed_document(store)
    store.save_document(
        bill_slug="dn-3-2026", doc_key="doc-other", version=1, content=b"%PDF", metadata={}
    )
    assert [ref.doc_key for ref in store.iter_bill_documents("dr-15-2026")] == ["doc-abc12345"]
    assert [ref.doc_key for ref in store.iter_bill_documents("dn-3-2026")] == ["doc-other"]
    assert list(store.iter_bill_documents("dr-99-2026")) == []


def test_markdown_akn_and_semantic_files_round_trip_beside_the_document(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_document(store)
    assert not store.has_markdown(**KEYS)
    assert not store.has_akn(**KEYS)
    assert not store.has_semantic(**KEYS)

    store.save_markdown(**KEYS, content="1. Tajuk.\n")
    store.save_akn(**KEYS, content=b"<akomaNtoso/>")
    store.save_jsonld(**KEYS, content=b'{"@graph": []}\n')
    store.save_rdf(**KEYS, content=b"<a> <b> <c> <d> .\n")

    assert store.has_markdown(**KEYS) and store.has_akn(**KEYS) and store.has_semantic(**KEYS)
    assert store.load_markdown(**KEYS) == "1. Tajuk.\n"
    assert store.load_akn(**KEYS) == b"<akomaNtoso/>"
    assert store.load_jsonld(**KEYS) == b'{"@graph": []}\n'
    assert store.load_rdf(**KEYS) == b"<a> <b> <c> <d> .\n"


def test_a_rejected_render_is_kept_as_evidence_without_becoming_the_documents_akn(tmp_path) -> None:
    """ADR-017 requires a failing artifact to be a review item rather than a discard: a verdict is
    only reviewable if what it judged is on the record. Nothing downstream may pick it up."""
    store = FileStore(tmp_path)
    seed_document(store)
    store.save_rejected_akn(**KEYS, content=b"<akomaNtoso/>")

    assert (version_dir(tmp_path) / "document.akn.rejected.xml").exists()
    assert not store.has_akn(**KEYS)
    assert store.load_akn(**KEYS) is None
    assert list(store.iter_unexpected_files()) == []


def test_withdrawing_an_akn_document_unpublishes_it_and_leaves_the_evidence(tmp_path) -> None:
    """Withdrawing a reading is a reviewable act, not a deletion.

    The gate verdict and the rejected render stay, because a withdrawal nobody can inspect is
    indistinguishable from a bug. The provenance goes with the file it describes: bytes that are no
    longer there, and a record left behind would make the artifact look current to `needs_rebuild`.
    """
    store = FileStore(tmp_path)
    seed_document(store)
    store.save_akn(**KEYS, content=b"<akomaNtoso/>")
    store.save_provenance(**KEYS, artifact="akn", record={"artifact": "akn", "inputs": {}})
    store.save_structure_gate(**KEYS, record={"gate": "P1", "status": "mismatch"})
    store.save_rejected_akn(**KEYS, content=b"<akomaNtoso><!-- the failing render --></akomaNtoso>")

    store.withdraw_akn(**KEYS)

    assert not store.has_akn(**KEYS)
    assert store.load_akn(**KEYS) is None
    assert store.load_provenance(**KEYS, artifact="akn") is None
    assert store.load_structure_gate(**KEYS) == {"gate": "P1", "status": "mismatch"}
    assert (version_dir(tmp_path) / "document.akn.rejected.xml").exists()
    assert list(store.iter_unexpected_files()) == []

    # And withdrawing a document that has none is not an error: the step calls this on any failure.
    store.withdraw_akn(**KEYS)


def test_withdrawing_an_akn_document_takes_the_semantic_files_derived_from_it(tmp_path) -> None:
    """A withdrawn reading cannot leave its own graph behind.

    The semantic pair is built from that exact XML and its provenance names the XML as its source,
    so leaving it orphans it twice: it describes a document that is no longer published, and
    `pipeline verify` correctly reports its source as missing — which made a pipeline behaving
    exactly as designed look damaged. Removing the derived pair with its source is the only
    internally consistent state.
    """
    store = FileStore(tmp_path)
    seed_document(store)
    store.save_akn(**KEYS, content=b"<akomaNtoso/>")
    store.save_provenance(**KEYS, artifact="akn", record={"artifact": "akn", "inputs": {}})
    store.save_jsonld(**KEYS, content=b'{"@graph": []}')
    store.save_rdf(**KEYS, content=b"\n")
    store.save_provenance(
        **KEYS,
        artifact="semantic",
        record={
            "artifact": "semantic",
            "inputs": {"source_files": [{"file": "document.akn.xml", "sha256": "0" * 64}]},
        },
    )
    assert store.has_semantic(**KEYS)

    store.withdraw_akn(**KEYS)

    assert not store.has_semantic(**KEYS)
    assert store.load_jsonld(**KEYS) is None
    assert store.load_rdf(**KEYS) is None
    assert store.load_provenance(**KEYS, artifact="semantic") is None


def test_the_akn_gate_verdict_round_trips_and_is_absent_before_the_step_runs(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_document(store)
    assert store.load_structure_gate(**KEYS) is None

    verdict = {"gate": "P1", "status": "mismatch", "coverage": 0.87, "findings": []}
    store.save_structure_gate(**KEYS, record=verdict)
    assert store.load_structure_gate(**KEYS) == verdict


def test_provenance_round_trips_per_artifact_and_is_not_shared_between_them(tmp_path) -> None:
    """The record — not the mere existence of a file — is what decides whether a step has work
    to do, so each artifact needs its own: otherwise fixing the renderer would read as a change
    to the markdown it was built from."""
    store = FileStore(tmp_path)
    seed_document(store)
    assert store.load_provenance(**KEYS, artifact="akn") is None

    markdown_record = {"artifact": "markdown", "inputs": {"language": "ms"}}
    akn_record = {"artifact": "akn", "inputs": {"code_version": "1.0.0"}}
    store.save_provenance(**KEYS, artifact="markdown", record=markdown_record)
    store.save_provenance(**KEYS, artifact="akn", record=akn_record)

    assert store.load_provenance(**KEYS, artifact="markdown") == markdown_record
    assert store.load_provenance(**KEYS, artifact="akn") == akn_record
    assert store.load_provenance(**KEYS, artifact="semantic") is None
    assert (version_dir(tmp_path) / "document.markdown.provenance.json").exists()
    assert (version_dir(tmp_path) / "document.akn.provenance.json").exists()


def test_an_artifact_this_pipeline_does_not_produce_has_no_provenance_path(tmp_path) -> None:
    """A typo'd artifact name must not quietly create a sidecar nothing will ever read again."""
    store = FileStore(tmp_path)
    seed_document(store)
    with pytest.raises(ValueError, match="unknown artifact"):
        store.save_provenance(**KEYS, artifact="markdwon", record={})
    with pytest.raises(ValueError, match="unknown artifact"):
        store.load_provenance(**KEYS, artifact="pdf")


def test_a_manifest_is_written_per_step_and_run_and_names_them_in_its_own_body(tmp_path) -> None:
    """Volatile facts live here and nowhere else: the path is already unique per run, so a
    timestamp costs nothing — whereas the same field in a per-artifact sidecar would make every
    re-run rewrite it."""
    store = FileStore(tmp_path)
    store.save_manifest(
        step="convert-to-akn",
        run_id="20260821T120000Z",
        payload={"counts": {"converted": 2}, "started_at": "2026-08-21T12:00:00+00:00"},
    )
    path = tmp_path / "manifests" / "convert-to-akn" / "20260821T120000Z.json"
    body = json.loads(path.read_text())
    assert body["step"] == "convert-to-akn"
    assert body["run_id"] == "20260821T120000Z"
    assert body["counts"] == {"converted": 2}


def test_two_runs_of_one_step_in_the_same_second_leave_two_manifests(tmp_path) -> None:
    """A manifest that can be overwritten is not an audit record.

    The path is the run's identity, and at second granularity an ordinary sequential shell loop over
    a few documents wrote the same path twice — the first run's record was simply gone.
    """
    store = FileStore(tmp_path)
    first = datetime(2026, 8, 21, 12, 0, 0, 1000, tzinfo=UTC)
    second = datetime(2026, 8, 21, 12, 0, 0, 750000, tzinfo=UTC)

    assert run_id_for(first) != run_id_for(second)
    for started_at, converted in ((first, 2), (second, 3)):
        store.save_manifest(
            step="convert-to-akn",
            run_id=run_id_for(started_at),
            payload={"counts": {"converted": converted}},
        )

    manifests = sorted((tmp_path / "manifests" / "convert-to-akn").iterdir())
    assert [json.loads(path.read_text())["counts"]["converted"] for path in manifests] == [2, 3]
    # Filesystem-safe, and sorting by name still sorts by time.
    assert [path.name for path in manifests] == [
        f"{run_id_for(first)}.json",
        f"{run_id_for(second)}.json",
    ]


def test_a_sidecar_the_store_cannot_parse_costs_its_own_document_and_no_other(tmp_path) -> None:
    """A reader's job is to keep going; `pipeline verify` is what reports the damage.

    These sidecars are read on the serving path and while walking the corpus, so one hand-edited or
    half-written file used to raise out of a listing and 500 every corpus page in the chamber.
    """
    store = FileStore(tmp_path)
    seed_document(store)
    store.save_document(
        bill_slug="dn-3-2026", doc_key="doc-other", version=1, content=b"%PDF", metadata={"a": 1}
    )
    (version_dir(tmp_path) / "metadata.json").write_bytes(b"{not json")

    assert [ref.doc_key for ref in store.iter_documents()] == ["doc-other"]
    assert list(store.iter_bill_documents("dr-15-2026")) == []


def test_an_unreadable_gate_verdict_or_provenance_record_reads_as_absent(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_document(store)
    (version_dir(tmp_path) / "document.structure.gate.json").write_bytes(
        b"\xff\xfe not utf-8 either"
    )
    (version_dir(tmp_path) / "document.akn.provenance.json").write_bytes(b"[]")

    assert store.load_structure_gate(**KEYS) is None
    # Valid JSON that is not an object is not a record either.
    assert store.load_provenance(**KEYS, artifact="akn") is None


def test_stored_text_is_read_back_as_the_utf_8_it_was_written_as(tmp_path) -> None:
    """`Path.read_text()` with no encoding uses the platform locale, so the same file read on a host
    with a non-UTF-8 locale decodes differently — silent corruption of a provision, not an error."""
    store = FileStore(tmp_path)
    seed_document(store)
    markdown = "1. Tafsiran\n\nAkta ini melindungi “saksi” dan pegawai berkuasa.\n"
    store.save_markdown(**KEYS, content=markdown)

    assert (version_dir(tmp_path) / "document.md").read_bytes() == markdown.encode("utf-8")
    assert store.load_markdown(**KEYS) == markdown


def test_iter_unexpected_files_reports_what_no_step_writes_and_nothing_it_does(tmp_path) -> None:
    """A killed process's leftover, a hand-dropped edit, or an artifact from a future version all
    have to be visible rather than silently served or silently ignored."""
    store = FileStore(tmp_path)
    seed_document(store)
    for filename in sorted(KNOWN_FILENAMES):
        (version_dir(tmp_path) / filename).write_bytes(b"x")
    assert list(store.iter_unexpected_files()) == []

    (version_dir(tmp_path) / ".document.akn.xml.tmp").write_bytes(b"half")
    (version_dir(tmp_path) / "notes.txt").write_bytes(b"by hand")
    (tmp_path / "documents" / "dr-15-2026" / "doc-abc12345" / "stray.md").write_bytes(b"misplaced")

    assert sorted(store.iter_unexpected_files()) == [
        "documents/dr-15-2026/doc-abc12345/stray.md",
        "documents/dr-15-2026/doc-abc12345/v001/.document.akn.xml.tmp",
        "documents/dr-15-2026/doc-abc12345/v001/notes.txt",
    ]


def test_a_known_filename_outside_a_version_directory_is_still_unexpected(tmp_path) -> None:
    """Storage paths are ours, so a `document.pdf` one level up is not a document — it is a file
    nothing wrote at a path nothing reads."""
    store = FileStore(tmp_path)
    seed_document(store)
    (tmp_path / "documents" / "dr-15-2026" / "doc-abc12345" / "document.pdf").write_bytes(b"%PDF")
    stray = "documents/dr-15-2026/doc-abc12345/document.pdf"
    assert list(store.iter_unexpected_files()) == [stray]


def test_iterators_are_empty_and_not_an_error_over_a_fresh_root(tmp_path) -> None:
    store = FileStore(tmp_path / "does-not-exist-yet")
    assert list(store.iter_listings()) == []
    assert list(store.iter_bill_slugs()) == []
    assert list(store.iter_documents()) == []
    assert list(store.iter_unexpected_files()) == []


def test_sha256_of_hashes_text_as_the_utf_8_bytes_it_is_stored_as(tmp_path) -> None:
    """Provenance hashes markdown as a `str` and XML as `bytes`; both have to name the same file."""
    assert sha256_of("Akta Contoh 2026") == sha256_of(b"Akta Contoh 2026")
    assert sha256_of("") == sha256_of(b"")
    assert sha256_of("a") != sha256_of("b")
