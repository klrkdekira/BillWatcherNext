"""Structure extraction with no vLLM endpoint: the handoff round trip (ADR-037)."""

import json
from pathlib import Path

import pytest

from billwatcher.graph.convert import convert_to_akn
from billwatcher.graph.handoff import (
    ANSWER_FILENAME,
    EXTRACTOR_NAME,
    FileStructureExtractor,
    HandoffError,
    StructureAnswer,
    load_answers,
    write_handoff,
)
from billwatcher.graph.structure import MarkdownStructureExtractor
from billwatcher.store import FileStore

MARKDOWN = """\
1. Tajuk ringkas

Akta ini bolehlah dinamakan Akta Contoh 2026.

2. Kewajipan untuk melaporkan

Seseorang hendaklah melaporkan kepada Pesuruhjaya dalam tempoh empat belas hari.
"""

ANSWER = {
    "children": [
        {
            "node_type": "clause",
            "num": "1",
            "heading": "Tajuk ringkas",
            "paragraphs": ["Akta ini bolehlah dinamakan Akta Contoh 2026."],
        },
        {
            "node_type": "clause",
            "num": "2",
            "heading": "Kewajipan untuk melaporkan",
            "paragraphs": [
                "Seseorang hendaklah melaporkan kepada Pesuruhjaya dalam tempoh empat belas hari."
            ],
        },
    ]
}


def seed(store: FileStore, *, slug: str = "dr-15-2026", markdown: str = MARKDOWN) -> dict:
    keys = {"bill_slug": slug, "doc_key": "doc-abc12345", "version": 1}
    store.save_bill(
        slug,
        {
            "identifier": {
                "slug": slug,
                "originating_chamber": "dewan_rakyat",
                "year": 2026,
                "number": 15,
            },
            "titles": {"raw_ms": "Rang Undang-Undang Contoh"},
        },
    )
    store.save_document(**keys, content=b"%PDF-1.4 fixture", metadata={"source_url": "https://x"})
    store.save_markdown(**keys, content=markdown)
    store.save_provenance(**keys, artifact="markdown", record={"inputs": {"language": "ms"}})
    return keys


def answer(root: Path, *, slug: str = "dr-15-2026", payload: dict | None = None) -> Path:
    path = root / slug / "doc-abc12345" / "v001" / ANSWER_FILENAME
    path.write_text(json.dumps(payload if payload is not None else ANSWER), encoding="utf-8")
    return path


def test_a_packet_is_self_contained(tmp_path) -> None:
    """An agent is pointed at a directory: it must need no store access, no knowledge of the
    layout, and no way to resolve a doc-key back to a document."""
    store = FileStore(tmp_path / "store")
    seed(store)
    root = tmp_path / "handoff"

    result = write_handoff(store, root=root)

    assert result.counts["written"] == 1
    packet = root / "dr-15-2026" / "doc-abc12345" / "v001"
    assert (packet / "document.md").read_text(encoding="utf-8") == MARKDOWN
    instruction = (packet / "INSTRUCTION.md").read_text(encoding="utf-8")
    assert "write `structure.json` beside it" in instruction
    assert "unit is **clause**" in instruction
    # The extraction rules are the real prompt, not a paraphrase: two producers reading one corpus
    # to different rules would put two structural conventions into one dataset.
    assert "legislative document structure extractor" in instruction
    assert "Skip rather than guess." in instruction
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["packets"][0]["markdown_sha256"]
    assert manifest["packets"][0]["answered"] is False


