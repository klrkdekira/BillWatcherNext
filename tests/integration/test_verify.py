"""`pipeline verify` over a real seeded store, tampered with one way at a time."""

import json
from pathlib import Path

from billwatcher.graph.convert import convert_to_akn
from billwatcher.graph.semantic import generate_semantic_files
from billwatcher.graph.structure import MarkdownStructureExtractor, RegexMarkdownStructureExtractor
from billwatcher.graph.tree import Node
from billwatcher.provenance import build_record
from billwatcher.store import FileStore, sha256_of
from billwatcher.verify import ISSUE_LIMIT, verify_store
from billwatcher.version import SEMANTIC_VERSION

MARKDOWN = """\
## BAHAGIAN I

### PERMULAAN

1. Tajuk ringkas dan permulaan kuat kuasa

(1) Akta ini bolehlah dinamakan Akta Pelaporan Contoh 2026.

(2) Akta ini mula berkuat kuasa pada tarikh yang ditetapkan oleh Menteri.

2. Tafsiran

Dalam Akta ini, melainkan jika konteksnya menghendaki makna yang lain, perkataan berikut
mempunyai makna yang diberikan kepadanya.

3. Kewajipan untuk melaporkan

(1) Setiap badan yang ditetapkan hendaklah melaporkan kepada Menteri.

(a) dalam tempoh tiga puluh hari selepas tarikh mula berkuat kuasa; dan

(b) selepas itu pada setiap tahun kalendar.
"""

# One sentence of the document, which the reading below simply does not report.
DROPPED_SUBSECTION = "(2) Akta ini mula berkuat kuasa pada tarikh yang ditetapkan oleh Menteri.\n"

PDF = b"%PDF-1.4 pretend document bytes"
BASE_IRI = "https://bills.example"
BILL_SLUG = "dr-15-2026"
DOC_KEY = "doc-abc12345"
KEYS = {"bill_slug": BILL_SLUG, "doc_key": DOC_KEY, "version": 1}
STORE_PATH = f"documents/{BILL_SLUG}/{DOC_KEY}/v001"


class LossyExtractor(RegexMarkdownStructureExtractor):
    """A reading that drops one sentence of the document it was given.

    Stands in for the ordinary imperfect model reading: structurally complete, every provision
    numbered, and one subsection's text simply absent. It scores 0.982 — above the 0.95 default and
    below a 0.999 an operator might be considering — which is the residue the slack exists for.
    """

    name = "stub-lossy"

    def extract(self, markdown_text: str, *, unit: str, blocks: object = None) -> Node:
        return super().extract(markdown_text.replace(DROPPED_SUBSECTION, ""), unit=unit)


def seed(
    root: Path,
    *,
    markdown: str = MARKDOWN,
    extractor: MarkdownStructureExtractor | None = None,
) -> FileStore:
    """A store holding one fully converted document: PDF, markdown, AKN, semantic files."""
    store = FileStore(root)
    store.save_bill(
        BILL_SLUG,
        {
            "identifier": {
                "slug": BILL_SLUG,
                "year": 2026,
                "number": 15,
                "normalized": "D.R. 15/2026",
                "originating_chamber": "dewan_rakyat",
            },
            "titles": {"raw_ms": "Rang Undang-undang Pelaporan Contoh 2026"},
        },
    )
    store.save_document(
        **KEYS,
        content=PDF,
        metadata={
            "source_url": "https://www.parlimen.gov.my/a.pdf",
            "sha256": sha256_of(PDF),
            "byte_size": len(PDF),
        },
    )
    store.save_markdown(**KEYS, content=markdown)
    store.save_provenance(
        **KEYS,
        artifact="markdown",
        record=build_record(
            artifact="markdown",
            inputs={
                "source_files": [{"file": "document.pdf", "sha256": sha256_of(PDF)}],
                "language": "ms",
                "producer": "operator-import",
            },
            outputs={"document.md": markdown.encode("utf-8")},
        ),
    )
    converted = convert_to_akn(store, extractor=extractor or RegexMarkdownStructureExtractor())
    assert converted.counts["converted"], converted.as_payload()
    assert generate_semantic_files(store, base_iri=BASE_IRI).counts["converted"]
    return store


