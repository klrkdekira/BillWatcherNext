"""`coverage`: what the corpus holds, what upstream does not publish, and what has not been run.

Every other reporting surface in this pipeline answers for one step. `fetch-documents` says how
many PDFs it downloaded, `extract-markdown` how many readings it wrote — and each is truthful about
its own run and silent about the shape of the corpus that run left behind. After a build an operator
still has to answer "is the corpus complete?" by hand, and the honest answer has three parts that a
per-step count cannot separate:

- **stored**, which the steps do report;
- **absent upstream**, which is not recoverable by running anything again and must therefore stop
  being counted as a failure to fix;
- **not yet run**, which is the only part anybody can act on.

Collapsing those three into one percentage is what makes a coverage number untrustworthy. A corpus
that is 97% downloaded and 50% read is not 73% anything. So this module reports per stage and per
language, and keeps the causes apart.

Like `verify`, it writes nothing into the corpus and leaves no manifest. A report is not a step: it
records no decision, produces no artifact another step consumes, and re-running it changes nothing.
That is what makes it safe to hang off the end of a Makefile target that does write. Unlike
`verify`, it is not a gate — it always exits 0, because "the English half is unread" is the finding,
not an error, and a build must not fail for describing itself accurately.

Language is reported as three buckets, not two. `ms` and `en` are the published languages
(ADR-040), and `unsettled` is the handful of documents both languages' listings name, whose language
the corpus deliberately does not claim. Folding those into either language would overstate that
language's coverage by exactly the number of documents nobody has established a language for.
"""

import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from billwatcher.download.documents import VERSION as DOCUMENT_VERSION
from billwatcher.download.documents import doc_key as document_key
from billwatcher.markdown.reading import NO_TEXT_LAYER
from billwatcher.store import PipelineStore, keys_for

# The published languages, in report order. `unsettled` is appended by the reader rather than
# named here: it is not a language, it is the absence of a settled one.
LANGUAGES: tuple[str, ...] = ("ms", "en")
UNSETTLED = "unsettled"

# How many named examples a report carries per finding. The counts above them already say how bad
# things are, and a JSON object listing two thousand URLs is not read by anybody — the same
# reasoning as `reporting.FAILURE_LIMIT`, which this deliberately matches.
SAMPLE_LIMIT = 50

# Why a bill has no English document. Ordered from "we have it" to "upstream never published it",
# because that is the order an operator triages in: only the first two are ever actionable.
ENGLISH_OUTCOMES: tuple[str, ...] = (
    "english_stored",
    "english_partial",
    "english_linked_but_absent_upstream",
    "english_titled_but_no_document_linked",
    "no_english_title",
)


@dataclass(frozen=True, slots=True)
class StageCoverage:
    """One language's progress through the four stages, as stored-over-expected pairs.

    Each stage's denominator is the previous stage's output, not the corpus total, because that is
    the only ratio an operator can act on: markdown coverage against *referenced* documents would
    charge this language for PDFs Parliament does not publish.
    """

    language: str
    referenced: int = 0
    stored: int = 0
    markdown: int = 0
    # Stored, attempted, and unreadable locally: a scan with no text layer. Counted apart from the
    # merely-unread, because re-running the reader will never produce a reading for these and a
    # report that lumps them together sends an operator to run a step that has already finished.
    no_text_layer: int = 0
    akn: int = 0
    semantic: int = 0

    @property
    def missing(self) -> int:
        return self.referenced - self.stored

    @property
    def not_read_yet(self) -> int:
        """Stored, no reading, and not known to be unreadable — the only actionable shortfall."""
        return self.stored - self.markdown - self.no_text_layer

    def as_payload(self) -> dict[str, int]:
        return {
            "referenced": self.referenced,
            "stored": self.stored,
            "missing": self.missing,
            "markdown": self.markdown,
            "no_text_layer": self.no_text_layer,
            "not_read_yet": self.not_read_yet,
            "akn": self.akn,
            "semantic": self.semantic,
        }


