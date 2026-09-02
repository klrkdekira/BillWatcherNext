"""`coverage`: the corpus reported per stage and per language, with gaps kept apart by cause."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from billwatcher.coverage import (
    build_report,
    render_markdown,
    summary_lines,
)
from billwatcher.download.documents import doc_key
from billwatcher.markdown.reading import NO_TEXT_LAYER
from billwatcher.store import FileStore

FIXED_NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

MALAY = "https://www.parlimen.gov.my/files/billindex/pdf/2024/DR%2017%20BM.pdf"
ENGLISH = "https://www.parlimen.gov.my/files/billindex/pdf/2024/DR%2017%20BI.pdf"
BOTH = "https://www.parlimen.gov.my/files/billindex/pdf/2005/DR012005.pdf"


def seed(store: FileStore, slug: str, *, titles: dict[str, str], documents: list[dict]) -> None:
    store.save_bill(
        slug,
        {
            "identifier": {"slug": slug, "year": int(slug.rsplit("-", 1)[-1])},
            "titles": titles,
            "documents": documents,
        },
    )


def store_pdf(store: FileStore, slug: str, url: str) -> None:
    store.save_document(
        bill_slug=slug,
        doc_key=doc_key(url),
        version=1,
        content=b"%PDF-1.7\ntiny",
        metadata={"source_url": url},
    )


def test_a_language_that_is_downloaded_but_unread_shows_as_exactly_that(tmp_path) -> None:
    """The finding the whole module exists to make legible: the English half landed and no part of
    it has been read. A single combined percentage would average it into the Malay half's 99%."""
    store = FileStore(tmp_path)
    seed(
        store,
        "dr-17-2024",
        titles={"raw_ms": "RUU", "raw_en": "A Bill"},
        documents=[
            {"url": MALAY, "chamber": "dewan_rakyat", "languages": ["ms"]},
            {"url": ENGLISH, "chamber": "dewan_rakyat", "languages": ["en"]},
        ],
    )
    store_pdf(store, "dr-17-2024", MALAY)
    store_pdf(store, "dr-17-2024", ENGLISH)
    store.save_markdown(bill_slug="dr-17-2024", doc_key=doc_key(MALAY), version=1, content="# ms")

    report = build_report(store, now=FIXED_NOW)
    stages = {stage.language: stage for stage in report.stages}

    assert stages["ms"].stored == 1
    assert stages["ms"].markdown == 1
    assert stages["en"].stored == 1
    assert stages["en"].markdown == 0
    assert report.stored == 2
    assert report.missing == 0


def test_a_document_upstream_does_not_hold_is_counted_apart_from_one_not_yet_processed(
    tmp_path,
) -> None:
    """The two gaps want opposite responses: one is permanent and must stop being retried, the
    other is the only kind anybody can act on. A report that adds them together hides both."""
    store = FileStore(tmp_path)
    seed(
        store,
        "dr-17-2024",
        titles={"raw_ms": "RUU", "raw_en": "A Bill"},
        documents=[
            {"url": MALAY, "chamber": "dewan_rakyat", "languages": ["ms"]},
            {"url": ENGLISH, "chamber": "dewan_rakyat", "languages": ["en"]},
        ],
    )
    store_pdf(store, "dr-17-2024", MALAY)  # the English PDF is referenced but never stored

    report = build_report(store, now=FIXED_NOW)
    stages = {stage.language: stage for stage in report.stages}

    assert stages["en"].referenced == 1
    assert stages["en"].stored == 0
    assert stages["en"].missing == 1
    assert report.missing_by_year == {"2024": {"en": 1}}
    assert report.english_outcomes["english_linked_but_absent_upstream"] == 1
    # Stored-but-unread is a different number and must not be folded into the one above.
    assert stages["ms"].stored == 1
    assert stages["ms"].markdown == 0


def test_a_document_both_languages_name_is_neither_language(tmp_path) -> None:
    """ADR-040 refuses to claim a language for a file both listings link. Adding it to either
    language's total would overstate that language by a document nobody has established."""
    store = FileStore(tmp_path)
    seed(
        store,
        "dr-1-2005",
        titles={"raw_ms": "RUU", "raw_en": "A Bill"},
        documents=[{"url": BOTH, "chamber": "dewan_rakyat", "languages": ["en", "ms"]}],
    )
    store_pdf(store, "dr-1-2005", BOTH)

    report = build_report(store, now=FIXED_NOW)
    stages = {stage.language: stage for stage in report.stages}

    assert stages["unsettled"].stored == 1
    assert stages["ms"].stored == 0
    assert stages["en"].stored == 0
    assert report.stored == 1


