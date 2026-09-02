"""`pipeline verify`: re-check the stored corpus against what the store itself claims.

Every other step in this pipeline asks "is there work to do?" and answers from a provenance record.
This one asks the opposite question — "is what is on disk still what it says it is?" — and answers
it by re-reading and re-hashing the bytes. It is the file-first analogue of `verify-audit`, with one
difference that matters: there is no database to diff against, so every claim being checked is one
the store made about itself (a sidecar digest, a provenance `output` block, a gate verdict). That is
enough to catch bit rot, a truncated write, a hand-edited file and a stale artifact. It is not
enough to catch a lie that was recorded consistently at the time.

What a clean run certifies:

- every stored `document.pdf` still hashes to the digest and length its sidecar recorded;
- every `metadata.json` is byte-for-byte what the deterministic sidecar writer would produce;
- every present derived artifact matches the digest its own provenance record wrote down;
- no file sits in a version directory that no step in this pipeline writes;
- the semantic pair is whole — `document.jsonld` and `document.nq` exist together or not at all;
- Gate P1, re-run offline from the stored XML and markdown, still returns the recorded verdict.

What it does not certify, and must not be read as certifying:

- that the markdown is a faithful reading of the PDF. Nothing here parses a PDF (ADR-021), so
  markdown that dropped a page is invisible to this command and to every gate it re-runs.
- that the Akoma Ntoso is a *correct* reading of the markdown. Gate P1 checks accountability, not
  correctness (`pipeline.fidelity`), so re-running it proves only that the same verdict still
  follows from the same files.
- that an artifact was produced by the extractor, model or prompt currently configured. This
  command has no extractor and deliberately does not build one, so `--strict` compares only what it
  can recompute offline: source digests, our own code versions, and the gate threshold. A corpus
  built by a since-improved prompt, or against a since-changed public base IRI, reads as current
  here — the step that produced it still knows better (`provenance.needs_rebuild`), and inventing a
  configured value to compare against would report a whole corpus stale on a typo.
- anything about the listings or bills tiers, or about the graph's conformance to the ELI ontology
  (Gate L5 is not built).

Nothing is recorded anywhere. The exit code and the printed report are the whole signal, which
is the property that makes this safe to run in a Makefile between two steps that do write.
"""

import json
import re
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from billwatcher.files import sidecar_bytes
from billwatcher.graph import fidelity
from billwatcher.graph.semantic import parse_akn
from billwatcher.provenance import RAW_FILES
from billwatcher.reporting import describe_error
from billwatcher.store import (
    ARTIFACTS,
    FileStore,
    PipelineStore,
    StoredDocumentRef,
    sha256_of,
)
from billwatcher.version import AKN_VERSION, SEMANTIC_VERSION

# How many issues the report carries. Higher than the 50-item limits in `reporting` and `fidelity`
# because those bound one run's failures while this bounds a whole corpus: an operator needs enough
# lines to tell "one document is damaged" from "everything is stale", and no more than that.
ISSUE_LIMIT = 200

# The version of our own code that produced each artifact. Markdown is absent on purpose: it is
# produced outside this pipeline (ADR-021), so there is no code version of ours to compare it to.
CODE_VERSIONS = {"akn": AKN_VERSION, "semantic": SEMANTIC_VERSION}

# Reading a file named by a sidecar goes through one of these, never through a path built from the
# name. A provenance record is normally ours, but it is still a file on disk, and joining a string
# out of it onto a directory is exactly the move HANDOFF 17 forbids.
_LOADERS: dict[str, Callable[[PipelineStore, dict[str, Any]], bytes | None]] = {
    "document.pdf": lambda store, keys: store.load_document(**keys),
    "document.md": lambda store, keys: _encoded(store.load_markdown(**keys)),
    "document.blocks.json": lambda store, keys: _sidecar(store.load_blocks(**keys)),
    "document.akn.xml": lambda store, keys: store.load_akn(**keys),
    "document.jsonld": lambda store, keys: store.load_jsonld(**keys),
    "document.nq": lambda store, keys: store.load_rdf(**keys),
}

_VERSION_DIR_RE = re.compile(r"^v\d+$")


