"""`audit-structure`: what the current parser and gate make of every stored reading, versus what is
recorded — the measurement every parser change is judged by.

Every fix to the structure parser in this project's history was found by running it over the whole
corpus and tracing each gate finding back to the line that produced it, and every regression was
caught by diffing the set of passing documents before and after. That loop lived in scratch scripts.
A rule that is only enforced by hand is not enforced, so this module makes it a step: read every
stored reading, parse it with its geometry (ADR-042), judge it with Gate P1, and compare the verdict
with the one recorded on disk by the last `convert-to-akn` run.

Like `coverage` it writes nothing into the corpus and always exits 0: a document that *would* fail
now is a finding for the operator to read, not an error in the build that reported it. The report is
written as Markdown so `git diff` shows the parser's reach moving between two commits, the same way
`coverage.md` shows the corpus moving.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from billwatcher.graph import fidelity
from billwatcher.graph.structure import (
    MarkdownStructureExtractor,
    assign_eids,
    infer_language_and_unit,
)
from billwatcher.reporting import describe_error
from billwatcher.store import PipelineStore, keys_for
from billwatcher.version import AKN_VERSION, STRUCTURE_GATE_VERSION

# How many named documents each list in the report carries. The counts say how much moved; a
# reader acts on a handful of names, not on hundreds.
SAMPLE_LIMIT = 40


@dataclass(frozen=True, slots=True)
class AuditReport:
    """What the current code would decide, against what the store recorded."""

    documents: int
    would_pass: int
    recorded_pass: int
    with_geometry: int
    gained: tuple[str, ...]
    lost: tuple[str, ...]
    unrecorded: int
    failed: tuple[tuple[str, str], ...]
    finding_families: dict[str, int] = field(default_factory=dict)
    finding_documents: dict[str, int] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "akn_version": AKN_VERSION,
            "gate_version": STRUCTURE_GATE_VERSION,
            "documents": self.documents,
            "would_pass": self.would_pass,
            "recorded_pass": self.recorded_pass,
            "with_geometry": self.with_geometry,
            "gained": list(self.gained[:SAMPLE_LIMIT]),
            "gained_count": len(self.gained),
            "lost": list(self.lost[:SAMPLE_LIMIT]),
            "lost_count": len(self.lost),
            "unrecorded": self.unrecorded,
            "failed": [{"document": doc, "reason": why} for doc, why in self.failed[:SAMPLE_LIMIT]],
            "failed_count": len(self.failed),
            "finding_families": dict(sorted(self.finding_families.items())),
            "finding_documents": dict(sorted(self.finding_documents.items())),
        }


def audit_structure(
    store: PipelineStore,
    *,
    extractor: MarkdownStructureExtractor,
    min_text_coverage: float = fidelity.MIN_TEXT_COVERAGE,
) -> AuditReport:
    """Parse and gate every stored reading in memory; compare with the recorded verdicts."""
    documents = would_pass = recorded_pass = with_geometry = unrecorded = 0
    gained: list[str] = []
    lost: list[str] = []
    failed: list[tuple[str, str]] = []
    families: Counter[str] = Counter()
    family_documents: Counter[str] = Counter()
    for ref in store.iter_documents():
        keys = keys_for(ref)
        markdown = store.load_markdown(**keys)
        if markdown is None:
            continue
        documents += 1
        name = f"{ref.bill_slug}/{ref.doc_key}/v{ref.version:03d}"
        recorded = store.load_structure_gate(**keys)
        recorded_status = recorded.get("status") if recorded else None
        if recorded_status is None:
            unrecorded += 1
        elif recorded_status == "passed":
            recorded_pass += 1
        geometry = store.load_blocks(**keys)
        blocks = geometry.get("blocks") if geometry is not None else None
        if isinstance(blocks, list):
            with_geometry += 1
        else:
            blocks = None
        try:
            _, unit = infer_language_and_unit(markdown)
            tree = extractor.extract(markdown, unit=unit, blocks=blocks)
            assign_eids(tree)
            verdict = fidelity.evaluate(tree, markdown, unit=unit, min_coverage=min_text_coverage)
        except Exception as error:  # a parser that raises on a stored reading is itself a finding
            failed.append((name, describe_error(error)))
            continue
        if verdict.passed:
            would_pass += 1
            if recorded_status is not None and recorded_status != "passed":
                gained.append(name)
        else:
            if recorded_status == "passed":
                lost.append(name)
            seen: set[str] = set()
            for finding in verdict.blocking:
                family = f"{_level(finding.eid)}/{finding.kind}"
                families[family] += 1
                seen.add(family)
            for family in seen:
                family_documents[family] += 1
    return AuditReport(
        documents=documents,
        would_pass=would_pass,
        recorded_pass=recorded_pass,
        with_geometry=with_geometry,
        gained=tuple(gained),
        lost=tuple(lost),
        unrecorded=unrecorded,
        failed=tuple(failed),
        finding_families=dict(families),
        finding_documents=dict(family_documents),
    )


def _level(eid: str) -> str:
    """Which depth of the tree a finding sits at, from the shape of its eId."""
    if not eid:
        return "document"
    tail = eid.rsplit("__", 1)[-1]
    prefix = tail.split("_", 1)[0]
    return {
        "part": "container",
        "chp": "container",
        "art": "container",
        "sched": "container",
        "cl": "provision",
        "sec": "provision",
        "subsec": "subsection",
        "para": "paragraph",
        "subpara": "subparagraph",
        "list": "list",
    }.get(prefix, "document")


def summary_lines(report: AuditReport) -> list[str]:
    return [
        f"{report.would_pass}/{report.documents} readings would pass Gate P1 "
        f"({report.recorded_pass} recorded as passing; {report.with_geometry} with geometry)",
        f"gained {len(report.gained)}, lost {len(report.lost)}, "
        f"unrecorded {report.unrecorded}, parser failures {len(report.failed)}",
    ]


def render_markdown(report: AuditReport) -> str:
    """The report as a tracked document, so `git diff` shows the parser's reach moving."""
    lines = [
        "# Structure audit",
        "",
        f"Parser `AKN_VERSION` {AKN_VERSION}, gate `STRUCTURE_GATE_VERSION` "
        f"{STRUCTURE_GATE_VERSION}, over every stored reading, without writing anything. "
        '"Recorded" is the verdict the last `convert-to-akn` run left beside the document; '
        '"would pass" is what the code in this checkout decides now.',
        "",
        "| | |",
        "| --- | --- |",
        f"| Readings audited | {report.documents:,} |",
        f"| — with block geometry | {report.with_geometry:,} |",
        f"| Would pass Gate P1 | {report.would_pass:,} |",
        f"| Recorded as passing | {report.recorded_pass:,} |",
        f"| Would pass, recorded failing | {len(report.gained):,} |",
        f"| Would fail, recorded passing | {len(report.lost):,} |",
        f"| No recorded verdict | {report.unrecorded:,} |",
        f"| Parser raised | {len(report.failed):,} |",
        "",
        "## Blocking findings, by depth and kind",
        "",
        "Documents carrying at least one finding of the family, and the total number of findings.",
        "",
        "| Family | Documents | Findings |",
        "| --- | --- | --- |",
    ]
    for family, count in sorted(
        report.finding_documents.items(), key=lambda item: (-item[1], item[0])
    ):
        lines.append(f"| `{family}` | {count:,} | {report.finding_families.get(family, 0):,} |")
    for title, names in (
        ("Would fail, recorded passing", report.lost),
        ("Would pass, recorded failing", report.gained),
    ):
        lines.extend(["", f"## {title}", ""])
        if not names:
            lines.append("None.")
        lines.extend(f"- `{name}`" for name in names[:SAMPLE_LIMIT])
        if len(names) > SAMPLE_LIMIT:
            lines.append(f"- … and {len(names) - SAMPLE_LIMIT:,} more")
    if report.failed:
        lines.extend(["", "## Parser raised", ""])
        lines.extend(f"- `{name}`: {reason}" for name, reason in report.failed[:SAMPLE_LIMIT])
    return "\n".join(lines) + "\n"
