"""`audit-structure`: the measurement a parser change is judged by, as a step, not a script."""

from billwatcher.audit import AuditReport, render_markdown, summary_lines


def test_the_report_names_what_moved_and_what_family_the_rest_fails_on() -> None:
    report = AuditReport(
        documents=3,
        would_pass=2,
        recorded_pass=1,
        with_geometry=3,
        gained=("dr-1-2026/doc-a/v001",),
        lost=(),
        unrecorded=1,
        failed=(),
        finding_families={"provision/duplicate_eid": 4},
        finding_documents={"provision/duplicate_eid": 1},
    )
    text = render_markdown(report)
    assert "| Would pass Gate P1 | 2 |" in text
    assert "| `provision/duplicate_eid` | 1 | 4 |" in text
    assert "- `dr-1-2026/doc-a/v001`" in text
    assert "## Would fail, recorded passing\n\nNone." in text
    assert summary_lines(report)[0].startswith("2/3 readings would pass Gate P1")
    payload = report.as_payload()
    assert payload["gained_count"] == 1 and payload["lost_count"] == 0
