"""The storage interface every pipeline step depends on, and its only implementation so far.

`PipelineStore` is deliberately backend-agnostic: a step calls `save_bill` or `has_document` and
never touches a filesystem path, a SQL statement, or an S3 key directly. `FileStore` is a local
directory implementation of that interface. A future `DatabaseStore` or `ObjectStore` extension
implements the same protocol — same method names, same semantics — and every step in
`billwatcher` keeps working unchanged, because none of them import `FileStore` by name;
they take a `PipelineStore` injected.

Derived artifacts (markdown, Akoma Ntoso, semantic files) each carry a provenance record naming
what they were built from. That record — not the mere existence of a file — is what decides whether
a step has work to do, so correcting the IRI scheme, the prompt, or a renderer regenerates the
corpus instead of leaving stale bytes behind an existence check that can never notice.
"""

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypedDict

from billwatcher.config import Settings
from billwatcher.files import sidecar_bytes, write_atomically

# The closed set of derived artifacts a document can have. Named rather than addressed by filename
# so a future `DatabaseStore` maps each to a row or column without inheriting this layout's paths.
ARTIFACTS = frozenset({"markdown", "akn", "crosscheck", "semantic"})

# Files a version directory may legitimately contain. `pipeline verify` reports anything else, so
# a killed process's leftovers or a hand-dropped file are visible rather than silently served.
KNOWN_FILENAMES = frozenset(
    {
        "document.pdf",
        "metadata.json",
        "document.md",
        "document.markdown.provenance.json",
        "document.crosscheck.md",
        "document.crosscheck.provenance.json",
        "document.akn.xml",
        "document.akn.provenance.json",
        "document.structure.gate.json",
        "document.akn.rejected.xml",
        "document.jsonld",
        "document.nq",
        "document.semantic.provenance.json",
    }
)


def _write_if_changed(path: Path, payload: bytes) -> bool:
    """Write only when the file is missing or its bytes differ.

    Makes every step idempotent against the store: re-running `parse_listings` over the same
    stored bytes recomputes the same merged bill and writes nothing new, and a repeat
    `fetch_documents` run over an already-downloaded PDF touches no file on disk. The comparison
    short-circuits before the write, so an unchanged file keeps its mtime as well as its bytes.
    """
    if path.exists() and path.read_bytes() == payload:
        return False
    write_atomically(path, payload)
    return True


@dataclass(frozen=True, slots=True)
class StoredListing:
    key: str
    metadata: dict[str, Any]
    body: bytes


@dataclass(frozen=True, slots=True)
class StoredDocumentRef:
    bill_slug: str
    doc_key: str
    version: int
    metadata: dict[str, Any]


class DocumentKeys(TypedDict):
    """The three coordinates that address one stored document version.

    A step touches the same document through a dozen store calls, and spelling all three arguments
    out at each one buries the interesting part of the line. This is typed rather than a plain dict
    so `store.save_akn(**keys)` still checks each argument's type under strict mypy.
    """

    bill_slug: str
    doc_key: str
    version: int


def keys_for(ref: StoredDocumentRef) -> DocumentKeys:
    return {"bill_slug": ref.bill_slug, "doc_key": ref.doc_key, "version": ref.version}


