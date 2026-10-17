from __future__ import annotations

from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Integer, MetaData, SmallInteger, Table, Text, delete, insert, select
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert

from .database import read_engine, write_engine
from .embedding_config import EMBEDDING_DIMENSION

metadata = MetaData()

knowledge_vectors = Table(
    "knowledge_vectors",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("chunk_id", Text, nullable=False, unique=True),
    Column("collection", Text, nullable=False, server_default=""),
    Column("source", Text, nullable=False),
    Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=False),
    Column("record_json", JSONB, nullable=False),
)

knowledge_index_state = Table(
    "knowledge_index_state",
    metadata,
    Column("id", SmallInteger, primary_key=True),
    Column("model_id", Text, nullable=False),
    Column("model_revision", Text, nullable=False),
    Column("dimension", Integer, nullable=False),
    Column("corpus_fingerprint", Text, nullable=False),
    Column("record_count", Integer, nullable=False),
)


class PostgresVectorStore:
    """PostgreSQL-backed vector storage and cosine-similarity search."""

    dimension = EMBEDDING_DIMENSION

    @classmethod
    def build(
        cls,
        records: list[dict[str, Any]],
        vectors: list[list[float]],
        *,
        model_id: str,
        model_revision: str,
        corpus_fingerprint: str,
    ) -> None:
        if len(records) != len(vectors):
            raise ValueError("Every record must have exactly one embedding")
        if not records:
            raise ValueError("Cannot build a vector index without records")
        if any(len(vector) != cls.dimension for vector in vectors):
            raise ValueError(f"Embeddings must have {cls.dimension} dimensions")

        rows = [
            {
                "chunk_id": record["chunk_id"],
                "collection": record.get("collection") or "",
                "source": record["source"],
                "embedding": vector,
                "record_json": record,
            }
            for record, vector in zip(records, vectors)
        ]
        state = {
            "id": 1,
            "model_id": model_id,
            "model_revision": model_revision,
            "dimension": cls.dimension,
            "corpus_fingerprint": corpus_fingerprint,
            "record_count": len(records),
        }
        state_upsert = pg_insert(knowledge_index_state).values(**state)
        state_upsert = state_upsert.on_conflict_do_update(
            index_elements=[knowledge_index_state.c.id],
            set_={key: state_upsert.excluded[key] for key in state if key != "id"},
        )

        with write_engine.begin() as connection:
            connection.execute(delete(knowledge_vectors))
            connection.execute(insert(knowledge_vectors), rows)
            connection.execute(state_upsert)

    @classmethod
    def load(
        cls,
        *,
        model_id: str,
        model_revision: str,
        corpus_fingerprint: str,
    ) -> "PostgresVectorStore":
        with read_engine.connect() as connection:
            state = connection.execute(
                select(knowledge_index_state).where(knowledge_index_state.c.id == 1)
            ).mappings().one_or_none()
        if state is None:
            raise RuntimeError("Knowledge vectors are missing; run python -m app.index_knowledge")

        expected = (model_id, model_revision, cls.dimension, corpus_fingerprint)
        actual = (
            state["model_id"],
            state["model_revision"],
            state["dimension"],
            state["corpus_fingerprint"],
        )
        if actual != expected:
            raise RuntimeError("Knowledge vector index is stale; run python -m app.index_knowledge")
        return cls()

    def search(
        self,
        query_vector: list[float],
        top_k: int = 3,
        *,
        collection: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        if top_k <= 0:
            return []
        if len(query_vector) != self.dimension:
            raise ValueError(
                f"Query embedding dimension {len(query_vector)} does not match database dimension {self.dimension}"
            )

        distance = knowledge_vectors.c.embedding.cosine_distance(query_vector)
        query = select(knowledge_vectors.c.record_json, distance.label("distance"))
        if collection is not None:
            query = query.where(knowledge_vectors.c.collection == collection)
        if source is not None:
            query = query.where(knowledge_vectors.c.source == source)
        query = query.order_by(distance).limit(top_k)

        with read_engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [
            {**row["record_json"], "score": round(1.0 - float(row["distance"]), 4)}
            for row in rows
        ]
