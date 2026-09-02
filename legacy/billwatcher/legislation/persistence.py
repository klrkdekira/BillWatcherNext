"""Store a structural reading and its Gate L1 verdict (HANDOFF 26.3).

Additive, in the same way `document_extractions` and `document_chunks` are additive: a newer
structure parser writes a new row and demotes the old one rather than overwriting it, so a fix
can be replayed from stored bytes and the reading it replaced stays inspectable.

Only a structure whose gate passed is `is_current`. That is the whole point of the gate: an
unvalidated reading is kept for review and is never the one anything downstream builds on.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from billwatcher.legislation import gate as gate_module
from billwatcher.legislation.layout import EXTRACTOR_NAME, extract_layout
from billwatcher.legislation.structure import (
    Node,
    Tree,
    parse_arrangement,
    parse_body,
    split_regions,
)
from billwatcher.models import (
    Anomaly,
    Blob,
    DocumentStructure,
    DocumentVersion,
    ProvisionNode,
    uuid4,
)
from billwatcher.operations import record_anomaly
from billwatcher.storage.blobs import BlobStore
from billwatcher.version import LAYOUT_EXTRACTOR_VERSION, STRUCTURE_VERSION

# A gate that fails on one document is a work item. A gate that fails on many at once means the
# parser or the upstream typography changed, which is an operational fact and is raised as one
# anomaly rather than as hundreds. This mirrors `evaluate_extraction_health` exactly.
STRUCTURE_SPIKE_WINDOW = 20
STRUCTURE_SPIKE_MIN_SAMPLE = 5
STRUCTURE_SPIKE_FRACTION = 0.5

# Gate outcomes that mean the reading may not be built on. `no_arrangement` is deliberately not
# among them: an explanatory statement legitimately has no Arrangement of Sections, so the gate
# has no oracle to apply and says so rather than failing.
#
# `no_text` is separate from `no_arrangement` on purpose. A scanned document yields no text at
# all, so it would otherwise be filed as "this document has no contents page" — indistinguishable
# from a legitimate one, and invisible in every count. The 22 known scans in the corpus are
# exactly the documents most likely to be wrong, so they get their own status and are counted as
# blocked until the OCR tier exists.
UNPUBLISHABLE = frozenset({"mismatch", "empty_body", "failed", "no_text"})


def persist_structure(
    session: Session,
    *,
    version: DocumentVersion,
    blob_store: BlobStore,
) -> DocumentStructure:
    """Read one document version's structure from its stored bytes and record the gate verdict."""
    existing = session.scalar(
        select(DocumentStructure).where(
            DocumentStructure.document_version_id == version.id,
            DocumentStructure.extractor_name == EXTRACTOR_NAME,
            DocumentStructure.extractor_version == LAYOUT_EXTRACTOR_VERSION,
            DocumentStructure.structure_version == STRUCTURE_VERSION,
        )
    )
    if existing is not None:
        return existing

    blob = session.get(Blob, version.blob_sha256)
    if blob is None:
        raise ValueError("document version blob row is missing")
    layout = extract_layout(blob_store.get(blob.sha256, compression=blob.compression))

    if layout.status in {"failed", "empty"}:
        structure = _row(
            version,
            unit="section",
            language=None,
            result=gate_module.GateResult(
                status="failed" if layout.status == "failed" else "no_text",
                unit="section",
                language=None,
                arrangement_count=0,
                body_count=0,
                error=layout.error,
            ),
            page_count=layout.page_count,
            duration_ms=layout.duration_ms,
        )
        _demote_older(session, version, publishable=False)
        session.add(structure)
        session.flush()
        return structure

    arrangement_lines, body_lines, unit, language = split_regions(layout.lines)
    arrangement = parse_arrangement(arrangement_lines, unit=unit, language=language)
    body = parse_body(body_lines, unit=unit, language=language)
    result = gate_module.evaluate(arrangement, body)

    structure = _row(
        version,
        unit=unit,
        language=language,
        result=result,
        page_count=layout.page_count,
        duration_ms=layout.duration_ms,
    )
    _demote_older(session, version, publishable=result.status not in UNPUBLISHABLE)
    session.add(structure)
    session.flush()
    _write_nodes(session, structure, arrangement, source="arrangement")
    _write_nodes(session, structure, body, source="body")
    session.flush()
    return structure


def _row(
    version: DocumentVersion,
    *,
    unit: str,
    language: str | None,
    result: gate_module.GateResult,
    page_count: int,
    duration_ms: int,
) -> DocumentStructure:
    return DocumentStructure(
        document_version_id=version.id,
        extractor_name=EXTRACTOR_NAME,
        extractor_version=LAYOUT_EXTRACTOR_VERSION,
        structure_version=STRUCTURE_VERSION,
        unit=unit,
        language=language,
        gate_status=result.status,
        arrangement_count=result.arrangement_count,
        body_count=result.body_count,
        difference_count=len(result.differences),
        blocking_count=len(result.blocking),
        detail_json=result.as_detail(),
        page_count=page_count,
        error=result.error,
        # A reading that did not pass is stored for review and is never the current one.
        is_current=result.status not in UNPUBLISHABLE,
        duration_ms=duration_ms,
    )


def _demote_older(session: Session, version: DocumentVersion, *, publishable: bool) -> None:
    """Supersede the previous reading — but only when the new one is fit to replace it.

    A newer parser that fails the gate must not withdraw a reading that passed. Demoting
    regardless would let a parser regression silently remove a good tree from everything
    downstream, which is the opposite of what an additive record is for.
    """
    if not publishable:
        return
    for older in session.scalars(
        select(DocumentStructure).where(
            DocumentStructure.document_version_id == version.id,
            DocumentStructure.is_current.is_(True),
        )
    ):
        older.is_current = False


