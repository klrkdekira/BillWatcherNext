"""Weight the search-unit vector and record proposed document relations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WEIGHTED_TSV = (
    "setweight(to_tsvector('simple', coalesce(content_a, '')), 'A') || "
    "setweight(to_tsvector('simple', content), "
    "CASE WHEN unit_kind = 'bill_metadata' THEN 'B'::\"char\" ELSE 'C'::\"char\" END)"
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    unit_columns = {column["name"] for column in inspector.get_columns("search_units")}
    if "content_a" not in unit_columns:
        op.add_column("search_units", sa.Column("content_a", sa.Text(), nullable=True))
    if "part" not in unit_columns:
        op.add_column(
            "search_units",
            sa.Column("part", sa.Integer(), nullable=False, server_default="1"),
        )
    if "document_relations" not in inspector.get_table_names():
        op.create_table(
            "document_relations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("from_document_id", sa.ForeignKey("documents.id"), nullable=False),
            sa.Column("to_document_id", sa.ForeignKey("documents.id"), nullable=False),
            sa.Column("relation", sa.String(32), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("decided_by", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.UniqueConstraint("from_document_id", "to_document_id", "relation"),
        )
    if bind.dialect.name != "postgresql":
        return
    # The generated column must be rebuilt because its expression now carries weights.
    op.execute("DROP INDEX IF EXISTS ix_search_units_tsv")
    op.execute("ALTER TABLE search_units DROP COLUMN IF EXISTS tsv")
    op.execute(
        "ALTER TABLE search_units ADD COLUMN tsv tsvector "
        f"GENERATED ALWAYS AS ({_WEIGHTED_TSV}) STORED"
    )
    op.execute("CREATE INDEX ix_search_units_tsv ON search_units USING GIN (tsv)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_search_units_bill_current "
        "ON search_units (bill_id, is_current)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_search_units_bill_current")
        op.execute("DROP INDEX IF EXISTS ix_search_units_tsv")
        op.execute("ALTER TABLE search_units DROP COLUMN IF EXISTS tsv")
        op.execute(
            "ALTER TABLE search_units ADD COLUMN tsv tsvector "
            "GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED"
        )
        op.execute("CREATE INDEX ix_search_units_tsv ON search_units USING GIN (tsv)")
    op.drop_table("document_relations")
    op.drop_column("search_units", "part")
    op.drop_column("search_units", "content_a")
