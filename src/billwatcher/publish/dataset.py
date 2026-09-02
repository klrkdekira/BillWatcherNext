"""Stage 4: project the gate-passing corpus into the tree GitHub Pages serves.

The corpus remains the complete private record. This module writes a separate projection of it:
only complete, Gate P1-passing Expressions, on their permanent FRBR manifestation paths, redacted
at this boundary when the configured publication mode is ``metadata``.

`docs/` has two writers. This one owns `akn/`, `definitions/`, `index.json`, `checksums.sha256`
and `CNAME`; the Vite build owns `index.html`, `assets/`, `404.html` and `.nojekyll`. Neither
reconciles outside its own namespaces, which is what lets the dataset and the frontend share one
committed directory without either deleting the other.

Writes are atomic and write-if-changed, so re-publishing an unchanged corpus leaves every file —
and every mtime — untouched, and the commit that follows is empty rather than a full-tree churn.
``checksums.sha256`` is written last and intentionally does not checksum itself: a file cannot
carry its own stable digest.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from billwatcher.config import PublicationMode, RepresentationSet, Settings
from billwatcher.files import sidecar_bytes, write_atomically
from billwatcher.frbr import FrbrIdentityError, WorkIdentity, identity_from_bill
from billwatcher.graph.semantic import jsonld_context_definition, parse_akn
from billwatcher.graph.vocabulary import AKN_ELEMENTS, EID_PREFIXES, NODE_LABELS, NODE_TYPES
from billwatcher.markdown.reading import (
    SUSPECT_HEADING_RATIO,
    SUSPECT_LONE_LETTER_RATE,
    SUSPECT_MIN_BLOCKS,
    SUSPECT_MIN_LONE_LETTERS,
    measure,
)
from billwatcher.publish.redact import (
    contains_provision_text,
    redact_akn,
    redact_semantic,
)
from billwatcher.reporting import StepFailure, StepResult, describe_error
from billwatcher.store import PipelineStore, StoredDocumentRef, keys_for, sha256_of

# The vendored Akoma Ntoso schemas live with the stage that validates against them; the published
# `definitions/` tree is a copy of exactly those files, so there is one vendored original.
_SCHEMA_DIRECTORY = Path(__file__).parent.parent / "graph" / "schemas"
_MANIFEST_EXTENSIONS = ("md", "xml", "jsonld", "nq")
# Which manifestation extensions each configured set publishes, in the order they are listed in
# `index.json`. "prioritise the jsonld for now" (ADR-032): JSON-LD is the published form, and the
# Akoma Ntoso XML and N-Quads wait for a recorded widening. The store keeps all three regardless.
_REPRESENTATION_SETS: dict[str, tuple[str, ...]] = {
    "jsonld": ("jsonld",),
    # "the semantic files such as jsonld and rdf" (ADR-033): the two RDF serialisations, without
    # the Akoma Ntoso XML. Both come from one graph (ADR-028), so they cannot disagree.
    "semantic": ("jsonld", "nq"),
    # The markdown milestone (ADR-036). Publishable on its own, because a reading of the corpus is
    # a resource in its own right and does not become one only once a graph is built from it.
    "markdown": ("md",),
    # Both milestones on one surface: the same Expression, its text and its graph, at one identity.
    "markdown-semantic": ("md", "jsonld", "nq"),
    "all": _MANIFEST_EXTENSIONS,
}

# Representations that *are* the legislative prose rather than a description of it. Metadata mode
# exists to publish a catalogue with the provision text removed, and there is no such thing as
# redacted markdown: strip the prose and nothing is left but headings. Rather than silently
# publishing an empty text dataset, asking for one is refused (see `require_publication_rights`).
_PROSE_EXTENSIONS = frozenset({"md"})
# The top-level names this step owns, and therefore the only ones it may reconcile. ADR-029 leaves
# the hosting decision open, and two of its three options — committing the cache to a repository,
# or syncing it into a static host's document root — put files the export did not write beside the
# ones it did: `.git/`, `CNAME`, `.nojekyll`, a hand-written `README.md`. Reconciling the whole root
# would delete them, so a publish prunes only inside these namespaces and leaves the rest alone.
# In this repository that sharing is the normal case rather than an edge one: `docs/` holds both
# this dataset and the compiled React frontend, and the two builds must not delete each other's
# output. Everything the frontend owns — `index.html`, `assets/`, `404.html`, `.nojekyll` — is
# deliberately absent from this set.
DATASET_ENTRIES = frozenset({"akn", "definitions", "index.json", "checksums.sha256", "CNAME"})


class StaticExportRefused(RuntimeError):
    """An irreversible export is refused.

    Either the rights decisions were not asserted, or a payload may not be published at all.
    """


@dataclass(frozen=True, slots=True)
class _Candidate:
    """One stored document that can contribute at least one requested representation.

    Every representation is optional, which is the whole point of ADR-036: a document with a
    markdown reading and no Akoma Ntoso is publishable on the markdown surface, and a document with
    a gate-passing graph and no reading is publishable on the semantic one. Requiring all three
    made the corpus publishable only at its slowest tier.
    """

    ref: StoredDocumentRef
    bill: dict[str, Any]
    identity: WorkIdentity
    language: str
    expression_uri: str
    markdown: bytes | None = None
    xml: bytes | None = None
    jsonld: bytes | None = None
    nquads: bytes | None = None
    quality: dict[str, float] = field(default_factory=dict)

    @property
    def suspect(self) -> bool:
        """Whether the markdown reading carries a quality signal a reader should see (ADR-035)."""
        return (
            self.quality.get("heading_ratio", 0.0) >= SUSPECT_HEADING_RATIO
            and self.quality.get("blocks", 0.0) >= SUSPECT_MIN_BLOCKS
        ) or (
            self.quality.get("lone_letter_rate", 0.0) >= SUSPECT_LONE_LETTER_RATE
            and self.quality.get("lone_letters", 0.0) >= SUSPECT_MIN_LONE_LETTERS
        )

    def available(self) -> frozenset[str]:
        """Which manifestation extensions this candidate actually has bytes for."""
        return frozenset(
            extension
            for extension, payload in (
                ("md", self.markdown),
                ("xml", self.xml),
                ("jsonld", self.jsonld),
                ("nq", self.nquads),
            )
            if payload is not None
        )


@dataclass(frozen=True, slots=True)
class Projection:
    """Everything a publishable tree needs, assembled but not yet written.

    Split out from the writing so that selection, gating, redaction and identity are decided in
    one place and testable without a filesystem.
    """

    payloads: dict[str, bytes]
    catalogue: dict[str, Any]
    counts: dict[str, int]
    failures: tuple[StepFailure, ...]


def require_publication_rights(settings: Settings) -> None:
    """Refuse every publish whose rights have not been explicitly confirmed.

    Unconditional on ``ENVIRONMENT``: writing the tree creates the publishable unit even on a
    development machine, and in this repository `docs/` is committed, so "local" is not a softer
    boundary — it is the same bytes one push earlier.
    """
    if not settings.publish_rights_confirmed:
        raise StaticExportRefused(
            "publish requires PUBLISH_RIGHTS_CONFIRMED=true; a published tree may be mirrored "
            "and cannot be withdrawn (ADR-029)"
        )
    prose = set(_REPRESENTATION_SETS[settings.site_representations]) & _PROSE_EXTENSIONS
    if settings.publication_mode == "metadata" and prose:
        raise StaticExportRefused(
            f"PUBLICATION_MODE=metadata cannot publish {sorted(prose)}: markdown is the provision "
            "prose itself, and there is no redacted form of it — strip the text and only headings "
            "remain. Publish the text in full mode, or drop it from SITE_REPRESENTATIONS "
            "(ADR-036)"
        )
    if (prose or settings.publication_mode == "full") and not settings.full_text_rights_confirmed:
        raise StaticExportRefused(
            "publishing the source document's own words requires FULL_TEXT_RIGHTS_CONFIRMED=true, "
            "which is a separate and higher decision than PUBLISH_RIGHTS_CONFIRMED (ADR-004, "
            "ADR-018, ADR-036)"
        )


def publish_dataset(
    store: PipelineStore,
    *,
    site_root: Path,
    publication_mode: PublicationMode,
    representations: RepresentationSet = "jsonld",
    prefix: str | None = None,
    prune: bool = False,
) -> StepResult:
    """Publish every complete, gate-passing Expression and return an auditable count histogram.

    Writes into the same tree the frontend build writes into, touching only `DATASET_ENTRIES`.
    Additive unless `prune`: see `write_tree`. `stale` counts what a prune would have removed.

    `prefix` is the custom domain, and `None` means "publish the dataset without claiming a
    domain" — a tree destined for a path-hosted Pages site, or a mirror. It is written here rather
    than shipped as a static file in the frontend because SITE_PREFIX is also the authority for
    every published FRBR IRI, and a domain configured in two places is a domain that will
    eventually disagree with the citations that dereference to it.
    """
    projection = build_projection(
        store, publication_mode=publication_mode, representations=representations
    )
    payloads = dict(projection.payloads)
    if prefix is not None:
        # GitHub Pages learns the custom domain from this file and nothing else. `Settings` has
        # already reduced it to a bare hostname, so an unusable value fails at configuration load
        # rather than by silently detaching the live domain.
        payloads["CNAME"] = f"{prefix}\n".encode()
    written, removed, stale = write_tree(
        site_root, payloads, managed_entries=DATASET_ENTRIES, prune=prune
    )
    counts = {**projection.counts, "written": written, "removed": removed, "stale": len(stale)}
    return StepResult(
        counts=counts, failures=projection.failures + _stale_failures(stale, pruned=prune)
    )


def build_projection(
    store: PipelineStore,
    *,
    publication_mode: PublicationMode,
    representations: RepresentationSet = "jsonld",
) -> Projection:
    """Select and render every publishable Expression, plus the definitions and the catalogue."""
    extensions = _REPRESENTATION_SETS[representations]
    counts = {
        "documents": 0,
        "exported": 0,
        "skipped_rejected": 0,
        "skipped_no_identity": 0,
        "skipped_incomplete": 0,
        "skipped_duplicate_expression": 0,
        # How much of the release is text-only, and how much of that text carries a quality signal
        # a reader should weigh (ADR-035/036). Counted rather than withheld: a dataset that quietly
        # drops a fifth of the corpus looks complete and is not.
        "markdown_only": 0,
        "suspect_readings": 0,
        # Bills Parliament lists that this release cannot show: named in a listing but with no
        # publishable expression. Present in the catalogue as an entry with no expressions and a
        # `missing` reason, never silently absent — an absence a reader cannot see is
        # indistinguishable from the bill never having existed (ADR-031's failure, again).
        "missing_works": 0,
        "conflicting_expressions": 0,
        "failed": 0,
        "written": 0,
        "removed": 0,
    }
    failures: list[StepFailure] = []
    grouped: dict[str, list[_Candidate]] = defaultdict(list)

    wants_markdown = "md" in extensions
    wants_semantic = bool(set(extensions) & {"xml", "jsonld", "nq"})

    for ref in store.iter_documents():
        counts["documents"] += 1
        keys = keys_for(ref)
        gate = store.load_structure_gate(**keys)
        xml = store.load_akn(**keys)
        jsonld = store.load_jsonld(**keys)
        nquads = store.load_rdf(**keys)
        # The semantic trio publishes only behind a passing Gate P1 verdict, exactly as before. What
        # changed in ADR-036 is that failing it no longer withholds the *reading* as well.
        semantic_ready = (
            (gate or {}).get("status") == "passed"
            and xml is not None
            and jsonld is not None
            and nquads is not None
        )
        if (gate or {}).get("status") == "passed" and not semantic_ready:
            counts["skipped_incomplete"] += 1
            failures.append(_failure(ref, "a promoted artifact is missing from the semantic trio"))

        markdown_text = store.load_markdown(**keys) if wants_markdown else None
        markdown = markdown_text.encode("utf-8") if markdown_text else None

        publishes_semantic = wants_semantic and semantic_ready
        publishes_markdown = wants_markdown and markdown is not None
        if not publishes_semantic and not publishes_markdown:
            counts["skipped_rejected"] += 1
            continue

        bill = store.load_bill(ref.bill_slug)
        try:
            if bill is None:
                raise FrbrIdentityError(f"no bill record for {ref.bill_slug!r}")
            if publishes_semantic:
                _, expression_uri, doc_type, language = parse_akn(xml or b"")
            else:
                # No Akoma Ntoso to read an identity out of, so it is derived the way the AKN step
                # derives it in the first place: the Work from the bill record, and the language
                # from what the reading was *declared* to be when it was imported. Declared rather
                # than detected is load-bearing — that value is already a permanent component of
                # the Expression IRI, so taking it from anywhere else could mint a second IRI for
                # one document.
                doc_type = "bill"
                language = _declared_language(store, ref)
                identity_for_language = identity_from_bill(bill, doc_type=doc_type)
                expression_uri = identity_for_language.expression_uri(language)
            # HANDOFF 28.12's cache is specifically the bill corpus. An Act-shaped reading in this
            # store is a classification defect, not permission to introduce an undocumented
            # /akn/my/act branch into this export.
            if doc_type != "bill":
                raise FrbrIdentityError(
                    f"static bill cache cannot publish document type {doc_type!r}"
                )
            identity = identity_from_bill(bill, doc_type=doc_type)
            expected_expression = identity.expression_uri(language)
            if expression_uri != expected_expression:
                raise FrbrIdentityError(
                    "Akoma Ntoso Expression does not match the current bill identity: "
                    f"stored={expression_uri!r} expected={expected_expression!r}"
                )
        except FrbrIdentityError as error:
            counts["skipped_no_identity"] += 1
            failures.append(_failure(ref, describe_error(error)))
            continue
        except Exception as error:
            counts["failed"] += 1
            failures.append(_failure(ref, describe_error(error)))
            continue
        grouped[expression_uri].append(
            _Candidate(
                ref=ref,
                bill=bill,
                identity=identity,
                language=language,
                expression_uri=expression_uri,
                markdown=markdown if publishes_markdown else None,
                xml=xml if publishes_semantic else None,
                jsonld=jsonld if publishes_semantic else None,
                nquads=nquads if publishes_semantic else None,
                quality=measure(markdown_text) if markdown_text else {},
            )
        )

    selected: list[_Candidate] = []
    for expression_uri in sorted(grouped):
        candidates = grouped[expression_uri]
        candidates.sort(key=_candidate_rank)
        selected.append(candidates[0])
        duplicates = len(candidates) - 1
        counts["skipped_duplicate_expression"] += duplicates
        if duplicates and len({_candidate_payload(candidate) for candidate in candidates}) > 1:
            counts["conflicting_expressions"] += 1

    payloads = _definition_payloads()
    works: dict[str, dict[str, Any]] = {}
    for candidate in selected:
        manifestation_payloads = _publishable_payloads(candidate, publication_mode, extensions)
        files: list[str] = []
        for extension in extensions:
            if extension not in manifestation_payloads:
                continue
            relative = candidate.identity.manifestation_uri(candidate.language, extension).lstrip(
                "/"
            )
            payloads[relative] = manifestation_payloads[extension]
            files.append(relative)
        if candidate.markdown is not None and candidate.xml is None:
            counts["markdown_only"] += 1
        if candidate.markdown is not None and candidate.suspect:
            counts["suspect_readings"] += 1
        work = works.setdefault(
            candidate.identity.work_uri,
            {
                "uri": candidate.identity.work_uri,
                "titles": _titles(candidate.bill),
                "expressions": [],
            },
        )
        expression: dict[str, Any] = {
            "uri": candidate.expression_uri,
            "language": candidate.language,
            "title": _expression_title(candidate.bill, candidate.language),
            "files": files,
        }
        if candidate.markdown is not None:
            # Published *with* its measured quality, never quietly. A consumer can filter on
            # `reading.suspect` without re-deriving anything, and one who ignores the field gets the
            # whole corpus rather than a silently trimmed 78% of it (ADR-036).
            expression["reading"] = {
                "extractor": "pdfminer-layout",
                "suspect": candidate.suspect,
                **{key: value for key, value in sorted(candidate.quality.items())},
            }
        work["expressions"].append(expression)

    # The sweep for what is *not* here. Every bill record with a resolvable identity whose Work
    # published nothing becomes a catalogue entry with no expressions and a reason a reader can
    # act on: the listing named no files, the files were never successfully downloaded (all 51 of
    # Parliament's own dead links look like this), or documents are stored but no reading of them
    # met the publication bar (a scan with no text layer, a gate-rejected structure).
    for slug in store.iter_bill_slugs():
        bill = store.load_bill(slug)
        if bill is None:
            continue
        try:
            identity = identity_from_bill(bill, doc_type="bill")
        except FrbrIdentityError:
            continue  # already counted per stored document as skipped_no_identity
        if identity.work_uri in works:
            continue
        listed = [d for d in bill.get("documents") or [] if d.get("url")]
        stored = any(True for _ in store.iter_bill_documents(slug))
        # A stored document outranks the listing: whatever the record says, bytes exist and it is
        # the reading of them that fell short. Only with nothing stored does the listing decide
        # whether the gap is a dead link or a bill Parliament never attached a file to.
        if stored:
            reason = "reading"
        elif listed:
            reason = "download"
        else:
            reason = "listing"
        counts["missing_works"] += 1
        works[identity.work_uri] = {
            "uri": identity.work_uri,
            "titles": _titles(bill),
            "expressions": [],
            "missing": {"reason": reason, "documents_listed": len(listed)},
        }

    catalogue = {
        "catalogue_version": 1,
        "publication_mode": publication_mode,
        # So a consumer can tell a JSON-LD-only release from a widened one without crawling.
        "representations": list(extensions),
        "works": [
            {
                **works[uri],
                "expressions": sorted(works[uri]["expressions"], key=lambda item: str(item["uri"])),
            }
            for uri in sorted(works)
        ],
    }
    payloads["index.json"] = sidecar_bytes(catalogue)
    counts["exported"] = len(selected)
    return Projection(
        payloads=payloads,
        catalogue=catalogue,
        counts=counts,
        failures=tuple(failures),
    )


def write_tree(
    root: Path,
    payloads: dict[str, bytes],
    *,
    managed_entries: frozenset[str],
    prune: bool = False,
) -> tuple[int, int, tuple[str, ...]]:
    """Checksum and atomically write a publishable tree. Returns (written, removed, stale).

    **A build does not delete by default.** `prune=False` reports what it would have removed and
    removes nothing; only `prune=True` unlinks. That default was bought expensively: a build run
    while the store was mid-repair found no artifacts to emit and would have deleted the published
    tree that was, by then, the only surviving copy of them. A build is derived output right up
    until the moment the source is incomplete, and then it is the last backup.

    The withdrawal property `prune` exists for is real and is not abandoned — a reading the gate now
    rejects must stop being published — so it becomes an explicit action with a named list rather
    than a silent side effect of every build. `stale` is that list, and the caller reports it.

    `checksums.sha256` is appended here rather than by the caller, so every tree — dataset or site
    — carries a digest for exactly the files it actually publishes. Note that under `prune=False` a
    stale file is *not* in the manifest: the checksums describe what this build publishes, so a
    leftover is detectable as a file present in the tree and absent from the digest list.
    """
    payloads = dict(payloads)
    payloads.pop("checksums.sha256", None)
    _refuse_source_bytes(payloads)
    checksum_lines = [
        f"{sha256_of(payloads[relative])}  {relative}" for relative in sorted(payloads)
    ]
    payloads["checksums.sha256"] = ("\n".join(checksum_lines) + "\n").encode("utf-8")

    stale = _stale_paths(root, expected=frozenset(payloads), managed=managed_entries)
    removed = 0
    if prune:
        for relative in stale:
            with suppress(OSError):
                (root / relative).unlink()
                removed += 1
    written = 0
    # The checksum manifest is the commit marker for a static mirror, so it is always considered
    # last. Every individual replacement is atomic.
    for relative in sorted(path for path in payloads if path != "checksums.sha256"):
        written += int(_write_if_changed(root / relative, payloads[relative]))
    written += int(_write_if_changed(root / "checksums.sha256", payloads["checksums.sha256"]))
    if prune:
        _remove_empty_directories(root, managed=managed_entries)
    return written, removed, stale


def _stale_failures(stale: tuple[str, ...], *, pruned: bool) -> tuple[StepFailure, ...]:
    """Name every leftover file, so an additive build is auditable rather than merely safe.

    A build that quietly leaves a withdrawn Expression in the tree has published it. Reported
    through `failures` because that is the channel `_report` prints and writes to the manifest, and
    a leftover is exactly the kind of thing an operator must see without going looking.
    """
    verb = "removed" if pruned else "left in place; re-run with --prune to remove"
    return tuple(
        StepFailure("", "", 0, f"no longer published: {relative} ({verb})") for relative in stale
    )


def _candidate_rank(candidate: _Candidate) -> tuple[bool, int, str]:
    """Prefer the originating chamber's copy, then the newest stored version, deterministically.

    Parliament commonly links the same bill PDF from both chamber listings. Those URL-addressed
    store records map to one permanent Expression path. Preferring the originating listing makes
    the projection independent of filesystem traversal while keeping a sole later-chamber copy.
    """
    identifier = candidate.bill.get("identifier") or {}
    originating = identifier.get("originating_chamber")
    return (
        candidate.ref.metadata.get("chamber") != originating,
        -candidate.ref.version,
        candidate.ref.doc_key,
    )


def _candidate_payload(
    candidate: _Candidate,
) -> tuple[bytes | None, bytes | None, bytes | None, bytes | None]:
    return candidate.markdown, candidate.xml, candidate.jsonld, candidate.nquads


def _publishable_payloads(
    candidate: _Candidate,
    publication_mode: PublicationMode,
    extensions: tuple[str, ...],
) -> dict[str, bytes]:
    """Build only the representations this candidate has, redacted when the mode says so.

    Intersected with what the candidate actually holds, because ADR-036 lets one release carry
    text-only Expressions beside fully converted ones. An extension the candidate has no bytes for
    is absent from the result and therefore absent from its `files` list in the catalogue.
    """
    publishing = tuple(e for e in extensions if e in candidate.available())
    if publication_mode == "full":
        available = {
            "md": candidate.markdown,
            "xml": candidate.xml,
            "jsonld": candidate.jsonld,
            "nq": candidate.nquads,
        }
        return {
            extension: payload
            for extension in publishing
            if (payload := available[extension]) is not None
        }
    # N-Quads is the canonical graph input for both redacted serialisations, exactly as the serving
    # boundary does it, so JSON-LD and N-Quads cannot disclose different facts.
    builders = {
        "xml": lambda: redact_akn(candidate.xml or b""),
        "jsonld": lambda: redact_semantic(candidate.nquads or b"", as_jsonld=True),
        "nq": lambda: redact_semantic(candidate.nquads or b"", as_jsonld=False),
    }
    payloads = {extension: builders[extension]() for extension in publishing}
    for extension, payload in payloads.items():
        if contains_provision_text(payload):
            raise RuntimeError(f"metadata redaction left provision text in {extension}")
    return payloads


def _refuse_source_bytes(payloads: dict[str, bytes]) -> None:
    """Refuse to publish the source document itself (ADR-029 decision 5, ADR-032).

    The dataset carries *readings* of bills — Akoma Ntoso, JSON-LD, N-Quads — never the official
    PDF the reading came from, whose republication is a separate rights question from A14's and
    whose bytes belong only to the private store. The exporter cannot construct such a payload
    today; this is the guard that keeps that true if a future step adds a manifestation type, since
    the failure would otherwise be a permanent publication rather than a bug report.
    """
    for relative in sorted(payloads):
        payload = payloads[relative]
        if relative.lower().endswith(".pdf") or payload[:5] == b"%PDF-":
            raise StaticExportRefused(
                f"refusing to export {relative!r}: the published dataset carries readings of "
                "bills, never the source PDF bytes (ADR-029, ADR-032)"
            )


def _definition_payloads() -> dict[str, bytes]:
    vocabulary = {
        "title": "Malaysian legislative structural vocabulary (HANDOFF 26.2)",
        "node_types": [
            {
                "type": node_type,
                "labels": {
                    "ms": NODE_LABELS[node_type][0],
                    "en": NODE_LABELS[node_type][1],
                },
                "akn_element": AKN_ELEMENTS[node_type],
                "akn_attributes": {"name": "schedule"} if node_type == "schedule" else {},
                "eid_prefix": (
                    f"{EID_PREFIXES[node_type]}_" if node_type in EID_PREFIXES else None
                ),
            }
            for node_type in sorted(NODE_TYPES)
        ],
    }
    notice = b"""# OASIS Akoma Ntoso schema notice

