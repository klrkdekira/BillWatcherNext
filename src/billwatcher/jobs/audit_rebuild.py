"""Keep the document tier of the audit tree honest against the database (HANDOFF 27.4).

Two offline operations, both scoped to `03-documents/` today (Package K covers the PDF download
step only; the listing and processing tiers are not built yet):

- `rebuild_documents` regenerates every accepted or quarantined document version's directory from
  the database and blob store. Run over an already-correct tree it writes nothing new, because
  every write it makes goes through `AuditTree`'s write-if-changed rule.
- `verify_documents` proves that claim rather than assuming it: it rebuilds into a throwaway
  directory and diffs the result against the real tree file by file, so a tampered byte, a
  missing artifact, or a stray file with no backing record all surface as a named issue.
"""

import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import Document, DocumentVersion
from billwatcher.operations import record_anomaly
from billwatcher.scraper.document_worker import write_version_to_audit_tree
from billwatcher.storage.audit_tree import AuditTree
from billwatcher.storage.blobs import BlobStore

# Both statuses are worth a directory: a quarantined download is still a raw bytes-on-the-wire
# fact, tagged by its own `validation_status` in the sidecar rather than left invisible.
_TREE_ELIGIBLE_STATUSES = ("accepted", "quarantined")


def rebuild_documents(
    session: Session, *, blob_store: BlobStore, audit_tree: AuditTree
) -> dict[str, int]:
    rows = session.execute(
        select(DocumentVersion, Document)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(DocumentVersion.validation_status.in_(_TREE_ELIGIBLE_STATUSES))
        .order_by(DocumentVersion.document_id, DocumentVersion.version_no)
    ).all()
    considered = 0
    skipped_no_bill_link = 0
    directories: set[Path] = set()
    for version, document in rows:
        considered += 1
        written = write_version_to_audit_tree(
            session,
            audit_tree=audit_tree,
            document=document,
            version=version,
            blob_store=blob_store,
            step="fetch-documents",
        )
        if not written:
            skipped_no_bill_link += 1
        directories.update(written)
    return {
        "versions_considered": considered,
        "directories_written": len(directories),
        "skipped_no_bill_link": skipped_no_bill_link,
    }


def verify_documents(
    session: Session, *, audit_tree: AuditTree, blob_store: BlobStore
) -> list[str]:
    """Regenerate the document tier into a scratch directory and diff it file by file."""
    issues: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        shadow = AuditTree(Path(scratch))
        rebuild_documents(session, blob_store=blob_store, audit_tree=shadow)
        real_root = audit_tree.root / "03-documents"
        shadow_root = shadow.root / "03-documents"
        real_files = _relative_files(real_root)
        shadow_files = _relative_files(shadow_root)
        for rel in sorted(shadow_files - real_files):
            issues.append(f"missing from tree: 03-documents/{rel}")
        for rel in sorted(real_files - shadow_files):
            issues.append(f"present in tree with no matching database record: 03-documents/{rel}")
        for rel in sorted(shadow_files & real_files):
            if (shadow_root / rel).read_bytes() != (real_root / rel).read_bytes():
                issues.append(f"content differs from the database record: 03-documents/{rel}")
    return issues


def _relative_files(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def check_audit_tree(
    session: Session,
    *,
    audit_tree: AuditTree,
    blob_store: BlobStore,
    now: datetime,
) -> list[str]:
    """Verify and, on any divergence, raise the HANDOFF 10.5 anomaly `make doctor` reads."""
    issues = verify_documents(session, audit_tree=audit_tree, blob_store=blob_store)
    if issues:
        record_anomaly(
            session,
            kind="audit_tree_divergence",
            severity="critical",
            detail={"issue_count": len(issues), "examples": issues[:10]},
            now=now,
        )
    return issues
