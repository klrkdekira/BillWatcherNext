"""CLI for the file-first pipeline. No database, no object store, no PDF parsing.

Registered as a sub-app (`billwatcher pipeline ...`) of the main CLI, but self-contained: nothing
here imports `billwatcher.db`, `billwatcher.models`, or any Postgres-backed scraper/jobs module.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from billwatcher.config import get_settings
from billwatcher.pipeline.akn import convert_to_akn
from billwatcher.pipeline.akn_llm import StructureExtractorUnavailable, build_structure_extractor
from billwatcher.pipeline.documents import fetch_documents
from billwatcher.pipeline.frbr import LANGUAGES
from billwatcher.pipeline.import_markdown import (
    MarkdownImportError,
    Producer,
    import_markdown,
    import_markdown_tree,
)
from billwatcher.pipeline.listings import fetch_listings, parse_listings
from billwatcher.pipeline.reporting import (
    StepFailure,
    StepResult,
    manifest_payload,
    run_id_for,
)
from billwatcher.pipeline.semantic import generate_semantic_files
from billwatcher.pipeline.store import FileStore, build_pipeline_store
from billwatcher.pipeline.verify import verify_store
from billwatcher.scraper.fetch import Fetcher
from billwatcher.scraper.policy import CrawlPolicy
from billwatcher.version import (
    AKN_FIDELITY_GATE_VERSION,
    AKN_VERSION,
    SEMANTIC_VERSION,
    __version__,
)

app = typer.Typer(no_args_is_help=True, help="File-first pipeline: listings -> bills -> documents.")


def _policy() -> CrawlPolicy:
    settings = get_settings()
    return CrawlPolicy(
        user_agent=(
            f"BillWatcherNext/0.1 (+{settings.public_base_url}/about; "
            f"contact: {settings.contact_email})"
        ),
        delay_seconds=settings.scrape_delay_seconds,
        concurrency=settings.scrape_concurrency,
        max_response_bytes=settings.document_max_bytes,
        ca_bundle=settings.upstream_ca_bundle,
    )


def _store() -> FileStore:
    store = build_pipeline_store(get_settings())
    assert isinstance(store, FileStore)  # the only backend built; narrows for `save_manifest`
    return store


def _require_live_approval(approve_live: bool) -> None:
    settings = get_settings()
    if not (settings.scrape_enabled or approve_live):
        raise typer.BadParameter(
            "live fetch is disabled; set SCRAPE_ENABLED=true or pass --approve-live"
        )


def _report(
    store: FileStore,
    result: StepResult,
    *,
    step: str,
    code_versions: dict[str, str],
    started_at: datetime,
    payload: dict[str, Any] | None = None,
) -> None:
    """Echo the histogram, name every failure on stderr, and leave a manifest behind.

    A count alone is not a report: an operator needs to know *which* document failed to act on it,
    and a later reader needs the run on the record. Failures go to stderr so the stdout line stays
    one parseable JSON object, matching the rest of this CLI.
    """
    for failure in result.failures:
        typer.echo(
            f"FAILED {failure.bill_slug}/{failure.doc_key}/v{failure.version:03d}: "
            f"{failure.reason}",
            err=True,
        )
    store.save_manifest(
        step=step,
        run_id=run_id_for(started_at),
        payload=manifest_payload(result, code_versions=code_versions, started_at=started_at),
    )
    typer.echo(json.dumps(payload if payload is not None else result.as_payload()))


@app.command("fetch-listings")
def fetch_listings_command(
    approve_live: bool = typer.Option(False, "--approve-live"),
    archive_years: int | None = typer.Option(
        None, "--archive-years", help="Read only the newest N archived years instead of all"
    ),
) -> None:
    """Step 1: fetch robots.txt, both current listings, and the whole archive tree, to files."""
    _require_live_approval(approve_live)
    with Fetcher(_policy()) as fetcher:
        counts = fetch_listings(fetcher, _store(), archive_year_limit=archive_years)
    typer.echo(json.dumps(counts))


@app.command("parse-listings")
def parse_listings_command() -> None:
    """Step 2: offline. Parse every stored listing snapshot into bills/<slug>/bill.json."""
    counts = parse_listings(_store())
    typer.echo(json.dumps(counts))


@app.command("fetch-documents")
def fetch_documents_command(
    approve_live: bool = typer.Option(False, "--approve-live"),
) -> None:
    """Step 3: download every document URL found in bills/*/bill.json, skipping what exists."""
    _require_live_approval(approve_live)
    with Fetcher(_policy()) as fetcher:
        counts = fetch_documents(fetcher, _store())
    typer.echo(json.dumps(counts))


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

    PDF extraction is not this pipeline's job (ADR-021) — the operator runs their own endpoint and
    brings the markdown here. This is where it enters the store, and where the document's language
    enters the system: that language becomes a permanent part of the Expression IRI, so it is
    declared rather than guessed, and cross-checked against the document's own Arrangement heading.

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
        _store(), strict=strict, min_text_coverage=get_settings().akn_gate_min_text_coverage
    )
    for issue in issues:
        typer.echo(issue, err=True)
    typer.echo(json.dumps({"issues": len(issues)}))
    if issues:
        raise typer.Exit(1)


@app.command("convert-to-akn")
def convert_to_akn_command() -> None:
    """Step 4: read each document's markdown structure with the configured vLLM endpoint and
    write Akoma Ntoso XML beside it. Needs AKN_LLM_ENABLED/AKN_LLM_BASE_URL/AKN_LLM_MODEL_ID;
    never contacts Parliament, but does call that endpoint for each eligible document.

    A document whose reading cannot account for its source is rejected by Gate P1: its verdict is
    written to document.akn.gate.json either way, and the rejected render is kept beside it, but no
    document.akn.xml appears for later steps to pick up."""
    settings = get_settings()
    try:
        extractor = build_structure_extractor(settings)
    except StructureExtractorUnavailable as error:
        typer.echo(f"FAIL: {error}", err=True)
        raise typer.Exit(2) from None
    started_at = datetime.now(UTC)
    store = _store()
    result = convert_to_akn(
        store,
        extractor=extractor,
        min_text_coverage=settings.akn_gate_min_text_coverage,
    )
    _report(
        store,
        result,
        step="convert-to-akn",
        code_versions={
            "billwatcher": __version__,
            "akn": AKN_VERSION,
            "akn_fidelity_gate": AKN_FIDELITY_GATE_VERSION,
        },
        started_at=started_at,
    )


@app.command("generate-semantic")
def generate_semantic_command() -> None:
    """Step 5: offline. Read each document's Akoma Ntoso XML and write ELI-style JSON-LD and
    RDF N-Quads beside it (document.jsonld, document.nq). No LLM, no network."""
    started_at = datetime.now(UTC)
    store = _store()
    result = generate_semantic_files(store, base_iri=get_settings().public_base_url)
    _report(
        store,
        result,
        step="generate-semantic",
        code_versions={"billwatcher": __version__, "semantic": SEMANTIC_VERSION},
        started_at=started_at,
    )
