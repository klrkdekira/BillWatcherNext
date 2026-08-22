from billwatcher.pipeline.akn import (
    RegexMarkdownStructureExtractor,
    convert_to_akn,
    parse_markdown_structure,
)
from billwatcher.pipeline.provenance import build_record
from billwatcher.pipeline.semantic import generate_semantic_files
from billwatcher.pipeline.store import FileStore, sha256_of
from billwatcher.pipeline.tree import Node
from billwatcher.pipeline.verify import verify_store

# A body long enough to be measured honestly. Gate P1 scores coverage over distinct words, so a
# three-line fixture would put the threshold within one word of failing and every test here would be
# about the fixture rather than about the step.
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

4. Penalti

Seseorang yang melanggar subfasal 3 melakukan suatu kesalahan dan boleh, apabila didapati \
bersalah, dikenakan denda tidak melebihi satu juta ringgit atau pemenjaraan selama tempoh tidak \
melebihi lima tahun atau kedua-duanya.
"""

# The same document as it is actually typeset: a table of contents, then the body it lists. Every
# entry repeats a heading from the body, which is exactly what makes it undetectable by wording.
ARRANGEMENT_MS = """\
# SUSUNAN FASAL

1. Tajuk ringkas dan permulaan kuat kuasa

2. Tafsiran

3. Kewajipan untuk melaporkan

4. Penalti

