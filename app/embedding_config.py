from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "embeddings" / "bge-small-zh-v1.5"
MODEL_ID = "BAAI/bge-small-zh-v1.5"
MODEL_REVISION = "modelscope:master"
EMBEDDING_DIMENSION = 512
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
