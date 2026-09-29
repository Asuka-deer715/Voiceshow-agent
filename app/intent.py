from __future__ import annotations

from typing import Any

from . import llm
from .schemas import ALLOWED_INTENTS, IntentResult
from .semantic_cache import get as cache_get
from .semantic_cache import set as cache_set


def classify_intent(session_id: str, query: str, context: str = "", trace_id: str = "") -> dict[str, Any]:
    cache_key = f"{session_id}:{context}:{query}"
    cached = cache_get("validated-intent", cache_key)
    if cached:
        return cached
    result = llm.classify_intent(query, context, trace_id) or {"intent": "unknown", "confidence": 0.0, "entities": {}}
    validated = IntentResult.model_validate(result).model_dump()
    cache_set("validated-intent", cache_key, validated)
    return validated
