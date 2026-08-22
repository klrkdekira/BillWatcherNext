import json

from rdflib import Dataset, Graph

from billwatcher.pipeline.akn import RegexMarkdownStructureExtractor, convert_to_akn
from billwatcher.pipeline.provenance import build_record
from billwatcher.pipeline.semantic import generate_semantic_files
from billwatcher.pipeline.store import FileStore, sha256_of

MARKDOWN = """\
## BAHAGIAN I

### PERMULAAN

1. Tajuk ringkas dan permulaan kuat kuasa

Akta ini bolehlah dinamakan Akta Pelaporan Kewangan 2026 dan hendaklah mula berkuat kuasa pada \
tarikh yang ditetapkan oleh Menteri melalui pemberitahuan dalam Gazet.

2. Tafsiran

Dalam Akta ini, melainkan jika konteksnya menghendaki makna yang lain, "Pesuruhjaya" ertinya \
Pesuruhjaya Pelaporan Kewangan yang dilantik di bawah fasal 5.

3. Kewajipan untuk melaporkan

(1) Seseorang yang menjalankan perniagaan berlesen hendaklah melaporkan setiap transaksi yang \
boleh disyaki kepada Pesuruhjaya dalam tempoh empat belas hari.

(a) melalui borang elektronik yang ditetapkan oleh Pesuruhjaya; atau

(b) melalui apa-apa cara bertulis yang diluluskan.
"""

DOC_KEY = "doc-abc12345"
BASE_IRI = "https://bills.example"
EXPRESSION_IRI = f"{BASE_IRI}/akn/my/bill/dr/2026/15/msa@"
KEYS = {"bill_slug": "dr-15-2026", "doc_key": DOC_KEY, "version": 1}


def version_dir(root, *, bill_slug="dr-15-2026", doc_key=DOC_KEY):
    return root / "documents" / bill_slug / doc_key / "v001"


def seed_document(
    store: FileStore,
    *,
    bill_slug: str = "dr-15-2026",
    doc_key: str = DOC_KEY,
    number: int = 15,
    language: str = "ms",
    markdown: str = MARKDOWN,
) -> None:
    store.save_bill(
        bill_slug,
        {
            "identifier": {
                "slug": bill_slug,
                "normalized": bill_slug.upper(),
                "originating_chamber": "dewan_rakyat",
                "year": 2026,
                "number": number,
            },
            "titles": {"raw_ms": "RUU Pelaporan Kewangan 2026", "raw_en": "Reporting Bill 2026"},
        },
    )
    keys = {"bill_slug": bill_slug, "doc_key": doc_key, "version": 1}
    store.save_document(**keys, content=b"%PDF-1.4 fake", metadata={"source_url": "https://x"})
    store.save_markdown(**keys, content=markdown)
    store.save_provenance(
        **keys,
        artifact="markdown",
        record=build_record(
            artifact="markdown",
            inputs={"language": language, "producer": "mineru"},
            outputs={"document.md": markdown.encode("utf-8")},
        ),
    )


def seed_document_with_akn(store: FileStore, **kwargs) -> None:
    seed_document(store, **kwargs)
    result = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())
    assert result.counts["converted"] >= 1, result.failures