@dataclass(frozen=True, slots=True)
class CoverageReport:
    generated_at: str
    bills_total: int = 0
    bills_by_title_language: dict[str, int] = field(default_factory=dict)
    stages: tuple[StageCoverage, ...] = ()
    listings_by_language: dict[str, int] = field(default_factory=dict)
    archive_years_absent: dict[str, list[int]] = field(default_factory=dict)
    missing_by_year: dict[str, dict[str, int]] = field(default_factory=dict)
    # Named examples for the written report only, deliberately not in `as_payload`: fifty long
    # URLs would dominate the one JSON object stdout promises and make it useless to pipe into jq.
    missing_samples: tuple[str, ...] = ()
    english_outcomes: dict[str, int] = field(default_factory=dict)
    gate_verdicts: dict[str, int] = field(default_factory=dict)
    published_expressions: dict[str, int] = field(default_factory=dict)
    published_works: int = 0
    expression_collisions: tuple[str, ...] = ()
    # Documents that lose their Expression IRI to another reading of the same bill and language,
    # and the subset whose text actually differs. The first number is what `publish` drops; the
    # second is the only part of it that costs the served corpus anything.
    published_collisions: tuple[str, ...] = ()
    published_conflicts: tuple[str, ...] = ()

    @property
    def referenced(self) -> int:
        return sum(stage.referenced for stage in self.stages)

    @property
    def stored(self) -> int:
        return sum(stage.stored for stage in self.stages)

    @property
    def missing(self) -> int:
        return sum(stage.missing for stage in self.stages)

    def as_payload(self) -> dict[str, Any]:
        """The single JSON object the CLI echoes, matching every other step's contract."""
        payload: dict[str, Any] = {
            "generated_at": self.generated_at,
            "bills": self.bills_total,
            "documents_referenced": self.referenced,
            "documents_stored": self.stored,
            "documents_absent_upstream": self.missing,
            "bills_by_title_language": dict(self.bills_by_title_language),
            "listings_by_language": dict(self.listings_by_language),
            "stages": {stage.language: stage.as_payload() for stage in self.stages},
            "english_outcomes": dict(self.english_outcomes),
            "gate_verdicts": dict(self.gate_verdicts),
            "published_works": self.published_works,
            "published_expressions": dict(self.published_expressions),
            "missing_by_year": {
                year: dict(counts) for year, counts in self.missing_by_year.items()
            },
        }
        if self.archive_years_absent:
            payload["archive_years_absent"] = {
                scope: list(years) for scope, years in self.archive_years_absent.items()
            }
        if self.expression_collisions:
            payload["expression_collisions"] = list(self.expression_collisions[:SAMPLE_LIMIT])
            payload["expression_collisions_truncated"] = (
                len(self.expression_collisions) > SAMPLE_LIMIT
            )
        payload["published_collisions"] = len(self.published_collisions)
        payload["published_conflicts"] = list(self.published_conflicts[:SAMPLE_LIMIT])
        return payload


def _language_of_reference(document: dict[str, Any]) -> str:
    """Which bucket one document reference counts towards.

    Deliberately not `documents.language_of`: that returns `None` for an unsettled document because
    its caller must not *claim* a language, whereas a report must still count the document
    somewhere. Same rule, different answer for the same case.
    """
    languages = [value for value in document.get("languages") or [] if isinstance(value, str)]
    return languages[0] if len(languages) == 1 else UNSETTLED


def _read_published(site_root: Path | None) -> tuple[int, dict[str, int]]:
    """Works and expressions-per-language in the published dataset, or zeroes if none is published.

    Read from the dataset's own `index.json` rather than recomputed from the corpus, because the
    question this answers is "what is currently being served", and the corpus cannot know whether
    `publish` has run since it last changed.
    """
    if site_root is None:
        return 0, {}
    index = site_root / "index.json"
    try:
        catalogue = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0, {}
    works = catalogue.get("works")
    if not isinstance(works, list):
        return 0, {}
    languages: Counter[str] = Counter()
    for work in works:
        for expression in (work or {}).get("expressions") or []:
            language = expression.get("language")
            if isinstance(language, str) and language:
                languages[language] += 1
    return len(works), dict(sorted(languages.items()))


