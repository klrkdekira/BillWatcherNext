"""Stage 3's step: markdown in, a gated reading and its Akoma Ntoso rendering out.

The orchestration only. Reading the structure is `graph.structure`, judging it is `graph.fidelity`
(Gate P1), serialising it is `graph.render`, and none of those know about the store; this module is
what walks the corpus, decides what is stale, and writes what survives the gate.

ADR-030 splits this in two — `extract-structure` (expensive, model-assisted, persists
`document.structure.json`) and `render-akn` (cheap, deterministic) — so that a renderer or
threshold change stops re-paying for the read. It is one fused step until that lands, which is why
the gate verdict is still stored under an `akn` name it outgrew: the gate judges a provision tree
against markdown and never looks at the XML.
"""

from billwatcher.files import sidecar_bytes
from billwatcher.frbr import AKN_LANGUAGES, FrbrIdentityError, identity_from_bill
from billwatcher.graph import fidelity
from billwatcher.graph.akn_schema import validate_akn
from billwatcher.graph.render import AknSchemaError, render_akn
from billwatcher.graph.structure import (
    MarkdownStructureExtractor,
    StructureUnavailable,
    assign_eids,
    infer_language_and_unit,
)
from billwatcher.provenance import build_record, needs_rebuild
from billwatcher.reporting import StepFailure, StepResult, describe_error
from billwatcher.store import (
    DocumentKeys,
    PipelineStore,
    StoredDocumentRef,
    keys_for,
    sha256_of,
)
from billwatcher.version import AKN_VERSION, STRUCTURE_GATE_VERSION

__all__ = ["convert_to_akn", "resolve_language"]


def resolve_language(
    store: PipelineStore, ref: StoredDocumentRef, markdown_text: str
) -> tuple[str, str | None]:
    """`(language, disagreement)` for one document, refusing to invent either.

    The language is a permanent component of the Expression IRI, so it comes from a recorded fact:
    what the operator declared when importing the markdown (they know which PDF they extracted),
    cross-checked against the document's own Arrangement heading. When both are present and
    disagree, the declared value wins and the disagreement is returned for the gate verdict to
    record — a silent overrule is how a wrong Expression IRI becomes permanent.

    Raises when neither source has an answer. Failing one document loudly is much cheaper than
    publishing a citable identifier that asserts a language nobody established.
    """
    detected, _ = infer_language_and_unit(markdown_text)
    record = store.load_provenance(
        bill_slug=ref.bill_slug, doc_key=ref.doc_key, version=ref.version, artifact="markdown"
    )
    declared = ((record or {}).get("inputs") or {}).get("language")
    if declared is not None and declared not in AKN_LANGUAGES:
        raise FrbrIdentityError(f"declared language is not one we publish: {declared!r}")
    if declared is None and detected is None:
        raise FrbrIdentityError(
            "no language on the record: the markdown declares no Arrangement heading and none was "
            "given at import; re-import it with --language"
        )
    if declared is None:
        return str(detected), None
    if detected is not None and detected != declared:
        return declared, f"declared {declared!r}, document reads {detected!r}"
    return declared, None


