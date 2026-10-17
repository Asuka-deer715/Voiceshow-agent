"""Add pgvector-backed knowledge storage."""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_pgvector_store"
down_revision = "0002_auth_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("VoiceShop now requires PostgreSQL with the pgvector extension")

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_vectors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("chunk_id", sa.Text, nullable=False, unique=True),
        sa.Column("collection", sa.Text, nullable=False, server_default=""),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("record_json", JSONB, nullable=False),
    )
    op.create_index(
        "ix_knowledge_vectors_embedding_hnsw",
        "knowledge_vectors",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_knowledge_vectors_collection_source",
        "knowledge_vectors",
        ["collection", "source"],
    )
    op.create_table(
        "knowledge_index_state",
        sa.Column("id", sa.SmallInteger, primary_key=True),
        sa.Column("model_id", sa.Text, nullable=False),
        sa.Column("model_revision", sa.Text, nullable=False),
        sa.Column("dimension", sa.Integer, nullable=False),
        sa.Column("corpus_fingerprint", sa.Text, nullable=False),
        sa.Column("record_count", sa.Integer, nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_knowledge_index_state_singleton"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_index_state")
    op.drop_index("ix_knowledge_vectors_collection_source", table_name="knowledge_vectors")
    op.drop_index("ix_knowledge_vectors_embedding_hnsw", table_name="knowledge_vectors")
    op.drop_table("knowledge_vectors")