def _archive_years(store: PipelineStore) -> tuple[dict[str, int], dict[str, set[int]]]:
    """Listing snapshots per language, and the archive years stored per chamber and language."""
    per_language: Counter[str] = Counter()
    years: dict[str, set[int]] = defaultdict(set)
    for listing in store.iter_listings():
        metadata = listing.metadata or {}
        language = metadata.get("language")
        if not isinstance(language, str) or not language:
            continue  # robots.txt, which has no language and is not a listing of anything
        per_language[language] += 1
        if metadata.get("listing_kind") != "archive_year":
            continue
        chamber = metadata.get("chamber")
        scope = str(metadata.get("scope", ""))
        if isinstance(chamber, str) and scope.isdigit():
            years[f"{chamber}/{language}"].add(int(scope))
    return dict(sorted(per_language.items())), years


def _absent_archive_years(years: dict[str, set[int]]) -> dict[str, list[int]]:
    """Years one language's archive tree offers and the other's does not.

    Upstream's own asymmetry, not a crawl failure: Dewan Negara's English index offered eight fewer
    year nodes than its Malay one on 2026-08-27. Reported because a whole missing year is invisible
    in a document count — those bills are not "documents we failed to fetch", they were never
    listed, so nothing in the corpus knows to miss them.
    """
    chambers = {scope.split("/", 1)[0] for scope in years}
    absent: dict[str, list[int]] = {}
    for chamber in sorted(chambers):
        for language in LANGUAGES:
            others: set[int] = set()
            for other in LANGUAGES:
                if other != language:
                    others |= years.get(f"{chamber}/{other}", set())
            gap = sorted(others - years.get(f"{chamber}/{language}", set()))
            if gap:
                absent[f"{chamber}/{language}"] = gap
    return absent


