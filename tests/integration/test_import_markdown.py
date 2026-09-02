import pytest

from billwatcher.download.documents import doc_key
from billwatcher.graph.convert import resolve_language
from billwatcher.markdown.imports import (
    MarkdownImportError,
    Producer,
    import_markdown,
    import_markdown_tree,
)
from billwatcher.store import FileStore, sha256_of

PDF = b"%PDF-1.4 fake bill bytes"
PDF_SHA256 = sha256_of(PDF)
SOURCE_URL = "https://www.parlimen.gov.my/DR152026%20BM.pdf"

MARKDOWN_MS = """\
## SUSUNAN FASAL

## BAHAGIAN I

1. Tajuk ringkas dan permulaan kuat kuasa.

Akta ini bolehlah dinamakan Akta Contoh 2026.
"""

MARKDOWN_EN = """\
## ARRANGEMENT OF CLAUSES

## PART I

1. Short title and commencement.

This Act may be cited as the Example Act 2026.
"""

PRODUCER = Producer(tool="vllm", model_id="Qwen2.5-VL-7B-Instruct", version="2026.08")


def seed(store: FileStore, *, bill_slug: str = "dr-15-2026", url: str = SOURCE_URL) -> str:
    """One stored bill and one stored PDF, exactly as `fetch_documents` would leave them."""
    store.save_bill(
        bill_slug,
        {
            "identifier": {
                "slug": bill_slug,
                "originating_chamber": "dewan_rakyat",
                "year": 2026,
                "number": 15,
            }
        },
    )
    key = doc_key(url)
    store.save_document(
        bill_slug=bill_slug,
        doc_key=key,
        version=1,
        content=PDF,
        metadata={"source_url": url, "sha256": PDF_SHA256, "byte_size": len(PDF)},
    )
    return key


def test_import_writes_the_markdown_and_a_record_naming_the_pdf_it_reads(tmp_path) -> None:
    store = FileStore(tmp_path)
    key = seed(store)

    imported = import_markdown(
        store,
        bill_slug="dr-15-2026",
        doc_key=key,
        markdown_text=MARKDOWN_MS,
        language="ms",
        producer=PRODUCER,
    )

    assert imported.language == "ms"
    assert imported.language_disagreement is None
    assert imported.wrote_markdown is True
    assert imported.wrote_provenance is True
    assert imported.changed is True

    assert store.load_markdown(bill_slug="dr-15-2026", doc_key=key, version=1) == MARKDOWN_MS
    record = store.load_provenance(
        bill_slug="dr-15-2026", doc_key=key, version=1, artifact="markdown"
    )
    assert record is not None
    assert record["metadata_schema_version"] == 1
    assert record["artifact"] == "markdown"
    assert record["raw_file"] == "document.md"
    assert record["inputs"] == {
        "source_files": [{"file": "document.pdf", "sha256": PDF_SHA256}],
        "language": "ms",
        "producer": "vllm",
        "model_id": "Qwen2.5-VL-7B-Instruct",
        "producer_version": "2026.08",
    }
    assert record["output"] == {
        "document.md": {
            "sha256": sha256_of(MARKDOWN_MS),
            "byte_size": len(MARKDOWN_MS.encode("utf-8")),
        }
    }


def test_a_repeat_import_of_identical_markdown_writes_nothing(tmp_path) -> None:
    store = FileStore(tmp_path)
    key = seed(store)
    directory = tmp_path / "documents" / "dr-15-2026" / key / "v001"
    files = [directory / "document.md", directory / "document.markdown.provenance.json"]

    first = import_markdown(
        store,
        bill_slug="dr-15-2026",
        doc_key=key,
        markdown_text=MARKDOWN_MS,
        language="ms",
        producer=PRODUCER,
    )
    assert first.changed is True
    before = [path.stat().st_mtime_ns for path in files]

    second = import_markdown(
        store,
        bill_slug="dr-15-2026",
        doc_key=key,
        markdown_text=MARKDOWN_MS,
        language="ms",
        producer=PRODUCER,
    )

    assert second.changed is False
    assert (second.wrote_markdown, second.wrote_provenance) == (False, False)
    assert [path.stat().st_mtime_ns for path in files] == before


