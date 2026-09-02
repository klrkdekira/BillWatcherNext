"""Offline acceptance tests for the public static-cache boundary (HANDOFF 28.12)."""

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from billwatcher.cli import app
from billwatcher.config import get_settings
from billwatcher.frbr import identity_from_bill
from billwatcher.graph.render import render_akn
from billwatcher.graph.semantic import (
    build_graph,
    parse_akn,
    render_jsonld,
    render_nquads,
)
from billwatcher.graph.structure import assign_eids, parse_markdown_structure
from billwatcher.publish.dataset import (
    StaticExportRefused,
    _refuse_source_bytes,
    publish_dataset,
    require_publication_rights,
)
from billwatcher.publish.redact import contains_provision_text
from billwatcher.store import FileStore

MARKDOWN = """\
1. Tajuk ringkas

Akta ini bolehlah dinamakan Akta Contoh 2026.

2. Kewajipan untuk melaporkan

Seseorang hendaklah melaporkan kepada Pesuruhjaya dalam tempoh empat belas hari.
"""


def bill(number: int = 15) -> dict:
    return {
        "identifier": {
            "slug": f"dr-{number}-2026",
            "normalized": f"DR-{number}-2026",
            "originating_chamber": "dewan_rakyat",
            "year": 2026,
            "number": number,
        },
        "titles": {"raw_ms": f"Rang Undang-Undang Contoh {number}"},
    }


def representations(record: dict) -> tuple[bytes, bytes, bytes]:
    tree = parse_markdown_structure(MARKDOWN, unit="clause")
    assign_eids(tree)
    identity = identity_from_bill(record, doc_type="bill")
    xml = render_akn(tree, identity=identity, language="ms", bill=record)
    parsed, expression_uri, doc_type, language = parse_akn(xml)
    dataset, document_iri = build_graph(
        parsed,
        base_iri="https://bills.example",
        expression_uri=expression_uri,
        doc_type=doc_type,
        language=language,
        bill=record,
        identity=identity,
    )
    return xml, render_jsonld(dataset, document_iri), render_nquads(dataset)


def seed(
    store: FileStore,
    *,
    record: dict,
    doc_key: str,
    gate_status: str = "passed",
    promote: bool = True,
    chamber: str = "dewan_rakyat",
) -> None:
    slug = record["identifier"]["slug"]
    keys = {"bill_slug": slug, "doc_key": doc_key, "version": 1}
    store.save_bill(slug, record)
    store.save_document(
        **keys,
        content=b"%PDF-1.4 fixture",
        metadata={"chamber": chamber, "source_url": f"https://example/{doc_key}.pdf"},
    )
    xml, jsonld, nquads = representations(bill(record["identifier"]["number"]))
    store.save_structure_gate(**keys, record={"gate": "P1", "status": gate_status})
    if promote:
        store.save_akn(**keys, content=xml)
        store.save_jsonld(**keys, content=jsonld)
        store.save_rdf(**keys, content=nquads)
    else:
        store.save_rejected_akn(**keys, content=xml)