def build_report(
    store: PipelineStore, *, site_root: Path | None = None, now: datetime | None = None
) -> CoverageReport:
    """Read the corpus and answer, per stage and per language, what it holds and what it lacks.

    One pass over the bills and one over the stored documents. Nothing is written, nothing is
    fetched, and no gate is re-run — the gate verdicts already on disk are read as recorded, which
    is what keeps this cheap enough to hang off the end of every build.
    """
    generated_at = (now or datetime.now(UTC)).isoformat()

    counters: dict[str, dict[str, int]] = {
        language: dict.fromkeys(
            ("referenced", "stored", "markdown", "no_text_layer", "akn", "semantic"), 0
        )
        for language in (*LANGUAGES, UNSETTLED)
    }
    title_languages: Counter[str] = Counter()
    english_outcomes: Counter[str] = Counter()
    missing_by_year: dict[str, Counter[str]] = defaultdict(Counter)
    missing_samples: list[str] = []
    bills_total = 0

    for slug in store.iter_bill_slugs():
        bill = store.load_bill(slug)
        if not bill:
            continue
        bills_total += 1
        titles = {
            key.removeprefix("raw_") for key in (bill.get("titles") or {}) if key.startswith("raw_")
        }
        title_languages["+".join(sorted(titles)) or "none"] += 1
        year = (bill.get("identifier") or {}).get("year")
        english_referenced = english_stored = 0

        for document in bill.get("documents") or []:
            url = document.get("url")
            if not url:
                continue
            language = _language_of_reference(document)
            key = document_key(url)
            stored = store.has_document(bill_slug=slug, doc_key=key, version=DOCUMENT_VERSION)
            counters[language]["referenced"] += 1
            if language == "en":
                english_referenced += 1
            if stored:
                counters[language]["stored"] += 1
                if language == "en":
                    english_stored += 1
                continue
            missing_by_year[str(year)][language] += 1
            if len(missing_samples) < SAMPLE_LIMIT:
                missing_samples.append(f"{slug} [{language}] {url}")

        english_outcomes[
            _english_outcome(
                has_english_title="en" in titles,
                referenced=english_referenced,
                stored=english_stored,
            )
        ] += 1

    # Derived artifacts are counted from the store rather than from the bill records, because a
    # reading exists per stored document version and the bill record knows only URLs.
    gate_verdicts: Counter[str] = Counter()
    promoted: dict[tuple[str, str], list[str]] = defaultdict(list)
    languages_by_document = _document_languages(store)
    unreadable = _documents_without_a_text_layer(store)
    # Keyed exactly as `publish` keys it — the *declared* language from the markdown provenance,
    # not the bill record — so this reports the collisions the published tree actually has.
    readings: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for ref in store.iter_documents():
        if ref.version != DOCUMENT_VERSION:
            continue
        keys = keys_for(ref)
        language = languages_by_document.get((ref.bill_slug, ref.doc_key), UNSETTLED)
        if store.has_markdown(**keys):
            counters[language]["markdown"] += 1
            record = store.load_provenance(**keys, artifact="markdown") or {}
            declared = (record.get("inputs") or {}).get("language")
            if isinstance(declared, str) and declared:
                digest = ((record.get("output") or {}).get("document.md") or {}).get("sha256", "")
                readings[(ref.bill_slug, declared)].append((ref.doc_key, str(digest)))
        elif (ref.bill_slug, ref.doc_key) in unreadable:
            counters[language]["no_text_layer"] += 1
        verdict = store.load_structure_gate(**keys) or {}
        status = verdict.get("status")
        if isinstance(status, str) and status:
            gate_verdicts[status] += 1
        if store.has_akn(**keys):
            counters[language]["akn"] += 1
            gate_language = verdict.get("language")
            if isinstance(gate_language, str) and gate_language:
                promoted[(ref.bill_slug, gate_language)].append(ref.doc_key)
        if store.has_semantic(**keys):
            counters[language]["semantic"] += 1

    collisions = tuple(
        f"{slug} ({language}): {', '.join(sorted(keys))}"
        for (slug, language), keys in sorted(promoted.items())
        if len(keys) > 1
    )
    published_collisions: list[str] = []
    published_conflicts: list[str] = []
    for (slug, language), entries in sorted(readings.items()):
        if len(entries) < 2:
            continue
        names = ", ".join(key for key, _ in sorted(entries))
        published_collisions.append(f"{slug} ({language}): {names}")
        # Digests compared from the provenance records rather than by re-hashing the markdown:
        # the same answer, without reading half a gigabyte of text to get it.
        if len({digest for _, digest in entries}) > 1:
            published_conflicts.append(f"{slug} ({language}): {names}")
    listings_by_language, years = _archive_years(store)
    published_works, published_expressions = _read_published(site_root)

    return CoverageReport(
        generated_at=generated_at,
        bills_total=bills_total,
        bills_by_title_language=dict(sorted(title_languages.items())),
        stages=tuple(
            StageCoverage(language=language, **counters[language])
            for language in (*LANGUAGES, UNSETTLED)
        ),
        listings_by_language=listings_by_language,
        archive_years_absent=_absent_archive_years(years),
        missing_by_year={
            year: dict(sorted(counts.items())) for year, counts in sorted(missing_by_year.items())
        },
        missing_samples=tuple(missing_samples),
        english_outcomes={name: english_outcomes.get(name, 0) for name in ENGLISH_OUTCOMES},
        gate_verdicts=dict(sorted(gate_verdicts.items())),
        published_works=published_works,
        published_expressions=published_expressions,
        expression_collisions=collisions,
        published_collisions=tuple(published_collisions),
        published_conflicts=tuple(published_conflicts),
    )


def _english_outcome(*, has_english_title: bool, referenced: int, stored: int) -> str:
    """Which of the five English outcomes one bill falls into. Exactly one, always."""
    if not has_english_title:
        return "no_english_title"
    if referenced == 0:
        return "english_titled_but_no_document_linked"
    if stored == 0:
        return "english_linked_but_absent_upstream"
    if stored < referenced:
        return "english_partial"
    return "english_stored"