def verify_store(
    store: PipelineStore,
    *,
    strict: bool = False,
    min_text_coverage: float = fidelity.MIN_TEXT_COVERAGE,
) -> list[str]:
    """Every integrity issue found in the store, as lower-case `"<what is wrong>: <path>"` lines.

    `strict` adds staleness. A stale artifact is not damaged — it is a correct artifact of an
    earlier source or an earlier version of our code, and it is fixed by re-running the step that
    produced it. Reporting it beside a corrupted file by default would mean a corpus that merely
    needs regenerating fails an operator's bit-rot check identically to one with a truncated PDF, so
    staleness carries its own `stale:` prefix and is off unless asked for.

    Structural checks — the version-directory layout and the `metadata.json` round-trip — read the
    filesystem directly, and therefore run only for a `FileStore`. Walking them through
    `iter_documents` would be worse than useless: that iterator skips a version directory with no
    `metadata.json` and accepts only `vNNN` names, which is precisely the set of layouts these
    checks exist to report. Every other check here goes through the `PipelineStore` protocol and so
    holds for any future backend; a `DatabaseStore` has no directory tree and would bring its own
    structural check.
    """
    issues: list[str] = []
    if isinstance(store, FileStore):
        issues.extend(_layout_issues(store))
    issues.extend(
        f"present in the store with no step that writes it: {path}"
        for path in store.iter_unexpected_files()
    )
    expressions: dict[tuple[str, str], list[str]] = {}
    for ref in _listed_documents(store, issues):
        issues.extend(
            _document_issues(store, ref, strict=strict, min_text_coverage=min_text_coverage)
        )
        _record_expression(store, ref, expressions)
    issues.extend(_collision_issues(expressions))
    return _bounded(issues)


def _record_expression(
    store: PipelineStore, ref: StoredDocumentRef, seen: dict[tuple[str, str], list[str]]
) -> None:
    """Note which (bill, language) each *published* document claims, for the collision check.

    Only promoted documents count. A gate-rejected reading has a verdict naming its language but no
    `document.akn.xml`, so nothing serves it and it cannot contend for an IRI — reporting it would
    be a false collision on a store that is behaving exactly as designed.
    """
    keys = _keys(ref)
    if not store.has_akn(**keys):
        return
    verdict = store.load_structure_gate(**keys) or {}
    language = verdict.get("language")
    if isinstance(language, str) and language:
        seen.setdefault((ref.bill_slug, language), []).append(ref.doc_key)


def _collision_issues(seen: dict[tuple[str, str], list[str]]) -> list[str]:
    """Report two documents claiming one Expression IRI.

    ADR-024 records that this scheme carries no version component, so two documents of one bill in
    one language resolve to the same permanent IRI, and A11 records that no bill has ever had a
    second version. That makes it a contract limitation rather than a bug — but an *undetected* one
    would be the worst identifier failure available here: a citable IRI silently resolving to
    whichever of two documents happened to sort first, with the other's reading unreachable and
    nothing anywhere saying so. Detection costs one dictionary, and it turns "not representable"
    into "not representable, and you will be told".
    """
    return [
        f"two documents claim one expression iri ({slug}, {language}): {', '.join(sorted(keys))}"
        for (slug, language), keys in sorted(seen.items())
        if len(keys) > 1
    ]


def _listed_documents(store: PipelineStore, issues: list[str]) -> Iterator[StoredDocumentRef]:
    """Every document the store can list, reporting the point at which it cannot list any more.

    `FileStore.iter_documents` now skips a document whose sidecar it cannot parse rather than
    raising, so on that backend this wrapper is defence with nothing to defend against: the
    unparseable sidecar is reported by the layout walk, and the listing just has one fewer document.
    It stays because the guarantee belongs to the *protocol* rather than to one implementation — a
    future backend may raise mid-iteration, and a verify pass must not die on the corruption it
    exists to report. A generator that raised cannot be resumed, which is why such a failure ends
    the listing rather than skipping a single item.
    """
    iterator = iter(store.iter_documents())
    while True:
        try:
            yield next(iterator)
        except StopIteration:
            return
        except Exception as error:
            issues.append(
                f"could not be listed past a document the store cannot read "
                f"({describe_error(error)}): documents"
            )
            return


def _bounded(issues: list[str]) -> list[str]:
    """Deduplicate, then cap — and say so rather than trailing off silently.

    Two checks can reach the same missing file from different directions (its pair is present, its
    provenance names it); an operator learns nothing from reading that twice.
    """
    unique = list(dict.fromkeys(issues))
    if len(unique) <= ISSUE_LIMIT:
        return unique
    remaining = len(unique) - ISSUE_LIMIT
    return [*unique[:ISSUE_LIMIT], f"report truncated: {remaining} further issues not listed"]


