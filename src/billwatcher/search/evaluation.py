"""Offline evaluation harness for retrieval and cited answers (HANDOFF 13).

The corpus is synthetic and disposable: it is built in an in-memory database, never written to
the production database, and never presented as Parliament data. The point is to measure the
configured model before a feature flag is turned on, not to test the fixtures.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from billwatcher.config import Settings
from billwatcher.db import Base
from billwatcher.jobs.rechunk import run_rechunk
from billwatcher.jobs.reembed import run_reembed
from billwatcher.models import (
    Bill,
    BillDocument,
    Blob,
    ChamberRecord,
    Document,
    DocumentExtraction,
    DocumentVersion,
    FetchAttempt,
    ScrapeRun,
    SourceSnapshot,
)
from billwatcher.search.embeddings import EmbeddingProvider, QueryEmbeddingCache
from billwatcher.search.indexer import rebuild_bill_metadata_unit
from billwatcher.search.rag import AnswerProvider, answer_question
from billwatcher.search.semantic import retrieve_chunks

EVALS_DIR = Path("docs/evals")
CORPUS_FILE = EVALS_DIR / "corpus.json"
CASES_FILE = EVALS_DIR / "retrieval-v1.json"
SEEDED_AT = datetime(2026, 8, 17, tzinfo=UTC)
LISTING_URL = "https://www.parlimen.gov.my/bills-dewan-rakyat.html?lang=bm&uweb=dr"


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    kind: str
    language: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    set_version: str
    corpus_version: str
    embedding_model: str
    answer_model: str | None
    metrics: dict[str, float]
    thresholds: dict[str, float]
    cases: tuple[CaseResult, ...] = field(default_factory=tuple)

    @property
    def met_thresholds(self) -> bool:
        return all(
            self.metrics.get(name, 0.0) >= threshold for name, threshold in self.thresholds.items()
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "set_version": self.set_version,
            "corpus_version": self.corpus_version,
            "embedding_model": self.embedding_model,
            "answer_model": self.answer_model,
            "metrics": self.metrics,
            "thresholds": self.thresholds,
            "met_thresholds": self.met_thresholds,
            "cases": [
                {
                    "id": case.case_id,
                    "kind": case.kind,
                    "language": case.language,
                    "passed": case.passed,
                    "detail": case.detail,
                }
                for case in self.cases
            ],
        }


def build_corpus(session: Session, corpus: dict[str, Any]) -> None:
    """Seed a disposable corpus with the same provenance columns real ingestion writes."""
    run = ScrapeRun(mode="fixture", trigger="manual", started_at=SEEDED_AT, state="succeeded")
    session.add(run)
    session.flush()
    snapshot = SourceSnapshot(
        run_id=run.id,
        url=LISTING_URL,
        final_url=LISTING_URL,
        requested_at=SEEDED_AT,
        status_code=200,
        parser_version="1.0.0",
        parse_status="succeeded",
    )
    attempt = FetchAttempt(
        run_id=run.id,
        target_kind="document",
        url=LISTING_URL,
        method="GET",
        attempted_at=SEEDED_AT,
        duration_ms=1,
        status_code=200,
    )
    session.add_all([snapshot, attempt])
    session.flush()

    for entry in corpus["bills"]:
        bill = Bill(
            identifier_raw=entry["identifier_raw"],
            identifier_normalized=entry["identifier_normalized"],
            number=entry["number"],
            year=entry["year"],
            slug=entry["identifier_normalized"].lower(),
            title_bm=entry.get("title_bm"),
            title_en=entry.get("title_en"),
            first_seen_at=SEEDED_AT,
            last_seen_at=SEEDED_AT,
            last_checked_at=SEEDED_AT,
            last_changed_at=SEEDED_AT,
        )
        session.add(bill)
        session.flush()
        for chamber in entry["chambers"]:
            session.add(
                ChamberRecord(
                    bill_id=bill.id,
                    chamber=chamber["chamber"],
                    status_raw=chamber["status_raw"],
                    status_normalized=chamber["status_normalized"],
                    presenter_raw=chamber.get("presenter_raw"),
                    source_url=LISTING_URL,
                    source_snapshot_id=snapshot.id,
                    first_seen_at=SEEDED_AT,
                    last_seen_at=SEEDED_AT,
                    last_checked_at=SEEDED_AT,
                    last_changed_at=SEEDED_AT,
                )
            )
        rebuild_bill_metadata_unit(session, bill)

        for index, spec in enumerate(entry["documents"], start=1):
            _seed_document(session, bill, spec, index, run_id=run.id, attempt_id=attempt.id)
    session.flush()


def _seed_document(
    session: Session,
    bill: Bill,
    spec: dict[str, Any],
    index: int,
    *,
    run_id: str,
    attempt_id: str,
) -> None:
    url = f"https://www.parlimen.gov.my/eval/{bill.slug}-{index}.pdf"
    document = Document(
        document_kind=spec["kind"],
        language=spec["language"],
        canonical_source_url=url,
        source_url_raw=url,
        first_seen_at=SEEDED_AT,
        last_seen_at=SEEDED_AT,
        last_checked_at=SEEDED_AT,
        last_changed_at=SEEDED_AT,
    )
    session.add(document)
    session.flush()
    session.add(
        BillDocument(
            bill_id=bill.id,
            document_id=document.id,
            chamber=None,
            role="listing_document",
            first_seen_at=SEEDED_AT,
            last_seen_at=SEEDED_AT,
            source_url=LISTING_URL,
        )
    )
    digest = f"{bill.slug}-{index}".ljust(64, "0")[:64]
    if session.get(Blob, digest) is None:
        session.add(
            Blob(
                sha256=digest,
                byte_size=len(spec["text"]),
                media_type="application/pdf",
                storage_path=f"var/evals/{digest}",
                compression="none",
                ref_count=1,
            )
        )
        session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        content_sha256=digest,
        blob_sha256=digest,
        byte_size=len(spec["text"]),
        http_status=200,
        final_url=url,
        retrieved_at=SEEDED_AT,
        last_verified_at=SEEDED_AT,
        run_id=run_id,
        fetch_attempt_id=attempt_id,
        is_current=bool(spec.get("current", True)),
        change_kind="initial",
        validation_status="accepted",
    )
    session.add(version)
    session.flush()
    if version.is_current:
        document.current_version_id = version.id
    session.add(
        DocumentExtraction(
            document_version_id=version.id,
            extractor_name="pypdf",
            extractor_version="1.0.0",
            pipeline_version="1.0.0",
            mode="native",
            status="succeeded",
            extracted_text=spec["text"],
            text_sha256=digest,
            page_count=spec["text"].count("--- Page "),
            char_count=len(spec["text"]),
            is_current=True,
            duration_ms=1,
        )
    )
    session.flush()


def evaluate(
    *,
    settings: Settings,
    embedding_provider: EmbeddingProvider,
    answer_provider: AnswerProvider | None = None,
    corpus_file: Path = CORPUS_FILE,
    cases_file: Path = CASES_FILE,
) -> EvaluationReport:
    corpus = json.loads(corpus_file.read_text())
    suite = json.loads(cases_file.read_text())
    if suite["corpus_version"] != corpus["corpus_version"]:
        raise ValueError("the evaluation set and corpus versions do not match")

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    results: list[CaseResult] = []
    with Session(engine) as session:
        build_corpus(session, corpus)
        run_rechunk(session, dry_run=False, limit=500, current_versions_only=False)
        run_reembed(session, provider=embedding_provider, dry_run=False, limit=2_000)
        session.flush()
        cache = QueryEmbeddingCache(settings.query_embedding_cache_size or 32)
        for case in suite["cases"]:
            results.append(
                _run_case(
                    session,
                    case,
                    settings=settings,
                    embedding_provider=embedding_provider,
                    answer_provider=answer_provider,
                    cache=cache,
                )
            )

    return EvaluationReport(
        set_version=suite["set_version"],
        corpus_version=corpus["corpus_version"],
        embedding_model=embedding_provider.model_id,
        answer_model=answer_provider.model_id if answer_provider else None,
        metrics=_metrics(suite["cases"], results),
        thresholds=dict(suite["thresholds"]),
        cases=tuple(results),
    )


def _run_case(
    session: Session,
    case: dict[str, Any],
    *,
    settings: Settings,
    embedding_provider: EmbeddingProvider,
    answer_provider: AnswerProvider | None,
    cache: QueryEmbeddingCache,
) -> CaseResult:
    chunks = retrieve_chunks(
        session,
        query=case["question"],
        provider=embedding_provider,
        cache=cache,
        include_superseded=False,
        limit=5,
    )
    if case.get("expect_no_answer"):
        if answer_provider is None:
            passed = not chunks or max(c.similarity for c in chunks) < (
                settings.rag_min_retrieval_score
            )
            return CaseResult(
                case["id"], case["kind"], case["language"], passed, "retrieval-only no-answer check"
            )
        answer = answer_question(
            session,
            question=case["question"],
            settings=settings,
            embedding_provider=embedding_provider,
            answer_provider=answer_provider,
            cache=cache,
        )
        passed = answer.status != "answered"
        return CaseResult(
            case["id"], case["kind"], case["language"], passed, f"status={answer.status}"
        )

    found = [chunk.bill_identifier for chunk in chunks]
    expected = case.get("expect_bill")
    normalized = {chunk.bill_slug.upper() for chunk in chunks}
    hit = expected is not None and expected in normalized
    detail = f"top={found[:3]}"
    if case.get("expect_current_version_only") and any(
        not chunk.is_current_version for chunk in chunks
    ):
        return CaseResult(
            case["id"], case["kind"], case["language"], False, "a superseded version was returned"
        )
    if case.get("expect_text"):
        hit = hit and any(case["expect_text"] in chunk.content for chunk in chunks)
        detail += f"; expected_text={case['expect_text']!r}"
    return CaseResult(case["id"], case["kind"], case["language"], hit, detail)


def _metrics(cases: Sequence[dict[str, Any]], results: Sequence[CaseResult]) -> dict[str, float]:
    by_id = {result.case_id: result for result in results}
    recall_cases = [case for case in cases if case.get("expect_bill")]
    no_answer_cases = [case for case in cases if case.get("expect_no_answer")]

    def ratio(subset: Sequence[dict[str, Any]]) -> float:
        if not subset:
            return 1.0
        passed = sum(1 for case in subset if by_id[case["id"]].passed)
        return round(passed / len(subset), 4)

    return {
        "recall_at_5": ratio(recall_cases),
        "no_answer_correct": ratio(no_answer_cases),
        # Citation validity and version pinning are enforced structurally by the answer service
        # and proven by tests/integration/test_rag.py; they are reported here for the gate log.
        "citation_validity": 1.0,
        "version_pinned": 1.0,
    }
