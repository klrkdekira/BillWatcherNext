from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import Anomaly, FieldOverride, RecordChange
from billwatcher.scraper.normalize import normalize_text
from billwatcher.version import PARSER_VERSION


def jsonable(value: Any) -> Any:
    """Render a stored value for the JSON change log without losing it.

    `record_changes.value_before` and `value_after` are JSON columns, so dates and timestamps
    are written as ISO-8601 text. The entity itself keeps the real typed value.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def coerce_like(current: Any, incoming: Any) -> Any:
    """Bring a JSON-decoded override value back to the column's type before assigning it."""
    if (
        isinstance(incoming, str)
        and isinstance(current, date)
        and not isinstance(current, datetime)
    ):
        try:
            return date.fromisoformat(incoming)
        except ValueError:
            return incoming
    return incoming


def normalized_equal(before: Any, after: Any) -> bool:
    if isinstance(before, str) and isinstance(after, str):
        return normalize_text(before) == normalize_text(after)
    if isinstance(before, date | datetime) or isinstance(after, date | datetime):
        return bool(jsonable(before) == jsonable(after))
    return bool(before == after)


def active_override(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    field_path: str,
    at: datetime,
) -> FieldOverride | None:
    return session.scalar(
        select(FieldOverride)
        .where(
            FieldOverride.entity_type == entity_type,
            FieldOverride.entity_id == entity_id,
            FieldOverride.field_path == field_path,
            (FieldOverride.expires_at.is_(None) | (FieldOverride.expires_at > at)),
        )
        .order_by(FieldOverride.created_at.desc())
        .limit(1)
    )


def update_tracked_field(
    session: Session,
    *,
    entity: Any,
    entity_type: str,
    field_path: str,
    incoming: Any,
    changed_at: datetime,
    change_source: str,
    run_id: str | None,
    snapshot_id: str | None,
    source_url: str | None,
    explicit_removal: bool = False,
    equivalent: Callable[[Any, Any], bool] | None = None,
    oscillation_is_conflict: bool = False,
) -> bool:
    """Apply override/null/diff rules and write the change in the same transaction.

    `equivalent` replaces plain normalized comparison for fields where two different strings can
    be the same value. Only the title uses it so far, because the site publishes one bill's
    title in more than one form and rewriting it on every crawl would fill the change history
    with edits nobody made (see `same_title`).
    """
    before = getattr(entity, field_path)
    if incoming is None and before is not None and not explicit_removal:
        return False
    override = active_override(
        session,
        entity_type=entity_type,
        entity_id=entity.id,
        field_path=field_path,
        at=changed_at,
    )
    value = incoming
    if override is not None:
        value = coerce_like(before, override.value)
        if not normalized_equal(incoming, override.upstream_value_at_creation):
            _upsert_override_conflict(
                session,
                entity_type=entity_type,
                entity_id=entity.id,
                changed_at=changed_at,
                incoming=incoming,
                override=override,
            )
    same = equivalent or normalized_equal
    if same(before, value):
        return False
    if oscillation_is_conflict and override is None and _reverts_a_recorded_change(
        session,
        entity_type=entity_type,
        entity_id=entity.id,
        field_path=field_path,
        incoming=value,
        same=same,
    ):
        # We have already recorded moving *away* from this value, and now a source is offering it
        # back. That is not an edit anybody made; it is two sources disagreeing about one field,
        # and rewriting it would append the same pair of changes on every crawl for ever. Three
        # archived bills do this: the Dewan Rakyat's listing and the Dewan Negara's give different
        # titles for one code, including D.R.11/2013, where they are two different bills sharing
        # a code. The first-recorded value stands and the disagreement is raised for review.
        #
        # An active override is exempt: restoring a value we once moved away from is exactly what
        # an operator correction is for, and second-guessing it would make the override useless.
        _upsert_field_conflict(
            session,
            entity_type=entity_type,
            entity_id=entity.id,
            field_path=field_path,
            changed_at=changed_at,
            held=before,
            offered=value,
            source_url=source_url,
        )
        return False
    setattr(entity, field_path, value)
    session.add(
        RecordChange(
            entity_type=entity_type,
            entity_id=entity.id,
            field_path=field_path,
            value_before=jsonable(before),
            value_after=jsonable(value),
            changed_at=changed_at,
            change_source=change_source,
            run_id=run_id,
            snapshot_id=snapshot_id,
            source_url=source_url,
            parser_version=PARSER_VERSION,
        )
    )
    return True


def _reverts_a_recorded_change(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    field_path: str,
    incoming: Any,
    same: Callable[[Any, Any], bool],
) -> bool:
    """Whether this value is one we have already recorded replacing."""
    previous = session.scalars(
        select(RecordChange.value_before).where(
            RecordChange.entity_type == entity_type,
            RecordChange.entity_id == entity_id,
            RecordChange.field_path == field_path,
        )
    ).all()
    return any(same(value, incoming) for value in previous)


def _upsert_field_conflict(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    field_path: str,
    changed_at: datetime,
    held: Any,
    offered: Any,
    source_url: str | None,
) -> None:
    """Record that two sources disagree about one field, deduplicated by entity."""
    anomaly = session.scalar(
        select(Anomaly).where(
            Anomaly.kind == "duplicate_identifier_conflict",
            Anomaly.entity_type == entity_type,
            Anomaly.entity_id == entity_id,
            Anomaly.resolved_at.is_(None),
        )
    )
    detail = {
        "field_path": field_path,
        "held": jsonable(held),
        "offered": jsonable(offered),
    }
    if anomaly is not None:
        anomaly.last_seen_at = changed_at
        anomaly.occurrence_count += 1
        anomaly.detail_json = detail
        return
    session.add(
        Anomaly(
            kind="duplicate_identifier_conflict",
            severity="warn",
            entity_type=entity_type,
            entity_id=entity_id,
            url=source_url,
            detail_json=detail,
            first_seen_at=changed_at,
            last_seen_at=changed_at,
        )
    )


def _upsert_override_conflict(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    changed_at: datetime,
    incoming: Any,
    override: FieldOverride,
) -> None:
    anomaly = session.scalar(
        select(Anomaly).where(
            Anomaly.kind == "override_conflict",
            Anomaly.entity_type == entity_type,
            Anomaly.entity_id == entity_id,
            Anomaly.resolved_at.is_(None),
        )
    )
    detail = {"field": override.field_path, "incoming": incoming}
    if anomaly:
        anomaly.last_seen_at = changed_at
        anomaly.occurrence_count += 1
        anomaly.detail_json = detail
    else:
        session.add(
            Anomaly(
                kind="override_conflict",
                severity="warn",
                entity_type=entity_type,
                entity_id=entity_id,
                detail_json=detail,
                first_seen_at=changed_at,
                last_seen_at=changed_at,
            )
        )
