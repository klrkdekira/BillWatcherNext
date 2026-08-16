from datetime import UTC, datetime

from billwatcher.scraper.versioning import (
    DownloadObservation,
    KnownVersion,
    VersionAction,
    decide_document_version,
)

NOW = datetime(2026, 8, 16, tzinfo=UTC)
PDF_1 = b"%PDF-1.7\\nfirst"
PDF_2 = b"%PDF-1.7\\nsecond"


def observation(body: bytes) -> DownloadObservation:
    return DownloadObservation(200, NOW, body, "application/pdf")


def test_304_creates_no_version() -> None:
    decision = decide_document_version(DownloadObservation(304, NOW), [])
    assert decision.action == VersionAction.NOT_MODIFIED
    assert decision.next_version_no is None


def test_identical_bytes_are_verified_without_a_version() -> None:
    initial = decide_document_version(observation(PDF_1), [])
    known = [KnownVersion(1, initial.content_sha256 or "", True)]
    decision = decide_document_version(observation(PDF_1), known)
    assert decision.action == VersionAction.VERIFIED
    assert decision.next_version_no is None


def test_changed_bytes_increment_version() -> None:
    initial = decide_document_version(observation(PDF_1), [])
    decision = decide_document_version(
        observation(PDF_2), [KnownVersion(1, initial.content_sha256 or "", True)]
    )
    assert decision.action == VersionAction.CREATED
    assert decision.next_version_no == 2


def test_older_bytes_create_new_rollback_version() -> None:
    first = decide_document_version(observation(PDF_1), [])
    second = decide_document_version(observation(PDF_2), [])
    known = [
        KnownVersion(1, first.content_sha256 or "", False),
        KnownVersion(2, second.content_sha256 or "", True),
    ]
    decision = decide_document_version(observation(PDF_1), known)
    assert decision.action == VersionAction.ROLLBACK
    assert decision.next_version_no == 3
    assert decision.matched_version_no == 1


def test_wrong_magic_bytes_are_quarantined() -> None:
    bad = DownloadObservation(200, NOW, b"<html>login</html>", "text/html")
    decision = decide_document_version(bad, [])
    assert decision.action == VersionAction.QUARANTINED
    assert decision.next_version_no == 1