def test_a_document_with_no_reading_gets_no_packet(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    keys = {"bill_slug": "dr-15-2026", "doc_key": "doc-abc12345", "version": 1}
    store.save_bill("dr-15-2026", {"identifier": {"slug": "dr-15-2026"}})
    store.save_document(**keys, content=b"%PDF-1.4", metadata={"source_url": "https://x"})

    result = write_handoff(store, root=tmp_path / "handoff")

    assert result.counts["no_reading"] == 1
    assert result.counts["written"] == 0


def test_re_emitting_a_handoff_keeps_the_answers(tmp_path) -> None:
    """The answer is the expensive part — someone's actual reading of a bill."""
    store = FileStore(tmp_path / "store")
    seed(store)
    root = tmp_path / "handoff"
    write_handoff(store, root=root)
    written = answer(root)

    result = write_handoff(store, root=root)

    assert written.exists()
    assert result.counts["answered"] == 1
    assert json.loads((root / "manifest.json").read_text())["packets"][0]["answered"] is True


def test_overwrite_answers_is_explicit(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store)
    root = tmp_path / "handoff"
    write_handoff(store, root=root)
    written = answer(root)

    write_handoff(store, root=root, overwrite_answers=True)

    assert not written.exists()


def test_the_file_extractor_satisfies_the_same_protocol_as_the_model_one() -> None:
    """`convert_to_akn` must not know or care which produced a reading."""
    extractor: MarkdownStructureExtractor = FileStructureExtractor(
        root=Path("."), answers={"x": StructureAnswer()}
    )
    assert extractor.name == EXTRACTOR_NAME
    assert extractor.prompt_sha256


def test_an_answer_converts_through_the_ordinary_gate(tmp_path) -> None:
    store = FileStore(tmp_path / "store")
    seed(store)
    root = tmp_path / "handoff"
    write_handoff(store, root=root)
    answer(root)

    result = convert_to_akn(
        store,
        extractor=FileStructureExtractor(root=root, model_id="claude-code"),
        min_text_coverage=0.95,
    )

    assert result.counts["converted"] == 1, result.failures
    keys = {"bill_slug": "dr-15-2026", "doc_key": "doc-abc12345", "version": 1}
    assert store.has_akn(**keys)
    assert (store.load_structure_gate(**keys) or {})["status"] == "passed"
    # Provenance keeps the two producers apart, which is what stops an agent-produced tree from
    # reading as a model-produced one after the fact (ADR-026 staleness uses exactly these fields).
    record = store.load_provenance(**keys, artifact="akn")
    assert record is not None
    assert record["inputs"]["producer"] == EXTRACTOR_NAME
    assert record["inputs"]["model_id"] == "claude-code"


def test_an_answer_written_against_edited_text_is_refused_not_misattributed(tmp_path) -> None:
    """Matching is by hash of the markdown, so an answer cannot be silently attached to text it
    was not read from — the failure mode a filename-keyed handoff would have."""
    store = FileStore(tmp_path / "store")
    seed(store)
    root = tmp_path / "handoff"
    write_handoff(store, root=root)
    answer(root)
    packet = root / "dr-15-2026" / "doc-abc12345" / "v001"
    packet.joinpath("document.md").write_text("1. Something else entirely.\n", encoding="utf-8")

    result = convert_to_akn(
        store, extractor=FileStructureExtractor(root=root), min_text_coverage=0.95
    )

    # Indistinguishable from unanswered, which is the safe direction: not converted, and above all
    # not attached to text it was not read from.
    assert result.counts["converted"] == 0
    assert result.counts["unanswered"] == 1
    assert result.failures == ()
    assert (
        store.load_structure_gate(bill_slug="dr-15-2026", doc_key="doc-abc12345", version=1) is None
    )


def test_an_unanswered_packet_reports_that_document_and_leaves_the_rest(tmp_path) -> None:
    """Partial agent work must convert what is ready and name what is not."""
    store = FileStore(tmp_path / "store")
    seed(store, slug="dr-15-2026")
    seed(store, slug="dr-16-2026", markdown=MARKDOWN.replace("Contoh", "Kedua"))
    root = tmp_path / "handoff"
    write_handoff(store, root=root)
    answer(root, slug="dr-15-2026")

    result = convert_to_akn(
        store, extractor=FileStructureExtractor(root=root), min_text_coverage=0.95
    )

    # The unanswered one is counted apart, not reported as a failure and not stamped with a failed
    # Gate P1 verdict: on a corpus answered incrementally that is the ordinary state of most
    # packets, and burying real failures under a thousand non-events is how a report gets ignored.
    assert result.counts["converted"] == 1
    assert result.counts["unanswered"] == 1
    assert result.failures == ()
    assert (
        store.load_structure_gate(bill_slug="dr-16-2026", doc_key="doc-abc12345", version=1) is None
    )


def test_unreadable_json_fails_loudly_rather_than_being_skipped(tmp_path) -> None:
    root = tmp_path / "handoff"
    packet = root / "dr-15-2026" / "doc-abc12345" / "v001"
    packet.mkdir(parents=True)
    packet.joinpath("document.md").write_text(MARKDOWN, encoding="utf-8")
    packet.joinpath(ANSWER_FILENAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(HandoffError) as error:
        load_answers(root)

    assert "not readable JSON" in str(error.value)


def test_a_missing_handoff_directory_is_refused(tmp_path) -> None:
    with pytest.raises(HandoffError):
        load_answers(tmp_path / "nope")


def test_an_answer_that_misnames_a_field_is_refused_rather_than_read_as_empty(tmp_path) -> None:
    """The failure the contract exists to catch: a writer that answers `text` for `paragraphs`.

    Tolerated, such an answer produces provisions with no body — a defect the fidelity gate can
    only find by coverage, long after the packet that caused it is out of view.
    """
    root = tmp_path / "handoff"
    packet = root / "dr-15-2026" / "doc-abc12345" / "v001"
    packet.mkdir(parents=True)
    packet.joinpath("document.md").write_text(MARKDOWN, encoding="utf-8")
    answer(
        root,
        payload={"children": [{"node_type": "clause", "num": "1", "text": ["Isi kandungan."]}]},
    )

    with pytest.raises(HandoffError) as error:
        load_answers(root)

    assert "does not match the answer contract" in str(error.value)
    # Named by path, so the operator knows which of hundreds of packets to fix.
    assert str(packet / ANSWER_FILENAME) in str(error.value)
    assert "text" in str(error.value)


def test_an_unknown_node_type_is_refused_at_load(tmp_path) -> None:
    root = tmp_path / "handoff"
    packet = root / "dr-15-2026" / "doc-abc12345" / "v001"
    packet.mkdir(parents=True)
    packet.joinpath("document.md").write_text(MARKDOWN, encoding="utf-8")
    answer(root, payload={"children": [{"node_type": "recital", "paragraphs": []}]})

    with pytest.raises(HandoffError) as error:
        load_answers(root)

    assert "unknown node_type" in str(error.value)


def test_typeset_punctuation_and_unquoted_numbers_survive_validation() -> None:
    """The normalisation `_normalize_num` was written for, now applied while validating.

    A `num` an answer left unquoted is JSON typing, not a misreading, so it is coerced rather than
    refused; parentheses and a trailing period are stripped, because an eId built from "(1)" is
    poisoned for every node beneath it.
    """
    parsed = StructureAnswer.model_validate(
        {
            "children": [
                {
                    "node_type": "clause",
                    "num": 5,
                    "paragraphs": ["Teks."],
                    "children": [{"node_type": "subsection", "num": "(1)", "paragraphs": []}],
                },
                {"node_type": "schedule", "num": None, "paragraphs": []},
            ]
        }
    )

    body = parsed.to_body()
    assert body.node_type == "body"
    assert [child.num for child in body.children] == ["5", "1"]
    assert body.children[0].children[0].num == "1"
    # An unnumbered lone schedule is schedule 1, matching the regex parser's own convention.
    assert body.children[1].node_type == "schedule"
