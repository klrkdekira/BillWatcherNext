"""Add the Stage 1 structural tables (HANDOFF 26.3).

Both readings of a document are stored — the Arrangement of Sections and the body — because
Gate L1's verdict is reviewable only if what it compared is on the record. Nothing here is
populated by the migration: structures are derived from stored bytes by
`billwatcher restructure`, so an empty database upgrades to head and stays empty.

Two conventions here are load-bearing and are easy to get wrong, because a fresh database never
exercises this body at all — migration 0001 runs `Base.metadata.create_all()`, which already
creates these tables from `models.py`, so the guards below skip. Only a database that reached
0003 *before* this change ever runs the DDL.

1. **Every foreign-key column states its type.** `sa.Column("x", sa.ForeignKey(...))` alone
   compiles to `NullType` inside a migration — Alembic builds each table in its own metadata, so
   there is no referenced column to infer from — and raises `CompileError` at upgrade time on
   exactly the deployments that need it.
2. **Constraint and index names match what `create_all` produces**, so a database built fresh and
   one upgraded in place carry the same object names. Unique constraints are left unnamed for
   the backend to name, as 0003 does, and the `is_current` index uses the name SQLAlchemy's
   `index=True` generates.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "document_structures" not in tables:
        op.create_table(
            "document_structures",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "document_version_id",
                sa.String(36),
                sa.ForeignKey("document_versions.id"),
                nullable=False,
            ),
            sa.Column("extractor_name", sa.String(64), nullable=False),
            sa.Column("extractor_version", sa.String(32), nullable=False),
            sa.Column("structure_version", sa.String(32), nullable=False),
            sa.Column("unit", sa.String(16), nullable=False),
            sa.Column("language", sa.String(16), nullable=True),
            sa.Column("gate_status", sa.String(24), nullable=False),
            sa.Column("arrangement_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("body_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("difference_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("blocking_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("detail_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("page_count", sa.Integer(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint(
                "document_version_id",
                "extractor_name",
                "extractor_version",
                "structure_version",
            ),
        )
        op.create_index(
            "ix_document_structures_gate", "document_structures", ["gate_status", "is_current"]
        )
        op.create_index(
            "ix_document_structures_is_current", "document_structures", ["is_current"]
        )

    if "provision_nodes" not in tables:
        op.create_table(
            "provision_nodes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "structure_id",
                sa.String(36),
                sa.ForeignKey("document_structures.id"),
                nullable=False,
            ),
            sa.Column("source", sa.String(16), nullable=False),
            sa.Column(
                "parent_id", sa.String(36), sa.ForeignKey("provision_nodes.id"), nullable=True
            ),
            sa.Column("node_type", sa.String(24), nullable=False),
            sa.Column("num", sa.String(16), nullable=False),
            sa.Column("heading", sa.Text(), nullable=True),
            sa.Column("eid", sa.Text(), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("page_from", sa.Integer(), nullable=True),
            sa.UniqueConstraint("structure_id", "source", "eid"),
        )
        op.create_index(
            "ix_provision_nodes_structure", "provision_nodes", ["structure_id", "source", "ordinal"]
        )


def downgrade() -> None:
    op.drop_table("provision_nodes")
    op.drop_table("document_structures")
