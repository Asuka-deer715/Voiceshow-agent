from __future__ import annotations

import os
import threading
from functools import lru_cache
from pathlib import Path

import torch
import torch.nn.functional as functional
from transformers import AutoModel, AutoTokenizer

from .embedding_config import MODEL_ID, MODEL_PATH, MODEL_REVISION, QUERY_INSTRUCTION

MODEL_PATH = Path(os.getenv("EMBEDDING_MODEL_PATH", MODEL_PATH))


class BGEEmbedder:
    """Local BGE sentence embeddings with normalized CLS pooling."""

    def __init__(self, model_path: Path = MODEL_PATH, device: str | None = None) -> None:
        if not (model_path / "model.safetensors").is_file():
            raise FileNotFoundError(f"Embedding weights not found: {model_path / 'model.safetensors'}")
        requested_device = device or os.getenv("EMBEDDING_DEVICE", "auto")
        self.device = "cuda" if requested_device == "auto" and torch.cuda.is_available() else requested_device
        if self.device == "auto":
            self.device = "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        self.model = AutoModel.from_pretrained(model_path, local_files_only=True, use_safetensors=True)
        self.model.to(self.device).eval()
        self.dimension = int(self.model.config.hidden_size)
        self._inference_lock = threading.Lock()

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._inference_lock:
            encoded = self.tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            ).to(self.device)
            with torch.inference_mode():
                hidden = self.model(**encoded).last_hidden_state[:, 0]
                vectors = functional.normalize(hidden, p=2, dim=1)
        return vectors.float().cpu().numpy().tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            vector
            for offset in range(0, len(texts), 32)
            for vector in self._encode(texts[offset : offset + 32])
        ]

    def embed_query(self, query: str) -> list[float]:
        return self._encode([QUERY_INSTRUCTION + query])[0]


@lru_cache(maxsize=1)
def get_embedder() -> BGEEmbedder:
    return BGEEmbedder()


def embed_text(text: str) -> list[float]:
    return get_embedder().embed_query(text)


def embed_batch(texts: list[str]) -> list[list[float]]:
    return get_embedder().embed_documents(texts)