def test_every_bill_lands_in_exactly_one_english_outcome(tmp_path) -> None:
    store = FileStore(tmp_path)
    seed(store, "dr-1-2024", titles={"raw_ms": "RUU"}, documents=[])
    seed(
        store,
        "dr-2-2024",
        titles={"raw_ms": "RUU", "raw_en": "Bill"},
        documents=[{"url": MALAY, "chamber": "dewan_rakyat", "languages": ["ms"]}],
    )
    seed(
        store,
        "dr-3-2024",
        titles={"raw_ms": "RUU", "raw_en": "Bill"},
        documents=[{"url": ENGLISH, "chamber": "dewan_rakyat", "languages": ["en"]}],
    )
    store_pdf(store, "dr-3-2024", ENGLISH)

    report = build_report(store, now=FIXED_NOW)

    assert report.english_outcomes["no_english_title"] == 1
    assert report.english_outcomes["english_titled_but_no_document_linked"] == 1
    assert report.english_outcomes["english_stored"] == 1
    assert sum(report.english_outcomes.values()) == report.bills_total == 3


def test_an_archive_year_one_language_lists_and_the_other_does_not_is_reported(tmp_path) -> None:
    """A missing year is invisible in a document count: those bills were never listed, so nothing
    in the corpus knows to miss them. Dewan Negara's English tree really is eight years shorter."""
    store = FileStore(tmp_path)
    for language, years in (("ms", (1994, 1995)), ("en", (1995,))):
        for year in years:
            store.save_listing(
                key=f"dewan_negara-archive-{year}-{language}",
                extension="xml",
                body=b"<tree/>",
                metadata={
                    "chamber": "dewan_negara",
                    "language": language,
                    "listing_kind": "archive_year",
                    "scope": str(year),
                },
            )

    report = build_report(store, now=FIXED_NOW)

    assert report.archive_years_absent == {"dewan_negara/en": [1994]}
    assert report.listings_by_language == {"en": 1, "ms": 2}
    assert any("absent from dewan_negara/en" in line for line in summary_lines(report))


def test_two_promoted_documents_of_one_bill_and_language_are_reported_as_a_collision(
    tmp_path,
) -> None:
    """ADR-024's identifier carries no chamber component, so a bill that passed through both
    chambers mints one Expression IRI for two documents. Detection is the whole mitigation."""
    store = FileStore(tmp_path)
    other = "https://www.parlimen.gov.my/files/billindex/pdf/2024/DN%2017%20BM.pdf"
    seed(
        store,
        "dr-17-2024",
        titles={"raw_ms": "RUU"},
        documents=[
            {"url": MALAY, "chamber": "dewan_rakyat", "languages": ["ms"]},
            {"url": other, "chamber": "dewan_negara", "languages": ["ms"]},
        ],
    )
    for url in (MALAY, other):
        store_pdf(store, "dr-17-2024", url)
        keys = {"bill_slug": "dr-17-2024", "doc_key": doc_key(url), "version": 1}
        store.save_akn(**keys, content=b"<akomaNtoso/>")
        store.save_structure_gate(**keys, record={"status": "passed", "language": "ms"})

    report = build_report(store, now=FIXED_NOW)

    assert len(report.expression_collisions) == 1
    assert report.expression_collisions[0].startswith("dr-17-2024 (ms):")
    assert report.gate_verdicts == {"passed": 2}


