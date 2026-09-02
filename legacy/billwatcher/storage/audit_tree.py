"""The audit tree: a human-legible, byte-reproducible projection of the archive (HANDOFF 27).

The database and blob store remain the authoritative, append-only record (HANDOFF 8-10). This
module never decides what happened; it only serialises what already happened into a directory a
person can browse with no database access. Nothing written here is read back into the database.

Scope today is `03-documents/` (Package K, the PDF download step) and `04-text/` (HANDOFF 27.7,
the MinerU markdown reading). The listing tier (`01-listings/`, `02-bills/`) and the remaining
processing tiers (`05-structures/` through `07-embeddings/`) are specified in HANDOFF 27.2 but not
yet built.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

METADATA_SCHEMA_VERSION = 1


def write_atomically(path: Path, payload: bytes) -> None:
    """Replace `path`'s contents with `payload` in one indivisible step.

    A plain `write_bytes` truncates first and writes second, so a crash between the two leaves a
    short file that still exists — and an existence-only check (`has_document`, `has_akn`) then
    calls it done forever. Writing a sibling and renaming it means a reader either sees the whole
    previous file or the whole new one; `os.replace` is atomic within a filesystem.

    The temp name is dotted so it matches none of the readers' globs (`body.*`, `metadata.json`,
    the blob store's `*/*/*`) and so a leftover from a killed process cannot be mistaken for an
    artifact by the audit tree's rebuild diff, which reports every unexpected file it finds.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def sidecar_bytes(data: dict[str, Any]) -> bytes:
    """Serialise a sidecar deterministically: sorted keys, two-space indent, UTF-8, LF.

    This determinism is what makes `audit-rebuild` provably a no-op over an already-correct
    tree (HANDOFF 27.4) — the whole point of the tree being a projection rather than a second
    place state can drift.
    """
    text = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def doc_key(document_id: str) -> str:
    """A path-safe identifier built only from our own primary key, never an upstream filename."""
    return f"doc-{document_id.replace('-', '')[:8]}"


def _write_if_changed(path: Path, payload: bytes) -> bool:
    """Write only when the file is missing or its bytes differ.

    This is the idempotence rule HANDOFF 27.1 requires of every step, and is what lets
    `audit-rebuild` claim "byte-identical, writes nothing" over a tree that is already correct.
    """
    if path.exists() and path.read_bytes() == payload:
        return False
    write_atomically(path, payload)
    return True


@dataclass(frozen=True, slots=True)
class WriteResult:
    directory: Path
    pdf_written: bool
    sidecar_written: bool


@dataclass(frozen=True, slots=True)
class ExtractionWriteResult:
    directory: Path
    content_written: bool
    sidecar_written: bool


class AuditTree:
    """Path layout and low-level writes for the audit tree (HANDOFF 27.2).

    Deliberately free of database and blob-store knowledge: callers hand over already-decided
    bytes and an already-built sidecar, and this class only ever decides *where* they go and
    *whether* they need writing.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def document_dir(self, *, bill_slug: str, document_id: str, version_no: int) -> Path:
        return self.root / "03-documents" / bill_slug / doc_key(document_id) / f"v{version_no:03d}"

    def write_document_version(
        self,
        *,
        bill_slug: str,
        document_id: str,
        version_no: int,
        pdf_bytes: bytes,
        sidecar: dict[str, Any],
    ) -> WriteResult:
        directory = self.document_dir(
            bill_slug=bill_slug, document_id=document_id, version_no=version_no
        )
        pdf_written = _write_if_changed(directory / "document.pdf", pdf_bytes)
        payload = dict(sidecar)
        payload.setdefault("metadata_schema_version", METADATA_SCHEMA_VERSION)
        payload.setdefault("artifact", "document")
        payload.setdefault("raw_file", "document.pdf")
        sidecar_written = _write_if_changed(directory / "metadata.json", sidecar_bytes(payload))
        return WriteResult(directory, pdf_written, sidecar_written)

    def extraction_dir(
        self,
        *,
        bill_slug: str,
        document_id: str,
        version_no: int,
        extractor_name: str,
        extractor_version: str,
    ) -> Path:
        return (
            self.root
            / "04-text"
            / bill_slug
            / doc_key(document_id)
            / f"v{version_no:03d}"
            / f"{extractor_name}@{extractor_version}"
        )

    def write_extraction(
        self,
        *,
        bill_slug: str,
        document_id: str,
        version_no: int,
        extractor_name: str,
        extractor_version: str,
        raw_file: str,
        content_bytes: bytes,
        sidecar: dict[str, Any],
    ) -> ExtractionWriteResult:
        directory = self.extraction_dir(
            bill_slug=bill_slug,
            document_id=document_id,
            version_no=version_no,
            extractor_name=extractor_name,
            extractor_version=extractor_version,
        )
        content_written = _write_if_changed(directory / raw_file, content_bytes)
        payload = dict(sidecar)
        payload.setdefault("metadata_schema_version", METADATA_SCHEMA_VERSION)
        payload.setdefault("artifact", "extraction")
        payload.setdefault("raw_file", raw_file)
        sidecar_written = _write_if_changed(directory / "metadata.json", sidecar_bytes(payload))
        return ExtractionWriteResult(directory, content_written, sidecar_written)

    def write_manifest(self, *, step: str, run_id: str, payload: dict[str, Any]) -> Path:
        path = self.root / "manifests" / step / f"{run_id}.json"
        body = dict(payload)
        body.setdefault("step", step)
        body.setdefault("run_id", run_id)
        write_atomically(path, sidecar_bytes(body))
        return path