def _document_languages(store: PipelineStore) -> dict[tuple[str, str], str]:
    """`(bill_slug, doc_key) -> bucket`, so a stored document can be attributed to a language.

    The bill record is the authority on a document's language (ADR-040), and a stored document is
    addressed by `doc_key` while the record knows only URLs — so the mapping has to be built once
    rather than re-derived per document.
    """
    languages: dict[tuple[str, str], str] = {}
    for slug in store.iter_bill_slugs():
        bill = store.load_bill(slug) or {}
        for document in bill.get("documents") or []:
            url = document.get("url")
            if url:
                languages[(slug, document_key(url))] = _language_of_reference(document)
    return languages


def _bar(stored: int, total: int, width: int = 18) -> str:
    """A fixed-width text bar. Empty stays visibly empty rather than rounding up to one block."""
    if total <= 0:
        return "·" * width
    filled = int(round(width * stored / total))
    if stored and filled == 0:
        filled = 1  # a nonzero share must never render as nothing
    return "█" * filled + "·" * (width - filled)


def _ratio(stored: int, total: int) -> str:
    return f"{stored:,}/{total:,}" if total else "—"


def summary_lines(report: CoverageReport) -> list[str]:
    """The report an operator actually reads after a run, for stderr.

    Per stage and per language, because that is the split the numbers mean. A single "coverage: 78%"
    would be the one number this whole module exists to avoid printing.
    """
    lines = [
        f"{report.bills_total:,} bills · "
        f"{report.stored:,}/{report.referenced:,} documents stored"
        + (f" · {report.missing:,} absent upstream" if report.missing else ""),
        "",
        f"  {'stage':<10} {'language':<10} {'coverage':<20} stored",
    ]
    stage_rows = (
        ("download", "stored", "referenced"),
        ("markdown", "markdown", "stored"),
        ("akn", "akn", "markdown"),
        ("semantic", "semantic", "akn"),
    )
    for label, got_key, of_key in stage_rows:
        for stage in report.stages:
            got = getattr(stage, got_key)
            of = getattr(stage, of_key)
            if of == 0 and got == 0:
                continue
            lines.append(
                f"  {label:<10} {stage.language:<10} {_bar(got, of):<20} {_ratio(got, of)}"
            )
        lines.append("")

    if report.published_works:
        served = ", ".join(
            f"{count:,} {language}" for language, count in report.published_expressions.items()
        )
        lines.append(
            f"  published  {report.published_works:,} works · {served or 'no expressions'}"
        )
    else:
        lines.append("  published  nothing published yet")

    lines.append("")
    for language, years in report.archive_years_absent.items():
        span = ", ".join(str(year) for year in years)
        lines.append(f"  ! {len(years)} archive year(s) absent from {language}: {span}")
    if report.missing:
        lines.append(f"  ! {report.missing:,} document(s) linked upstream but not held there")
    if report.published_collisions:
        harmless = len(report.published_collisions) - len(report.published_conflicts)
        lines.append(
            f"  ! {len(report.published_collisions):,} reading(s) dropped at publish: their "
            "expression iri is already taken"
        )
        lines.append(
            f"    of those, {len(report.published_conflicts)} lose differing text; "
            f"{harmless:,} are the same file linked from both chambers"
        )
    for stage in report.stages:
        if stage.not_read_yet:
            lines.append(
                f"  ! {stage.not_read_yet:,} {stage.language} document(s) stored but not read"
            )
    scans = sum(stage.no_text_layer for stage in report.stages)
    if scans:
        lines.append(
            f"  · {scans:,} document(s) have no text layer — only the cross-check tier "
            "can read them; re-running the reader will not"
        )
    return lines


