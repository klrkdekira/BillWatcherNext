import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class VersionAction(StrEnum):
    NOT_MODIFIED = "not_modified"
    VERIFIED = "verified"
    CREATED = "created"
    ROLLBACK = "rollback"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class KnownVersion:
    version_no: int
    content_sha256: str
    is_current: bool


@dataclass(frozen=True, slots=True)
class DownloadObservation:
    status_code: int
    checked_at: datetime
    body: bytes | None = None
    media_type_declared: str | None = None


@dataclass(frozen=True, slots=True)
class VersionDecision:
    action: VersionAction
    content_sha256: str | None
    next_version_no: int | None
    validation_error: str | None = None
    matched_version_no: int | None = None


def decide_document_version(
    observation: DownloadObservation,
    known_versions: list[KnownVersion],
    *,
    expected_pdf: bool = True,
) -> VersionDecision:
    """Pure implementation of HANDOFF §9.3; persistence happens transactionally elsewhere."""
    current = next((version for version in known_versions if version.is_current), None)
    if observation.status_code == 304:
        return VersionDecision(VersionAction.NOT_MODIFIED, None, None)
    if observation.status_code != 200 or observation.body is None:
        raise ValueError("only successful 200/304 observations enter the version state machine")

    digest = hashlib.sha256(observation.body).hexdigest()
    if current and digest == current.content_sha256:
        return VersionDecision(
            VersionAction.VERIFIED, digest, None, matched_version_no=current.version_no
        )

    matching = next(
        (version for version in known_versions if version.content_sha256 == digest), None
    )
    next_number = max((version.version_no for version in known_versions), default=0) + 1

    declared = (observation.media_type_declared or "").split(";", 1)[0].strip().casefold()
    invalid_pdf = declared != "application/pdf" or not observation.body.startswith(b"%PDF-")
    if expected_pdf and invalid_pdf:
        reason = "expected application/pdf with PDF magic bytes"
        return VersionDecision(VersionAction.QUARANTINED, digest, next_number, reason)

    if matching is not None:
        return VersionDecision(
            VersionAction.ROLLBACK, digest, next_number, matched_version_no=matching.version_no
        )
    return VersionDecision(VersionAction.CREATED, digest, next_number)