def version_dir(root: Path) -> Path:
    return root / STORE_PATH


def named(issues: list[str], prefix: str) -> list[str]:
    return [issue for issue in issues if issue.startswith(prefix)]


def test_a_clean_store_reports_nothing_in_either_mode(tmp_path) -> None:
    store = seed(tmp_path)

    assert verify_store(store) == []
    assert verify_store(store, strict=True) == []


def test_rewritten_document_bytes_are_reported_against_the_recorded_digest(tmp_path) -> None:
    store = seed(tmp_path)
    tampered = b"%PDF-1.4 PRETEND document bytes"
    assert len(tampered) == len(PDF)
    (version_dir(tmp_path) / "document.pdf").write_bytes(tampered)

    assert verify_store(store) == [
        f"content differs from the recorded digest: {STORE_PATH}/document.pdf"
    ]


def test_a_truncated_document_reports_both_its_digest_and_its_length(tmp_path) -> None:
    store = seed(tmp_path)
    (version_dir(tmp_path) / "document.pdf").write_bytes(PDF[:10])

    assert verify_store(store) == [
        f"content differs from the recorded digest: {STORE_PATH}/document.pdf",
        f"byte size differs from the recorded size: {STORE_PATH}/document.pdf",
    ]


def test_a_sidecar_that_is_not_its_canonical_serialisation_is_reported(tmp_path) -> None:
    store = seed(tmp_path)
    path = version_dir(tmp_path) / "metadata.json"
    # Same facts, hand-reformatted: the round-trip is what notices, not any field comparison.
    path.write_bytes(json.dumps(json.loads(path.read_text())).encode("utf-8"))

    assert verify_store(store) == [
        f"content differs from its canonical serialisation: {STORE_PATH}/metadata.json"
    ]


def test_an_unparseable_sidecar_is_reported_rather_than_raising(tmp_path) -> None:
    """A corrupt sidecar costs its own document and nothing else.

    The store's readers return None for a sidecar they cannot parse rather than raising, so
    `iter_documents` walks past this document instead of dying on it — one hand-edited or
    half-written file used to 500 every corpus listing page and abort a whole verify pass. Reporting
    it is this command's job; the layout walk is what sees it, because the listing no longer can.
    """
    store = seed(tmp_path)
    (version_dir(tmp_path) / "metadata.json").write_bytes(b"{not json")

    assert list(store.iter_documents()) == []

    issues = verify_store(store)

    assert named(issues, "not readable as json")
    assert f"{STORE_PATH}/metadata.json" in issues[0]
    assert not named(issues, "could not be listed past a document the store cannot read")


def test_a_version_directory_with_no_sidecar_is_reported_though_iter_documents_skips_it(
    tmp_path,
) -> None:
    store = seed(tmp_path)
    (version_dir(tmp_path) / "metadata.json").unlink()

    # Nothing that walks `iter_documents` can see this directory at all; the layout walk is the
    # only reason the missing sidecar is reported instead of the whole document disappearing.
    assert list(store.iter_documents()) == []
    assert verify_store(store) == [f"missing from the store: {STORE_PATH}/metadata.json"]


def test_a_non_canonical_version_directory_name_is_reported(tmp_path) -> None:
    store = seed(tmp_path)
    version_dir(tmp_path).rename(version_dir(tmp_path).parent / "v1")

    issues = verify_store(store)

    assert issues[0] == (
        "not a canonical version directory, so nothing in it can be addressed: "
        f"documents/{BILL_SLUG}/{DOC_KEY}/v1"
    )


def test_half_of_the_semantic_pair_is_reported_though_has_semantic_only_says_no(tmp_path) -> None:
    store = seed(tmp_path)
    (version_dir(tmp_path) / "document.nq").unlink()

    # `has_semantic` requires both files, so on its own it reports the pair as simply absent.
    assert not store.has_semantic(**KEYS)
    assert verify_store(store) == [f"missing from the store: {STORE_PATH}/document.nq"]


