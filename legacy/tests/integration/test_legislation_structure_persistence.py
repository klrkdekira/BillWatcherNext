"""A structural reading is stored additively, and the gate decides what is built on.

HANDOFF 26.3.
"""

from datetime import UTC, datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from billwatcher.db import Base
from billwatcher.legislation.persistence import (
    evaluate_structure_health,
    persist_structure,
)
from billwatcher.models import (
    Anomaly,
    Blob,
    Document,
    DocumentStructure,
    DocumentVersion,
    ProvisionNode,
    ScrapeRun,
)
from billwatcher.storage.blobs import FilesystemBlobStore
from tests.support.pdfs import act_with_missing_section, act_without_arrangement, sample_act

NOW = datetime(2026, 8, 19, tzinfo=UTC)


def _seed(
    session: Session, store: FilesystemBlobStore, content: bytes, suffix: str
) -> DocumentVersion:
    """One accepted, current document version whose bytes are in the blob store."""
    stored = store.put(content)
    digest = stored.sha256
    session.add(
        Blob(
            sha256=digest,
            byte_size=stored.byte_size,
            media_type="application/pdf",
            storage_path=stored.location,
            compression=stored.compression,
        )
    )
    document = Document(
        document_kind="bill_as_introduced",
        language="unknown",
        canonical_source_url=f"https://www.parlimen.gov.my/{suffix}.pdf",
        source_url_raw=f"https://www.parlimen.gov.my/{suffix}.pdf",
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_checked_at=NOW,
        last_changed_at=NOW,
    )
    session.add(document)
    session.add(
        ScrapeRun(
            id=f"run-{suffix}",
            mode="fixture",
            trigger="test",
            started_at=NOW,
            state="succeeded",
        )
    )
    session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_no=1,
        content_sha256=digest,
        blob_sha256=digest,
        byte_size=len(content),
        http_status=200,
        final_url=document.canonical_source_url,
        retrieved_at=NOW,
        last_verified_at=NOW,
        run_id=f"run-{suffix}",
        fetch_attempt_id=f"attempt-{suffix}",
        is_current=True,
        change_kind="created",
        validation_status="accepted",
    )
    session.add(version)
    session.flush()
    return version