def test_the_published_dataset_is_read_from_what_is_actually_served(tmp_path) -> None:
    """The corpus cannot know whether `publish` has run since it last changed, so the count of
    what is being served has to come from the served tree itself."""
    store = FileStore(tmp_path / "corpus")
    seed(store, "dr-17-2024", titles={"raw_ms": "RUU"}, documents=[])
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.json").write_text(
        json.dumps(
            {
                "works": [
                    {"expressions": [{"language": "ms"}, {"language": "en"}]},
                    {"expressions": [{"language": "ms"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    report = build_report(store, site_root=site, now=FIXED_NOW)

    assert report.published_works == 2
    assert report.published_expressions == {"en": 1, "ms": 2}


def test_no_published_dataset_reports_nothing_rather_than_failing(tmp_path) -> None:
    store = FileStore(tmp_path / "corpus")
    seed(store, "dr-17-2024", titles={"raw_ms": "RUU"}, documents=[])

    report = build_report(store, site_root=tmp_path / "absent", now=FIXED_NOW)

    assert report.published_works == 0
    assert report.published_expressions == {}
    assert any("nothing published yet" in line for line in summary_lines(report))


def test_the_markdown_body_is_identical_between_two_runs_of_one_corpus(tmp_path) -> None:
    """The reason the report is Markdown at all: `git diff` between two runs should show coverage
    moving, not a clock ticking. Only the footer may differ, so the timestamp lives there."""
    store = FileStore(tmp_path)
    seed(
        store,
        "dr-17-2024",
        titles={"raw_ms": "RUU", "raw_en": "Bill"},
        documents=[{"url": MALAY, "chamber": "dewan_rakyat", "languages": ["ms"]}],
    )
    store_pdf(store, "dr-17-2024", MALAY)

    first = render_markdown(build_report(store, now=datetime(2026, 8, 27, 9, 0, tzinfo=UTC)))
    second = render_markdown(build_report(store, now=datetime(2026, 8, 28, 17, 30, tzinfo=UTC)))

    assert first != second  # the footer records when it ran
    body = lambda text: text.split("\n---\n")[0]  # noqa: E731
    assert body(first) == body(second)
    assert "2026-08-27T09:00" in first
    assert "2026-08-28T17:30" in second
    # No timestamp above the rule, or every diff would show the clock rather than the corpus.
    assert "2026-08-2" not in body(first)


def test_the_report_writes_nothing_into_the_corpus(tmp_path) -> None:
    """A report is not a step: no manifest, no artifact, nothing another step consumes. That is
    what makes it safe to hang off the end of a Makefile target that does write."""
    store = FileStore(tmp_path)
    seed(
        store,
        "dr-17-2024",
        titles={"raw_ms": "RUU"},
        documents=[{"url": MALAY, "chamber": "dewan_rakyat", "languages": ["ms"]}],
    )
    store_pdf(store, "dr-17-2024", MALAY)
    before = {path: path.stat().st_mtime_ns for path in sorted(Path(tmp_path).rglob("*"))}

    report = build_report(store, now=FIXED_NOW)
    render_markdown(report)
    summary_lines(report)

    after = {path: path.stat().st_mtime_ns for path in sorted(Path(tmp_path).rglob("*"))}
    assert before == after
    assert not (tmp_path / "manifests").exists()


def test_the_payload_carries_the_counts_and_not_fifty_urls(tmp_path) -> None:
    """Stdout is one JSON object the rest of the CLI promises is pipeable. Fifty long URLs would
    dominate it, so named examples live in the written report instead."""
    store = FileStore(tmp_path)
    seed(
        store,
        "dr-17-2024",
        titles={"raw_ms": "RUU", "raw_en": "Bill"},
        documents=[{"url": ENGLISH, "chamber": "dewan_rakyat", "languages": ["en"]}],
    )

    report = build_report(store, now=FIXED_NOW)
    payload = report.as_payload()

    assert payload["documents_referenced"] == 1
    assert payload["documents_absent_upstream"] == 1
    assert payload["stages"]["en"]["missing"] == 1
    assert "documents_absent_upstream_samples" not in payload
    assert json.dumps(payload)  # serialisable, which is the contract stdout depends on
    # …but the written report does name them, because that is where there is room.
    assert ENGLISH in render_markdown(report)


def test_a_scan_with_no_text_layer_is_not_reported_as_work_still_to_do(tmp_path) -> None:
    """Twelve stored Malay bills are image-only scans. Nothing is written for a reading that found
    nothing, so the corpus alone cannot tell them from documents nobody has read yet — and calling
    them actionable sends an operator to re-run a step that is already finished."""
    store = FileStore(tmp_path)
    scanned = "https://www.parlimen.gov.my/files/billindex/pdf/2018/D.R.%201_2018%20-%20bm.pdf"
    seed(
        store,
        "dr-1-2018",
        titles={"raw_ms": "RUU"},
        documents=[
            {"url": scanned, "chamber": "dewan_rakyat", "languages": ["ms"]},
            {"url": MALAY, "chamber": "dewan_rakyat", "languages": ["ms"]},
        ],
    )
    store_pdf(store, "dr-1-2018", scanned)
    store_pdf(store, "dr-1-2018", MALAY)
    store.save_manifest(
        step="extract-markdown",
        run_id="20260827T001022.079395Z",
        payload={
            "counts": {"empty": 1},
            "failures": [
                {
                    "bill_slug": "dr-1-2018",
                    "doc_key": doc_key(scanned),
                    "version": 1,
                    "reason": NO_TEXT_LAYER,
                }
            ],
        },
    )

    report = build_report(store, now=FIXED_NOW)
    stage = {s.language: s for s in report.stages}["ms"]

    assert stage.stored == 2
    assert stage.no_text_layer == 1
    assert stage.not_read_yet == 1  # the other one, which really is outstanding
    summary = "\n".join(summary_lines(report))
    assert "1 ms document(s) stored but not read" in summary
    assert "no text layer" in summary
    markdown = render_markdown(report)
    assert "Scanned — needs the cross-check tier, not another run" in markdown


def test_a_manifest_naming_a_document_that_has_since_been_read_changes_nothing(tmp_path) -> None:
    """The manifest is a hint about a document still unread, never an authority over the corpus:
    a reading on disk always wins, so a stale run record cannot un-read a document."""
    store = FileStore(tmp_path)
    seed(
        store,
        "dr-1-2018",
        titles={"raw_ms": "RUU"},
        documents=[{"url": MALAY, "chamber": "dewan_rakyat", "languages": ["ms"]}],
    )
    store_pdf(store, "dr-1-2018", MALAY)
    store.save_markdown(bill_slug="dr-1-2018", doc_key=doc_key(MALAY), version=1, content="# read")
    store.save_manifest(
        step="extract-markdown",
        run_id="20260101T000000.000000Z",
        payload={
            "failures": [
                {
                    "bill_slug": "dr-1-2018",
                    "doc_key": doc_key(MALAY),
                    "version": 1,
                    "reason": NO_TEXT_LAYER,
                }
            ]
        },
    )

    stage = {s.language: s for s in build_report(store, now=FIXED_NOW).stages}["ms"]

    assert stage.markdown == 1
    assert stage.no_text_layer == 0
    assert stage.not_read_yet == 0


def test_the_newest_manifest_is_the_one_read(tmp_path) -> None:
    """Run ids are UTC timestamps, so the newest is the lexicographic maximum — not the newest
    mtime, which a checkout or a copy would reorder."""
    store = FileStore(tmp_path)
    for run_id, count in (("20260101T000000.000000Z", 99), ("20260827T120000.000000Z", 7)):
        store.save_manifest(
            step="extract-markdown", run_id=run_id, payload={"counts": {"n": count}}
        )

    latest = store.latest_manifest(step="extract-markdown")

    assert latest is not None
    assert latest["counts"]["n"] == 7
    assert store.latest_manifest(step="never-run") is None


def read(store: FileStore, slug: str, url: str, *, language: str, text: str) -> None:
    """A stored reading, with the provenance `publish` derives its Expression IRI from."""
    key = doc_key(url)
    store.save_markdown(bill_slug=slug, doc_key=key, version=1, content=text)
    store.save_provenance(
        bill_slug=slug,
        doc_key=key,
        version=1,
        artifact="markdown",
        record={
            "inputs": {"language": language},
            "output": {"document.md": {"sha256": hashlib.sha256(text.encode()).hexdigest()}},
        },
    )


def test_two_readings_of_one_bill_and_language_are_reported_as_a_dropped_publish(tmp_path) -> None:
    """`publish` keeps one reading per Expression IRI, so a bill that passed through both chambers
    loses one document per language. 118 of the corpus's 120 cost nothing — the chambers link the
    same file — so reporting only the total would overstate the damage by sixty times."""
    store = FileStore(tmp_path)
    dn = "https://www.parlimen.gov.my/files/billindex/pdf/2025/DN/x.pdf"
    dr = "https://www.parlimen.gov.my/files/billindex/pdf/2025/DR/x.pdf"
    seed(
        store,
        "dr-33-2025",
        titles={"raw_ms": "RUU"},
        documents=[
            {"url": dn, "chamber": "dewan_negara", "languages": ["ms"]},
            {"url": dr, "chamber": "dewan_rakyat", "languages": ["ms"]},
        ],
    )
    for url in (dn, dr):
        store_pdf(store, "dr-33-2025", url)
    read(store, "dr-33-2025", dn, language="ms", text="# as introduced")
    read(store, "dr-33-2025", dr, language="ms", text="# as amended")  # genuinely different

    report = build_report(store, now=FIXED_NOW)

    assert len(report.published_collisions) == 1
    assert len(report.published_conflicts) == 1
    summary = "\n".join(summary_lines(report))
    assert "1 reading(s) dropped at publish" in summary
    assert "1 lose differing text; 0 are the same file" in summary


def test_the_same_file_linked_from_both_chambers_is_a_collision_that_costs_nothing(
    tmp_path,
) -> None:
    """The ordinary case, and the reason the two numbers are reported apart: the dropped reading is
    byte-identical to the kept one, so the served corpus is not missing anything."""
    store = FileStore(tmp_path)
    dn = "https://www.parlimen.gov.my/files/billindex/pdf/2025/DN/y.pdf"
    dr = "https://www.parlimen.gov.my/files/billindex/pdf/2025/DR/y.pdf"
    seed(
        store,
        "dr-40-2025",
        titles={"raw_ms": "RUU"},
        documents=[
            {"url": dn, "chamber": "dewan_negara", "languages": ["ms"]},
            {"url": dr, "chamber": "dewan_rakyat", "languages": ["ms"]},
        ],
    )
    for url in (dn, dr):
        store_pdf(store, "dr-40-2025", url)
        read(store, "dr-40-2025", url, language="ms", text="# identical text")

    report = build_report(store, now=FIXED_NOW)

    assert len(report.published_collisions) == 1
    assert report.published_conflicts == ()
    assert "0 lose differing text; 1 are the same file" in "\n".join(summary_lines(report))