# --- structural checks (FileStore only; see `verify_store`) ---


def _layout_issues(store: FileStore) -> list[str]:
    issues: list[str] = []
    documents_dir = store.root / "documents"
    if not documents_dir.exists():
        return issues
    for bill_dir in sorted(p for p in documents_dir.iterdir() if p.is_dir()):
        for doc_dir in sorted(p for p in bill_dir.iterdir() if p.is_dir()):
            for version_dir in sorted(p for p in doc_dir.iterdir() if p.is_dir()):
                relative = version_dir.relative_to(store.root)
                name = version_dir.name
                if not _VERSION_DIR_RE.match(name):
                    # Not a version directory at all. Every file under it is already reported by
                    # `iter_unexpected_files`, which is the more useful report of the two.
                    continue
                if name != f"v{int(name[1:]):03d}":
                    issues.append(
                        f"not a canonical version directory, so nothing in it can be "
                        f"addressed: {relative}"
                    )
                    continue
                issues.extend(_sidecar_issues(version_dir, relative))
    return issues


def _sidecar_issues(version_dir: Path, relative: Path) -> list[str]:
    """`metadata.json` present, parseable, and identical to its canonical serialisation.

    The round-trip is the file-first analogue of the audit tree's rebuild diff: re-serialising the
    parsed sidecar and comparing bytes proves the file is what the deterministic writer produces,
    with no database and no shadow rebuild needed (ADR-019). It catches a hand edit that reordered
    keys or changed indentation as readily as a flipped byte.
    """
    metadata_path = version_dir / "metadata.json"
    if not metadata_path.exists():
        if any(path.is_file() for path in version_dir.iterdir()):
            # No sidecar means `iter_documents` skips the whole directory, so nothing else in this
            # module would ever look at it. This is the only line that can see it.
            return [f"missing from the store: {relative}/metadata.json"]
        return []
    raw = metadata_path.read_bytes()
    try:
        parsed = json.loads(raw)
    except ValueError as error:
        return [f"not readable as json ({describe_error(error)}): {relative}/metadata.json"]
    if not isinstance(parsed, dict):
        return [f"not a json object: {relative}/metadata.json"]
    if sidecar_bytes(parsed) != raw:
        return [f"content differs from its canonical serialisation: {relative}/metadata.json"]
    return []


# --- per-document checks (protocol only) ---


def _document_issues(
    store: PipelineStore,
    ref: StoredDocumentRef,
    *,
    strict: bool,
    min_text_coverage: float,
) -> list[str]:
    issues = _stored_document_issues(store, ref)
    issues.extend(_semantic_pair_issues(store, ref))
    for artifact in sorted(ARTIFACTS):
        issues.extend(
            _artifact_issues(
                store,
                ref,
                artifact=artifact,
                strict=strict,
                min_text_coverage=min_text_coverage,
            )
        )
    issues.extend(_gate_issues(store, ref, min_text_coverage=min_text_coverage))
    return issues


def _stored_document_issues(store: PipelineStore, ref: StoredDocumentRef) -> list[str]:
    """Re-hash the downloaded PDF against its sidecar.

    Deliberately not done in `has_document`: that predicate runs once per document URL on every
    fetch run, so hashing there would turn "is this already downloaded?" into a full read of the
    corpus every time the scraper starts. The re-verification belongs in a command an operator runs
    on purpose, which is this one.
    """
    keys = _keys(ref)
    path = _path(ref, "document.pdf")
    payload = store.load_document(**keys)
    if payload is None:
        return [f"missing from the store: {path}"]
    issues: list[str] = []
    digest = ref.metadata.get("sha256")
    size = ref.metadata.get("byte_size")
    if not isinstance(digest, str):
        issues.append(f"records no digest for its document: {_path(ref, 'metadata.json')}")
    elif sha256_of(payload) != digest:
        issues.append(f"content differs from the recorded digest: {path}")
    if isinstance(size, int) and size != len(payload):
        issues.append(f"byte size differs from the recorded size: {path}")
    return issues