def convert_to_akn(
    store: PipelineStore,
    *,
    extractor: MarkdownStructureExtractor,
    min_text_coverage: float = fidelity.MIN_TEXT_COVERAGE,
) -> StepResult:
    """Converts every document whose Akoma Ntoso is missing or no longer matches its source.

    `extractor` is injected — never constructed here — so this function never knows what read the
    structure: the deterministic regex reader, a handoff tree someone answered by hand, or a model
    an operator drives themselves. That decision belongs to the caller (`cli.akn_command`), and
    keeping it there is what lets `name`/`model_id` in the provenance record tell those apart
    afterwards rather than blending them.

    Gate P1 decides whether the file exists. In this pipeline `has_akn` is the promotion flag every
    later step reads, so a tree that cannot account for its source must not leave one behind — but
    the verdict is written either way, and a rejected render is kept under a name nothing reads,
    because ADR-017 requires a failing artifact to be a review item rather than a discard.
    """
    counts = {"eligible": 0, "converted": 0, "rejected": 0, "unanswered": 0, "failed": 0}
    failures: list[StepFailure] = []
    for ref in store.iter_documents():
        keys = keys_for(ref)
        if not store.has_markdown(**keys):
            continue
        markdown = store.load_markdown(**keys)
        if markdown is None:
            counts["failed"] += 1
            failures.append(_failure(ref, "markdown disappeared between listing and read"))
            continue
        # Every input this render reads has to be in the staleness key, or a correction to it
        # silently leaves the published artifact behind. Two are not files in this document's own
        # directory, so they are recorded as digests rather than as `source_files` — that list is
        # what `pipeline verify` re-hashes on disk, and naming a file it cannot find there would
        # make a correct store report itself as damaged.
        #
        # `bill.json`: `render_akn` takes the FRBR identity, `FRBRdate` and `<longTitle>` from it,
        # so a later crawl correcting a bill's title or first-reading date must regenerate the XML.
        # The markdown provenance: `resolve_language` reads the declared language out of it, and
        # that language is a permanent component of the Expression IRI, so a corrected language that
        # did not regenerate would leave the document published at an IRI asserting the wrong one.
        bill_record = store.load_bill(ref.bill_slug)
        markdown_provenance = store.load_provenance(**keys, artifact="markdown")
        geometry = store.load_blocks(**keys)
        source_files = [{"file": "document.md", "sha256": sha256_of(markdown)}]
        if geometry is not None:
            # The reading's geometry is an input to the structure (ADR-042): a re-read that moves
            # a block's depth can change what is quoted and what is a clause.
            source_files.append(
                {"file": "document.blocks.json", "sha256": sha256_of(sidecar_bytes(geometry))}
            )
        inputs = {
            "source_files": source_files,
            "bill_sha256": sha256_of(sidecar_bytes(bill_record or {})),
            "markdown_provenance_sha256": sha256_of(sidecar_bytes(markdown_provenance or {})),
            "code_version": AKN_VERSION,
            "gate_version": STRUCTURE_GATE_VERSION,
            "min_text_coverage": min_text_coverage,
            "producer": extractor.name,
            "model_id": extractor.model_id,
            "prompt_sha256": extractor.prompt_sha256,
        }
        if not needs_rebuild(
            store, ref, artifact="akn", inputs=inputs, present=store.has_akn(**keys)
        ):
            continue
        counts["eligible"] += 1

        try:
            language, disagreement = resolve_language(store, ref, markdown)
            _, unit = infer_language_and_unit(markdown)
            bill = store.load_bill(ref.bill_slug)
            if bill is None:
                raise FrbrIdentityError(f"no bill record for {ref.bill_slug!r}")
            identity = identity_from_bill(bill, doc_type="act" if unit == "section" else "bill")
            blocks = geometry.get("blocks") if geometry is not None else None
            tree = extractor.extract(
                markdown, unit=unit, blocks=blocks if isinstance(blocks, list) else None
            )
            assign_eids(tree)
            verdict = fidelity.evaluate(tree, markdown, unit=unit, min_coverage=min_text_coverage)
            xml_bytes = render_akn(tree, identity=identity, language=language, bill=bill)
            # Schema validity only has to hold for a reading that might be published — a rejected
            # reading's XML is a review artifact, not a citable Manifestation (ADR-017), so it is
            # validated only when Gate P1 would otherwise have let it through. Found live: several
            # of the tree defects Gate P1 already names as findings (a duplicate eId, a provision
            # with no printed number) are *also* schema violations, and validating unconditionally
            # meant `validate_akn` raised first and every one of them turned into an opaque "failed"
            # step instead of a reviewable "mismatch" verdict — discarding the informative finding
            # fidelity.evaluate() had already computed, and never writing document.akn.rejected.xml.
            if verdict.passed:
                schema_errors = validate_akn(xml_bytes)
                if schema_errors:
                    # Not a bad reading — a broken renderer. Fail loudly rather than publish XML
                    # that calls itself Akoma Ntoso and cannot be read by Akoma Ntoso tooling.
                    raise AknSchemaError("; ".join(schema_errors[:3]))
        except StructureUnavailable:
            # Deliberately before the general handler, and deliberately writing nothing: no verdict,
            # no withdrawal, no named failure. The document is simply not read yet.
            counts["unanswered"] += 1
            continue
        except Exception as error:
            reason = describe_error(error)
            store.save_structure_gate(**keys, record=fidelity.failure(reason).as_detail())
            _withdraw(store, keys, present=store.has_akn(**keys))
            counts["failed"] += 1
            failures.append(_failure(ref, reason))
            continue

        record = verdict.as_detail()
        record["language"] = language
        if disagreement is not None:
            record["language_disagreement"] = disagreement
        store.save_structure_gate(**keys, record=record)
        if not verdict.passed:
            store.save_rejected_akn(**keys, content=xml_bytes)
            _withdraw(store, keys, present=store.has_akn(**keys))
            counts["rejected"] += 1
            failures.append(_failure(ref, f"gate P1 {verdict.status}: {_summarise(verdict)}"))
            continue

        store.save_akn(**keys, content=xml_bytes)
        store.save_provenance(
            **keys,
            artifact="akn",
            record=build_record(
                artifact="akn", inputs=inputs, outputs={"document.akn.xml": xml_bytes}
            ),
        )
        counts["converted"] += 1
    return StepResult(counts=counts, failures=tuple(failures))


def _withdraw(store: PipelineStore, keys: DocumentKeys, *, present: bool) -> None:
    """Unpublish an Akoma Ntoso document whose latest reading no longer passes the gate.

    Without this, a re-read that fails leaves the *previous* reading promoted while the verdict
    beside it says `mismatch` — so the served document and the confidence statement printed next to
    it describe different things, and a reader is told a reading was checked when the check it was
    shown belongs to a different render. The published Expression is withdrawn instead, which is the
    same rule as first conversion: the gate decides whether the file exists.

    The rejected render and the verdict both stay on disk, so the withdrawal is reviewable rather
    than silent (ADR-017, ADR-025).
    """
    if present:
        store.withdraw_akn(**keys)


def _failure(ref: StoredDocumentRef, reason: str) -> StepFailure:
    return StepFailure(
        bill_slug=ref.bill_slug, doc_key=ref.doc_key, version=ref.version, reason=reason
    )


def _summarise(verdict: fidelity.FidelityResult) -> str:
    kinds = sorted({item.kind for item in verdict.blocking})
    return ", ".join(kinds) if kinds else verdict.status
