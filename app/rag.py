from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .embedding_config import MODEL_ID, MODEL_REVISION
from .vector_store import PostgresVectorStore

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"


def load_chunks() -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        sections = [part.strip() for part in re.split(r"\n(?=##?\s)", content) if part.strip()]
        for index, section in enumerate(sections):
            chunks.append({"chunk_id": f"{path.stem}-{index + 1}", "source": path.name, "text": section})
    for path in sorted(KNOWLEDGE_DIR.glob("*/chunks.jsonl")):
        chunks.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return chunks


def corpus_fingerprint(chunks: list[dict[str, Any]]) -> str:
    serialized = json.dumps(chunks, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@lru_cache(maxsize=2)
def _load_store(fingerprint: str) -> PostgresVectorStore:
    return PostgresVectorStore.load(
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        corpus_fingerprint=fingerprint,
    )


def retrieve(
    query: str,
    top_k: int = 3,
    *,
    collection: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    if top_k <= 0 or not query.strip():
        return []
    chunks = load_chunks()
    fingerprint = corpus_fingerprint(chunks)

    named_sources = {
        item["source"] for item in chunks
        if item.get("source", "").lower() in query.lower()
    }
    if named_sources:
        if len(named_sources) == 1:
            source = source or next(iter(named_sources))
        for name in named_sources:
            query = re.sub(re.escape(name), "", query, flags=re.IGNORECASE)

    from .embedding import embed_text

    vector = embed_text(query)
    store = _load_store(fingerprint)
    return store.search(vector, top_k, collection=collection, source=source)


def assemble_context(results: list[dict[str, Any]]) -> str:
    def citation(item: dict[str, Any]) -> str:
        page = f" / page {item['page']}" if item.get("page") else ""
        return f"[{item['source']}{page} / {item['chunk_id']}]\n{item['text']}"
    return "\n\n".join(citation(item) for item in results)
