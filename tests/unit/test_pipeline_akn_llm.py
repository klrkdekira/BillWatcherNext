import json

import httpx
import pytest

from billwatcher.config import Settings
from billwatcher.legislation.vocabulary import schedule_heading
from billwatcher.pipeline.akn_llm import (
    StructureExtractorUnavailable,
    VllmMarkdownStructureExtractor,
    build_structure_extractor,
)

CANNED_TREE = {
    "children": [
        {
            "node_type": "part",
            "num": "I",
            "heading": None,
            "paragraphs": ["PERMULAAN"],
            "children": [
                {
                    "node_type": "clause",
                    "num": "1",
                    "heading": "Tajuk ringkas dan permulaan kuat kuasa.",
                    "paragraphs": ["Akta ini bolehlah dinamakan Akta Contoh 2026."],
                    "children": [],
                }
            ],
        }
    ]
}


def _transport(payload: dict, *, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload, request=request)

    return httpx.MockTransport(handler)


def _chat_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def test_extract_builds_the_node_tree_from_the_models_json() -> None:
    extractor = VllmMarkdownStructureExtractor(
        model_id="test-model",
        base_url="https://llm.example.org/v1",
        transport=_transport(_chat_response(json.dumps(CANNED_TREE))),
    )
    tree = extractor.extract("some markdown", unit="clause")
    assert tree.node_type == "body"
    part = tree.children[0]
    assert part.node_type == "part" and part.num == "I"
    assert part.paragraphs == ["PERMULAAN"]
    clause = part.children[0]
    assert clause.node_type == "clause" and clause.num == "1"
    assert clause.heading == "Tajuk ringkas dan permulaan kuat kuasa."
    # No eId assigned by the extractor itself — that is `pipeline.akn.assign_eids`'s job.
    assert clause.eid == ""


def test_num_is_stripped_of_parentheses_and_trailing_periods_defensively() -> None:
    """Found live: the model's first real response wrapped every parenthesised token as "(1)",
    "(a)", "(i)" despite the prompt saying not to, which would have poisoned every eId beneath
    those nodes with literal parentheses. Normalised regardless of what the model returns."""
    tree_with_punctuation = {
        "children": [
            {
                "node_type": "clause",
                "num": "5.",
                "heading": None,
                "paragraphs": [],
                "children": [
                    {
                        "node_type": "subsection",
                        "num": "(1)",
                        "heading": None,
                        "paragraphs": [],
                        "children": [
                            {
                                "node_type": "paragraph",
                                "num": "(a)",
                                "heading": None,
                                "paragraphs": [],
                                "children": [],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    extractor = VllmMarkdownStructureExtractor(
        model_id="test-model",
        base_url="https://llm.example.org/v1",
        transport=_transport(_chat_response(json.dumps(tree_with_punctuation))),
    )
    tree = extractor.extract("some markdown", unit="clause")
    clause = tree.children[0]
    assert clause.num == "5"
    subsection = clause.children[0]
    assert subsection.num == "1"
    paragraph = subsection.children[0]
    assert paragraph.num == "a"


def test_an_unnumbered_schedule_is_read_as_schedule_1_rather_than_as_a_missing_number() -> None:
    """A document with one schedule does not number it, so a faithful reading of a bare `JADUAL` has
    no number to report — and the gate's `missing_num` check would have rejected it for being right.

    The convention is the one `vocabulary.schedule_heading` already applies for the regex reader, so
    both producers name that schedule the same thing rather than two things.
    """
    unnumbered_schedule = {
        "children": [
            {
                "node_type": "schedule",
                "num": None,
                "heading": None,
                "paragraphs": [],
                "children": [
                    {
                        "node_type": "paragraph",
                        "num": "1",
                        "heading": None,
                        "paragraphs": ["Borang notis pelaporan."],
                        "children": [],
                    }
                ],
            }
        ]
    }
    extractor = VllmMarkdownStructureExtractor(
        model_id="test-model",
        base_url="https://llm.example.org/v1",
        transport=_transport(_chat_response(json.dumps(unnumbered_schedule))),
    )
    schedule = extractor.extract(
        "## JADUAL\n\n1. Borang notis pelaporan.\n", unit="clause"
    ).children[0]
    assert schedule.node_type == "schedule"
    assert schedule.num == "1"
    # The same convention, applied from the same document's own text by the regex path.
    assert schedule_heading("JADUAL") == "1"
    # Only a schedule gets the convention: any other node with no number is a real defect.
    assert [child.num for child in schedule.children] == ["1"]


def test_a_provision_other_than_a_schedule_keeps_its_missing_number_for_the_gate_to_catch() -> None:
    """`missing_num` exists because `assign_eids` falls back to the parent's eId, silently merging
    two provisions into one identifier. Filling a number in here would hide that from the gate."""
    unnumbered_clause = {
        "children": [{"node_type": "clause", "num": None, "heading": None, "paragraphs": ["Teks."]}]
    }
    extractor = VllmMarkdownStructureExtractor(
        model_id="test-model",
        base_url="https://llm.example.org/v1",
        transport=_transport(_chat_response(json.dumps(unnumbered_clause))),
    )
    assert extractor.extract("markdown", unit="clause").children[0].num is None


def test_a_non_json_response_raises_unavailable() -> None:
    extractor = VllmMarkdownStructureExtractor(
        model_id="test-model",
        base_url="https://llm.example.org/v1",
        transport=_transport(_chat_response("not json at all")),
    )
    with pytest.raises(StructureExtractorUnavailable, match="not the expected JSON"):
        extractor.extract("some markdown", unit="clause")


def test_an_unknown_node_type_raises_unavailable() -> None:
    bad_tree = {"children": [{"node_type": "bogus", "num": "1", "heading": None, "paragraphs": []}]}
    extractor = VllmMarkdownStructureExtractor(
        model_id="test-model",
        base_url="https://llm.example.org/v1",
        transport=_transport(_chat_response(json.dumps(bad_tree))),
    )
    with pytest.raises(StructureExtractorUnavailable, match="did not match the expected shape"):
        extractor.extract("some markdown", unit="clause")


def test_a_server_error_raises_unavailable() -> None:
    extractor = VllmMarkdownStructureExtractor(
        model_id="test-model",
        base_url="https://llm.example.org/v1",
        transport=_transport({"error": "boom"}, status=500),
    )
    with pytest.raises(StructureExtractorUnavailable, match="request failed"):
        extractor.extract("some markdown", unit="clause")


def test_build_structure_extractor_refuses_when_not_enabled() -> None:
    with pytest.raises(StructureExtractorUnavailable, match="AKN_LLM_ENABLED"):
        build_structure_extractor(Settings())


def test_build_structure_extractor_resolves_the_configured_endpoint() -> None:
    settings = Settings(
        akn_llm_enabled=True,
        akn_llm_base_url="https://llm.loqasi.io/v1",
        akn_llm_model_id="some-model",
    )
    extractor = build_structure_extractor(settings)
    assert extractor.model_id == "some-model"
    assert extractor.endpoint == "https://llm.loqasi.io/v1/chat/completions"