def _table(headers: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> list[str]:
    """A GitHub-flavoured Markdown table, right-aligning every column but the first."""
    align = ["---", *(["--:"] * (len(headers) - 1))]
    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(align) + " |",
        *("| " + " | ".join(row) + " |" for row in rows),
    ]


def render_markdown(report: CoverageReport) -> str:
    """The report as Markdown, written to a file so two runs can be diffed.

    Ordered by what a reader needs first: the totals, then the stages, then the gaps grouped by
    cause. Absolute counts throughout and no percentages except where a ratio is the point — a
    percentage that drifts by one document between runs makes a diff noisy for no information.
    """
    out: list[str] = [
        "# Corpus coverage",
        "",
        "<!-- Generated by `billwatcher coverage`. Do not edit; re-run the command. -->",
        "",
        "## Totals",
        "",
        *_table(
            ("Measure", "Count"),
            [
                ("Bills", f"{report.bills_total:,}"),
                ("Documents referenced", f"{report.referenced:,}"),
                ("Documents stored", f"{report.stored:,}"),
                ("Documents absent upstream", f"{report.missing:,}"),
                ("Listing snapshots", f"{sum(report.listings_by_language.values()):,}"),
            ],
        ),
        "",
        "Bills by the languages they carry a title in:",
        "",
        *_table(
            ("Title languages", "Bills"),
            [
                (f"`{languages}`", f"{count:,}")
                for languages, count in report.bills_by_title_language.items()
            ],
        ),
        "",
        "## Stages",
        "",
        "Each stage's denominator is the previous stage's output, so a language is never charged",
        "for documents upstream does not publish.",
        "",
        *_table(
            (
                "Language",
                "Referenced",
                "Stored",
                "Markdown",
                "No text layer",
                "Akoma Ntoso",
                "Semantic",
            ),
            [
                (
                    f"`{stage.language}`",
                    f"{stage.referenced:,}",
                    f"{stage.stored:,}",
                    f"{stage.markdown:,}",
                    f"{stage.no_text_layer:,}",
                    f"{stage.akn:,}",
                    f"{stage.semantic:,}",
                )
                for stage in report.stages
            ],
        ),
        "",
    ]

    if report.gate_verdicts:
        out += [
            "### Fidelity gate verdicts",
            "",
            *_table(
                ("Verdict", "Readings"),
                [(f"`{status}`", f"{count:,}") for status, count in report.gate_verdicts.items()],
            ),
            "",
        ]

    served = [
        (f"`{language}`", f"{count:,}") for language, count in report.published_expressions.items()
    ]
    out += [
        "### Published dataset",
        "",
        (
            f"{report.published_works:,} works currently served."
            if report.published_works
            else "Nothing published yet."
        ),
        "",
    ]
    if served:
        out += [*_table(("Expression language", "Expressions"), served), ""]

    out += ["## Gaps, by cause", "", "### Absent upstream — not recoverable by re-running", ""]
    if report.missing or report.archive_years_absent:
        if report.missing:
            out += [
                f"{report.missing:,} document(s) are linked from a listing but not held by "
                "Parliament.",
                "",
                *_table(
                    ("Bill year", *(f"`{lang}`" for lang in (*LANGUAGES, UNSETTLED)), "Total"),
                    [
                        (
                            year,
                            *(
                                f"{counts.get(lang, 0):,}" if counts.get(lang) else "—"
                                for lang in (*LANGUAGES, UNSETTLED)
                            ),
                            f"{sum(counts.values()):,}",
                        )
                        for year, counts in sorted(
                            report.missing_by_year.items(),
                            key=lambda item: -sum(item[1].values()),
                        )
                    ],
                ),
                "",
            ]
        for language, years in report.archive_years_absent.items():
            out += [
                f"`{language}` archive tree offers no node for "
                f"{len(years)} year(s) the other language lists: "
                + ", ".join(str(year) for year in years),
                "",
            ]
    else:
        out += ["None.", ""]

    out += [
        "### English coverage, per bill",
        "",
        *_table(
            ("Outcome", "Bills"),
            [
                (name.replace("_", " "), f"{count:,}")
                for name, count in report.english_outcomes.items()
            ],
        ),
        "",
    ]

    out += ["### Not yet run — actionable", ""]
    pending = [
        f"{stage.not_read_yet:,} `{stage.language}` document(s) stored but not read"
        for stage in report.stages
        if stage.not_read_yet
    ] + [
        f"{stage.markdown - stage.akn:,} `{stage.language}` reading(s) without Akoma Ntoso"
        for stage in report.stages
        if stage.markdown > stage.akn
    ]
    out += ([f"- {item}" for item in pending] if pending else ["None."]) + [""]

    scans = sum(stage.no_text_layer for stage in report.stages)
    if scans:
        out += [
            "### Scanned — needs the cross-check tier, not another run",
            "",
            f"{scans:,} stored document(s) are image-only scans with no text layer. The local "
            "reader (ADR-035) found nothing in them and correctly wrote nothing, so re-running "
            "`extract-markdown` will never produce a reading. These are the documents "
            "`structure-handoff` and the cross-check tier exist for.",
            "",
        ]

    if report.published_collisions:
        harmless = len(report.published_collisions) - len(report.published_conflicts)
        out += [
            "### Needs a decision",
            "",
            f"{len(report.published_collisions):,} reading(s) are dropped by `publish` because "
            "another reading of the same bill and language already claims their Expression IRI. "
            "ADR-024's scheme carries no chamber component, and a bill that passes through both "
            "chambers has one document per chamber per language.",
            "",
            f"**{harmless:,} of them cost nothing**: the two chambers link the same file, so the "
            "dropped reading is byte-identical to the one that was kept.",
            "",
        ]
        if report.published_conflicts:
            out += [
                f"**{len(report.published_conflicts)} lose text that differs** — this is the real "
                "consequence of the limitation, and the served corpus is missing one version of "
                "each:",
                "",
                *(f"- `{item}`" for item in report.published_conflicts[:SAMPLE_LIMIT]),
                "",
            ]
        if report.expression_collisions:
            out += [
                f"{len(report.expression_collisions)} of these also collide among promoted Akoma "
                "Ntoso, which is what `verify` reports.",
                "",
            ]

    if report.missing_samples:
        out += [
            "## Absent documents, named",
            "",
            f"The first {len(report.missing_samples)} of {report.missing:,}, so a link can be "
            "retried by hand without re-deriving it from a bill record.",
            "",
            "```",
            *report.missing_samples,
            "```",
            "",
        ]

    # Last, not first: the body above is byte-identical between two runs that found the same
    # corpus, so `git diff` on this file shows coverage moving rather than the clock ticking.
    out += [
        "---",
        "",
        f"Generated {report.generated_at} · read-only; nothing here was written by",
        "this report. Run `billwatcher coverage` to regenerate.",
    ]
    return "\n".join(out).rstrip() + "\n"


def _documents_without_a_text_layer(store: PipelineStore) -> set[tuple[str, str]]:
    """Documents the reader opened and found no text in, from its own newest run record.

    Nothing is written for a reading that produced nothing — correctly, because blank markdown is
    not a reading of a document — so the corpus itself cannot distinguish "a scan only the
    cross-check tier can read" from "not read yet". The step knew, and said so in its manifest
    (ADR-019), which is the one place that answer survives.

    Read as a hint, never as authority: the verdict is only applied to a document that is *still*
    unread, so a stale manifest naming a document that has since been read changes nothing.
    """
    manifest = store.latest_manifest(step="extract-markdown")
    if not manifest:
        return set()
    unreadable: set[tuple[str, str]] = set()
    for failure in manifest.get("failures") or []:
        if not isinstance(failure, dict):
            continue
        if failure.get("reason") == NO_TEXT_LAYER:
            slug, key = failure.get("bill_slug"), failure.get("doc_key")
            if isinstance(slug, str) and isinstance(key, str):
                unreadable.add((slug, key))
    return unreadable
