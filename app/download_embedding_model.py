from __future__ import annotations

from .embedding_config import MODEL_PATH

MODEL_REPOSITORY = "AI-ModelScope/bge-small-zh-v1.5"
MODEL_FILES = [
    "model.safetensors",
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "special_tokens_map.json",
    "config_sentence_transformers.json",
    "1_Pooling/config.json",
]


def download() -> str:
    from modelscope.hub.snapshot_download import snapshot_download

    return snapshot_download(
        model_id=MODEL_REPOSITORY,
        revision="master",
        cache_dir=str(MODEL_PATH.parents[1] / "modelscope"),
        local_dir=str(MODEL_PATH),
        allow_patterns=MODEL_FILES,
    )


if __name__ == "__main__":
    print(download())