def test_the_same_markdown_from_a_different_model_rewrites_only_the_record(tmp_path) -> None:
    store = FileStore(tmp_path)
    key = seed(store)
    import_markdown(
        store,
        bill_slug="dr-15-2026",
        doc_key=key,
        markdown_text=MARKDOWN_MS,
        language="ms",
        producer=PRODUCER,
    )

    again = import_markdown(
        store,
        bill_slug="dr-15-2026",
        doc_key=key,
        markdown_text=MARKDOWN_MS,
        language="ms",
        producer=Producer(tool="vllm", model_id="Qwen3-VL-8B-Instruct", version="2026.09"),
    )

    assert (again.wrote_markdown, again.wrote_provenance) == (False, True)
    record = store.load_provenance(
        bill_slug="dr-15-2026", doc_key=key, version=1, artifact="markdown"
    )
    assert record is not None
    assert record["inputs"]["model_id"] == "Qwen3-VL-8B-Instruct"


def test_addressing_the_document_by_its_url_resolves_the_same_directory(tmp_path) -> None:
    store = FileStore(tmp_path)
    key = seed(store)

    imported = import_markdown(
        store,
        bill_slug="dr-15-2026",
        document_url=SOURCE_URL,
        markdown_text=MARKDOWN_MS,
        language="ms",
        producer=PRODUCER,
    )

    assert imported.doc_key == key
    assert store.has_markdown(bill_slug="dr-15-2026", doc_key=key, version=1)


def test_a_markdown_file_on_disk_is_read_without_its_byte_order_mark(tmp_path) -> None:
    store = FileStore(tmp_path)
    key = seed(store)
    source = tmp_path / "out.md"
    source.write_bytes(b"\xef\xbb\xbf" + MARKDOWN_MS.encode("utf-8"))

    imported = import_markdown(
        store,
        bill_slug="dr-15-2026",
        doc_key=key,
        markdown_path=source,
        language="ms",
        producer=PRODUCER,
    )

    stored = store.load_markdown(bill_slug="dr-15-2026", doc_key=key, version=1)
    assert stored == MARKDOWN_MS
    # A surviving BOM would sit on the Arrangement heading and hide it from the language check.
    assert imported.language_disagreement is None


