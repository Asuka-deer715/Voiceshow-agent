from __future__ import annotations

import json
import builtins
import re
import threading
import time
from collections.abc import Iterable
from typing import Any

_memory: dict[str, tuple[float, set[str], Any]] = {}
_lock = threading.Lock()
_redis = None


def _redis_client():
    global _redis
    if _redis is not None:
        return _redis
    import os
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        import redis
        client = redis.from_url(url, decode_responses=True)
        client.ping()
        _redis = client
    except Exception:
        _redis = False
    return _redis or None


def _tokens(text: str) -> set[str]:
    return builtins.set(re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower()))


def _similarity(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = builtins.set(left), builtins.set(right)
    return len(a & b) / max(len(a | b), 1)


def get(namespace: str, query: str, ttl: int = 300, threshold: float = 0.82) -> Any | None:
    client = _redis_client()
    exact_key = f"semantic:{namespace}:{abs(hash(query))}"
    if client:
        cached = client.get(exact_key)
        if cached:
            return json.loads(cached)
    now = time.time()
    tokens = _tokens(query)
    with _lock:
        expired = [key for key, (created, _, _) in _memory.items() if now - created > ttl]
        for key in expired:
            _memory.pop(key, None)
        for key, (created, cached_tokens, value) in _memory.items():
            if key.startswith(namespace + ":") and now - created <= ttl and _similarity(tokens, cached_tokens) >= threshold:
                return value
    return None


def set(namespace: str, query: str, value: Any) -> None:
    key = f"{namespace}:{abs(hash(query))}"
    client = _redis_client()
    if client:
        client.setex(f"semantic:{key}", 300, json.dumps(value, ensure_ascii=False))
    with _lock:
        _memory[key] = (time.time(), _tokens(query), json.loads(json.dumps(value, ensure_ascii=False)))