def test_a_stray_file_in_a_version_directory_is_reported(tmp_path) -> None:
    store = seed(tmp_path)
    (version_dir(tmp_path) / "notes.txt").write_bytes(b"scratch")

    assert verify_store(store) == [
        f"present in the store with no step that writes it: {STORE_PATH}/notes.txt"
    ]


def test_a_derived_artifact_that_no_longer_matches_its_provenance_digest_is_reported(
    tmp_path,
) -> None:
    store = seed(tmp_path)
    path = version_dir(tmp_path) / "document.jsonld"
    path.write_bytes(path.read_bytes().replace(b"Rang Undang-undang", b"Rang undang-undang"))

    assert (
        f"content differs from the digest its provenance records: {STORE_PATH}/document.jsonld"
        in verify_store(store)
    )


def test_an_artifact_whose_provenance_record_is_gone_is_reported(tmp_path) -> None:
    store = seed(tmp_path)
    (version_dir(tmp_path) / "document.akn.provenance.json").unlink()

    assert verify_store(store) == [
        f"present with no provenance record: {STORE_PATH}/document.akn.xml"
    ]


def test_unprovenanced_markdown_waits_for_strict_because_it_is_imported_not_produced(
    tmp_path,
) -> None:
    store = seed(tmp_path)
    (version_dir(tmp_path) / "document.markdown.provenance.json").unlink()

    assert verify_store(store) == []
    assert verify_store(store, strict=True) == [
        f"present with no provenance record: {STORE_PATH}/document.md"
    ]


def test_provenance_naming_a_file_no_step_writes_is_reported(tmp_path) -> None:
    store = seed(tmp_path)
    record = store.load_provenance(**KEYS, artifact="semantic")
    assert record is not None
    record["output"]["../../escape.json"] = {"sha256": "0" * 64, "byte_size": 1}
    store.save_provenance(**KEYS, artifact="semantic", record=record)

    assert verify_store(store) == [
        "claims to have written a file no step writes ('../../escape.json'): "
        f"{STORE_PATH}/document.semantic.provenance.json"
    ]


def test_a_re_imported_source_makes_the_artifact_stale_only_under_strict(tmp_path) -> None:
    store = seed(tmp_path)
    # The whole staleness scenario in one move: markdown is re-imported with its own provenance
    # updated, and the Akoma Ntoso built from the previous bytes is left behind. A page-boundary
    # comment carries no text of its own, so Gate P1's verdict is untouched and nothing is damaged.
    markdown = MARKDOWN + "\n<!-- page 2 -->\n"
    store.save_markdown(**KEYS, content=markdown)
    store.save_provenance(
        **KEYS,
        artifact="markdown",
        record=build_record(
            artifact="markdown",
            inputs={
                "source_files": [{"file": "document.pdf", "sha256": sha256_of(PDF)}],
                "language": "ms",
                "producer": "operator-import",
            },
            outputs={"document.md": markdown.encode("utf-8")},
        ),
    )

    assert verify_store(store) == []
    assert verify_store(store, strict=True) == [
        f"stale: built from different document.md bytes: {STORE_PATH}/document.akn.xml"
    ]


def test_a_hand_edited_source_is_corruption_against_its_own_provenance(tmp_path) -> None:
    store = seed(tmp_path)
    path = version_dir(tmp_path) / "document.md"
    path.write_bytes(path.read_bytes() + b"\n<!-- page 2 -->\n")

    # The markdown's own provenance record names the digest of the file it produced, so editing it
    # in place is reported without --strict: this is a changed artifact, not merely an outdated one.
    assert verify_store(store) == [
        f"content differs from the digest its provenance records: {STORE_PATH}/document.md",
        f"byte size differs from the size its provenance records: {STORE_PATH}/document.md",
    ]