def exported_files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def test_only_the_gate_passing_document_is_exported(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    seed(store, record=bill(16), doc_key="doc-rejected", gate_status="mismatch", promote=False)
    root = tmp_path / "cache"

    result = publish_dataset(store, site_root=root, publication_mode="full", representations="all")

    assert result.counts["exported"] == 1
    assert result.counts["skipped_rejected"] == 1
    assert {
        "akn/my/bill/dr/2026/15/msa@.xml",
        "akn/my/bill/dr/2026/15/msa@.jsonld",
        "akn/my/bill/dr/2026/15/msa@.nq",
    } <= exported_files(root)
    assert not (root / "akn/my/bill/dr/2026/16").exists()
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    # The rejected bill publishes no files, but it does not vanish: it is a catalogue entry with
    # no expressions and a `missing` reason, so its absence is visible rather than silent.
    assert [work["uri"] for work in index["works"]] == [
        "/akn/my/bill/dr/2026/15",
        "/akn/my/bill/dr/2026/16",
    ]
    assert index["works"][1]["missing"]["reason"] == "reading"
    assert index["works"][1]["expressions"] == []
    assert index["works"][0]["expressions"][0]["files"] == [
        "akn/my/bill/dr/2026/15/msa@.xml",
        "akn/my/bill/dr/2026/15/msa@.jsonld",
        "akn/my/bill/dr/2026/15/msa@.nq",
    ]


def test_metadata_export_contains_no_provision_text_by_the_independent_reader(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(), doc_key="doc-passing")
    root = tmp_path / "cache"

    publish_dataset(store, site_root=root, publication_mode="metadata", representations="all")

    expression = root / "akn/my/bill/dr/2026/15"
    for extension in ("xml", "jsonld", "nq"):
        payload = (expression / f"msa@.{extension}").read_bytes()
        assert contains_provision_text(payload) is False
        assert b"Seseorang hendaklah melaporkan" not in payload


def test_every_exported_payload_is_named_in_the_checksum_manifest_and_verifies(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(), doc_key="doc-passing")
    root = tmp_path / "cache"
    publish_dataset(store, site_root=root, publication_mode="full")

    entries = {}
    for line in (root / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        entries[relative] = digest

    # The checksum file cannot include its own stable digest; every other exported file does.
    assert set(entries) == exported_files(root) - {"checksums.sha256"}
    for relative, expected in entries.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected
    assert "Copyright (c) OASIS Open 2018" in (root / "definitions/akomantoso30.xsd").read_text(
        encoding="utf-8"
    )
    assert json.loads((root / "definitions/jsonld-context.jsonld").read_text())["@context"]
    assert json.loads((root / "definitions/structural-vocabulary.json").read_text())["node_types"]


def test_reexport_of_an_unchanged_store_changes_neither_hash_nor_mtime(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(), doc_key="doc-passing")
    root = tmp_path / "cache"
    first = publish_dataset(store, site_root=root, publication_mode="metadata")
    before = {
        path.relative_to(root).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        for path in root.rglob("*")
        if path.is_file()
    }

    second = publish_dataset(store, site_root=root, publication_mode="metadata")
    after = {
        path.relative_to(root).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        for path in root.rglob("*")
        if path.is_file()
    }

    assert first.counts["written"] == len(before)
    assert second.counts["written"] == 0
    assert second.counts["removed"] == 0
    assert after == before


def test_same_expression_records_prefer_the_originating_chamber_deterministically(tmp_path) -> None:
    """The real store links many bills through both chambers, but FRBR gives them one path.

    Traversal order must not decide which promoted reading survives that many-to-one projection.
    """
    store = FileStore(tmp_path / "store")
    record = bill()
    seed(store, record=record, doc_key="doc-originating")
    seed(
        store,
        record=record,
        doc_key="doc-later-chamber",
        chamber="dewan_negara",
    )
    later_keys = {"bill_slug": "dr-15-2026", "doc_key": "doc-later-chamber", "version": 1}
    later_xml = store.load_akn(**later_keys)
    assert later_xml is not None
    store.save_akn(
        **later_keys,
        content=later_xml.replace(b"empat belas hari", b"tiga puluh hari"),
    )
    originating = store.load_akn(bill_slug="dr-15-2026", doc_key="doc-originating", version=1)

    result = publish_dataset(
        store, site_root=tmp_path / "cache", publication_mode="full", representations="all"
    )

    assert result.counts["exported"] == 1
    assert result.counts["skipped_duplicate_expression"] == 1
    assert result.counts["conflicting_expressions"] == 1
    assert (tmp_path / "cache/akn/my/bill/dr/2026/15/msa@.xml").read_bytes() == originating


def test_a_bill_that_cannot_mint_an_identity_is_absent_not_placeholdered(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    invalid = bill()
    del invalid["identifier"]["originating_chamber"]
    seed(store, record=invalid, doc_key="doc-unidentified")
    root = tmp_path / "cache"

    result = publish_dataset(store, site_root=root, publication_mode="full")

    assert result.counts["exported"] == 0
    assert result.counts["skipped_no_identity"] == 1
    assert not (root / "akn").exists()
    assert "unknown" not in "\n".join(exported_files(root))
    assert json.loads((root / "index.json").read_text())["works"] == []


def test_publish_command_refuses_without_the_publication_rights_confirmation(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("SITE_ROOT", str(tmp_path / "site"))
    monkeypatch.setenv("SITE_REPRESENTATIONS", "jsonld")
    get_settings.cache_clear()

    result = CliRunner().invoke(app, ["publish"])

    assert result.exit_code == 2
    assert "PUBLISH_RIGHTS_CONFIRMED=true" in result.stderr
    assert not (tmp_path / "site").exists()


def test_publish_command_refuses_full_text_without_its_own_confirmation(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("SITE_ROOT", str(tmp_path / "site"))
    monkeypatch.setenv("PUBLISH_RIGHTS_CONFIRMED", "true")
    monkeypatch.setenv("PUBLICATION_MODE", "full")
    get_settings.cache_clear()

    result = CliRunner().invoke(app, ["publish"])

    assert result.exit_code == 2
    assert "FULL_TEXT_RIGHTS_CONFIRMED=true" in result.stderr
    assert not (tmp_path / "site").exists()


def test_publishing_markdown_needs_the_full_text_confirmation_even_in_metadata_mode(
    tmp_path, monkeypatch
) -> None:
    """Markdown *is* the prose. Metadata mode already refuses it (ADR-036), but the refusal that
    matters is the one an operator hits after switching to full mode without the second
    confirmation, since that is the configuration that would otherwise publish the text."""
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("SITE_ROOT", str(tmp_path / "site"))
    monkeypatch.setenv("PUBLISH_RIGHTS_CONFIRMED", "true")
    monkeypatch.setenv("SITE_REPRESENTATIONS", "markdown-semantic")
    get_settings.cache_clear()

    result = CliRunner().invoke(app, ["publish"])

    assert result.exit_code == 2
    assert "PUBLICATION_MODE=metadata cannot publish ['md']" in result.stderr
    assert not (tmp_path / "site").exists()


def test_the_published_tree_names_the_domain_it_is_hosted_on(tmp_path) -> None:
    """`CNAME` is how Pages learns the custom domain, and the domain is also the authority for
    every published FRBR IRI — so it comes from one setting, written by this step."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "site"

    result = publish_dataset(
        store,
        site_root=root,
        publication_mode="full",
        prefix="bills.engineers.my",
    )

    assert (root / "CNAME").read_text(encoding="utf-8") == "bills.engineers.my\n"
    assert "CNAME" in dict(
        line.split("  ", 1)[::-1]
        for line in (root / "checksums.sha256").read_text().strip().splitlines()
    ), "a mirror must be able to verify every file the build publishes, CNAME included"
    assert result.counts["written"] >= 1


def test_a_reexport_does_not_disturb_files_the_export_root_did_not_come_from(tmp_path) -> None:
    """ADR-029 leaves hosting open; two of its options put foreign files in the export root.

    Committing the cache to its own repository, or syncing it into a static host's document root,
    means `.git/`, `CNAME`, `.nojekyll` and a hand-written `README.md` sit beside the export. The
    step owns `akn/`, `definitions/`, `index.json` and `checksums.sha256` — and nothing else.
    """
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "cache"
    publish_dataset(store, site_root=root, publication_mode="full")

    foreign = {
        ".git/config": b"[core]\n",
        ".git/HEAD": b"ref: refs/heads/main\n",
        "CNAME": b"corpus.example.my\n",
        ".nojekyll": b"",
        "README.md": b"# Hand-written, not ours\n",
        "assets/logo.svg": b"<svg/>",
    }
    for relative, payload in foreign.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    result = publish_dataset(store, site_root=root, publication_mode="full")

    assert result.counts["removed"] == 0
    assert result.counts["written"] == 0
    for relative, payload in foreign.items():
        assert (root / relative).read_bytes() == payload, relative
    assert (root / "assets").is_dir()


def test_a_reexport_expunges_a_reading_that_stopped_passing_the_gate_when_asked(tmp_path) -> None:
    """The withdrawal property, now an explicit action: a cache must not publish a rejected reading
    forever, but a build must not delete on its own either (ADR-038). `--prune` is that decision."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "cache"
    publish_dataset(store, site_root=root, publication_mode="full", representations="all")
    assert (root / "akn/my/bill/dr/2026/15/msa@.xml").exists()

    stale = root / "akn/my/bill/dr/2026/99/msa@.xml"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"<akomaNtoso/>")
    (root / "definitions/leftover.json").write_bytes(b"{}")

    result = publish_dataset(
        store, site_root=root, publication_mode="full", representations="all", prune=True
    )

    assert result.counts["removed"] == 2
    assert not stale.exists()
    assert not (root / "definitions/leftover.json").exists()
    assert not (root / "akn/my/bill/dr/2026/99").exists()
    assert (root / "akn/my/bill/dr/2026/15/msa@.xml").exists()


def test_the_default_release_publishes_json_ld_only(tmp_path) -> None:
    """ "Prioritise the jsonld for now" (ADR-032): JSON-LD is the published representation.

    The Akoma Ntoso XML and the N-Quads are still generated and still kept in the store; they are
    simply not part of this release, and `index.json` says so rather than leaving a consumer to
    discover it by probing paths.
    """
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "cache"

    result = publish_dataset(store, site_root=root, publication_mode="full")

    assert result.counts["exported"] == 1
    expression = root / "akn/my/bill/dr/2026/15"
    assert (expression / "msa@.jsonld").exists()
    assert not (expression / "msa@.xml").exists()
    assert not (expression / "msa@.nq").exists()
    assert not any(path.suffix in {".xml", ".nq"} for path in (root / "akn").rglob("*"))

    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    assert index["representations"] == ["jsonld"]
    assert index["works"][0]["expressions"][0]["files"] == ["akn/my/bill/dr/2026/15/msa@.jsonld"]
    # The JSON-LD context is a definition, so a JSON-LD-only release is still self-describing.
    assert (root / "definitions/jsonld-context.jsonld").exists()


def test_widening_to_all_representations_adds_them_without_disturbing_the_json_ld(tmp_path) -> None:
    """Widening is one recorded value change, and it is additive over an existing release."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "cache"
    publish_dataset(store, site_root=root, publication_mode="full")
    jsonld = root / "akn/my/bill/dr/2026/15/msa@.jsonld"
    before = jsonld.read_bytes()

    result = publish_dataset(store, site_root=root, publication_mode="full", representations="all")

    assert result.counts["removed"] == 0
    assert jsonld.read_bytes() == before
    for extension in ("xml", "jsonld", "nq"):
        assert (root / f"akn/my/bill/dr/2026/15/msa@.{extension}").exists()
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    assert index["representations"] == ["md", "xml", "jsonld", "nq"]
    # `representations` is what the *release* is configured to carry; what each Expression actually
    # has is its own `files` list. This document has no markdown reading, so no .md is written and
    # none is claimed — a text-only Expression and a fully converted one coexist (ADR-036).
    assert not (root / "akn/my/bill/dr/2026/15/msa@.md").exists()
    (expression,) = index["works"][0]["expressions"]
    assert not any(name.endswith(".md") for name in expression["files"])
    assert "reading" not in expression


def test_narrowing_back_to_json_ld_expunges_the_other_representations(tmp_path) -> None:
    """The reverse is reconciliation, not an orphaned tree: a narrowed release removes what it no
    longer publishes, so `checksums.sha256` and the tree cannot disagree."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "cache"
    publish_dataset(store, site_root=root, publication_mode="full", representations="all")

    result = publish_dataset(store, site_root=root, publication_mode="full", prune=True)

    assert result.counts["removed"] == 2
    assert (root / "akn/my/bill/dr/2026/15/msa@.jsonld").exists()
    assert not (root / "akn/my/bill/dr/2026/15/msa@.xml").exists()
    assert not (root / "akn/my/bill/dr/2026/15/msa@.nq").exists()
    manifest = (root / "checksums.sha256").read_text(encoding="utf-8")
    assert ".xml" not in manifest and ".nq" not in manifest.replace(".nquads", "")


def test_no_export_ever_carries_the_source_pdf(tmp_path) -> None:
    """The dataset carries readings of bills, never the official PDF (ADR-029 decision 5).

    Republishing the stored bytes is a different rights question from A14's, and the store keeps
    the PDF privately. Asserted end to end, and on the guard directly, because a regression here
    would be a permanent publication rather than a failing build.
    """
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "cache"

    publish_dataset(store, site_root=root, publication_mode="full", representations="all")

    for path in root.rglob("*"):
        if path.is_file():
            assert path.suffix.lower() != ".pdf"
            assert not path.read_bytes().startswith(b"%PDF-")

    with pytest.raises(StaticExportRefused, match="never the source PDF"):
        _refuse_source_bytes({"akn/my/bill/dr/2026/15/msa@.jsonld": b"%PDF-1.4 smuggled"})
    with pytest.raises(StaticExportRefused, match="never the source PDF"):
        _refuse_source_bytes({"akn/my/bill/dr/2026/15/document.pdf": b"not-really-a-pdf"})


# --- ADR-036: the markdown milestone publishes on its own ---


def seed_reading(
    store: FileStore, *, record: dict, doc_key: str, markdown: str, language: str = "ms"
) -> dict:
    """A document with a markdown reading and its provenance, and nothing else derived from it."""
    slug = record["identifier"]["slug"]
    keys = {"bill_slug": slug, "doc_key": doc_key, "version": 1}
    store.save_bill(slug, record)
    store.save_document(
        **keys,
        content=b"%PDF-1.4 fixture",
        metadata={"chamber": "dewan_rakyat", "source_url": f"https://example/{doc_key}.pdf"},
    )
    store.save_markdown(**keys, content=markdown)
    store.save_provenance(
        **keys,
        artifact="markdown",
        record={"inputs": {"language": language, "tool": "pdfminer-layout"}},
    )
    return keys


def test_a_reading_publishes_with_no_akoma_ntoso_behind_it(tmp_path) -> None:
    """The milestone claim. Before ADR-036 a document reached the dataset only once it had a
    gate-passing graph, so the markdown tier could not be published at all — which made the
    corpus publishable only at the speed of its slowest stage."""
    store = FileStore(tmp_path / "store")
    seed_reading(store, record=bill(15), doc_key="doc-read", markdown="## Tajuk\n\n1. Contoh.")
    root = tmp_path / "cache"

    result = publish_dataset(
        store, site_root=root, publication_mode="full", representations="markdown"
    )

    assert result.counts["exported"] == 1
    assert result.counts["markdown_only"] == 1
    published = root / "akn/my/bill/dr/2026/15/msa@.md"
    assert published.read_text(encoding="utf-8") == "## Tajuk\n\n1. Contoh."
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    (expression,) = index["works"][0]["expressions"]
    assert expression["uri"] == "/akn/my/bill/dr/2026/15/msa@"
    assert expression["files"] == ["akn/my/bill/dr/2026/15/msa@.md"]


def test_the_identity_comes_from_the_declared_language_not_from_the_text(tmp_path) -> None:
    """With no Akoma Ntoso to read an Expression out of, the language must come from what the
    reading was declared to be: that value is already part of the IRI, so taking it from anywhere
    else could mint a second IRI for one document."""
    store = FileStore(tmp_path / "store")
    seed_reading(
        store, record=bill(15), doc_key="doc-read", markdown="1. An English reading.", language="en"
    )
    root = tmp_path / "cache"

    publish_dataset(store, site_root=root, publication_mode="full", representations="markdown")

    assert (root / "akn/my/bill/dr/2026/15/eng@.md").exists()
    assert not (root / "akn/my/bill/dr/2026/15/msa@.md").exists()


def test_a_reading_with_no_declared_language_has_no_expression(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    keys = seed_reading(store, record=bill(15), doc_key="doc-read", markdown="1. Contoh.")
    store.save_provenance(**keys, artifact="markdown", record={"inputs": {"tool": "x"}})
    root = tmp_path / "cache"

    result = publish_dataset(
        store, site_root=root, publication_mode="full", representations="markdown"
    )

    assert result.counts["skipped_no_identity"] == 1
    assert result.counts["exported"] == 0
    assert "no declared language" in result.failures[0].reason


def test_a_gate_rejected_document_still_publishes_its_reading(tmp_path) -> None:
    """Failing Gate P1 withholds the *graph*, which is what the gate judges. It no longer withholds
    the reading as well — the reading is a resource in its own right (ADR-036)."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-rejected", gate_status="mismatch", promote=False)
    store.save_markdown(
        bill_slug="dr-15-2026", doc_key="doc-rejected", version=1, content="1. Contoh."
    )
    store.save_provenance(
        bill_slug="dr-15-2026",
        doc_key="doc-rejected",
        version=1,
        artifact="markdown",
        record={"inputs": {"language": "ms"}},
    )
    root = tmp_path / "cache"

    semantic = publish_dataset(store, site_root=root, publication_mode="full")
    assert semantic.counts["exported"] == 0
    assert semantic.counts["skipped_rejected"] == 1

    text = publish_dataset(
        store, site_root=root, publication_mode="full", representations="markdown"
    )
    assert text.counts["exported"] == 1
    assert (root / "akn/my/bill/dr/2026/15/msa@.md").exists()


def test_a_suspect_reading_is_published_and_labelled_rather_than_withheld(tmp_path) -> None:
    """Withholding the ~270 suspect readings would make the release silently 78% of the corpus
    while looking complete, which is the failure ADR-031 exists to prevent. It is labelled."""
    store = FileStore(tmp_path / "store")
    # Big enough to clear SUSPECT_MIN_BLOCKS: the flag refuses to read a ratio over a handful of
    # blocks, and a genuinely heading-inflated reading is a large one misread wholesale.
    mostly_headings = "\n\n".join(
        [f"## heading {n}" for n in range(30)] + [f"{n}. body" for n in range(1, 11)]
    )
    seed_reading(store, record=bill(15), doc_key="doc-read", markdown=mostly_headings)
    root = tmp_path / "cache"

    result = publish_dataset(
        store, site_root=root, publication_mode="full", representations="markdown"
    )

    assert result.counts["exported"] == 1
    assert result.counts["suspect_readings"] == 1
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    (expression,) = index["works"][0]["expressions"]
    assert expression["reading"]["suspect"] is True
    assert expression["reading"]["extractor"] == "pdfminer-layout"
    assert expression["reading"]["heading_ratio"] >= 0.5


def test_both_milestones_share_one_expression_identity(tmp_path) -> None:
    """One layered site: the text and the graph of one document sit at one identity, differing only
    in extension — the "reserved extensions on the same identifier" mechanism ADR-032 described."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    store.save_markdown(
        bill_slug="dr-15-2026", doc_key="doc-passing", version=1, content="1. Contoh."
    )
    store.save_provenance(
        bill_slug="dr-15-2026",
        doc_key="doc-passing",
        version=1,
        artifact="markdown",
        record={"inputs": {"language": "ms"}},
    )
    root = tmp_path / "cache"

    result = publish_dataset(
        store, site_root=root, publication_mode="full", representations="markdown-semantic"
    )

    assert result.counts["exported"] == 1
    assert result.counts["markdown_only"] == 0  # it has both tiers
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    (expression,) = index["works"][0]["expressions"]
    assert expression["files"] == [
        "akn/my/bill/dr/2026/15/msa@.md",
        "akn/my/bill/dr/2026/15/msa@.jsonld",
        "akn/my/bill/dr/2026/15/msa@.nq",
    ]


def test_metadata_mode_refuses_to_publish_prose_representations(tmp_path, monkeypatch) -> None:
    """There is no redacted markdown: strip the provision text and only headings remain. Silently
    publishing that would ship an empty text dataset under a name promising the corpus."""
    monkeypatch.setenv("CORPUS_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("PUBLISH_RIGHTS_CONFIRMED", "true")
    monkeypatch.setenv("PUBLICATION_MODE", "metadata")
    monkeypatch.setenv("SITE_REPRESENTATIONS", "markdown")
    get_settings.cache_clear()

    with pytest.raises(StaticExportRefused) as refusal:
        require_publication_rights(get_settings())

    assert "cannot publish ['md']" in str(refusal.value)
    assert "no redacted form" in str(refusal.value)


# --- ADR-038: a build is not destructive ---


def test_a_build_against_an_empty_store_does_not_delete_the_published_tree(tmp_path) -> None:
    """The incident this default exists for. A build was run while the store was mid-repair, found
    no artifacts to emit, and would have deleted the published tree that was by then the only
    surviving copy of them. Derived output is derived right up until the source is incomplete."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "cache"
    publish_dataset(store, site_root=root, publication_mode="full", representations="all")
    published = root / "akn/my/bill/dr/2026/15/msa@.jsonld"
    before = published.read_bytes()

    empty = FileStore(tmp_path / "gone")
    result = publish_dataset(empty, site_root=root, publication_mode="full", representations="all")

    assert result.counts["exported"] == 0
    assert result.counts["removed"] == 0
    assert published.read_bytes() == before, "a build must not delete what it cannot rebuild"


def test_what_a_build_no_longer_publishes_is_named_not_merely_counted(tmp_path) -> None:
    """Safe is not enough: a build that quietly leaves a withdrawn Expression in the tree has
    published it. Every leftover is named through the channel `_report` prints and manifests."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "cache"
    publish_dataset(store, site_root=root, publication_mode="full", representations="all")
    stale = root / "akn/my/bill/dr/2026/99/msa@.xml"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"<akomaNtoso/>")

    result = publish_dataset(store, site_root=root, publication_mode="full", representations="all")

    assert result.counts["stale"] == 1
    assert result.counts["removed"] == 0
    assert stale.exists()
    reasons = [failure.reason for failure in result.failures]
    assert any("akn/my/bill/dr/2026/99/msa@.xml" in reason for reason in reasons)
    assert any("re-run with --prune" in reason for reason in reasons)


def test_the_checksums_describe_what_this_build_publishes_not_what_is_lying_around(
    tmp_path,
) -> None:
    """So a leftover stays detectable: present in the tree, absent from the digest list."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "cache"
    publish_dataset(store, site_root=root, publication_mode="full")
    stale = root / "akn/my/bill/dr/2026/99/msa@.jsonld"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"{}")

    publish_dataset(store, site_root=root, publication_mode="full")

    checksums = (root / "checksums.sha256").read_text(encoding="utf-8")
    assert "akn/my/bill/dr/2026/15/msa@.jsonld" in checksums
    assert "akn/my/bill/dr/2026/99" not in checksums


def test_a_build_still_leaves_foreign_files_alone_even_when_pruning(tmp_path) -> None:
    """Unchanged from before: `.git/`, CNAME and a hand-written README are not ours to delete."""
    store = FileStore(tmp_path / "store")
    seed(store, record=bill(15), doc_key="doc-passing")
    root = tmp_path / "cache"
    root.mkdir(parents=True)
    (root / "README.md").write_bytes(b"# Hand-written\n")
    (root / ".git").mkdir()
    (root / ".git/HEAD").write_bytes(b"ref: refs/heads/main\n")

    publish_dataset(store, site_root=root, publication_mode="full", prune=True)

    assert (root / "README.md").exists()
    assert (root / ".git/HEAD").exists()


def test_a_listed_bill_with_nothing_publishable_appears_as_missing(tmp_path) -> None:
    """A bill Parliament lists but this release cannot show is an entry with no expressions and a
    reason, never a silent absence — an absence a reader cannot see is indistinguishable from the
    bill never having existed."""
    store = FileStore(tmp_path / "store")
    # One bill publishes normally; one was listed but its downloads all failed; one was never
    # listed with any file at all.
    seed_reading(store, record=bill(15), doc_key="doc-read", markdown="1. Ada.")
    dead = bill(16)
    dead["documents"] = [
        {"url": "https://www.parlimen.gov.my/files/billindex/pdf/2026/DR162026.pdf"}
    ]
    store.save_bill("dr-16-2026", dead)
    unlisted = bill(17)
    unlisted["documents"] = []
    store.save_bill("dr-17-2026", unlisted)

    result = publish_dataset(
        store, site_root=tmp_path / "cache", publication_mode="full", representations="markdown"
    )

    assert result.counts["missing_works"] == 2
    index = json.loads((tmp_path / "cache/index.json").read_text(encoding="utf-8"))
    by_uri = {work["uri"]: work for work in index["works"]}
    assert "missing" not in by_uri["/akn/my/bill/dr/2026/15"]
    assert by_uri["/akn/my/bill/dr/2026/16"]["missing"]["reason"] == "download"
    assert by_uri["/akn/my/bill/dr/2026/16"]["expressions"] == []
    assert by_uri["/akn/my/bill/dr/2026/17"]["missing"]["reason"] == "listing"