"""

ARRANGEMENT_EN = ARRANGEMENT_MS.replace("SUSUNAN FASAL", "ARRANGEMENT OF CLAUSES")

DOC_KEY = "doc-abc12345"
BASE_IRI = "https://bills.example"


class BodyOnlyExtractor:
    """What the LLM-assisted extractor exists to do: read the body and drop the Arrangement.

    Stands in for `VllmMarkdownStructureExtractor` so these tests exercise step 4 with a reading
    that is *correct*, without an endpoint. The split is by the body's first Part heading, which is
    a thing a fixture may know and a real extractor may not.
    """

    name = "stub-llm"
    model_id = "test-model"
    prompt_sha256 = "0" * 64

    def extract(self, markdown_text: str, *, unit: str) -> Node:
        body = markdown_text[markdown_text.index("## BAHAGIAN") :]
        return parse_markdown_structure(body, unit=unit)


class RelabelledExtractor(RegexMarkdownStructureExtractor):
    """Byte-for-byte the same reading, under a different producer identity."""

    name = "vllm"
    model_id = "test-model"
    prompt_sha256 = "f" * 64


def version_dir(root, *, bill_slug="dr-15-2026", doc_key=DOC_KEY):
    return root / "documents" / bill_slug / doc_key / "v001"


def seed_document(
    store: FileStore,
    *,
    bill_slug: str = "dr-15-2026",
    doc_key: str = DOC_KEY,
    chamber: str = "dewan_rakyat",
    number: int = 15,
    year: int = 2026,
    markdown: str | None = MARKDOWN,
    language: str | None = "ms",
) -> None:
    """One stored document, optionally with markdown and a markdown provenance record.

    `language=None` leaves no provenance record behind, which is the "nothing was declared at
    import" case — the document then has to speak for itself or be refused.
    """
    store.save_bill(
        bill_slug,
        {
            "identifier": {
                "slug": bill_slug,
                "normalized": bill_slug.upper(),
                "originating_chamber": chamber,
                "year": year,
                "number": number,
            },
            "titles": {"raw_ms": "RUU Pelaporan Kewangan 2026"},
        },
    )
    keys = {"bill_slug": bill_slug, "doc_key": doc_key, "version": 1}
    store.save_document(
        **keys,
        content=b"%PDF-1.4 fake",
        metadata={"source_url": "https://www.parlimen.gov.my/a.pdf"},
    )
    if markdown is None:
        return
    store.save_markdown(**keys, content=markdown)
    if language is not None:
        store.save_provenance(
            **keys,
            artifact="markdown",
            record=build_record(
                artifact="markdown",
                inputs={"language": language, "producer": "mineru"},
                outputs={"document.md": markdown.encode("utf-8")},
            ),
        )


def test_converts_a_document_whose_language_was_declared_when_its_markdown_was_imported(
    tmp_path,
) -> None:
    store = FileStore(tmp_path)
    seed_document(store)

    result = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())

    assert result.counts == {"eligible": 1, "converted": 1, "rejected": 0, "failed": 0}
    assert result.failures == ()
    xml_text = (version_dir(tmp_path) / "document.akn.xml").read_text()
    assert '<FRBRuri value="/akn/my/bill/dr/2026/15"' in xml_text
    assert '<FRBRthis value="/akn/my/bill/dr/2026/15/msa@"' in xml_text
    assert 'eId="part_I__cl_1"' in xml_text
    assert store.load_akn_gate(bill_slug="dr-15-2026", doc_key=DOC_KEY, version=1) is not None


def test_the_language_is_read_from_the_documents_own_arrangement_heading_when_none_was_declared(
    tmp_path,
) -> None:
    """HANDOFF 26.7 blesses the Arrangement heading as the source, and warns against sniffing the
    language out of a URL or filename — which upstream spells inconsistently."""
    store = FileStore(tmp_path)
    seed_document(store, markdown=ARRANGEMENT_MS + MARKDOWN, language=None)

    result = convert_to_akn(store, extractor=BodyOnlyExtractor())

    assert result.counts["converted"] == 1
    verdict = store.load_akn_gate(bill_slug="dr-15-2026", doc_key=DOC_KEY, version=1)
    assert verdict["status"] == "passed"
    assert verdict["language"] == "ms"
    assert "language_disagreement" not in verdict
    xml_text = (version_dir(tmp_path) / "document.akn.xml").read_text()
    assert '<FRBRthis value="/akn/my/bill/dr/2026/15/msa@"' in xml_text


def test_a_declared_language_overrules_the_document_and_the_disagreement_is_recorded(
    tmp_path,
) -> None:
    """The declared value wins because the operator knows which PDF they extracted — but a silent
    overrule is how a wrong Expression IRI becomes permanent, so the conflict goes on the record."""
    store = FileStore(tmp_path)
    seed_document(store, markdown=ARRANGEMENT_EN + MARKDOWN, language="ms")

    result = convert_to_akn(store, extractor=BodyOnlyExtractor())

    assert result.counts["converted"] == 1
    verdict = store.load_akn_gate(bill_slug="dr-15-2026", doc_key=DOC_KEY, version=1)
    assert verdict["language"] == "ms"
    assert verdict["language_disagreement"] == "declared 'ms', document reads 'en'"
    assert "/msa@" in (version_dir(tmp_path) / "document.akn.xml").read_text()


def test_a_document_that_declares_no_language_anywhere_fails_instead_of_being_guessed(
    tmp_path,
) -> None:
    """Failing one document loudly is much cheaper than publishing a citable identifier that
    asserts a language nobody established."""
    store = FileStore(tmp_path)
    seed_document(store, language=None)  # no Arrangement heading either

    result = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())

    assert result.counts == {"eligible": 1, "converted": 0, "rejected": 0, "failed": 1}
    assert "no language on the record" in result.failures[0].reason
    assert not (version_dir(tmp_path) / "document.akn.xml").exists()
    verdict = store.load_akn_gate(bill_slug="dr-15-2026", doc_key=DOC_KEY, version=1)
    assert verdict["status"] == "failed"
    assert "FrbrIdentityError" in verdict["error"]


def test_a_bill_that_does_not_identify_itself_fails_rather_than_minting_a_placeholder_iri(
    tmp_path,
) -> None:
    store = FileStore(tmp_path)
    seed_document(store)
    store.save_bill("dr-15-2026", {"identifier": {"slug": "dr-15-2026", "year": 2026}})

    result = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())

    assert result.counts == {"eligible": 1, "converted": 0, "rejected": 0, "failed": 1}
    assert "FrbrIdentityError" in result.failures[0].reason
    assert not (version_dir(tmp_path) / "document.akn.xml").exists()


def test_a_document_with_no_markdown_is_not_eligible(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_document(store, markdown=None)

    result = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())

    assert result.counts == {"eligible": 0, "converted": 0, "rejected": 0, "failed": 0}
    assert not (version_dir(tmp_path) / "document.akn.xml").exists()
    assert not (version_dir(tmp_path) / "document.akn.gate.json").exists()


def test_a_document_already_converted_is_not_reprocessed_and_nothing_is_rewritten(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_document(store)

    first = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())
    assert first.counts["converted"] == 1
    before = {
        path.name: path.stat().st_mtime_ns for path in sorted(version_dir(tmp_path).iterdir())
    }

    second = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())

    assert second.counts == {"eligible": 0, "converted": 0, "rejected": 0, "failed": 0}
    after = {path.name: path.stat().st_mtime_ns for path in sorted(version_dir(tmp_path).iterdir())}
    assert after == before


def test_changing_the_markdown_makes_a_converted_document_eligible_again(tmp_path) -> None:
    """An existence check can never notice this: `document.akn.xml` is still there, and it now
    describes a document that no longer exists."""
    store = FileStore(tmp_path)
    seed_document(store)
    convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())
    first_xml = (version_dir(tmp_path) / "document.akn.xml").read_bytes()

    revised = MARKDOWN + "\n5. Pembatalan.\n\nAkta Contoh 1999 dibatalkan.\n"
    seed_document(store, markdown=revised)

    second = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())

    assert second.counts == {"eligible": 1, "converted": 1, "rejected": 0, "failed": 0}
    assert (version_dir(tmp_path) / "document.akn.xml").read_bytes() != first_xml
    recorded = store.load_provenance(
        bill_slug="dr-15-2026", doc_key=DOC_KEY, version=1, artifact="akn"
    )
    assert recorded["inputs"]["source_files"] == [
        {"file": "document.md", "sha256": sha256_of(revised)}
    ]


def test_correcting_the_bill_record_makes_a_converted_document_eligible_again(tmp_path) -> None:
    """`bill.json` is a real input to this render, so a later crawl correcting it has to regenerate.

    `render_akn` takes the FRBR identity, the `FRBRdate` and the `<longTitle>` from it. It is
    recorded as a digest rather than in `source_files` because that list is what `pipeline verify`
    re-hashes inside the document's own directory, and `bill.json` does not live there — naming it
    would make a correct store report itself as damaged.
    """
    store = FileStore(tmp_path)
    seed_document(store)
    first = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())
    assert first.counts["converted"] == 1
    keys = {"bill_slug": "dr-15-2026", "doc_key": DOC_KEY, "version": 1}
    recorded = store.load_provenance(**keys, artifact="akn")
    assert recorded["inputs"]["source_files"] == [
        {"file": "document.md", "sha256": sha256_of(MARKDOWN)}
    ]
    assert recorded["inputs"]["bill_sha256"]
    assert recorded["inputs"]["markdown_provenance_sha256"]

    bill = store.load_bill("dr-15-2026")
    bill["titles"]["raw_ms"] = "RUU Pelaporan Kewangan 2026 (dibetulkan)"
    store.save_bill("dr-15-2026", bill)

    second = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())

    assert second.counts == {"eligible": 1, "converted": 1, "rejected": 0, "failed": 0}
    xml_text = (version_dir(tmp_path) / "document.akn.xml").read_text()
    assert "RUU Pelaporan Kewangan 2026 (dibetulkan)" in xml_text
    rebuilt = store.load_provenance(**keys, artifact="akn")
    assert rebuilt["inputs"]["bill_sha256"] != recorded["inputs"]["bill_sha256"]
    assert rebuilt["inputs"]["source_files"] == recorded["inputs"]["source_files"]


def test_correcting_the_declared_language_makes_the_document_eligible_again(tmp_path) -> None:
    """The declared language is read out of the markdown's provenance record and becomes a permanent
    component of the Expression IRI, so a corrected language that did not regenerate would leave the
    document published at an IRI asserting the wrong one."""
    store = FileStore(tmp_path)
    seed_document(store, language="ms")
    first = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())
    assert first.counts["converted"] == 1
    assert "/msa@" in (version_dir(tmp_path) / "document.akn.xml").read_text()

    seed_document(store, language="en")  # the operator re-declares what they extracted

    second = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())

    assert second.counts == {"eligible": 1, "converted": 1, "rejected": 0, "failed": 0}
    assert "/eng@" in (version_dir(tmp_path) / "document.akn.xml").read_text()


def test_changing_the_extractor_identity_makes_a_converted_document_eligible_again(
    tmp_path,
) -> None:
    """A prompt improvement or a model swap must not leave every existing artifact looking current.
    The bytes here are identical; only the record of what produced them changed, and that is enough
    — otherwise the corpus silently mixes readings with no way to tell which is which."""
    store = FileStore(tmp_path)
    seed_document(store)
    convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())
    first_xml = (version_dir(tmp_path) / "document.akn.xml").read_bytes()

    second = convert_to_akn(store, extractor=RelabelledExtractor())

    assert second.counts == {"eligible": 1, "converted": 1, "rejected": 0, "failed": 0}
    assert (version_dir(tmp_path) / "document.akn.xml").read_bytes() == first_xml
    recorded = store.load_provenance(
        bill_slug="dr-15-2026", doc_key=DOC_KEY, version=1, artifact="akn"
    )
    assert recorded["inputs"]["producer"] == "vllm"
    assert recorded["inputs"]["model_id"] == "test-model"
    assert recorded["inputs"]["prompt_sha256"] == "f" * 64


def test_an_extractor_failure_is_counted_and_named_not_raised(tmp_path) -> None:
    class FailingExtractor:
        name = "stub-llm"
        model_id = "test-model"
        prompt_sha256 = None

        def extract(self, markdown_text: str, *, unit: str) -> Node:
            raise RuntimeError("endpoint unreachable")

    store = FileStore(tmp_path)
    seed_document(store)

    result = convert_to_akn(store, extractor=FailingExtractor())

    assert result.counts == {"eligible": 1, "converted": 0, "rejected": 0, "failed": 1}
    failure = result.failures[0]
    assert (failure.bill_slug, failure.doc_key, failure.version) == ("dr-15-2026", DOC_KEY, 1)
    assert failure.reason == "RuntimeError: endpoint unreachable"
    assert not (version_dir(tmp_path) / "document.akn.xml").exists()
    assert store.load_akn_gate(bill_slug="dr-15-2026", doc_key=DOC_KEY, version=1)["status"] == (
        "failed"
    )


def test_a_reading_that_cannot_account_for_its_source_is_kept_as_evidence_and_never_promoted(
    tmp_path,
) -> None:
    """The regex extractor cannot tell a table-of-contents line from the body provision it lists,
    so it reads the Arrangement's entries as real clauses and the document's numbering runs
    1..4 then 1 again. Gate P1 exists to catch exactly that before it is published."""
    store = FileStore(tmp_path)
    seed_document(store, markdown=ARRANGEMENT_MS + MARKDOWN)

    result = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())

    assert result.counts == {"eligible": 1, "converted": 0, "rejected": 1, "failed": 0}
    assert "gate P1 mismatch: sequence_order" in result.failures[0].reason

    directory = version_dir(tmp_path)
    assert (directory / "document.akn.gate.json").exists()
    assert (directory / "document.akn.rejected.xml").exists()
    assert not (directory / "document.akn.xml").exists()

    verdict = store.load_akn_gate(bill_slug="dr-15-2026", doc_key=DOC_KEY, version=1)
    assert verdict["status"] == "mismatch"
    assert [finding["kind"] for finding in verdict["findings"]] == ["sequence_order"]

    # `has_akn` is the promotion flag every later step reads, so step 5 must find nothing.
    assert generate_semantic_files(store, base_iri=BASE_IRI).counts == {
        "eligible": 0,
        "converted": 0,
        "failed": 0,
    }
    assert not (directory / "document.jsonld").exists()


def test_a_re_read_that_fails_the_gate_withdraws_the_reading_that_was_already_published(
    tmp_path,
) -> None:
    """The served document and the verdict printed beside it have to describe the same render.

    A failing re-read used to leave the *previous* reading promoted with a `mismatch` verdict beside
    it, so a reader was told a reading had been checked while being shown a different one. The
    published Expression is withdrawn instead — the same rule as first conversion, where the gate
    decides whether the file exists — and the rejected render and the verdict stay as evidence.
    """
    store = FileStore(tmp_path)
    seed_document(store)
    first = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())
    assert first.counts["converted"] == 1
    directory = version_dir(tmp_path)
    assert (directory / "document.akn.xml").exists()
    keys = {"bill_slug": "dr-15-2026", "doc_key": DOC_KEY, "version": 1}
    assert store.load_akn_gate(**keys)["status"] == "passed"

    # The markdown is re-imported with its Arrangement of Clauses this time, which the regex reader
    # cannot tell from the body: the document now numbers 1..4 and then starts over.
    seed_document(store, markdown=ARRANGEMENT_MS + MARKDOWN)
    second = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())

    assert second.counts == {"eligible": 1, "converted": 0, "rejected": 1, "failed": 0}
    assert not (directory / "document.akn.xml").exists()
    assert not store.has_akn(**keys)
    # The provenance goes with the bytes it describes, or the artifact reads as current.
    assert not (directory / "document.akn.provenance.json").exists()
    # The evidence stays: the verdict that withdrew it, and the render it judged.
    assert store.load_akn_gate(**keys)["status"] == "mismatch"
    assert (directory / "document.akn.rejected.xml").exists()
    assert list(store.iter_unexpected_files()) == []


def test_a_withdrawn_reading_leaves_no_orphaned_graph_to_accuse_the_store_of_damage(
    tmp_path,
) -> None:
    """A correct pipeline run must not end with the store reporting itself damaged.

    The semantic pair is derived from the withdrawn XML and its provenance names that XML as its
    source, so leaving it behind made `pipeline verify` report `missing from the store:
    .../document.akn.xml` after a run in which every step did exactly the right thing. The
    withdrawal takes the derived pair with it, which is also the only state in which the corpus does
    not hold a graph describing an unpublished reading.
    """
    store = FileStore(tmp_path)
    seed_document(store)
    assert convert_to_akn(store, extractor=RegexMarkdownStructureExtractor()).counts["converted"]
    assert generate_semantic_files(store, base_iri=BASE_IRI).counts["converted"] == 1
    keys = {"bill_slug": "dr-15-2026", "doc_key": DOC_KEY, "version": 1}
    assert store.has_semantic(**keys)

    seed_document(store, markdown=ARRANGEMENT_MS + MARKDOWN)
    assert (
        convert_to_akn(store, extractor=RegexMarkdownStructureExtractor()).counts["rejected"] == 1
    )

    assert not store.has_semantic(**keys)
    assert store.load_provenance(**keys, artifact="semantic") is None
    # This fixture's sidecar carries no digest, so verify is not silent overall — it has to be
    # silent about the *withdrawn* artifacts specifically, which is what the orphan broke.
    issues = verify_store(store)
    assert not [issue for issue in issues if "document.akn.xml" in issue]
    assert not [issue for issue in issues if "document.nq" in issue]
    assert not [issue for issue in issues if "document.jsonld" in issue]


def test_a_re_read_that_raises_also_withdraws_the_reading_that_was_already_published(
    tmp_path,
) -> None:
    """An extractor that starts failing is the same problem as a gate rejection: whatever is served
    afterwards must not be described by a verdict belonging to a different render."""

    class FailingExtractor(RegexMarkdownStructureExtractor):
        name = "stub-llm"

        def extract(self, markdown_text: str, *, unit: str) -> Node:
            raise RuntimeError("endpoint unreachable")

    store = FileStore(tmp_path)
    seed_document(store)
    first = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())
    assert first.counts["converted"] == 1

    result = convert_to_akn(store, extractor=FailingExtractor())

    assert result.counts == {"eligible": 1, "converted": 0, "rejected": 0, "failed": 1}
    directory = version_dir(tmp_path)
    assert not (directory / "document.akn.xml").exists()
    assert not (directory / "document.akn.provenance.json").exists()
    verdict = store.load_akn_gate(bill_slug="dr-15-2026", doc_key=DOC_KEY, version=1)
    assert verdict["status"] == "failed"
    assert "endpoint unreachable" in verdict["error"]


def test_the_work_iri_comes_from_the_bills_identifier_not_from_the_document_it_was_read_from(
    tmp_path,
) -> None:
    """Two documents of one bill — the Malay and English readings — are one Work. The previous
    scheme keyed the IRI off each document's own URL hash, so they were two unrelated Works."""
    store = FileStore(tmp_path)
    seed_document(store, doc_key="doc-malay01", language="ms")
    seed_document(store, doc_key="doc-english1", language="en")

    result = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())

    assert result.counts["converted"] == 2
    malay = (version_dir(tmp_path, doc_key="doc-malay01") / "document.akn.xml").read_text()
    english = (version_dir(tmp_path, doc_key="doc-english1") / "document.akn.xml").read_text()
    assert '<FRBRuri value="/akn/my/bill/dr/2026/15"' in malay
    assert '<FRBRuri value="/akn/my/bill/dr/2026/15"' in english
    assert '<FRBRthis value="/akn/my/bill/dr/2026/15/msa@"' in malay
    assert '<FRBRthis value="/akn/my/bill/dr/2026/15/eng@"' in english
    assert "doc-malay01" not in malay and "doc-english1" not in english


def test_a_dewan_negara_bill_keeps_its_own_chamber_in_the_work_iri(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed_document(store, bill_slug="dn-3-2026", chamber="dewan_negara", number=3)

    result = convert_to_akn(store, extractor=RegexMarkdownStructureExtractor())
    assert result.counts["converted"] == 1
    xml_text = (version_dir(tmp_path, bill_slug="dn-3-2026") / "document.akn.xml").read_text()
    assert '<FRBRuri value="/akn/my/bill/dn/2026/3"' in xml_text
    assert '<FRBRsubtype value="dn"' in xml_text