def test_an_artifact_built_by_an_earlier_code_version_is_stale(tmp_path) -> None:
    store = seed(tmp_path)
    record = store.load_provenance(**KEYS, artifact="semantic")
    assert record is not None
    record["inputs"]["code_version"] = "0.9.0"
    store.save_provenance(**KEYS, artifact="semantic", record=record)

    assert verify_store(store) == []
    assert verify_store(store, strict=True) == [
        f"stale: built by code version '0.9.0', this code is {SEMANTIC_VERSION!r}: "
        f"{STORE_PATH}/document.jsonld"
    ]


def test_a_gate_threshold_the_corpus_was_not_built_under_is_stale(tmp_path) -> None:
    store = seed(tmp_path)

    issues = verify_store(store, strict=True, min_text_coverage=0.99)

    assert (
        f"stale: gated at a minimum text coverage of 0.95, now 0.99: "
        f"{STORE_PATH}/document.akn.xml" in issues
    )


def test_gate_p1_is_re_run_from_the_stored_files_and_reports_a_disagreement(tmp_path) -> None:
    store = seed(tmp_path)
    path = version_dir(tmp_path) / "document.md"
    # Words the stored tree cannot account for, because the tree was built before they existed.
    path.write_bytes(
        path.read_bytes() + b"\nSATU perkara tambahan yang panjang lebar dan penuh perkataan asing "
        b"sekali lagi berulang tanpa henti mengenai perihal lampiran khas tersebut.\n"
    )

    assert (
        f"gate p1 now reads 'mismatch' where the recorded verdict is 'passed': "
        f"{STORE_PATH}/document.akn.xml" in verify_store(store)
    )


def test_a_threshold_change_re_judges_the_whole_store_with_no_model_call(tmp_path) -> None:
    """Tightening the gate is evaluable over the stored corpus without re-invoking the extractor.

    The stored reading here dropped one subsection of the document, which is the ordinary imperfect
    reading rather than a damaged store: it scores 0.982, above the 0.95 the corpus was built under
    and below the 0.999 an operator might be considering. Raising the number re-judges it from the
    stored XML and markdown alone.
    """
    store = seed(tmp_path, extractor=LossyExtractor())

    assert verify_store(store) == []
    assert store.load_structure_gate(**KEYS)["coverage"] == 0.9818

    issues = verify_store(store, min_text_coverage=0.999)

    assert (
        f"gate p1 now reads 'mismatch' where the recorded verdict is 'passed': "
        f"{STORE_PATH}/document.akn.xml" in issues
    )


def test_akn_with_no_gate_verdict_beside_it_is_reported(tmp_path) -> None:
    store = seed(tmp_path)
    (version_dir(tmp_path) / "document.structure.gate.json").unlink()

    assert verify_store(store) == [
        f"present with no gate p1 verdict beside it: {STORE_PATH}/document.akn.xml"
    ]


def test_akn_that_cannot_be_read_back_is_reported_rather_than_raising(tmp_path) -> None:
    store = seed(tmp_path)
    (version_dir(tmp_path) / "document.akn.xml").write_bytes(b"<akomaNtoso")

    issues = verify_store(store)

    assert named(issues, "not readable back as akoma ntoso")
    assert (
        f"content differs from the digest its provenance records: {STORE_PATH}/document.akn.xml"
        in issues
    )


def test_a_missing_source_file_is_reported_without_strict(tmp_path) -> None:
    store = seed(tmp_path)
    (version_dir(tmp_path) / "document.md").unlink()

    assert verify_store(store) == [f"missing from the store: {STORE_PATH}/document.md"]


def test_the_report_is_bounded_and_says_how_much_it_left_out(tmp_path) -> None:
    store = seed(tmp_path)
    strays = ISSUE_LIMIT + 12
    for index in range(strays):
        (version_dir(tmp_path) / f"stray-{index:04d}.txt").write_bytes(b"x")

    issues = verify_store(store)

    assert len(issues) == ISSUE_LIMIT + 1
    assert issues[-1] == f"report truncated: {strays - ISSUE_LIMIT} further issues not listed"


def test_an_empty_store_is_clean(tmp_path) -> None:
    assert verify_store(FileStore(tmp_path)) == []
