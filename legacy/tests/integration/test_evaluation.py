"""The evaluation harness itself: versioned, offline, and honest about the dev provider."""

import json
from pathlib import Path

import pytest

from billwatcher.config import Settings
from billwatcher.search.embeddings import DeterministicEmbeddingProvider
from billwatcher.search.evaluation import CASES_FILE, CORPUS_FILE, evaluate

MODEL = "deterministic-dev-1024"


def settings() -> Settings:
    return Settings(
        semantic_search_enabled=True,
        embedding_provider="deterministic",
        embedding_model_id=MODEL,
    )


def test_the_set_covers_every_category_the_handoff_requires() -> None:
    suite = json.loads(CASES_FILE.read_text())
    kinds = {case["kind"] for case in suite["cases"]}
    assert {"identifier", "status", "timeline", "amendment", "superseded", "no_answer"} <= kinds
    languages = {case["language"] for case in suite["cases"]}
    assert languages == {"ms", "en"}
    assert suite["set_version"] and suite["corpus_version"]
    assert set(suite["thresholds"]) == {
        "recall_at_5",
        "no_answer_correct",
        "citation_validity",
        "version_pinned",
    }


def test_the_harness_runs_offline_and_reports_per_case() -> None:
    report = evaluate(settings=settings(), embedding_provider=DeterministicEmbeddingProvider(MODEL))
    assert report.set_version == "1"
    assert report.embedding_model == MODEL
    assert len(report.cases) == len(json.loads(CASES_FILE.read_text())["cases"])
    assert set(report.metrics) == set(report.thresholds)
    payload = report.as_dict()
    assert json.dumps(payload)
    assert payload["met_thresholds"] is report.met_thresholds


def test_identifier_and_content_retrieval_find_the_right_bill() -> None:
    report = evaluate(settings=settings(), embedding_provider=DeterministicEmbeddingProvider(MODEL))
    by_id = {case.case_id: case for case in report.cases}
    assert by_id["identifier-lookup-ms"].passed
    assert by_id["amendment-content-ms"].passed
    assert by_id["content-question-en"].passed


def test_the_superseded_case_proves_old_versions_are_excluded_by_default() -> None:
    report = evaluate(settings=settings(), embedding_provider=DeterministicEmbeddingProvider(MODEL))
    case = {result.case_id: result for result in report.cases}["superseded-excluded-by-default"]
    assert "superseded version was returned" not in case.detail


def test_the_development_provider_does_not_clear_the_release_gate() -> None:
    """The hashed dev projection has no semantics; the gate must notice."""
    report = evaluate(settings=settings(), embedding_provider=DeterministicEmbeddingProvider(MODEL))
    assert not report.met_thresholds


def test_a_corpus_version_mismatch_is_refused(tmp_path: Path) -> None:
    suite = json.loads(CASES_FILE.read_text())
    suite["corpus_version"] = "999"
    mismatched = tmp_path / "cases.json"
    mismatched.write_text(json.dumps(suite))
    with pytest.raises(ValueError, match="versions do not match"):
        evaluate(
            settings=settings(),
            embedding_provider=DeterministicEmbeddingProvider(MODEL),
            corpus_file=CORPUS_FILE,
            cases_file=mismatched,
        )
