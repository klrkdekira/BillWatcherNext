from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from billwatcher.models import Anomaly, FieldOverride, RecordChange
from billwatcher.scraper.normalize import normalize_text
from billwatcher.version import PARSER_VERSION


def normalized_equal(before: Any, after: Any) -> bool:
    if isinstance(before, str) and isinstance(after, str):
        return normalize_text(before) == normalize_text(after)
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
) -> bool:
    """Apply override/null/diff rules and write the change in the same transaction."""
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
        value = override.value
        if not normalized_equal(incoming, override.upstream_value_at_creation):
            _upsert_override_conflict(
                session,
                entity_type=entity_type,
                entity_id=entity.id,
                changed_at=changed_at,
                incoming=incoming,
                override=override,
            )
    if normalized_equal(before, value):
        return False
    setattr(entity, field_path, value)
    session.add(
        RecordChange(
            entity_type=entity_type,
            entity_id=entity.id,
            field_path=field_path,
            value_before=before,
            value_after=value,
            changed_at=changed_at,
            change_source=change_source,
            run_id=run_id,
            snapshot_id=snapshot_id,
            source_url=source_url,
            parser_version=PARSER_VERSION,
        )
    )
    return True


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
