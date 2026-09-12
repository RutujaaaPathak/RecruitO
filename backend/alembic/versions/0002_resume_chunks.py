"""resume chunks (pgvector RAG index)

Revision ID: 0002_resume_chunks
Revises: 0001_initial_tables
Create Date: 2026-09-11
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector  # pyrefly: ignore [missing-import]

# revision identifiers, used by Alembic.
revision = "0002_resume_chunks"
down_revision = "0001_initial_tables"
branch_labels = None
depends_on = None

# Must match app.models.VECTOR_DIM (All-MiniLM-L6-v2 embeddings).
_VECTOR_DIM = 384


def upgrade() -> None:
    # Enable the pgvector extension before creating the VECTOR column type.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "resume_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "resume_id", sa.Integer(), sa.ForeignKey("resumes.id"), nullable=False
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(_VECTOR_DIM), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "resume_id", "chunk_index", name="uq_resume_chunk_index"
        ),
    )
    op.create_index("ix_resume_chunks_id", "resume_chunks", ["id"])
    op.create_index("ix_resume_chunks_resume_id", "resume_chunks", ["resume_id"])
    # HNSW cosine index for fast nearest-neighbor retrieval (pgvector >= 0.5.0).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_resume_chunks_embedding_hnsw "
        "ON resume_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_resume_chunks_embedding_hnsw")
    op.drop_index("ix_resume_chunks_resume_id", table_name="resume_chunks")
    op.drop_index("ix_resume_chunks_id", table_name="resume_chunks")
    op.drop_table("resume_chunks")