def _database(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, FilesystemBlobStore(tmp_path)


def test_a_passing_reading_stores_both_trees_and_is_current(tmp_path) -> None:
    engine, store = _database(tmp_path)
    with Session(engine) as session:
        version = _seed(session, store, sample_act(), "good")
        structure = persist_structure(session, version=version, blob_store=store)
        session.flush()

        assert structure.gate_status == "passed"
        assert structure.unit == "section"
        assert structure.language == "ms"
        assert structure.is_current is True
        assert structure.blocking_count == 0

        nodes = session.scalars(
            select(ProvisionNode).where(ProvisionNode.structure_id == structure.id)
        ).all()
        # Both readings are on the record, because a verdict is reviewable only if what it
        # compared is stored too.
        assert {node.source for node in nodes} == {"arrangement", "body"}
        body = [node for node in nodes if node.source == "body"]
        assert any(node.eid == "part_II__sec_3__subsec_1__para_a" for node in body)
        # Parentage survives the flattening.
        parents = {node.id: node for node in nodes}
        child = next(node for node in body if node.eid == "part_I__sec_1")
        assert parents[child.parent_id].eid == "part_I"


def test_a_failing_reading_is_kept_for_review_and_is_never_current(tmp_path) -> None:
    engine, store = _database(tmp_path)
    with Session(engine) as session:
        version = _seed(session, store, act_with_missing_section(), "bad")
        structure = persist_structure(session, version=version, blob_store=store)
        session.flush()

        assert structure.gate_status == "mismatch"
        assert structure.is_current is False
        assert structure.blocking_count == 1
        assert structure.detail_json["differences"][0]["eid"] == "sec_3"
        # Kept, not discarded: the row is the review item.
        assert session.scalar(select(DocumentStructure).where(DocumentStructure.id == structure.id))


def test_a_second_read_at_the_same_versions_is_idempotent(tmp_path) -> None:
    engine, store = _database(tmp_path)
    with Session(engine) as session:
        version = _seed(session, store, sample_act(), "same")
        first = persist_structure(session, version=version, blob_store=store)
        session.flush()
        nodes_after_first = session.scalar(
            select(ProvisionNode).where(ProvisionNode.structure_id == first.id).limit(1)
        )
        second = persist_structure(session, version=version, blob_store=store)
        session.flush()

        assert second.id == first.id
        assert nodes_after_first is not None
        current = session.scalar(
            select(DocumentStructure).where(DocumentStructure.is_current)
        )
        assert current is first


def test_a_scanned_document_is_distinguished_from_one_with_no_contents_page(tmp_path) -> None:
    """The 22 known scans are the documents most likely to be wrong.

    They must not be filed as though they simply lacked a contents page.
    """
    engine, store = _database(tmp_path)
    with Session(engine) as session:
        scan = _seed(session, store, b"%PDF-1.4\n" + b"\x00" * 32, "scan")
        no_contents = _seed(session, store, act_without_arrangement(), "plain")

        scanned = persist_structure(session, version=scan, blob_store=store)
        plain = persist_structure(session, version=no_contents, blob_store=store)
        session.flush()

        assert scanned.gate_status in {"no_text", "failed"}
        assert scanned.is_current is False
        # A document that simply has no Arrangement of Sections is not a failure.
        assert plain.gate_status == "no_arrangement"
        assert plain.is_current is True


def test_a_failing_reread_does_not_withdraw_a_reading_that_passed(tmp_path) -> None:
    """A parser regression must not silently remove a good tree from everything downstream."""
    engine, store = _database(tmp_path)
    with Session(engine) as session:
        version = _seed(session, store, sample_act(), "regress")
        good = persist_structure(session, version=version, blob_store=store)
        session.flush()
        assert good.is_current is True

        # A later parser version that fails the gate on the same bytes.
        session.add(
            DocumentStructure(
                document_version_id=version.id,
                extractor_name=good.extractor_name,
                extractor_version=good.extractor_version,
                structure_version="9.9.9",
                unit="section",
                language="ms",
                gate_status="mismatch",
                is_current=False,
            )
        )
        session.flush()
        session.refresh(good)
        assert good.is_current is True


def test_a_burst_of_gate_failures_raises_one_anomaly_not_hundreds(tmp_path) -> None:
    engine, store = _database(tmp_path)
    with Session(engine) as session:
        for index in range(6):
            # Distinct bytes per document: identity is the content hash, so six identical
            # documents would correctly collapse to one blob and one version.
            content = act_with_missing_section() + b"%% copy " + str(index).encode() + b"\n"
            version = _seed(session, store, content, f"burst{index}")
            persist_structure(session, version=version, blob_store=store)
        session.flush()
        rate = evaluate_structure_health(session, now=NOW)
        session.flush()

        assert rate == 1.0
        anomalies = session.scalars(
            select(Anomaly).where(Anomaly.kind == "structure_gate_failure_spike")
        ).all()
        assert len(anomalies) == 1
        assert anomalies[0].severity == "warn"
        assert anomalies[0].detail_json["by_status"] == {"mismatch": 6}


def test_one_unreadable_document_costs_one_document(tmp_path) -> None:
    """A failure mid-batch must not abort the transaction and take the rest of the run with it."""
    from billwatcher.jobs.restructure import run_restructure

    engine, store = _database(tmp_path)
    with Session(engine) as session:
        # A version whose blob row exists but whose bytes are not in the store.
        broken = _seed(session, store, sample_act() + b"%% broken\n", "broken")
        store.delete(broken.blob_sha256)
        for index in range(2):
            _seed(
                session,
                store,
                sample_act() + b"%% ok " + str(index).encode() + b"\n",
                f"ok{index}",
            )
        session.flush()

        job = run_restructure(session, blob_store=store, dry_run=False, limit=10)
        session.flush()

        assert job.counts["eligible"] == 3
        assert job.counts["failed"] == 1
        assert job.counts["processed"] == 2
        assert job.counts["gate_passed"] == 2
        # The two good readings survived the bad one and are queryable.
        assert (
            session.scalar(
                select(func.count())
                .select_from(DocumentStructure)
                .where(DocumentStructure.gate_status == "passed")
            )
            == 2
        )


def test_a_repeated_provision_number_fails_the_gate_before_it_reaches_the_database(
    tmp_path,
) -> None:
    """Two section 1s make every later reference ambiguous, and the unique index would reject them.

    Catching it in the gate keeps the failure a reported review item rather than a write error.
    """
    from tests.support.pdfs import BODY, MARGIN, Placement, build_pdf

    engine, store = _database(tmp_path)
    pdf = build_pdf(
        [
            [
                Placement(MARGIN, 780, "SUSUNAN SEKSYEN", 13.0),
                Placement(MARGIN, 740, "1. Tajuk"),
                Placement(MARGIN, 722, "2. Tafsiran"),
            ],
            [
                Placement(MARGIN, 760, "1. Tajuk."),
                Placement(BODY, 742, "Teks."),
                Placement(MARGIN, 700, "2. Tafsiran."),
                Placement(BODY, 682, "Teks."),
                Placement(MARGIN, 640, "1. Tajuk lagi."),
                Placement(BODY, 622, "Teks berulang."),
            ],
        ]
    )
    with Session(engine) as session:
        version = _seed(session, store, pdf, "dupe")
        structure = persist_structure(session, version=version, blob_store=store)
        session.flush()

        assert structure.gate_status == "mismatch"
        assert structure.is_current is False
        assert any(
            item["kind"] == "duplicate_eid" and item["eid"] == "sec_1"
            for item in structure.detail_json["differences"]
        )


def test_status_counts_only_the_current_parser_versions(tmp_path) -> None:
    """Readings are additive, so /status must not keep reporting failures a parser fix cleared."""
    from billwatcher.legislation.persistence import structure_summary

    engine, store = _database(tmp_path)
    with Session(engine) as session:
        version = _seed(session, store, sample_act(), "counted")
        persist_structure(session, version=version, blob_store=store)
        # The same document as read by an older structure parser, which failed the gate.
        session.add(
            DocumentStructure(
                document_version_id=version.id,
                extractor_name="pdfminer-layout",
                extractor_version="0.9.0",
                structure_version="0.9.0",
                unit="section",
                language="ms",
                gate_status="mismatch",
                is_current=False,
            )
        )
        session.flush()

        summary = structure_summary(session)
        assert summary["total"] == 1
        assert summary["by_status"] == {"passed": 1}
        assert summary["blocked"] == 0
        assert summary["pass_rate"] == 1.0


def test_a_duplicate_provisions_own_children_are_not_dropped(tmp_path) -> None:
    """The second (ambiguous) occurrence of a repeated eId still has its subtree stored.

    Gate L1 already flags the repeat as a blocking `duplicate_eid` finding; that is not a reason
    to also lose the evidence a reviewer needs to understand it. Only the stored key is
    disambiguated (`sec_1~2`), never the content.
    """
    from tests.support.pdfs import BODY, INDENT, MARGIN, Placement, build_pdf

    engine, store = _database(tmp_path)
    pdf = build_pdf(
        [
            [
                Placement(MARGIN, 780, "SUSUNAN SEKSYEN", 13.0),
                Placement(MARGIN, 740, "1. Tajuk"),
                Placement(MARGIN, 722, "2. Tafsiran"),
            ],
            [
                Placement(MARGIN, 760, "1. Tajuk."),
                Placement(BODY, 742, "Teks."),
                Placement(MARGIN, 700, "2. Tafsiran."),
                Placement(BODY, 682, "Teks."),
                Placement(MARGIN, 640, "1. Tajuk lagi."),
                Placement(BODY, 622, "(1) Subseksyen tersembunyi."),
                Placement(INDENT, 604, "(a) Perenggan tersembunyi."),
            ],
        ]
    )
    with Session(engine) as session:
        version = _seed(session, store, pdf, "dupe-with-children")
        structure = persist_structure(session, version=version, blob_store=store)
        session.flush()

        assert structure.gate_status == "mismatch"
        nodes = session.scalars(
            select(ProvisionNode).where(
                ProvisionNode.structure_id == structure.id, ProvisionNode.source == "body"
            )
        ).all()
        eids = {node.eid for node in nodes}
        # The duplicate top-level section is disambiguated for storage; its child's own eid is
        # built by the tree parser from the *logical* parent eid and needs no further collision
        # here, because only one `sec_1` in this document has a subsection at all. Parentage is
        # what proves the subtree survived and is attached to the right occurrence: it is checked
        # by following the actual row, not by comparing eid strings.
        assert "sec_1~2" in eids
        assert "sec_1__subsec_1" in eids
        assert "sec_1__subsec_1__para_a" in eids
        by_id = {node.id: node for node in nodes}
        duplicate_section = next(n for n in nodes if n.eid == "sec_1~2")
        subsection = next(n for n in nodes if n.eid == "sec_1__subsec_1")
        paragraph = next(n for n in nodes if n.eid == "sec_1__subsec_1__para_a")
        assert subsection.parent_id == duplicate_section.id
        assert by_id[paragraph.parent_id].id == subsection.id