def _semantic_pair_issues(store: PipelineStore, ref: StoredDocumentRef) -> list[str]:
    """Both halves or neither.

    `has_semantic` requires both files, so a half-written pair reads as "no semantic files yet" to
    every step that asks — the step would rebuild it, but until then the store holds a JSON-LD
    document with no N-Quads beside it, and `has_semantic` will never say so.
    """
    keys = _keys(ref)
    present = {
        "document.jsonld": store.load_jsonld(**keys) is not None,
        "document.nq": store.load_rdf(**keys) is not None,
    }
    if all(present.values()) or not any(present.values()):
        return []
    return [
        f"missing from the store: {_path(ref, name)}"
        for name, exists in present.items()
        if not exists
    ]


def _artifact_issues(
    store: PipelineStore,
    ref: StoredDocumentRef,
    *,
    artifact: str,
    strict: bool,
    min_text_coverage: float,
) -> list[str]:
    keys = _keys(ref)
    record = store.load_provenance(**keys, artifact=artifact)
    raw_path = _path(ref, RAW_FILES[artifact])
    if record is None:
        if not _artifact_present(store, ref, artifact):
            return []
        if artifact == "markdown" and not strict:
            # Markdown arrives from outside this pipeline and its provenance is written by whatever
            # imported it, so an unprovenanced file is under-documented rather than damaged. Saying
            # so on every document of a legitimately imported corpus is how a check teaches an
            # operator to stop reading it (ADR-017), so it waits for --strict.
            return []
        return [f"present with no provenance record: {raw_path}"]
    provenance_path = _path(ref, f"document.{artifact}.provenance.json")
    issues = _output_issues(store, ref, record, provenance_path=provenance_path)
    issues.extend(
        _input_issues(
            store,
            ref,
            record,
            artifact=artifact,
            provenance_path=provenance_path,
            strict=strict,
            min_text_coverage=min_text_coverage,
        )
    )
    return issues


def _artifact_present(store: PipelineStore, ref: StoredDocumentRef, artifact: str) -> bool:
    """Whether this artifact exists for this document version.

    Exhaustive rather than defaulting. A trailing `return store.has_semantic(...)` read every
    artifact it did not recognise as the semantic pair, so adding one to `ARTIFACTS` silently made
    verify report a missing provenance record for a file that was never there — found the moment
    the cross-check artifact was added (ADR-035). An unknown name is a programming error and says
    so, rather than answering about a different artifact.
    """
    keys = _keys(ref)
    if artifact == "markdown":
        return store.has_markdown(**keys)
    if artifact == "crosscheck":
        return store.has_crosscheck(**keys)
    if artifact == "akn":
        return store.has_akn(**keys)
    if artifact == "semantic":
        return store.has_semantic(**keys)
    raise ValueError(f"unknown artifact: {artifact!r}")


def _output_issues(
    store: PipelineStore,
    ref: StoredDocumentRef,
    record: dict[str, Any],
    *,
    provenance_path: str,
) -> list[str]:
    """What the provenance record says it wrote, against what is there now."""
    issues: list[str] = []
    for filename, expected in sorted(_mapping(record.get("output")).items()):
        if filename not in _LOADERS:
            issues.append(
                f"claims to have written a file no step writes ({filename!r}): {provenance_path}"
            )
            continue
        payload = _load(store, ref, filename)
        path = _path(ref, filename)
        if payload is None:
            issues.append(f"missing from the store: {path}")
            continue
        digest = _mapping(expected).get("sha256")
        size = _mapping(expected).get("byte_size")
        if not isinstance(digest, str):
            issues.append(f"provenance records no digest for it: {path}")
        elif sha256_of(payload) != digest:
            issues.append(f"content differs from the digest its provenance records: {path}")
        if isinstance(size, int) and size != len(payload):
            issues.append(f"byte size differs from the size its provenance records: {path}")
    return issues


