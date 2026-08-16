"""Create the Release 1 archival schema."""

from collections.abc import Sequence

from alembic import op

from billwatcher import models  # noqa: F401
from billwatcher.db import Base

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute(
            "ALTER TABLE search_units ADD COLUMN IF NOT EXISTS tsv tsvector "
            "GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED"
        )
        op.execute("CREATE INDEX IF NOT EXISTS ix_search_units_tsv ON search_units USING GIN (tsv)")


def downgrade() -> None:
    # Destructive downgrades are for disposable development databases only.
    Base.metadata.drop_all(bind=op.get_bind())