class PipelineStore(Protocol):
    """What a pipeline step may assume about where its input and output live.

    Four tiers, one per pipeline stage: listings (raw fetched pages), bills (parsed, merged
    records — the one mutable, current-state artifact), documents (downloaded PDFs), and each
    document's alternate representations — markdown (produced elsewhere; this pipeline does not
    parse PDFs), Akoma Ntoso XML, and the semantic files derived from that XML. Each derived
    representation also carries a provenance record and, for Akoma Ntoso, a gate verdict.
    """

    def save_listing(
        self, *, key: str, extension: str, body: bytes, metadata: dict[str, Any]
    ) -> None: ...
    def has_listing(self, *, key: str) -> bool: ...
    def iter_listings(self) -> Iterator[StoredListing]: ...

    def load_bill(self, slug: str) -> dict[str, Any] | None: ...
    def save_bill(self, slug: str, record: dict[str, Any]) -> None: ...
    def iter_bill_slugs(self) -> Iterator[str]: ...

    def has_document(self, *, bill_slug: str, doc_key: str, version: int) -> bool: ...
    def save_document(
        self,
        *,
        bill_slug: str,
        doc_key: str,
        version: int,
        content: bytes,
        metadata: dict[str, Any],
    ) -> None: ...
    def load_document(self, *, bill_slug: str, doc_key: str, version: int) -> bytes | None: ...
    def iter_documents(self) -> Iterator[StoredDocumentRef]: ...
    def iter_bill_documents(self, bill_slug: str) -> Iterator[StoredDocumentRef]: ...

    def has_markdown(self, *, bill_slug: str, doc_key: str, version: int) -> bool: ...
    def load_markdown(self, *, bill_slug: str, doc_key: str, version: int) -> str | None: ...
    def save_markdown(
        self, *, bill_slug: str, doc_key: str, version: int, content: str
    ) -> None: ...

    def has_crosscheck(self, *, bill_slug: str, doc_key: str, version: int) -> bool: ...
    def load_crosscheck(self, *, bill_slug: str, doc_key: str, version: int) -> str | None: ...
    def save_crosscheck(
        self, *, bill_slug: str, doc_key: str, version: int, content: str
    ) -> None: ...

    def has_akn(self, *, bill_slug: str, doc_key: str, version: int) -> bool: ...
    def load_akn(self, *, bill_slug: str, doc_key: str, version: int) -> bytes | None: ...
    def save_akn(self, *, bill_slug: str, doc_key: str, version: int, content: bytes) -> None: ...
    def save_rejected_akn(
        self, *, bill_slug: str, doc_key: str, version: int, content: bytes
    ) -> None: ...
    def withdraw_akn(self, *, bill_slug: str, doc_key: str, version: int) -> None: ...

    def save_structure_gate(
        self, *, bill_slug: str, doc_key: str, version: int, record: dict[str, Any]
    ) -> None: ...
    def load_structure_gate(
        self, *, bill_slug: str, doc_key: str, version: int
    ) -> dict[str, Any] | None: ...

    def has_semantic(self, *, bill_slug: str, doc_key: str, version: int) -> bool: ...
    def load_jsonld(self, *, bill_slug: str, doc_key: str, version: int) -> bytes | None: ...
    def load_rdf(self, *, bill_slug: str, doc_key: str, version: int) -> bytes | None: ...
    def save_jsonld(
        self, *, bill_slug: str, doc_key: str, version: int, content: bytes
    ) -> None: ...
    def save_rdf(self, *, bill_slug: str, doc_key: str, version: int, content: bytes) -> None: ...

    def load_provenance(
        self, *, bill_slug: str, doc_key: str, version: int, artifact: str
    ) -> dict[str, Any] | None: ...
    def save_provenance(
        self, *, bill_slug: str, doc_key: str, version: int, artifact: str, record: dict[str, Any]
    ) -> None: ...

    def save_manifest(self, *, step: str, run_id: str, payload: dict[str, Any]) -> None: ...
    def latest_manifest(self, *, step: str) -> dict[str, Any] | None: ...

    def iter_unexpected_files(self) -> Iterator[str]: ...


