"""The pipeline's whole command surface: local files in, local files out.

One command per step, each one runnable on its own and safe to re-run. Only `fetch-listings` and
`fetch-documents` touch the network, and both refuse to unless an operator says so in the same
breath (`--approve-live`, or `DOWNLOAD_ENABLED=true`). Everything else reads the corpus on disk.

Every step prints one JSON object on stdout and everything else on stderr, so a step can be piped
into `jq` while a fifty-minute download still narrates itself. Every step also leaves a manifest in
the corpus recording what it did and which code versions did it, which is what makes a build
auditable after the fact rather than only while it is running.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from billwatcher.audit import audit_structure
from billwatcher.audit import render_markdown as render_audit_markdown
from billwatcher.audit import summary_lines as audit_summary_lines
from billwatcher.config import get_settings
from billwatcher.coverage import build_report, render_markdown, summary_lines
from billwatcher.download.documents import DocumentImportError, fetch_documents, import_document
from billwatcher.download.fetch import Fetcher
from billwatcher.download.listings import fetch_listings, parse_listings
from billwatcher.download.policy import CrawlPolicy
from billwatcher.frbr import LANGUAGES
from billwatcher.graph.convert import convert_to_akn
from billwatcher.graph.handoff import (
    FileStructureExtractor,
    HandoffError,
    write_handoff,
)
from billwatcher.graph.semantic import generate_semantic_files
from billwatcher.graph.structure import MarkdownStructureExtractor, RegexMarkdownStructureExtractor
from billwatcher.markdown.crosscheck import (
    CROSSCHECK_FILENAME,
    MIN_AGREEMENT,
    cross_reference,
    import_crosscheck,
    import_crosscheck_tree,
)
from billwatcher.markdown.imports import (
    MarkdownImportError,
    Producer,
    import_markdown,
    import_markdown_tree,
)
from billwatcher.markdown.reading import extract_markdown
from billwatcher.publish.dataset import (
    StaticExportRefused,
    publish_dataset,
    require_publication_rights,
)
from billwatcher.reporting import (
    StepFailure,
    StepResult,
    manifest_payload,
    run_id_for,
)
from billwatcher.store import FileStore, build_pipeline_store
from billwatcher.verify import verify_store
from billwatcher.version import (
    AKN_VERSION,
    CROSSCHECK_VERSION,
    LAYOUT_EXTRACTOR_VERSION,
    LOCAL_READING_VERSION,
    SEMANTIC_VERSION,
    STATIC_EXPORT_VERSION,
    STRUCTURE_GATE_VERSION,
    __version__,
)

app = typer.Typer(
    no_args_is_help=True,
    help="Download Parliament's bills, read them into markdown, publish them as a graph.",
)


def _policy() -> CrawlPolicy:
    settings = get_settings()
    return CrawlPolicy(
        user_agent=(
            f"BillWatcherNext/{__version__} (+{settings.site_base_url}/about; "
            f"contact: {settings.contact_email})"
        ),
        delay_seconds=settings.download_delay_seconds,
        # SCRAPE_CONCURRENCY is deliberately not passed on. Nothing in this pipeline fetches in
        # parallel — every live step drives one `Fetcher`, and so one `httpx.Client`, through a
        # sequential loop — so accepting the setting here only advertised a knob that did nothing:
        # an operator who raised it to shorten a fifty-minute download waited the same fifty
        # minutes. The real rate limit is the spacing in `Fetcher.get`, and `DOWNLOAD_DELAY_SECONDS`
        # is floored at two seconds on purpose (`CrawlPolicy.__post_init__`), which is a promise
        # about the load Parliament sees that concurrent requests could not keep.
        max_response_bytes=settings.document_max_bytes,
        ca_bundle=settings.upstream_ca_bundle,
    )


def _store() -> FileStore:
    store = build_pipeline_store(get_settings())
    assert isinstance(store, FileStore)  # the only backend built; narrows for `save_manifest`
    return store


def _progress(message: str) -> None:
    """Live commentary for the long steps, on stderr so stdout stays one JSON object.

    A cold document download is ~1,295 requests two seconds apart: without this, the run's first
    and only output arrived fifty minutes in, which is indistinguishable from a hung process.
    """
    typer.echo(message, err=True)


def _require_live_approval(approve_live: bool) -> None:
    settings = get_settings()
    if not (settings.download_enabled or approve_live):
        raise typer.BadParameter(
            "live fetch is disabled; set DOWNLOAD_ENABLED=true or pass --approve-live"
        )


def _report(
    store: FileStore,
    result: StepResult,
    *,
    step: str,
    code_versions: dict[str, str],
    started_at: datetime,
    payload: dict[str, Any] | None = None,
    progress_counts: tuple[str, ...] = (),
) -> None:
    """Echo the histogram, name every failure on stderr, and leave a manifest behind.

    A count alone is not a report: an operator needs to know *which* document failed to act on it,
    and a later reader needs the run on the record. Failures go to stderr so the stdout line stays
    one parseable JSON object, matching the rest of this CLI.

    `progress_counts` names the counters that mean "this step accomplished something". When they are
    all zero *and* something failed, the step exits non-zero. A partial failure still exits 0 — a
    handful of unreachable PDFs in a 2,400-document crawl is normal and resumable — but a step that
    achieved nothing at all is a misconfiguration, and `make download` chains the live steps, so
    reporting success for it sends the next step out over the same broken setup. This is not
    hypothetical: a crawl that failed all nine targets on an incomplete certificate chain exited 0.
    """
    for failure in result.failures:
        typer.echo(f"FAILED {failure.label}: {failure.reason}", err=True)
    store.save_manifest(
        step=step,
        run_id=run_id_for(started_at),
        payload=manifest_payload(result, code_versions=code_versions, started_at=started_at),
    )
    typer.echo(json.dumps(payload if payload is not None else result.as_payload()))
    made_progress = any(result.counts.get(name, 0) for name in progress_counts)
    if progress_counts and result.failures and not made_progress:
        typer.echo(
            f"{step} accomplished nothing: {len(result.failures)} failure(s) and no progress",
            err=True,
        )
        raise typer.Exit(1)


@app.command("fetch-listings")
def fetch_listings_command(
    approve_live: bool = typer.Option(False, "--approve-live"),
    archive_years: int | None = typer.Option(
        None, "--archive-years", help="Read only the newest N archived years instead of all"
    ),
    refetch_archive: bool = typer.Option(
        False,
        "--refetch-archive",
        help="Re-download closed archive years that are already stored (default: skip them)",
    ),
) -> None:
    """Stage 1a: fetch robots.txt, both current listings, and the whole archive tree, to files.

    Resumable by default: a closed archive year already stored is skipped. The current listings,
    the archive indices and the current year are always re-fetched, because they are how new bills
    and new years are discovered.
    """
    _require_live_approval(approve_live)
    started_at = datetime.now(UTC)
    store = _store()
    with Fetcher(_policy()) as fetcher:
        result = fetch_listings(
            fetcher,
            store,
            archive_year_limit=archive_years,
            skip_existing=not refetch_archive,
            progress=_progress,
        )
    _report(
        store,
        result,
        step="fetch-listings",
        code_versions={"billwatcher": __version__},
        started_at=started_at,
        progress_counts=("fetched", "skipped"),
    )


@app.command("parse-listings")
def parse_listings_command() -> None:
    """Stage 1b: offline. Parse every stored listing snapshot into bills/<slug>/bill.json."""
    started_at = datetime.now(UTC)
    store = _store()
    result = parse_listings(store)
    _report(
        store,
        result,
        step="parse-listings",
        code_versions={"billwatcher": __version__},
        started_at=started_at,
    )


@app.command("fetch-documents")
def fetch_documents_command(
    approve_live: bool = typer.Option(False, "--approve-live"),
) -> None:
    """Stage 1c: download every document PDF named in bills/*/bill.json, skipping what exists."""
    _require_live_approval(approve_live)
    started_at = datetime.now(UTC)
    store = _store()
    with Fetcher(_policy()) as fetcher:
        result = fetch_documents(fetcher, store, progress=_progress)
    _report(
        store,
        result,
        step="fetch-documents",
        code_versions={"billwatcher": __version__},
        started_at=started_at,
        progress_counts=("downloaded", "skipped"),
    )


@app.command("import-document")
def import_document_command(
    source: Path = typer.Option(..., "--source", help="The PDF file to import"),
    bill: str = typer.Option(..., "--bill", help="Bill slug, e.g. dr-1-2006"),
    url: str = typer.Option(..., "--url", help="The document URL the bill's record names"),
    via: str = typer.Option(..., "--via", help="Where the bytes came from, e.g. a mirror URL"),
    replace: bool = typer.Option(False, "--replace", help="Overwrite an already-stored document"),
) -> None:
    """Record a PDF obtained outside the crawler, under the identity its URL already has.

    For a document whose official link is dead but whose bytes were recovered elsewhere — the
    Wayback Machine, a library mirror, a paper file scanned by hand. The URL must be one the
    bill's own record names, so the import can never invent a document, and --via records where
    the bytes actually came from."""
    started_at = datetime.now(UTC)
    store = _store()
    try:
        detail = import_document(
            store, bill_slug=bill, url=url, content=source.read_bytes(), via=via, replace=replace
        )
    except (DocumentImportError, OSError) as error:
        typer.echo(f"FAIL: {error}", err=True)
        raise typer.Exit(2) from None
    _report(
        store,
        StepResult(counts={"imported": 1}),
        step="import-document",
        code_versions={"billwatcher": __version__},
        started_at=started_at,
        payload=detail,
    )


@app.command("extract-markdown")
def extract_markdown_command(
    language: str = typer.Option(
        ...,
        "--language",
        help=(
            f"Fallback for documents whose listing language is unrecorded; one of "
            f"{sorted(LANGUAGES)}"
        ),
    ),
    replace_foreign: bool = typer.Option(
        False,
        "--replace-foreign",
        help="Re-read documents whose markdown another tool produced, discarding that reading",
    ),
) -> None:
    """Stage 2: offline. Read every stored PDF locally into markdown (ADR-035).

    No network and no model. The geometric reader of ADR-016 does the reading — which matters,
    because a marginal note shares a baseline with the provision it annotates and a naive reader
    splices one into the other — and this records the result through the same import path a
    hand-produced reading uses, provenance and all. Reads the whole corpus in minutes.

    Each document is read in the language of the listing that named it, which the corpus records
    per document — the corpus holds both published languages (ADR-040). `--language` is only the
    fallback for the documents that leaves unsettled, and the run reports how many there were.

    Documents whose reading looks unreliable are counted as `suspect` and named rather than
    hidden: that is the list worth reading by hand, and the list `structure-handoff` exists for.

    A document whose markdown some other tool produced — anything put back through
    `import-markdown` — is counted as `kept_foreign` and left alone. Re-reading it would replace a
    reading someone chose to make with the cheap local one, which is the opposite of why that
    command exists. `--replace-foreign` asks for exactly that, for an operator who wants the local
    reading back.
    """
    if language not in LANGUAGES:
        typer.echo(f"FAIL: {language!r} is not one of {sorted(LANGUAGES)}", err=True)
        raise typer.Exit(2)
    started_at = datetime.now(UTC)
    store = _store()
    result = extract_markdown(
        store, language=language, progress=_progress, replace_foreign=replace_foreign
    )
    _report(
        store,
        result,
        step="extract-markdown",
        code_versions={
            "billwatcher": __version__,
            "layout_extractor": LAYOUT_EXTRACTOR_VERSION,
            "local_reading": LOCAL_READING_VERSION,
        },
        started_at=started_at,
    )


@app.command("import-markdown")
def import_markdown_command(
    source: Path = typer.Option(..., "--source", help="A markdown file, or a tree of them"),
    language: str = typer.Option(..., "--language", help=f"One of {sorted(LANGUAGES)}"),
    tool: str = typer.Option(..., "--tool", help="What produced the markdown, e.g. 'mineru'"),
    model: str | None = typer.Option(None, "--model", help="The model it used, if any"),
    tool_version: str | None = typer.Option(None, "--tool-version"),
    bill: str | None = typer.Option(None, "--bill", help="Bill slug; single-file import only"),
    document_url: str | None = typer.Option(None, "--document-url"),
    doc_key: str | None = typer.Option(None, "--doc-key"),
    version: int = typer.Option(1, "--version"),
) -> None:
    """Record a markdown reading of a stored document, with the provenance that makes it usable.

    A reading produced anywhere else — another tool, another machine, a person — enters the corpus
    here rather than being copied in, and this is also where the document's language enters the
    system: that language becomes a permanent part of the Expression IRI, so it is declared rather
    than guessed, and cross-checked against the document's own Arrangement heading.

    Pass a directory to --source to import a whole tree laid out as the store's own
    <bill-slug>/<doc-key>/v<NNN>/document.md; pass a file with --bill and one of --document-url or
    --doc-key for a single document."""
    producer = Producer(tool=tool, model_id=model, version=tool_version)
    started_at = datetime.now(UTC)
    store = _store()
    try:
        if source.is_dir():
            report = import_markdown_tree(
                store, source_root=source, language=language, producer=producer
            )
            payload, warnings = report.as_payload(), report.warnings
            result = report.as_step_result()
        else:
            if not bill:
                raise MarkdownImportError("a single-file import needs --bill")
            imported = import_markdown(
                store,
                bill_slug=bill,
                language=language,
                producer=producer,
                doc_key=doc_key,
                document_url=document_url,
                version=version,
                markdown_path=source,
            )
            payload = imported.as_detail()
            warnings = (
                (
                    StepFailure(
                        bill_slug=imported.bill_slug,
                        doc_key=imported.doc_key,
                        version=imported.version,
                        reason=imported.language_disagreement,
                    ),
                )
                if imported.language_disagreement is not None
                else ()
            )
            result = StepResult(counts={"imported": 1, "changed": int(imported.changed)})
    except MarkdownImportError as error:
        typer.echo(f"FAIL: {error}", err=True)
        raise typer.Exit(2) from None
    for warning in warnings:
        typer.echo(
            f"WARNING {warning.bill_slug}/{warning.doc_key}/v{warning.version:03d}: "
            f"{warning.reason}",
            err=True,
        )
    if source.is_dir():
        for name in report.unrecognised:
            typer.echo(f"WARNING source file matched no stored document: {name}", err=True)
    _report(
        store,
        result,
        step="import-markdown",
        code_versions={"billwatcher": __version__},
        started_at=started_at,
        payload=payload,
    )


@app.command("import-crosscheck")
def import_crosscheck_command(
    source: Path = typer.Option(..., "--source", help="A markdown file, or a tree of them"),
    tool: str = typer.Option(..., "--tool", help="What produced this reading, e.g. 'mineru'"),
    model: str | None = typer.Option(None, "--model", help="The model it used, if any"),
    tool_version: str | None = typer.Option(None, "--tool-version"),
    filename: str = typer.Option(
        CROSSCHECK_FILENAME, "--filename", help="What the second reader named its files"
    ),
    bill: str | None = typer.Option(None, "--bill", help="Bill slug; single-file import only"),
    document_url: str | None = typer.Option(None, "--document-url"),
    doc_key: str | None = typer.Option(None, "--doc-key"),
    version: int = typer.Option(1, "--version"),
) -> None:
    """Record a *second* reading of a stored document, beside the first rather than over it.

    This is where MinerU's reading lands — or any second reader's, including a model an operator
    drives themselves (ADR-035). It writes `document.crosscheck.md` and its own provenance, and it
    never touches `document.md`: the whole value of a second reading is the disagreement, and
    overwriting the first destroys it. Run `cross-reference` afterwards to compare them.

    No --language, deliberately. The language is a permanent component of the Expression IRI and
    the reading that entered through `import-markdown` already declared it; a cross-check is
    evidence about the text, never about the document's identity.
    """
    producer = Producer(tool=tool, model_id=model, version=tool_version)
    started_at = datetime.now(UTC)
    store = _store()
    try:
        if source.is_dir():
            result = import_crosscheck_tree(
                store,
                source_root=source,
                producer=producer,
                filename=filename,
                progress=_progress,
            )
        else:
            if not bill:
                raise MarkdownImportError("a single-file import needs --bill")
            changed = import_crosscheck(
                store,
                bill_slug=bill,
                producer=producer,
                doc_key=doc_key,
                document_url=document_url,
                version=version,
                markdown_path=source,
            )
            result = StepResult(counts={"imported": 1, "changed": int(changed)})
    except MarkdownImportError as error:
        typer.echo(f"FAIL: {error}", err=True)
        raise typer.Exit(2) from None
    _report(
        store,
        result,
        step="import-crosscheck",
        code_versions={"billwatcher": __version__},
        started_at=started_at,
    )


@app.command("cross-reference")
def cross_reference_command(
    min_agreement: float = typer.Option(
        MIN_AGREEMENT,
        "--min-agreement",
        help="Below this symmetric word overlap, two readings disagree about the substance",
    ),
) -> None:
    """Stage 2: offline. Compare each document's two readings and name where they disagree.

    Gate P1 scores a provision tree against the markdown, never against the page, so whatever
    produced that markdown is unchecked. Two readings with disjoint failure modes are what closes
    that hole (ADR-035), and this is the comparison over them.

    It writes nothing and it never promotes one reading over the other: when two readings disagree
    this step knows that one of them is wrong, not which. Every divergence is named for a person to
    work through, worst agreement first. Documents with only one reading are counted as
    `unchecked`, not reported as failures — that is the ordinary state of a corpus cross-checked
    incrementally.
    """
    if not 0.0 <= min_agreement <= 1.0:
        typer.echo(f"FAIL: --min-agreement must be between 0 and 1, got {min_agreement}", err=True)
        raise typer.Exit(2)
    started_at = datetime.now(UTC)
    store = _store()
    result = cross_reference(store, min_agreement=min_agreement, progress=_progress)
    _report(
        store,
        result,
        step="cross-reference",
        code_versions={"billwatcher": __version__, "crosscheck": CROSSCHECK_VERSION},
        started_at=started_at,
    )


@app.command("verify")
def verify_command(
    strict: bool = typer.Option(
        False, "--strict", help="Also report artifacts that are stale rather than damaged"
    ),
) -> None:
    """Re-hash the stored corpus against its own sidecars, provenance records and gate verdicts.

    Offline: no network, no LLM, no database. Exits non-zero on any issue. A clean run certifies
    only what this command can recompute from stored files — it says nothing about whether a
    reading is a correct reading of the printed page, which is Gate P1's separate judgement."""
    issues = verify_store(
        _store(), strict=strict, min_text_coverage=get_settings().structure_gate_min_text_coverage
    )
    for issue in issues:
        typer.echo(issue, err=True)
    typer.echo(json.dumps({"issues": len(issues)}))
    if issues:
        raise typer.Exit(1)


@app.command("coverage")
def coverage_command(
    markdown_out: Path | None = typer.Option(
        None,
        "--markdown",
        help="Also write the report as Markdown to this path, for diffing between runs",
    ),
) -> None:
    """What the corpus holds, what upstream does not publish, and what has not been run yet.

    Offline and read-only: writes nothing into the corpus, leaves no manifest, and always exits 0.
    A report is not a gate — "the English half is unread" is a finding to act on, not a reason to
    fail a build that described itself accurately.

    Counts are per stage and per language, never rolled into one percentage: a corpus 97% downloaded
    and 50% read is not 73% anything, and the three causes of a gap — stored, absent upstream, not
    yet run — want different responses.
    """
    settings = get_settings()
    report = build_report(_store(), site_root=settings.site_root)
    for line in summary_lines(report):
        typer.echo(line, err=True)
    if markdown_out is not None:
        markdown_out.parent.mkdir(parents=True, exist_ok=True)
        markdown_out.write_text(render_markdown(report), encoding="utf-8")
        typer.echo(f"wrote {markdown_out}", err=True)
    typer.echo(json.dumps(report.as_payload()))


@app.command("audit-structure")
def audit_structure_command(
    markdown_out: Path | None = typer.Option(
        None,
        "--markdown",
        help="Also write the report as Markdown to this path, for diffing between commits",
    ),
) -> None:
    """Parse and gate every stored reading with the code in this checkout, against the recorded
    verdicts.

    Offline, read-only, always exits 0. This is the measurement a parser change is judged by: how
    many readings would pass now, which documents that passed would stop, and which finding
    families remain — the loop that used to live in scratch scripts, made a step.
    """
    settings = get_settings()
    report = audit_structure(
        _store(),
        extractor=RegexMarkdownStructureExtractor(),
        min_text_coverage=settings.structure_gate_min_text_coverage,
    )
    for line in audit_summary_lines(report):
        typer.echo(line, err=True)
    if markdown_out is not None:
        markdown_out.parent.mkdir(parents=True, exist_ok=True)
        markdown_out.write_text(render_audit_markdown(report), encoding="utf-8")
        typer.echo(f"wrote {markdown_out}", err=True)
    typer.echo(json.dumps(report.as_payload()))


@app.command("structure-handoff")
def structure_handoff_command(
    out: Path = typer.Option(..., "--out", help="Directory to write the work packets into"),
    overwrite_answers: bool = typer.Option(
        False,
        "--overwrite-answers",
        help="Delete structure.json answers already in the tree instead of keeping them",
    ),
) -> None:
    """Stage 3a, the good path: one self-contained work packet per document, for a reader that is
    not a regex — a coding agent, or a person.

    Each packet is a directory holding the document's markdown and an INSTRUCTION.md naming exactly
    the JSON to write beside it. Feed the finished tree back with
    `convert-to-akn --from-handoff`, which runs the identical conversion, eId assignment and
    Gate P1 as the deterministic path. Existing answers are preserved unless --overwrite-answers:
    the answer is the expensive part.
    """
    started_at = datetime.now(UTC)
    store = _store()
    result = write_handoff(store, root=out, progress=_progress, overwrite_answers=overwrite_answers)
    _report(
        store,
        result,
        step="structure-handoff",
        code_versions={"billwatcher": __version__},
        started_at=started_at,
    )


@app.command("convert-to-akn")
def convert_to_akn_command(
    from_handoff: Path | None = typer.Option(
        None,
        "--from-handoff",
        help="Read structures from a handoff tree instead of the deterministic parser",
    ),
    produced_by: str | None = typer.Option(
        None,
        "--produced-by",
        help="What produced the handoff answers, e.g. 'claude-code'; recorded in provenance",
    ),
) -> None:
    """Stage 3a: read each document's provision structure and write Akoma Ntoso XML beside it.

    Two model-free routes in, and the choice is recorded rather than blended: without
    `--from-handoff` the deterministic parser reads the markdown directly, which is offline, free
    and weakest on the Arrangement/body split; with it, the answers in a `structure-handoff` tree
    are read back through the identical conversion, eId assignment, gate and provenance path, so a
    hand- or agent-produced reading is judged exactly as strictly and stays distinguishable in the
    record.

    A document whose reading cannot account for its source is rejected by Gate P1: the verdict is
    written to `document.structure.gate.json` either way and the rejected render is kept beside
    it, but
    no `document.akn.xml` appears for later steps to pick up.
    """
    settings = get_settings()
    extractor: MarkdownStructureExtractor
    if from_handoff is not None:
        try:
            extractor = FileStructureExtractor(root=from_handoff, model_id=produced_by)
        except HandoffError as error:
            typer.echo(f"FAIL: {error}", err=True)
            raise typer.Exit(2) from None
    else:
        extractor = RegexMarkdownStructureExtractor()
    started_at = datetime.now(UTC)
    store = _store()
    result = convert_to_akn(
        store,
        extractor=extractor,
        min_text_coverage=settings.structure_gate_min_text_coverage,
    )
    _report(
        store,
        result,
        step="convert-to-akn",
        code_versions={
            "billwatcher": __version__,
            "akn": AKN_VERSION,
            "structure_gate": STRUCTURE_GATE_VERSION,
        },
        started_at=started_at,
    )


@app.command("generate-semantic")
def generate_semantic_command() -> None:
    """Stage 3b: offline. Read each document's Akoma Ntoso XML and write ELI-style JSON-LD and
    RDF N-Quads beside it. Both are serialised from one graph, so they cannot disagree."""
    started_at = datetime.now(UTC)
    store = _store()
    result = generate_semantic_files(store, base_iri=get_settings().site_base_url)
    _report(
        store,
        result,
        step="generate-semantic",
        code_versions={"billwatcher": __version__, "semantic": SEMANTIC_VERSION},
        started_at=started_at,
    )


@app.command("publish")
def publish_command(
    prune: bool = typer.Option(
        False,
        "--prune",
        help="Also delete files this step owns but no longer publishes (default: report only)",
    ),
) -> None:
    """Stage 4: write the gate-passing corpus into SITE_ROOT, the tree GitHub Pages serves.

    This creates the publishable unit, so the rights confirmations are mandatory in every
    environment — in this repository the tree is committed, which makes a local publish one push
    away from a permanent one.

    Touches only the dataset entries: `akn/`, `definitions/`, `index.json`, `checksums.sha256` and
    `CNAME`. The compiled frontend shares the same directory and is left alone.

    **Additive by default.** Files this step owns but no longer publishes are reported by name and
    left in place; `--prune` deletes them. A published tree can outlive the corpus that produced
    it, so a build has to be safe to run against one that is mid-repair.
    """
    settings = get_settings()
    try:
        require_publication_rights(settings)
    except StaticExportRefused as error:
        typer.echo(f"FAIL: {error}", err=True)
        raise typer.Exit(2) from None
    started_at = datetime.now(UTC)
    store = _store()
    result = publish_dataset(
        store,
        site_root=settings.site_root,
        prefix=settings.cname_host,
        publication_mode=settings.publication_mode,
        representations=settings.site_representations,
        prune=prune,
    )
    _report(
        store,
        result,
        step="publish",
        code_versions={"billwatcher": __version__, "static_export": STATIC_EXPORT_VERSION},
        started_at=started_at,
    )