`akomantoso30.xsd` is the unmodified OASIS LegalDocML Akoma Ntoso 3.0 schema and `xml.xsd`
is its unmodified XML namespace dependency. Their embedded copyright, source, licence, and other
notices are preserved. The main schema states that OASIS provides it under CC BY 4.0:
https://creativecommons.org/licenses/by/4.0/

Upstream source:
https://docs.oasis-open.org/legaldocml/akn-core/v1.0/os/part2-specs/schemas/
"""
    return {
        "definitions/akomantoso30.xsd": (_SCHEMA_DIRECTORY / "akomantoso30.xsd").read_bytes(),
        "definitions/xml.xsd": (_SCHEMA_DIRECTORY / "xml.xsd").read_bytes(),
        "definitions/jsonld-context.jsonld": sidecar_bytes(jsonld_context_definition()),
        "definitions/structural-vocabulary.json": sidecar_bytes(vocabulary),
        "definitions/OASIS-AKN-NOTICE.md": notice,
    }


def _declared_language(store: PipelineStore, ref: StoredDocumentRef) -> str:
    """The language this reading was declared to be when it was imported.

    Read from the markdown provenance rather than sniffed from the text: the declared value is
    already a permanent component of the Expression IRI, and detection disagreeing with it is a
    recorded finding (`language_disagreement`), not a licence to mint a second IRI.
    """
    record = store.load_provenance(**keys_for(ref), artifact="markdown")
    language = (record or {}).get("inputs", {}).get("language")
    if not isinstance(language, str) or not language:
        raise FrbrIdentityError(
            "markdown has no declared language in its provenance record, so it has no Expression"
        )
    return language


def _titles(bill: dict[str, Any]) -> dict[str, str]:
    source = bill.get("titles") or {}
    titles: dict[str, str] = {}
    for language in ("ms", "en"):
        value = source.get(f"raw_{language}")
        if isinstance(value, str) and value.strip():
            titles[language] = value.strip()
    return titles


def _expression_title(bill: dict[str, Any], language: str) -> str | None:
    titles = _titles(bill)
    return titles.get(language) or titles.get("ms") or next(iter(titles.values()), None)


def _failure(ref: StoredDocumentRef, reason: str) -> StepFailure:
    return StepFailure(ref.bill_slug, ref.doc_key, ref.version, reason)


def _write_if_changed(path: Path, payload: bytes) -> bool:
    if path.exists() and not path.is_symlink() and path.is_file() and path.read_bytes() == payload:
        return False
    if path.is_symlink():
        path.unlink()
    write_atomically(path, payload)
    return True


def _is_managed(relative: str, managed: frozenset[str]) -> bool:
    """Whether this root-relative path lies in a namespace the writing step owns."""
    return relative.split("/", 1)[0] in managed


def _stale_paths(
    root: Path, *, expected: frozenset[str], managed: frozenset[str]
) -> tuple[str, ...]:
    """Files this step owns and no longer publishes — named, so removing them can be a decision.

    Scoped to `managed`: anything else in the root belongs to whoever hosts it. This is what makes
    it safe to build straight into a checkout of the publishing repository — `.git/`, its
    `README.md` and its `LICENSE` are not ours to delete, or even to mention.
    """
    if not root.exists():
        return ()
    stale: list[str] = []
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir() and not path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if not _is_managed(relative, managed):
            continue
        if path.is_symlink() or relative not in expected:
            stale.append(relative)
    return tuple(stale)


def _remove_empty_directories(root: Path, *, managed: frozenset[str]) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        if not path.is_dir() or path.is_symlink():
            continue
        if not _is_managed(path.relative_to(root).as_posix(), managed):
            continue
        with suppress(OSError):
            path.rmdir()