def test_refuses_a_document_that_is_not_in_the_store(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed(store)

    with pytest.raises(MarkdownImportError, match=r"dr-15-2026/doc-deadbeef/v001"):
        import_markdown(
            store,
            bill_slug="dr-15-2026",
            doc_key="doc-deadbeef",
            markdown_text=MARKDOWN_MS,
            language="ms",
            producer=PRODUCER,
        )

    assert not (tmp_path / "documents" / "dr-15-2026" / "doc-deadbeef").exists()


def test_refuses_a_language_the_corpus_does_not_publish(tmp_path) -> None:
    store = FileStore(tmp_path)
    key = seed(store)

    with pytest.raises(MarkdownImportError, match=r"expected one of \['en', 'ms'\]"):
        import_markdown(
            store,
            bill_slug="dr-15-2026",
            doc_key=key,
            markdown_text=MARKDOWN_MS,
            language="zh",
            producer=PRODUCER,
        )

    assert not store.has_markdown(bill_slug="dr-15-2026", doc_key=key, version=1)


def test_refuses_blank_markdown(tmp_path) -> None:
    store = FileStore(tmp_path)
    key = seed(store)

    with pytest.raises(MarkdownImportError, match="blank markdown"):
        import_markdown(
            store,
            bill_slug="dr-15-2026",
            doc_key=key,
            markdown_text="   \n\n",
            language="ms",
            producer=PRODUCER,
        )


def test_a_declared_language_the_document_contradicts_is_reported_not_silently_applied(
    tmp_path,
) -> None:
    store = FileStore(tmp_path)
    key = seed(store)

    imported = import_markdown(
        store,
        bill_slug="dr-15-2026",
        doc_key=key,
        markdown_text=MARKDOWN_EN,
        language="ms",
        producer=PRODUCER,
    )

    assert imported.language_disagreement == "declared 'ms', document reads 'en'"
    assert imported.as_detail()["language_disagreement"] == "declared 'ms', document reads 'en'"
    # The declaration still wins — the operator knows which PDF they read — but it is on the record.
    record = store.load_provenance(
        bill_slug="dr-15-2026", doc_key=key, version=1, artifact="markdown"
    )
    assert record is not None
    assert record["inputs"]["language"] == "ms"


def test_the_akn_step_reads_back_the_declared_language(tmp_path) -> None:
    store = FileStore(tmp_path)
    key = seed(store)
    import_markdown(
        store,
        bill_slug="dr-15-2026",
        doc_key=key,
        markdown_text=MARKDOWN_MS,
        language="ms",
        producer=PRODUCER,
    )

    ref = next(ref for ref in store.iter_bill_documents("dr-15-2026") if ref.doc_key == key)
    assert resolve_language(store, ref, MARKDOWN_MS) == ("ms", None)


def test_the_akn_step_sees_the_disagreement_the_import_recorded(tmp_path) -> None:
    store = FileStore(tmp_path)
    key = seed(store)
    import_markdown(
        store,
        bill_slug="dr-15-2026",
        doc_key=key,
        markdown_text=MARKDOWN_EN,
        language="ms",
        producer=PRODUCER,
    )

    ref = next(ref for ref in store.iter_bill_documents("dr-15-2026") if ref.doc_key == key)
    language, disagreement = resolve_language(store, ref, MARKDOWN_EN)
    assert language == "ms"
    assert disagreement == "declared 'ms', document reads 'en'"


def write_source(root, *, bill_slug: str, key: str, version: int, text: str) -> None:
    path = root / bill_slug / key / f"v{version:03d}" / "document.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_mirrored_directory_imports_every_document_and_settles_on_a_second_run(
    tmp_path,
) -> None:
    store = FileStore(tmp_path / "store")
    first_key = seed(store)
    second_key = seed(
        store, bill_slug="dr-16-2026", url="https://www.parlimen.gov.my/DR162026%20BM.pdf"
    )
    source = tmp_path / "markdown"
    write_source(source, bill_slug="dr-15-2026", key=first_key, version=1, text=MARKDOWN_MS)
    write_source(source, bill_slug="dr-16-2026", key=second_key, version=1, text=MARKDOWN_MS)

    report = import_markdown_tree(store, source_root=source, language="ms", producer=PRODUCER)

    assert report.counts == {
        "found": 2,
        "imported": 2,
        "unchanged": 0,
        "failed": 0,
        "language_disagreements": 0,
        "unrecognised": 0,
    }
    assert report.failures == ()
    assert store.has_markdown(bill_slug="dr-16-2026", doc_key=second_key, version=1)

    again = import_markdown_tree(store, source_root=source, language="ms", producer=PRODUCER)
    assert again.counts["imported"] == 0
    assert again.counts["unchanged"] == 2


def test_a_mirrored_directory_names_what_it_could_not_import(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    key = seed(store)
    source = tmp_path / "markdown"
    write_source(source, bill_slug="dr-15-2026", key=key, version=1, text=MARKDOWN_MS)
    # A document nobody fetched, and a file at a depth that addresses no document at all.
    write_source(source, bill_slug="dr-99-2026", key="doc-deadbeef", version=1, text=MARKDOWN_MS)
    stray = source / "notes" / "document.md"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text(MARKDOWN_MS, encoding="utf-8")

    report = import_markdown_tree(store, source_root=source, language="ms", producer=PRODUCER)

    assert report.counts["imported"] == 1
    assert report.counts["failed"] == 1
    assert report.counts["unrecognised"] == 1
    assert [failure.bill_slug for failure in report.failures] == ["dr-99-2026"]
    assert "no stored document" in report.failures[0].reason
    assert report.unrecognised == ("notes/document.md",)
    payload = report.as_payload()
    assert payload["unrecognised_files"] == ["notes/document.md"]
    assert payload["failures"][0]["doc_key"] == "doc-deadbeef"


def test_a_misfiled_language_is_a_warning_not_a_failure(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    key = seed(store)
    source = tmp_path / "markdown"
    write_source(source, bill_slug="dr-15-2026", key=key, version=1, text=MARKDOWN_EN)

    report = import_markdown_tree(store, source_root=source, language="ms", producer=PRODUCER)

    assert report.counts["imported"] == 1
    assert report.counts["failed"] == 0
    assert report.counts["language_disagreements"] == 1
    assert report.failures == ()
    assert report.warnings[0].reason == (
        "language disagreement: declared 'ms', document reads 'en'"
    )
    assert report.as_payload()["warnings"][0]["bill_slug"] == "dr-15-2026"
    assert "failures" not in report.as_payload()
    assert report.as_step_result().counts["imported"] == 1