class FileStore:
    """Local-directory `PipelineStore`: the only backend built so far.

    Layout, all under `root`:
        listings/<key>/body.<ext> + metadata.json
        bills/<slug>/bill.json
        manifests/<step>/<run-id>.json
        documents/<bill-slug>/<doc-key>/v<NNN>/
            document.pdf                        the downloaded bytes + metadata.json sidecar
            document.md                         markdown, produced elsewhere (ADR-021)
            document.markdown.provenance.json   what it was extracted from, and by what
            document.akn.xml                    Akoma Ntoso, from pipeline.akn
            document.akn.provenance.json        the markdown, model, prompt and code behind it
            document.structure.gate.json              Gate P1's verdict, written pass or fail
            document.akn.rejected.xml           a failing render, kept as evidence, never promoted
            document.jsonld / document.nq       ELI JSON-LD + RDF N-Quads, from pipeline.semantic
            document.semantic.provenance.json

    Sidecars are serialised with the same deterministic writer the DB-backed audit tree uses
    (`storage.audit_tree.sidecar_bytes`) — sorted keys, two-space indent, UTF-8, LF — so a diff
    between two runs is ever only the fields that actually changed. Every write is atomic, so a
    reader — a later step, a verify pass, the public serving surface — never observes a
    half-written artifact.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    # --- listings ---

    def save_listing(
        self, *, key: str, extension: str, body: bytes, metadata: dict[str, Any]
    ) -> None:
        directory = self.root / "listings" / key
        _write_if_changed(directory / f"body.{extension}", body)
        _write_if_changed(directory / "metadata.json", sidecar_bytes(metadata))

    def has_listing(self, *, key: str) -> bool:
        """Whether a *successful* snapshot for this key is already stored.

        A stored non-200 deliberately does not count. Re-running a crawl should retry a failure,
        not cement it: the whole point of skipping is to avoid redundant work, not to freeze a bad
        response into the record.
        """
        directory = self.root / "listings" / key
        metadata = _read_json(directory / "metadata.json")
        if metadata is None or metadata.get("status_code") != 200:
            return False
        return any(directory.glob("body.*"))

    def iter_listings(self) -> Iterator[StoredListing]:
        listings_dir = self.root / "listings"
        if not listings_dir.exists():
            return
        for directory in sorted(p for p in listings_dir.iterdir() if p.is_dir()):
            metadata_path = directory / "metadata.json"
            if not metadata_path.exists():
                continue
            body_paths = sorted(directory.glob("body.*"))
            if not body_paths:
                continue
            metadata = _read_json(metadata_path)
            if metadata is None:
                continue
            yield StoredListing(directory.name, metadata, body_paths[0].read_bytes())

    # --- bills ---

    def load_bill(self, slug: str) -> dict[str, Any] | None:
        path = self.root / "bills" / slug / "bill.json"
        return _read_json(path) if path.exists() else None

    def save_bill(self, slug: str, record: dict[str, Any]) -> None:
        path = self.root / "bills" / slug / "bill.json"
        _write_if_changed(path, sidecar_bytes(record))

    def iter_bill_slugs(self) -> Iterator[str]:
        bills_dir = self.root / "bills"
        if not bills_dir.exists():
            return
        for directory in sorted(p for p in bills_dir.iterdir() if p.is_dir()):
            if (directory / "bill.json").exists():
                yield directory.name

    # --- documents ---

    def _document_dir(self, *, bill_slug: str, doc_key: str, version: int) -> Path:
        return self.root / "documents" / bill_slug / doc_key / f"v{version:03d}"

    def has_document(self, *, bill_slug: str, doc_key: str, version: int) -> bool:
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        return (directory / "document.pdf").exists() and (directory / "metadata.json").exists()

    def save_document(
        self,
        *,
        bill_slug: str,
        doc_key: str,
        version: int,
        content: bytes,
        metadata: dict[str, Any],
    ) -> None:
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        _write_if_changed(directory / "document.pdf", content)
        _write_if_changed(directory / "metadata.json", sidecar_bytes(metadata))

    def load_document(self, *, bill_slug: str, doc_key: str, version: int) -> bytes | None:
        path = (
            self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
            / "document.pdf"
        )
        return path.read_bytes() if path.exists() else None

    def iter_documents(self) -> Iterator[StoredDocumentRef]:
        documents_dir = self.root / "documents"
        if not documents_dir.exists():
            return
        for bill_dir in sorted(p for p in documents_dir.iterdir() if p.is_dir()):
            yield from self.iter_bill_documents(bill_dir.name)

    def iter_bill_documents(self, bill_slug: str) -> Iterator[StoredDocumentRef]:
        """Every stored document of one bill, without walking the whole corpus.

        The serving surface resolves a request to a single bill, so it must not pay for a scan of
        every other bill's directories to find one document.
        """
        bill_dir = self.root / "documents" / bill_slug
        if not bill_dir.exists():
            return
        for doc_dir in sorted(p for p in bill_dir.iterdir() if p.is_dir()):
            for version_dir in sorted(p for p in doc_dir.iterdir() if p.is_dir()):
                metadata_path = version_dir / "metadata.json"
                if not metadata_path.exists() or not _is_version_dir(version_dir.name):
                    continue
                metadata = _read_json(metadata_path)
                if metadata is None:
                    continue
                version_no = int(version_dir.name.removeprefix("v"))
                yield StoredDocumentRef(bill_slug, doc_dir.name, version_no, metadata)

    # --- markdown (an alternate representation of a document; produced elsewhere) ---

    def has_markdown(self, *, bill_slug: str, doc_key: str, version: int) -> bool:
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        return (directory / "document.md").exists()

    def load_markdown(self, *, bill_slug: str, doc_key: str, version: int) -> str | None:
        path = (
            self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
            / "document.md"
        )
        return _read_text(path) if path.exists() else None

    def save_markdown(self, *, bill_slug: str, doc_key: str, version: int, content: str) -> None:
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        _write_if_changed(directory / "document.md", content.encode("utf-8"))

    # --- the second, independent reading kept for cross-reference (ADR-035) ---
    #
    # A separate slot rather than a second `document.md`, because the two readings answer different
    # questions and only one of them is the corpus. `document.md` is what the AKN step converts and
    # what Gate P1 scores; this is the opinion it is checked against, and it must be able to
    # disagree without displacing anything downstream.

    def has_crosscheck(self, *, bill_slug: str, doc_key: str, version: int) -> bool:
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        return (directory / "document.crosscheck.md").exists()

    def load_crosscheck(self, *, bill_slug: str, doc_key: str, version: int) -> str | None:
        path = (
            self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
            / "document.crosscheck.md"
        )
        return _read_text(path) if path.exists() else None

    def save_crosscheck(self, *, bill_slug: str, doc_key: str, version: int, content: str) -> None:
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        _write_if_changed(directory / "document.crosscheck.md", content.encode("utf-8"))

    # --- Akoma Ntoso XML (derived from markdown by pipeline.akn) ---

    def has_akn(self, *, bill_slug: str, doc_key: str, version: int) -> bool:
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        return (directory / "document.akn.xml").exists()

    def load_akn(self, *, bill_slug: str, doc_key: str, version: int) -> bytes | None:
        path = (
            self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
            / "document.akn.xml"
        )
        return path.read_bytes() if path.exists() else None

    def save_akn(self, *, bill_slug: str, doc_key: str, version: int, content: bytes) -> None:
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        _write_if_changed(directory / "document.akn.xml", content)

    def save_rejected_akn(
        self, *, bill_slug: str, doc_key: str, version: int, content: bytes
    ) -> None:
        """Keep a gate-rejected render as evidence, under a name no `has_*` predicate reads.

        ADR-017 requires a failing artifact to be a review item rather than a discard: a verdict
        is only reviewable if what it judged is on the record. Nothing downstream picks this up.
        """
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        _write_if_changed(directory / "document.akn.rejected.xml", content)

    def withdraw_akn(self, *, bill_slug: str, doc_key: str, version: int) -> None:
        """Unpublish a reading: the Akoma Ntoso, and everything derived from it.

        The cascade is the point, not a convenience. The semantic files are built from this exact
        XML and their provenance names it as their source, so leaving them behind a withdrawn
        reading orphans them twice over — they describe a document that is no longer published, and
        `pipeline verify` correctly reports their source as missing from the store, which makes a
        pipeline that behaved exactly as designed look damaged. Removing the derived pair with its
        source is the only state that is internally consistent.

        The gate verdict and `document.akn.rejected.xml` stay: withdrawing a reading is a reviewable
        act, not a deletion. Each provenance record goes with the file it describes, because a
        record for bytes that are gone would make the artifact look current to `needs_rebuild`.
        """
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        for name in (
            "document.akn.xml",
            "document.akn.provenance.json",
            "document.jsonld",
            "document.nq",
            "document.semantic.provenance.json",
        ):
            (directory / name).unlink(missing_ok=True)

    def save_structure_gate(
        self, *, bill_slug: str, doc_key: str, version: int, record: dict[str, Any]
    ) -> None:
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        _write_if_changed(directory / "document.structure.gate.json", sidecar_bytes(record))

    def load_structure_gate(
        self, *, bill_slug: str, doc_key: str, version: int
    ) -> dict[str, Any] | None:
        path = (
            self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
            / "document.structure.gate.json"
        )
        return _read_json(path) if path.exists() else None

    # --- semantic files (ELI-style JSON-LD + RDF N-Quads, derived from Akoma Ntoso) ---

    def has_semantic(self, *, bill_slug: str, doc_key: str, version: int) -> bool:
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        return (directory / "document.jsonld").exists() and (directory / "document.nq").exists()

    def load_jsonld(self, *, bill_slug: str, doc_key: str, version: int) -> bytes | None:
        path = (
            self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
            / "document.jsonld"
        )
        return path.read_bytes() if path.exists() else None

    def load_rdf(self, *, bill_slug: str, doc_key: str, version: int) -> bytes | None:
        path = (
            self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
            / "document.nq"
        )
        return path.read_bytes() if path.exists() else None

    def save_jsonld(self, *, bill_slug: str, doc_key: str, version: int, content: bytes) -> None:
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        _write_if_changed(directory / "document.jsonld", content)

    def save_rdf(self, *, bill_slug: str, doc_key: str, version: int, content: bytes) -> None:
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        _write_if_changed(directory / "document.nq", content)

    # --- provenance of each derived artifact ---

    def load_provenance(
        self, *, bill_slug: str, doc_key: str, version: int, artifact: str
    ) -> dict[str, Any] | None:
        path = self._provenance_path(
            bill_slug=bill_slug, doc_key=doc_key, version=version, artifact=artifact
        )
        return _read_json(path) if path.exists() else None

    def save_provenance(
        self, *, bill_slug: str, doc_key: str, version: int, artifact: str, record: dict[str, Any]
    ) -> None:
        path = self._provenance_path(
            bill_slug=bill_slug, doc_key=doc_key, version=version, artifact=artifact
        )
        _write_if_changed(path, sidecar_bytes(record))

    def _provenance_path(
        self, *, bill_slug: str, doc_key: str, version: int, artifact: str
    ) -> Path:
        if artifact not in ARTIFACTS:
            raise ValueError(f"unknown artifact: {artifact!r}")
        directory = self._document_dir(bill_slug=bill_slug, doc_key=doc_key, version=version)
        return directory / f"document.{artifact}.provenance.json"

    # --- per-run manifests ---

    def save_manifest(self, *, step: str, run_id: str, payload: dict[str, Any]) -> None:
        """One record per step run: what it read, what it wrote, and what failed (HANDOFF 27.3).

        Timestamps and run ids belong here and nowhere else. The path is already per-run, so a
        volatile field costs nothing — whereas the same field inside a per-artifact sidecar would
        make every re-run rewrite it and destroy the "a repeat run writes nothing" guarantee.
        """
        body = dict(payload)
        body.setdefault("step", step)
        body.setdefault("run_id", run_id)
        write_atomically(self.root / "manifests" / step / f"{run_id}.json", sidecar_bytes(body))

    def latest_manifest(self, *, step: str) -> dict[str, Any] | None:
        """The newest run record for one step, or `None` if that step has never run.

        Run ids are UTC timestamps, so the newest is the lexicographic maximum of the filenames —
        no need to open every manifest to sort them, and no dependence on filesystem mtimes, which
        a checkout or a copy would reorder.

        Read-only callers use this to learn something a step knew and the corpus does not record:
        `coverage` asks which documents the reader found no text layer in, because nothing is
        written for a reading that produced nothing.
        """
        directory = self.root / "manifests" / step
        if not directory.is_dir():
            return None
        names = sorted(path.name for path in directory.glob("*.json"))
        if not names:
            return None
        return _read_json(directory / names[-1])

    # --- integrity ---

    def iter_unexpected_files(self) -> Iterator[str]:
        """Store-relative paths of files no step in this pipeline writes.

        A leftover atomic-write temp file, a hand-dropped edit, or an artifact from a future
        version all show up here rather than being silently served or silently ignored.
        """
        documents_dir = self.root / "documents"
        if not documents_dir.exists():
            return
        for path in sorted(documents_dir.rglob("*")):
            if path.is_dir():
                continue
            if path.name in KNOWN_FILENAMES and _is_version_dir(path.parent.name):
                continue
            yield str(path.relative_to(self.root))


def _is_version_dir(name: str) -> bool:
    return name.startswith("v") and name[1:].isdigit()


def _read_text(path: Path) -> str:
    """Read a stored text file as UTF-8, which is how every writer here wrote it.

    `Path.read_text()` without an encoding uses the platform's locale, so the same file read on a
    host with a non-UTF-8 locale decodes differently — silent corruption of a bill title or a
    provision heading rather than an error.
    """
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any] | None:
    """A stored sidecar, or None when it cannot be read.

    None rather than an exception because these are read on the serving path and while walking the
    corpus: one hand-edited or half-written sidecar must cost its own document, not every listing
    page in the chamber and not a whole step run. `pipeline verify` is what reports it as damage —
    a reader's job is to keep going.
    """
    try:
        loaded = json.loads(_read_text(path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def sha256_of(payload: bytes | str) -> str:
    """The one hashing call for pipeline provenance, matching the rest of the codebase."""
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(data).hexdigest()


def build_pipeline_store(settings: Settings) -> PipelineStore:
    """Resolve the configured pipeline backend. No caller picks an implementation.

    Shaped like `storage.build_blob_store`, and here rather than beside either caller because both
    the CLI and the serving surface need it: two factories would be two places for a second backend
    to be added to, which is exactly the coupling `PipelineStore` exists to prevent.
    """
    return FileStore(settings.corpus_root)
