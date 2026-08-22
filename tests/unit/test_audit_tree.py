import json

from billwatcher.storage.audit_tree import AuditTree, doc_key, sidecar_bytes


def test_sidecar_bytes_are_deterministic_regardless_of_key_order() -> None:
    first = sidecar_bytes({"b": 2, "a": 1})
    second = sidecar_bytes({"a": 1, "b": 2})
    assert first == second
    assert first.endswith(b"\n")
    assert json.loads(first) == {"a": 1, "b": 2}


def test_doc_key_is_path_safe_and_derived_only_from_the_id() -> None:
    key = doc_key("3f9a1234-5678-90ab-cdef-000000000000")
    assert key == "doc-3f9a1234"
    assert "/" not in key


def test_write_document_version_creates_pdf_and_sidecar(tmp_path) -> None:
    tree = AuditTree(tmp_path)
    result = tree.write_document_version(
        bill_slug="dr-15-2026",
        document_id="3f9a1234-5678-90ab-cdef-000000000000",
        version_no=1,
        pdf_bytes=b"%PDF-1.4 fake",
        sidecar={"sha256": "abc"},
    )
    assert result.pdf_written is True
    assert result.sidecar_written is True
    directory = tmp_path / "03-documents" / "dr-15-2026" / "doc-3f9a1234" / "v001"
    assert directory == result.directory
    assert (directory / "document.pdf").read_bytes() == b"%PDF-1.4 fake"
    sidecar = json.loads((directory / "metadata.json").read_text())
    assert sidecar["sha256"] == "abc"
    assert sidecar["artifact"] == "document"
    assert sidecar["raw_file"] == "document.pdf"
    assert sidecar["metadata_schema_version"] == 1


def test_write_document_version_is_idempotent_when_unchanged(tmp_path) -> None:
    tree = AuditTree(tmp_path)
    kwargs = dict(
        bill_slug="dr-15-2026",
        document_id="3f9a1234-5678-90ab-cdef-000000000000",
        version_no=1,
        pdf_bytes=b"%PDF-1.4 fake",
        sidecar={"sha256": "abc"},
    )
    first = tree.write_document_version(**kwargs)
    assert first.pdf_written and first.sidecar_written
    second = tree.write_document_version(**kwargs)
    assert not second.pdf_written
    assert not second.sidecar_written


def test_write_document_version_rewrites_only_what_changed(tmp_path) -> None:
    tree = AuditTree(tmp_path)
    kwargs = dict(
        bill_slug="dr-15-2026",
        document_id="3f9a1234-5678-90ab-cdef-000000000000",
        version_no=1,
        pdf_bytes=b"%PDF-1.4 fake",
    )
    tree.write_document_version(sidecar={"sha256": "abc"}, **kwargs)
    result = tree.write_document_version(sidecar={"sha256": "def"}, **kwargs)
    assert result.pdf_written is False
    assert result.sidecar_written is True


def test_write_manifest_is_deterministic(tmp_path) -> None:
    tree = AuditTree(tmp_path)
    path = tree.write_manifest(step="fetch-documents", run_id="run-1", payload={"considered": 3})
    assert path == tmp_path / "manifests" / "fetch-documents" / "run-1.json"
    body = json.loads(path.read_text())
    assert body["step"] == "fetch-documents"
    assert body["run_id"] == "run-1"
    assert body["considered"] == 3