def _write_nodes(
    session: Session, structure: DocumentStructure, tree: Tree, *, source: str
) -> int:
    """Flatten one tree into rows, preserving parentage and document order.

    Parent linkage is passed down as the parent's own row id, not looked up from a map keyed by
    eId string. That is deliberate: an ambiguous document can repeat an eId (`duplicate_eid` is a
    blocking Gate L1 finding precisely because it can), and a document that failed the gate is
    stored for review regardless. If parentage were resolved by eId, a repeated eId would make
    every one of its children attach to whichever occurrence was seen first, or be silently
    dropped along with the "duplicate" — evidence a reviewer needs is exactly what would be lost.
    Passing the row id instead makes every node's position exact and independent of naming.
    """
    written = 0
    seen: dict[str, int] = {}

    def emit(node: Node, parent_id: str | None, depth: int) -> None:
        nonlocal written
        stored_eid = node.eid
        occurrence = seen.get(node.eid, 0) + 1
        seen[node.eid] = occurrence
        if occurrence > 1:
            # `uq_provision_nodes_eid` is a real invariant — an eId is an identifier — so a
            # repeat cannot be stored under the same key. It is suffixed for storage only; the
            # gate's `duplicate_eid` finding already names the true eId and its repeat count.
            stored_eid = f"{node.eid}~{occurrence}"
        # The id is assigned here rather than left to the column default, which SQLAlchemy only
        # applies at INSERT: recursion needs it immediately, and asking the database for it would
        # cost one round trip per provision across a corpus of hundreds of thousands of them.
        node_id = uuid4()
        row = ProvisionNode(
            id=node_id,
            structure_id=structure.id,
            source=source,
            parent_id=parent_id,
            node_type=node.node_type,
            num=node.num[:16],
            heading=node.heading,
            eid=stored_eid,
            ordinal=written,
            depth=depth,
            page_from=node.page,
        )
        session.add(row)
        written += 1
        for child in node.children:
            emit(child, node_id, depth + 1)

    for root in tree.nodes:
        emit(root, None, 0)
    return written


def evaluate_structure_health(
    session: Session,
    *,
    now: datetime | None = None,
    window: int = STRUCTURE_SPIKE_WINDOW,
    min_sample: int = STRUCTURE_SPIKE_MIN_SAMPLE,
    threshold: float = STRUCTURE_SPIKE_FRACTION,
) -> float | None:
    """Raise `structure_gate_failure_spike` when Gate L1 starts failing at an abnormal rate.

    Returns the measured failure rate, or None when there is too little data to judge. One
    failing document is a review item, not an incident; many at once is an incident.
    """
    now = now or datetime.now(UTC)
    recent = session.scalars(
        select(DocumentStructure)
        .order_by(DocumentStructure.created_at.desc())
        .limit(window)
    ).all()
    if len(recent) < min_sample:
        return None
    failed = sum(1 for row in recent if row.gate_status in UNPUBLISHABLE)
    rate = failed / len(recent)
    existing = session.scalar(
        select(Anomaly).where(
            Anomaly.kind == "structure_gate_failure_spike",
            Anomaly.resolved_at.is_(None),
        )
    )
    if rate < threshold:
        if existing is not None:
            existing.resolved_at = now
        return rate
    record_anomaly(
        session,
        kind="structure_gate_failure_spike",
        severity="warn",
        detail={
            "failure_rate": round(rate, 4),
            "threshold": threshold,
            "sample": len(recent),
            "failed": failed,
            # The histogram, so an operator sees *which* way the gate is failing without
            # querying: a spike of `no_text` is a scan backlog, `mismatch` is a parser defect.
            "by_status": _histogram(recent),
        },
        now=now,
    )
    return rate


def _histogram(rows: Sequence[DocumentStructure]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.gate_status] = counts.get(row.gate_status, 0) + 1
    return dict(sorted(counts.items()))


def structure_summary(session: Session) -> dict[str, object]:
    """Gate L1's standing over the corpus, for `/status` (HANDOFF 26.3, 10.4).

    Freshness is per target because an average hides a broken one; the same reasoning applies
    here, so the histogram is reported rather than a single pass rate. `blocked` is the number
    of readings nothing may be built on, which is the figure an operator acts on.

    Counts are for the current extractor and structure versions only. Older readings are kept —
    that is what additive means — but reporting them would mean the panel described a corpus that
    no longer exists.
    """
    # Restricted to the versions currently in force. Structures are additive, so without this a
    # document read at 1.0.0 and again at 1.1.0 is counted twice and the `blocked` figure never
    # falls after a parser fix — the panel would keep reporting failures that have been fixed.
    by_status: dict[str, int] = {
        str(status): int(count)
        for status, count in session.execute(
            select(DocumentStructure.gate_status, func.count())
            .where(
                DocumentStructure.extractor_name == EXTRACTOR_NAME,
                DocumentStructure.extractor_version == LAYOUT_EXTRACTOR_VERSION,
                DocumentStructure.structure_version == STRUCTURE_VERSION,
            )
            .group_by(DocumentStructure.gate_status)
        ).tuples()
    }
    total = sum(by_status.values())
    blocked = sum(count for status, count in by_status.items() if status in UNPUBLISHABLE)
    return {
        "total": total,
        "by_status": dict(sorted(by_status.items())),
        "blocked": blocked,
        "passed": by_status.get("passed", 0),
        # Reported as a fraction of readings that ran, so a corpus that has not been read yet
        # shows nothing rather than a misleading 100%.
        "pass_rate": round(by_status.get("passed", 0) / total, 4) if total else None,
    }
