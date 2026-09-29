from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.request
from typing import Any

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def _load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def config(name: str, default: str = "") -> str:
    return os.getenv(name) or _load_env().get(name, default)


def configured() -> bool:
    return bool(config("LLM_API_KEY") or config("OPENAI_API_KEY"))


def extract_slots(query: str) -> dict[str, Any] | None:
    if not configured():
        return None
    endpoint = config("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions").rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    payload = {
        "model": config("LLM_MODEL", "gpt-4o-mini"),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Extract shopping slots as JSON. Keys: category, budget_max, usage_scene, brand_preference, must_have. category must be one of: 跑鞋, 耳机, 手表, 口红, null."},
            {"role": "user", "content": query},
        ],
    }
    request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": f"Bearer {config('LLM_API_KEY') or config('OPENAI_API_KEY')}"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        return None


def generate_answer(query: str, context: str) -> str | None:
    if not configured() or not context:
        return None
    endpoint = config("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    payload = {
        "model": config("LLM_MODEL", "gpt-4o-mini"),
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": "You are a shopping support assistant. Answer only from the provided knowledge context. If the context is insufficient, say that a human agent is needed. Cite the source filename in the answer."},
            {"role": "user", "content": f"Question: {query}\n\nKnowledge context:\n{context}"},
        ],
    }
    request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": f"Bearer {config('LLM_API_KEY') or config('OPENAI_API_KEY')}"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def classify_intent(query: str, context: str = "") -> dict[str, Any] | None:
    if not configured():
        return None
    endpoint = config("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    payload = {
        "model": config("LLM_MODEL", "gpt-4o-mini"),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Classify the user's primary intent for a shopping assistant. Return JSON only with keys intent, confidence, entities. Allowed intents: product_recommendation, product_compare, product_price_query, product_availability_query, product_detail_query, order_history_query, order_detail_query, logistics_query, after_sales_query, knowledge_query, change_preference, chitchat, greeting, unknown. Positive requests such as 'I want casual shoes' or 'are there casual shoes' are product_availability_query or product_recommendation, never change_preference. Use change_preference only for explicit negation or replacement such as 'I do not want running shoes' or 'change to headphones'. entities may include category, requested_category, budget_max, order_no, excluded_category. category must be one of: 跑鞋, 耳机, 手表, 口红, or null. If the user requests an unsupported category such as 水果 or 书, put the original category name in requested_category and set category to null."},
            {"role": "user", "content": f"Conversation context: {context}\nUser query: {query}"},
        ],
    }
    request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": f"Bearer {config('LLM_API_KEY') or config('OPENAI_API_KEY')}"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        result = json.loads(body["choices"][0]["message"]["content"])
        return result if isinstance(result, dict) and result.get("intent") else None
    except Exception:
        return None
