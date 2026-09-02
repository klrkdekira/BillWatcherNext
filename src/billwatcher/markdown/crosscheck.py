"""The second reading, and what it is for: disagreement, not correction (ADR-035).

Gate P1 scores a provision tree against **the markdown**, never against the page, so whatever
produced that markdown is unchecked. A reading that drops a subsection, splices a marginal note
into a provision, or returns letter-spaced fragments passes the gate exactly as a faithful one
does, provided the tree faithfully reproduces it. One reading of a document cannot close that
hole. Two readings with disjoint failure modes can.

This module is that second reading and the comparison over it. Two things it deliberately is not:

- **It is not a second markdown writer.** The cross-check reading lands in its own artifact slot,
  `document.crosscheck.md`, beside the first rather than over it. Overwriting the first would
  destroy the only thing this step produces — the divergence — and leave one unchecked reading
  again, which is the state ADR-035 exists to end. Promoting a better reading into `markdown` is
  `import-markdown`'s job, one document at a time, because it is a decision.
- **It does not adjudicate.** When two readings disagree this step knows that one of them is
  wrong, not which. Every divergence is a finding for a person.

What produced the second reading is not this module's business either. MinerU is what ADR-035
budgeted for — one model call per page, ~27,833 for this corpus — but the step needs only markdown
and the name of whatever produced it, so an operator's own model, or a person, reads back through
exactly the same ingress.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from billwatcher.download.documents import VERSION as DOCUMENT_VERSION
from billwatcher.graph.fidelity import tokens_for_comparison
from billwatcher.markdown.imports import (
    MarkdownImportError,
    Producer,
    resolve_doc_key,
    resolve_text,
    source_digest,
    target_of,
)
from billwatcher.provenance import build_record
from billwatcher.reporting import (
    Progress,
    StepFailure,
    StepResult,
    announce,
    describe_error,
)
from billwatcher.store import DocumentKeys, PipelineStore, keys_for

CROSSCHECK_FILENAME = "document.crosscheck.md"

# Where two readings stop being two renderings of one document and start disagreeing about what
# the document says. Deliberately far below Gate P1's 0.95 (ADR-035 decision 6): two independent
# readings of one page legitimately differ on hyphenation, on furniture, and on how a table is
# rendered as prose. This is a "these disagree about the substance" line, not a fidelity score.
MIN_AGREEMENT = 0.75

__all__ = [
    "CROSSCHECK_FILENAME",
    "MIN_AGREEMENT",
    "Divergence",
    "agreement",
    "cross_reference",
    "import_crosscheck",
    "import_crosscheck_tree",
]


def agreement(first: str, second: str) -> float:
    """Symmetric distinct-word overlap between two readings of one document.

    Symmetric because neither reading is the reference. A one-sided measure — "how much of the
    first does the second contain" — hides the direction it does not look in, and the direction it
    does not look in is where a reading that *invents* text shows up. Distinct words rather than a
    token sequence, because two readings order a table's cells differently without disagreeing
    about a single word in it.

    Gate P1's own tokenisation (`tokens_for_comparison`), so a divergence number and a coverage
    number mean comparable things. Two empty readings agree completely: there is nothing for them
    to disagree about, and the emptiness is `extract-markdown`'s finding to report, not this one's.
    """
    left = set(tokens_for_comparison(first))
    right = set(tokens_for_comparison(second))
    if not left and not right:
        return 1.0
    union = left | right
    return round(len(left & right) / len(union), 4) if union else 1.0


@dataclass(frozen=True, slots=True)
class Divergence:
    """Two readings of one document that disagree about its substance."""

    bill_slug: str
    doc_key: str
    version: int
    score: float
    first_tokens: int
    second_tokens: int
    produced_by: str | None = None

    @property
    def label(self) -> str:
        return f"{self.bill_slug}/{self.doc_key}/v{self.version:03d}"

    def as_failure(self) -> StepFailure:
        """A divergence in the shape every step reports its findings in.

        Reported as a failure rather than a warning, unlike `import-markdown`'s language
        disagreement, and the difference is real: a misfiled language is one field to correct on a
        document that imported fine, while a divergence means one of two readings of this bill is
        wrong and nobody yet knows which. That belongs in the list an operator works through.
        """
        return StepFailure(
            self.bill_slug,
            self.doc_key,
            self.version,
            f"readings disagree: agreement {self.score:.4f} < {MIN_AGREEMENT} "
            f"({self.first_tokens} vs {self.second_tokens} distinct words"
            + (f", second read by {self.produced_by}" if self.produced_by else "")
            + ")",
        )


def import_crosscheck(
    store: PipelineStore,
    *,
    bill_slug: str,
    producer: Producer,
    doc_key: str | None = None,
    document_url: str | None = None,
    version: int = 1,
    markdown_path: Path | None = None,
    markdown_text: str | None = None,
) -> bool:
    """Record one cross-check reading of one already-stored document. Returns whether it changed.

    Shaped after `import_markdown` and sharing its refusals deliberately, with one field absent:
    no `language`. The language is a permanent component of the Expression IRI (ADR-024), it is
    already recorded by the reading that entered through `import-markdown`, and a second producer
    asserting it again is a second answer to a question that must have exactly one. A cross-check
    is evidence about the text, never about the document's identity.
    """
    key = resolve_doc_key(doc_key=doc_key, document_url=document_url)
    keys: DocumentKeys = {"bill_slug": bill_slug, "doc_key": key, "version": version}
    if version < 1:
        raise MarkdownImportError(f"not a usable document version: {version!r}")
    if not store.has_document(**keys):
        raise MarkdownImportError(
            f"no stored document {bill_slug}/{key}/v{version:03d}: "
            "fetch the PDF before importing a reading of it"
        )
    text = resolve_text(markdown_path=markdown_path, markdown_text=markdown_text)
    inputs: dict[str, Any] = {
        "source_files": [{"file": "document.pdf", "sha256": source_digest(store, **keys)}],
        **producer.as_inputs(),
    }
    record = build_record(
        artifact="crosscheck", inputs=inputs, outputs={CROSSCHECK_FILENAME: text.encode("utf-8")}
    )
    changed = store.load_crosscheck(**keys) != text or (
        store.load_provenance(**keys, artifact="crosscheck") != record
    )
    store.save_crosscheck(**keys, content=text)
    store.save_provenance(**keys, artifact="crosscheck", record=record)
    return changed


def import_crosscheck_tree(
    store: PipelineStore,
    *,
    source_root: Path,
    producer: Producer,
    filename: str = CROSSCHECK_FILENAME,
    progress: Progress = None,
) -> StepResult:
    """Import every cross-check reading in a tree mirroring the store's own document layout.

    `<bill-slug>/<doc-key>/v<NNN>/<filename>`, resolved by `imports.target_of` — the same layout
    `import-markdown` takes, so one exported tree can be read by one tool and handed back to
    either ingress. `filename` defaults to this artifact's own name but is settable, because a
    second reader writes what it writes and renaming two thousand files to suit us is not a step.
    """
    if filename != Path(filename).name or filename in {"", ".", ".."}:
        raise MarkdownImportError(f"not a usable markdown filename: {filename!r}")
    counts = {"found": 0, "imported": 0, "unchanged": 0, "failed": 0, "unrecognised": 0}
    failures: list[StepFailure] = []
    for path in sorted(source_root.rglob(filename)):
        if not path.is_file():
            continue
        target = target_of(path.relative_to(source_root))
        if target is None:
            counts["unrecognised"] += 1
            continue
        counts["found"] += 1
        slug, key, version = target
        try:
            changed = import_crosscheck(
                store,
                bill_slug=slug,
                doc_key=key,
                version=version,
                markdown_path=path,
                producer=producer,
            )
        except MarkdownImportError as error:
            counts["failed"] += 1
            failures.append(StepFailure(slug, key, version, describe_error(error)))
            continue
        counts["imported" if changed else "unchanged"] += 1
    announce(progress, f"{counts['found']} cross-check reading(s) found under {source_root}")
    return StepResult(counts=counts, failures=tuple(failures))


def cross_reference(
    store: PipelineStore, *, min_agreement: float = MIN_AGREEMENT, progress: Progress = None
) -> StepResult:
    """Compare every document's two readings and report where they disagree.

    Pure measurement: it writes nothing. A document with only one reading is counted as
    `unchecked` rather than reported as a failure — on a corpus cross-checked incrementally that
    is the ordinary state of most documents, and burying real divergences under two thousand
    non-events is how a report gets ignored.
    """
    counts = {"documents": 0, "compared": 0, "agreed": 0, "diverged": 0, "unchecked": 0}
    divergences: list[Divergence] = []
    refs = [ref for ref in store.iter_documents() if ref.version == DOCUMENT_VERSION]
    announce(progress, f"{len(refs)} stored document(s) to cross-reference")

    for ref in refs:
        counts["documents"] += 1
        keys = keys_for(ref)
        first = store.load_markdown(**keys)
        second = store.load_crosscheck(**keys)
        if first is None or second is None:
            counts["unchecked"] += 1
            continue
        counts["compared"] += 1
        score = agreement(first, second)
        if score >= min_agreement:
            counts["agreed"] += 1
            continue
        counts["diverged"] += 1
        divergences.append(
            Divergence(
                bill_slug=ref.bill_slug,
                doc_key=ref.doc_key,
                version=ref.version,
                score=score,
                first_tokens=len(set(tokens_for_comparison(first))),
                second_tokens=len(set(tokens_for_comparison(second))),
                produced_by=_produced_by(store, keys),
            )
        )
        announce(progress, f"DIVERGED {ref.bill_slug}/{ref.doc_key} agreement {score:.4f}")

    # Worst agreement first: this list is worked through by a person, and the document the two
    # readings disagree about most is the one most likely to be damaged rather than merely
    # rendered differently.
    divergences.sort(key=lambda item: (item.score, item.label))
    return StepResult(
        counts=counts,
        failures=tuple(item.as_failure() for item in divergences),
    )


def _produced_by(store: PipelineStore, keys: DocumentKeys) -> str | None:
    """The tool named in the cross-check's provenance, so a divergence says who disagreed."""
    record = store.load_provenance(**keys, artifact="crosscheck")
    if record is None:
        return None
    inputs = record.get("inputs")
    if not isinstance(inputs, dict):
        return None
    producer = inputs.get("producer")
    return producer if isinstance(producer, str) else None