def test_generates_jsonld_and_nquads_for_a_document_with_akn(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_document_with_akn(store)

    result = generate_semantic_files(store, base_iri=BASE_IRI)

    assert result.counts == {"eligible": 1, "converted": 1, "failed": 0}
    assert result.failures == ()

    directory = version_dir(tmp_path)
    jsonld_doc = json.loads((directory / "document.jsonld").read_text())
    assert jsonld_doc["@graph"][0]["@id"] == EXPRESSION_IRI
    assert jsonld_doc["@graph"][0]["eli:is_realized_by"] == {
        "@id": f"{BASE_IRI}/akn/my/bill/dr/2026/15"
    }

    nquads = (directory / "document.nq").read_text()
    assert f"<{EXPRESSION_IRI}/~part_I>" in nquads
    assert all(line.endswith(f"<{EXPRESSION_IRI}> .") for line in nquads.splitlines())


def test_the_provisions_are_addressed_beneath_the_expression_they_belong_to(tmp_path) -> None:
    """A provision IRI hangs off its Expression, not off the Work: the Malay clause 5 and the
    English clause 5 are different strings of text and must be separately citable."""
    store = FileStore(tmp_path)
    seed_document_with_akn(store, doc_key="doc-malay01", language="ms")
    seed_document_with_akn(store, doc_key="doc-english1", language="en")

    assert generate_semantic_files(store, base_iri=BASE_IRI).counts["converted"] == 2

    malay = (version_dir(tmp_path, doc_key="doc-malay01") / "document.nq").read_text()
    english = (version_dir(tmp_path, doc_key="doc-english1") / "document.nq").read_text()
    assert f"<{EXPRESSION_IRI}/~part_I__cl_1>" in malay
    assert f"<{BASE_IRI}/akn/my/bill/dr/2026/15/eng@/~part_I__cl_1>" in english
    # Both realise the one Work, which is what makes the two readings findable from each other.
    for nquads in (malay, english):
        assert f"<{BASE_IRI}/akn/my/bill/dr/2026/15>" in nquads


def test_a_document_with_no_akn_yet_is_not_eligible(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_document(store)

    result = generate_semantic_files(store, base_iri=BASE_IRI)

    assert result.counts == {"eligible": 0, "converted": 0, "failed": 0}
    assert not (version_dir(tmp_path) / "document.jsonld").exists()


def test_a_document_already_converted_is_not_reprocessed_and_nothing_is_rewritten(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_document_with_akn(store)

    first = generate_semantic_files(store, base_iri=BASE_IRI)
    assert first.counts["converted"] == 1
    before = {
        path.name: path.stat().st_mtime_ns for path in sorted(version_dir(tmp_path).iterdir())
    }

    second = generate_semantic_files(store, base_iri=BASE_IRI)

    assert second.counts == {"eligible": 0, "converted": 0, "failed": 0}
    after = {path.name: path.stat().st_mtime_ns for path in sorted(version_dir(tmp_path).iterdir())}
    assert after == before


def test_changing_the_base_iri_makes_a_converted_document_eligible_again(tmp_path) -> None:
    """The base IRI is part of every subject in the graph, so it is part of what the files were
    built from — an existence check would leave the whole corpus pointing at the old host."""
    store = FileStore(tmp_path)
    seed_document_with_akn(store)
    generate_semantic_files(store, base_iri=BASE_IRI)

    second = generate_semantic_files(store, base_iri="https://bills.example.org")

    assert second.counts == {"eligible": 1, "converted": 1, "failed": 0}
    nquads = (version_dir(tmp_path) / "document.nq").read_text()
    assert "https://bills.example.org/akn/my/bill/dr/2026/15" in nquads
    recorded = store.load_provenance(**KEYS, artifact="semantic")
    assert recorded["inputs"]["base_iri"] == "https://bills.example.org"


def test_correcting_only_the_bill_record_makes_the_semantic_files_eligible_again(tmp_path) -> None:
    """`build_graph` reads `eli:number` and the document's `schema:name` out of `bill.json`, so a
    later crawl correcting either has to regenerate the graph — the Akoma Ntoso is untouched, and an
    existence check or a source digest over it alone would leave the old title published.

    It is recorded as a digest rather than in `source_files` because that list is what
    `pipeline verify` re-hashes inside the document's own directory, and `bill.json` is not there.
    """
    store = FileStore(tmp_path)
    seed_document_with_akn(store)
    assert generate_semantic_files(store, base_iri=BASE_IRI).counts["converted"] == 1
    recorded = store.load_provenance(**KEYS, artifact="semantic")
    assert recorded["inputs"]["bill_sha256"]

    bill = store.load_bill("dr-15-2026")
    bill["titles"]["raw_ms"] = "RUU Pelaporan Kewangan 2026 (dibetulkan)"
    store.save_bill("dr-15-2026", bill)

    second = generate_semantic_files(store, base_iri=BASE_IRI)

    assert second.counts == {"eligible": 1, "converted": 1, "failed": 0}
    nquads = (version_dir(tmp_path) / "document.nq").read_text()
    assert "RUU Pelaporan Kewangan 2026 (dibetulkan)" in nquads
    rebuilt = store.load_provenance(**KEYS, artifact="semantic")
    assert rebuilt["inputs"]["bill_sha256"] != recorded["inputs"]["bill_sha256"]
    assert rebuilt["inputs"]["source_files"] == recorded["inputs"]["source_files"]


def test_the_semantic_files_record_the_akoma_ntoso_they_were_derived_from(tmp_path) -> None:
    """Step 5 reads step 4's file, never the markdown or the PDF again, so its provenance names
    exactly one source — which is what lets the two steps run any time apart."""
    store = FileStore(tmp_path)
    seed_document_with_akn(store)
    generate_semantic_files(store, base_iri=BASE_IRI)

    xml_bytes = store.load_akn(**KEYS)
    recorded = store.load_provenance(**KEYS, artifact="semantic")
    assert recorded["raw_file"] == "document.jsonld"
    assert recorded["inputs"]["source_files"] == [
        {"file": "document.akn.xml", "sha256": sha256_of(xml_bytes)}
    ]
    assert recorded["inputs"]["producer"] == "rdflib"
    assert set(recorded["output"]) == {"document.jsonld", "document.nq"}


def test_a_malformed_akn_file_is_counted_and_named_not_raised(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_document(store)
    store.save_akn(**KEYS, content=b"not xml")

    result = generate_semantic_files(store, base_iri=BASE_IRI)

    assert result.counts == {"eligible": 1, "converted": 0, "failed": 1}
    failure = result.failures[0]
    assert (failure.bill_slug, failure.doc_key, failure.version) == ("dr-15-2026", DOC_KEY, 1)
    assert failure.reason.startswith("SemanticConversionError:")
    assert not (version_dir(tmp_path) / "document.jsonld").exists()
    assert not (version_dir(tmp_path) / "document.nq").exists()


def test_the_two_stored_files_state_exactly_the_same_triples(tmp_path) -> None:
    """ADR-023's guarantee, read back off disk: one graph construction, two serialisations, so
    neither file can carry a fact the other lacks."""
    store = FileStore(tmp_path)
    seed_document_with_akn(store)
    generate_semantic_files(store, base_iri=BASE_IRI)

    directory = version_dir(tmp_path)
    from_jsonld = Graph()
    from_jsonld.parse(source=directory / "document.jsonld", format="json-ld")
    from_nquads = Dataset()
    from_nquads.parse(source=directory / "document.nq", format="nquads")

    assert set(from_jsonld)
    assert {quad[:3] for quad in from_nquads.quads((None, None, None, None))} == set(from_jsonld)


def test_the_step_leaves_only_files_this_pipeline_knows_about(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_document_with_akn(store)
    generate_semantic_files(store, base_iri=BASE_IRI)

    assert list(store.iter_unexpected_files()) == []
    assert sorted(path.name for path in version_dir(tmp_path).iterdir()) == [
        "document.akn.gate.json",
        "document.akn.provenance.json",
        "document.akn.xml",
        "document.jsonld",
        "document.markdown.provenance.json",
        "document.md",
        "document.nq",
        "document.pdf",
        "document.semantic.provenance.json",
        "metadata.json",
    ]