def _input_issues(
    store: PipelineStore,
    ref: StoredDocumentRef,
    record: dict[str, Any],
    *,
    artifact: str,
    provenance_path: str,
    strict: bool,
    min_text_coverage: float,
) -> list[str]:
    """What the artifact was built from, against what its source says now.

    A source file that has since changed does not make the artifact wrong — it makes it *previous*.
    Hence the `stale:` prefix and the `strict` gate: this is a queue for the step that produced the
    artifact, not evidence of damage. A named source that has vanished altogether is reported
    either way, because nothing can rebuild the artifact from it any more.
    """
    issues: list[str] = []
    inputs = _mapping(record.get("inputs"))
    raw_path = _path(ref, RAW_FILES[artifact])
    for entry in _sequence(inputs.get("source_files")):
        source = _mapping(entry)
        filename = source.get("file")
        if not isinstance(filename, str) or filename not in _LOADERS:
            issues.append(
                f"claims to have read a file no step writes ({filename!r}): {provenance_path}"
            )
            continue
        payload = _load(store, ref, filename)
        if payload is None:
            issues.append(f"missing from the store: {_path(ref, filename)}")
        elif strict and source.get("sha256") != sha256_of(payload):
            issues.append(f"stale: built from different {filename} bytes: {raw_path}")
    if not strict:
        return issues
    expected_version = CODE_VERSIONS.get(artifact)
    recorded_version = inputs.get("code_version")
    if expected_version is not None and recorded_version != expected_version:
        issues.append(
            f"stale: built by code version {recorded_version!r}, this code is "
            f"{expected_version!r}: {raw_path}"
        )
    recorded_coverage = inputs.get("min_text_coverage")
    if artifact == "akn" and recorded_coverage != min_text_coverage:
        issues.append(
            f"stale: gated at a minimum text coverage of {recorded_coverage!r}, now "
            f"{min_text_coverage!r}: {raw_path}"
        )
    return issues


def _gate_issues(
    store: PipelineStore, ref: StoredDocumentRef, *, min_text_coverage: float
) -> list[str]:
    """Re-run Gate P1 from the stored files and compare it to the recorded verdict.

    The tree comes back out of `document.akn.xml` (`semantic.parse_akn`) rather than out of the
    extractor, which is what makes this offline: a threshold change, or a suspicion that a verdict
    was written against different bytes, becomes answerable over the whole corpus without one model
    call. A disagreement means the verdict and the files no longer tell the same story — either the
    files moved under a correct verdict, or the verdict was never true of these files.
    """
    keys = _keys(ref)
    if not store.has_akn(**keys):
        return []
    xml_bytes = store.load_akn(**keys)
    if xml_bytes is None:
        return [f"missing from the store: {_path(ref, 'document.akn.xml')}"]
    akn_path = _path(ref, "document.akn.xml")
    recorded = store.load_structure_gate(**keys)
    if recorded is None:
        return [f"present with no gate p1 verdict beside it: {akn_path}"]
    markdown = store.load_markdown(**keys)
    if markdown is None:
        # The gate cannot be re-run without its source; the missing file is reported by
        # `_input_issues` (or by the unprovenanced-artifact check) rather than twice here.
        return []
    try:
        tree, _, doc_type, _ = parse_akn(xml_bytes)
    except Exception as error:
        return [f"not readable back as akoma ntoso ({describe_error(error)}): {akn_path}"]
    # The step derived the document type from the unit ("act" for sections); inverting that gives
    # back the unit the recorded verdict was reached under, with no second reading of the markdown.
    unit = "section" if doc_type == "act" else "clause"
    verdict = fidelity.evaluate(tree, markdown, unit=unit, min_coverage=min_text_coverage)
    if verdict.status == recorded.get("status"):
        return []
    return [
        f"gate p1 now reads {verdict.status!r} where the recorded verdict is "
        f"{recorded.get('status')!r}: {akn_path}"
    ]


# --- helpers ---


def _keys(ref: StoredDocumentRef) -> dict[str, Any]:
    return {"bill_slug": ref.bill_slug, "doc_key": ref.doc_key, "version": ref.version}


def _path(ref: StoredDocumentRef, filename: str) -> str:
    """The store-relative path of one file, built from our own identifiers only (HANDOFF 17)."""
    return f"documents/{ref.bill_slug}/{ref.doc_key}/v{ref.version:03d}/{filename}"


def _load(store: PipelineStore, ref: StoredDocumentRef, filename: str) -> bytes | None:
    return _LOADERS[filename](store, _keys(ref))


def _encoded(text: str | None) -> bytes | None:
    return None if text is None else text.encode("utf-8")


def _sidecar(record: dict[str, Any] | None) -> bytes | None:
    return None if record is None else sidecar_bytes(record)


def _mapping(value: Any) -> dict[str, Any]:
    """A sidecar field read defensively: this file may have been edited by hand."""
    return value if isinstance(value, dict) else {}


def _sequence(value: Any) -> Iterable[Any]:
    return value if isinstance(value, list) else []
