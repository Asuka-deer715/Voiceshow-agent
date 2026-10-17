from __future__ import annotations

from .embedding import get_embedder
from .embedding_config import MODEL_ID, MODEL_REVISION
from .rag import corpus_fingerprint, load_chunks
from .vector_store import PostgresVectorStore


def rebuild() -> dict[str, object]:
    chunks = load_chunks()
    embedder = get_embedder()
    vectors = embedder.embed_documents([chunk["text"] for chunk in chunks])
    fingerprint = corpus_fingerprint(chunks)
    PostgresVectorStore.build(
        chunks,
        vectors,
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        corpus_fingerprint=fingerprint,
    )
    return {
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "device": embedder.device,
        "dimension": embedder.dimension,
        "chunk_count": len(chunks),
        "backend": "PostgreSQL + pgvector",
    }


if __name__ == "__main__":
    result = rebuild()
    print("Knowledge vector index ready")
    for key, value in result.items():
        print(f"{key}: {value}")
