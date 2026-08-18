"""Add the Release 3 chunk and embedding tables.

The vector width here is a schema decision. A model whose dimension differs needs its own
migration plus a recorded `reembed` backfill; dimensions are never silently mixed (HANDOFF 8).
The HNSW index is deliberately not created here — HANDOFF 12.3 builds it only once
representative data exists, through `billwatcher semantic-index`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from billwatcher.models import EMBEDDING_DIMENSION

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "document_chunks" not in tables:
        op.create_table(
            "document_chunks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("extraction_id", sa.ForeignKey("document_extractions.id"), nullable=False),
            sa.Column("chunker_version", sa.String(32), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("heading", sa.Text(), nullable=True),
            sa.Column("page_start", sa.Integer(), nullable=True),
            sa.Column("page_end", sa.Integer(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("token_count", sa.Integer(), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("extraction_id", "chunker_version", "chunk_index"),
        )
        op.create_index(
            "ix_document_chunks_extraction", "document_chunks", ["extraction_id", "chunker_version"]
        )
        op.create_index("ix_document_chunks_is_current", "document_chunks", ["is_current"])

    if "chunk_embeddings" in tables:
        return
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        embedding_column = sa.Column("embedding", sa.Text(), nullable=False)
    else:
        embedding_column = sa.Column("embedding", sa.JSON(), nullable=False)
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chunk_id", sa.ForeignKey("document_chunks.id"), nullable=False),
        sa.Column("embedding_model_id", sa.String(128), nullable=False),
        sa.Column("model_dimension", sa.Integer(), nullable=False),
        embedding_column,
        sa.Column("embedding_pipeline_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("chunk_id", "embedding_model_id"),
    )
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE chunk_embeddings ALTER COLUMN embedding "
            f"TYPE vector({EMBEDDING_DIMENSION}) USING embedding::vector"
        )


def downgrade() -> None:
    op.drop_table("chunk_embeddings")
    op.drop_table("document_chunks")
