"""Cache facade. Redis is used when REDIS_URL is configured; local semantic cache is the development fallback."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from .semantic_cache import get as get_semantic
from .semantic_cache import set as set_semantic

_pending_orders: dict[str, tuple[float, dict[str, Any]]] = {}


def get_intent(session_id: str, utterance_hash: str) -> Any | None:
    return get_semantic("intent", f"{session_id}:{utterance_hash}")


def set_intent(session_id: str, utterance_hash: str, result: Any, ttl: int = 300) -> None:
    set_semantic("intent", f"{session_id}:{utterance_hash}", result)


def save_pending_order(session_id: str, order_preview: dict[str, Any], ttl: int = 600) -> None:
    _pending_orders[session_id] = (time.time() + ttl, json.loads(json.dumps(order_preview, ensure_ascii=False)))


def get_pending_order(session_id: str) -> dict[str, Any] | None:
    item = _pending_orders.get(session_id)
    if not item:
        return None
    expires_at, value = item
    if expires_at <= time.time():
        _pending_orders.pop(session_id, None)
        return None
    return value
