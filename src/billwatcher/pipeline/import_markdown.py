"""The markdown ingress: how a PDF's text reading enters the pipeline, and on whose authority.

Reading a PDF is deliberately outside this pipeline (ADR-021 decision 4) — the operator points
their own vLLM endpoint at the bytes and gets markdown back. What was missing is the other half of
that arrangement: nothing ever called `save_markdown`, so markdown arrived by hand and the first
link of the provenance chain simply did not exist. Every later artifact then cited a source that
could not say which PDF it was read from, by what, or in which language.

This step closes that. It writes `document.md` and, beside it, the `markdown` provenance record
naming the stored PDF's own sha256 — the link back to the bytes this text claims to be a reading of
— the tool that produced it, and the language the operator declared.

That last field is the load-bearing one. The language becomes a permanent component of the
Expression IRI (`/akn/my/bill/dr/2026/15/msa@` and `.../eng@` are two Expressions of one Work), so
it must be a recorded fact rather than a guess: the old renderer hard-coded `msa` for every
document, and `akn.resolve_language` now refuses to proceed when neither this record nor the
document's own Arrangement heading has an answer. Sniffing it from the document's URL is expressly
forbidden (HANDOFF 26.7) — upstream spells it `DR 17 BM.pdf`, `DR 17 BI.pdf`, `D.R.45_2017 (bm).pdf`
or not at all, so a filename is not evidence of anything. When the operator's declaration and the
document's own heading disagree, the declaration wins and the disagreement is *reported*: silently
overruling a document about its own language is how a wrong permanent identifier gets minted.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from billwatcher.pipeline.akn import infer_language_and_unit
from billwatcher.pipeline.documents import doc_key as doc_key_for_url
from billwatcher.pipeline.frbr import LANGUAGES, valid_slug
from billwatcher.pipeline.provenance import build_record
from billwatcher.pipeline.reporting import FAILURE_LIMIT, StepFailure, StepResult, describe_error
from billwatcher.pipeline.store import DocumentKeys, PipelineStore, sha256_of

MARKDOWN_FILENAME = "document.md"

# A document key as `documents.doc_key` mints one, checked as a path component rather than against
# that function's exact hash width: a bulk import reads these out of a directory tree the operator
# assembled, and HANDOFF 17 allows a storage path to be built only from identifiers we have
# validated ourselves.
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_VERSION_DIR_RE = re.compile(r"^v([0-9]{1,6})$")

__all__ = [
    "MARKDOWN_FILENAME",
    "ImportReport",
    "ImportedMarkdown",
    "MarkdownImportError",
    "Producer",
    "import_markdown",
    "import_markdown_tree",
]


class MarkdownImportError(ValueError):
    """The import cannot proceed on the facts given.

    Raised rather than defaulted, in the same spirit as `FrbrIdentityError`: every refusal here
    guards against writing a record that reads as authoritative while asserting something nobody
    established — a reading of a PDF that is not in the store, in a language the corpus does not
    publish, or produced by nothing in particular.
    """


@dataclass(frozen=True, slots=True)
class Producer:
    """What turned the PDF into markdown, as the operator names it.

    Free-form strings, not an enum: this pipeline does not do PDF extraction and so cannot know
    which tools exist. It only insists that *something* is named, because `provenance.needs_rebuild`
    compares these fields — so re-importing the same document from a better model or a newer build
    correctly restages every downstream artifact, whereas an unattributed reading is one nobody can
    reproduce or supersede.
    """

    tool: str
    model_id: str | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        if not self.tool.strip():
            raise MarkdownImportError("name the tool that produced this markdown")

    def as_inputs(self) -> dict[str, Any]:
        return {
            "producer": self.tool.strip(),
            "model_id": self.model_id,
            "producer_version": self.version,
        }


@dataclass(frozen=True, slots=True)
class ImportedMarkdown:
    """What one import did — deliberately not a counts histogram.

    A single-document import has exactly one outcome, and the two things the operator most needs
    back from it are not countable: which language went on the record (it becomes a permanent part
    of the Expression IRI) and whether the document contradicted it. `{"imported": 1}` reports
    neither. The bulk path aggregates these into a histogram, where a histogram is the right shape.
    """

    bill_slug: str
    doc_key: str
    version: int
    language: str
    language_disagreement: str | None = None
    wrote_markdown: bool = False
    wrote_provenance: bool = False

    @property
    def changed(self) -> bool:
        """False when the store already held this exact text and this exact provenance."""
        return self.wrote_markdown or self.wrote_provenance

    def as_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "bill_slug": self.bill_slug,
            "doc_key": self.doc_key,
            "version": self.version,
            "language": self.language,
            "wrote_markdown": self.wrote_markdown,
            "wrote_provenance": self.wrote_provenance,
        }
        if self.language_disagreement is not None:
            detail["language_disagreement"] = self.language_disagreement
        return detail


@dataclass(frozen=True, slots=True)
class ImportReport:
    """A bulk import's histogram, plus the two things a histogram cannot hold.

    Not a bare `StepResult`, because that carries counts and failures and nothing between them. A
    language disagreement is neither: the document imported correctly and a human needs to look at
    it. Filing it under `failures` would have the CLI print `FAILED` for a document that is on
    disk and fine, which is how a real warning gets trained away. Unaddressable source files are
    the other gap — a file we could not resolve to any document is not a document that failed, and
    it must not be silently skipped either, or a mis-shaped source tree reports a contented zero.

    `as_step_result` hands the caller the shape every other step reports, for the manifest.
    """

    counts: dict[str, int]
    warnings: tuple[StepFailure, ...] = ()
    failures: tuple[StepFailure, ...] = ()
    unrecognised: tuple[str, ...] = ()

    def as_step_result(self) -> StepResult:
        return StepResult(counts=dict(self.counts), failures=self.failures)

    def as_payload(self) -> dict[str, Any]:
        payload = self.as_step_result().as_payload()
        if self.warnings:
            payload["warnings"] = [item.as_detail() for item in self.warnings[:FAILURE_LIMIT]]
            payload["warnings_truncated"] = len(self.warnings) > FAILURE_LIMIT
        if self.unrecognised:
            payload["unrecognised_files"] = list(self.unrecognised[:FAILURE_LIMIT])
            payload["unrecognised_truncated"] = len(self.unrecognised) > FAILURE_LIMIT
        return payload


def import_markdown(
    store: PipelineStore,
    *,
    bill_slug: str,
    language: str,
    producer: Producer,
    doc_key: str | None = None,
    document_url: str | None = None,
    version: int = 1,
    markdown_path: Path | None = None,
    markdown_text: str | None = None,
) -> ImportedMarkdown:
    """Record one markdown reading of one already-stored document. The primitive.

    Addressing is by `doc_key` when the operator has it, or by `document_url` — the same URL the
    fetch step downloaded, put through the same `documents.doc_key`, so the two can never disagree
    about which directory a document lives in.

    Idempotent by construction: the text and the provenance record are both compared before being
    handed to the store, so a repeat import of identical markdown from an identical producer writes
    nothing and says so (`changed` is False). That is what lets the operator re-run a whole
    directory after a partial failure without touching two thousand mtimes.
    """
    key = _resolve_doc_key(doc_key=doc_key, document_url=document_url)
    if language not in LANGUAGES:
        raise MarkdownImportError(
            f"{language!r} is not a language this corpus publishes; "
            f"expected one of {sorted(LANGUAGES)}"
        )
    if not valid_slug(bill_slug):
        raise MarkdownImportError(f"not a usable bill slug: {bill_slug!r}")
    if not _KEY_RE.match(key):
        raise MarkdownImportError(f"not a usable document key: {key!r}")
    if version < 1:
        raise MarkdownImportError(f"not a usable document version: {version!r}")

    keys: DocumentKeys = {"bill_slug": bill_slug, "doc_key": key, "version": version}
    if not store.has_document(**keys):
        raise MarkdownImportError(
            f"no stored document {bill_slug}/{key}/v{version:03d}: "
            "fetch the PDF before importing a reading of it"
        )

    # After the cheap refusals, so a mistyped language or an unfetched document costs no file read.
    text = _resolve_text(markdown_path=markdown_path, markdown_text=markdown_text)
    inputs: dict[str, Any] = {
        "source_files": [
            {"file": "document.pdf", "sha256": _source_digest(store, **keys)},
        ],
        "language": language,
        **producer.as_inputs(),
    }
    record = build_record(
        artifact="markdown", inputs=inputs, outputs={MARKDOWN_FILENAME: text.encode("utf-8")}
    )

    wrote_markdown = store.load_markdown(**keys) != text
    wrote_provenance = store.load_provenance(**keys, artifact="markdown") != record
    store.save_markdown(**keys, content=text)
    store.save_provenance(**keys, artifact="markdown", record=record)

    detected, _ = infer_language_and_unit(text)
    disagreement = (
        f"declared {language!r}, document reads {detected!r}"
        if detected is not None and detected != language
        else None
    )
    return ImportedMarkdown(
        bill_slug=bill_slug,
        doc_key=key,
        version=version,
        language=language,
        language_disagreement=disagreement,
        wrote_markdown=wrote_markdown,
        wrote_provenance=wrote_provenance,
    )


def import_markdown_tree(
    store: PipelineStore,
    *,
    source_root: Path,
    language: str,
    producer: Producer,
    filename: str = MARKDOWN_FILENAME,
) -> ImportReport:
    """Import every markdown file in a tree mirroring the store's own document layout.

    Worth having because the corpus is a couple of thousand documents and the alternative is two
    thousand invocations, but built strictly on top of the single-file primitive — every refusal,
    every provenance field and the idempotence all come from there, not from a second code path.

    The expected source layout is the store's own, relative:
    `<bill-slug>/<doc-key>/v<NNN>/document.md`. Mirroring it means the operator can point at a copy
    of the store's `documents/` tree, and — the reason it is not a flat directory of files named
    after their PDFs — every path component is one of our own identifiers, validated and then
    existence-checked against the store, never an upstream filename joined onto a storage path
    (HANDOFF 17).

    One `language` for the whole run, deliberately: a bill's Malay and English readings are separate
    documents with separate keys, so per-document languages would need a manifest format nobody
    asked for. The operator asserts one language per run — `--language ms` over a tree of Malay
    markdown — and a misfiled document surfaces as a disagreement warning rather than a wrong IRI.
    """
    if filename != Path(filename).name or filename in {"", ".", ".."}:
        raise MarkdownImportError(f"not a usable markdown filename: {filename!r}")

    counts = {
        "found": 0,
        "imported": 0,
        "unchanged": 0,
        "failed": 0,
        "language_disagreements": 0,
        "unrecognised": 0,
    }
    warnings: list[StepFailure] = []
    failures: list[StepFailure] = []
    unrecognised: list[str] = []

    for path in sorted(source_root.rglob(filename)):
        if not path.is_file():
            continue
        target = _target_of(path.relative_to(source_root))
        if target is None:
            counts["unrecognised"] += 1
            unrecognised.append(str(path.relative_to(source_root)))
            continue
        counts["found"] += 1
        slug, key, version = target
        try:
            imported = import_markdown(
                store,
                bill_slug=slug,
                doc_key=key,
                version=version,
                markdown_path=path,
                language=language,
                producer=producer,
            )
        except Exception as error:
            counts["failed"] += 1
            failures.append(
                StepFailure(
                    bill_slug=slug, doc_key=key, version=version, reason=describe_error(error)
                )
            )
            continue
        counts["imported" if imported.changed else "unchanged"] += 1
        if imported.language_disagreement is not None:
            counts["language_disagreements"] += 1
            warnings.append(
                StepFailure(
                    bill_slug=slug,
                    doc_key=key,
                    version=version,
                    reason=f"language disagreement: {imported.language_disagreement}",
                )
            )

    return ImportReport(
        counts=counts,
        warnings=tuple(warnings),
        failures=tuple(failures),
        unrecognised=tuple(unrecognised),
    )


def _resolve_text(*, markdown_path: Path | None, markdown_text: str | None) -> str:
    """The markdown to store, from a file or from memory, refusing a blank one either way.

    Read as `utf-8-sig` so a BOM some extractor prepended does not survive into the text: it would
    ride along on the first line and hide the Arrangement heading from every reader of this file,
    which is exactly the heading the language cross-check depends on. Nothing else is normalised —
    line endings included — because this text is the artifact of record, not a rendering of one.
    """
    if (markdown_path is None) == (markdown_text is None):
        raise MarkdownImportError("give exactly one of markdown_path or markdown_text")
    if markdown_path is not None:
        if not markdown_path.is_file():
            raise MarkdownImportError(f"no markdown file at {markdown_path}")
        text = markdown_path.read_text(encoding="utf-8-sig")
    else:
        text = markdown_text or ""
    if not text.strip():
        raise MarkdownImportError(
            "refusing to import blank markdown: an extraction that produced nothing is not a "
            "reading of the document"
        )
    return text


def _resolve_doc_key(*, doc_key: str | None, document_url: str | None) -> str:
    if (doc_key is None) == (document_url is None):
        raise MarkdownImportError("give exactly one of doc_key or document_url")
    return doc_key if doc_key is not None else doc_key_for_url(str(document_url))


def _source_digest(store: PipelineStore, *, bill_slug: str, doc_key: str, version: int) -> str:
    """The stored PDF's sha256: the link from this text back to the bytes it claims to read.

    Prefers the digest the fetch step recorded in `metadata.json`, because that is the value the
    rest of the chain quotes, and falls back to hashing the stored bytes for a document seeded
    without one. Whether the two agree is `pipeline verify`'s question, not the ingress's — a
    check here would be one file's opinion of itself.
    """
    for ref in store.iter_bill_documents(bill_slug):
        if ref.doc_key == doc_key and ref.version == version:
            recorded = ref.metadata.get("sha256")
            if isinstance(recorded, str) and recorded:
                return recorded
            break
    content = store.load_document(bill_slug=bill_slug, doc_key=doc_key, version=version)
    if content is None:
        raise MarkdownImportError(
            f"stored document {bill_slug}/{doc_key}/v{version:03d} has no bytes to hash"
        )
    return sha256_of(content)


def _target_of(relative: Path) -> tuple[str, str, int] | None:
    """`(bill_slug, doc_key, version)` for a mirrored source path, or None if it is not one."""
    parts = relative.parts
    if len(parts) != 4:
        return None
    match = _VERSION_DIR_RE.match(parts[2])
    if match is None:
        return None
    version = int(match.group(1))
    if version < 1:
        return None
    return parts[0], parts[1], version
