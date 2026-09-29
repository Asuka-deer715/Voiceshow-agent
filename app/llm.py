from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .model_observability import record_model_call
from .prompt_manager import get_prompt
from .schemas import IntentResult, SlotResult
from .semantic_cache import get as cache_get
from .semantic_cache import set as cache_set
from .tool_contracts import TOOL_DEFINITIONS

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


def _endpoint() -> str:
    endpoint = config("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    return endpoint if endpoint.endswith("/chat/completions") else endpoint + "/chat/completions"


def _model(primary: bool = True) -> str:
    key = "LLM_MODEL" if primary else "LLM_FALLBACK_MODEL"
    return config(key, "deepseek-chat" if primary else "deepseek-reasoner")


def _request(messages: list[dict[str, str]], *, node: str, trace_id: str = "", schema: dict[str, Any] | None = None, temperature: float = 0, primary: bool = True) -> dict[str, Any] | None:
    if not configured():
        return None
    prompt_name = "intent" if node == "intent_classification" else "answer"
    system_prompt, prompt_version = get_prompt(prompt_name)
    request_messages = [{"role": "system", "content": system_prompt}, *messages]
    payload: dict[str, Any] = {"model": _model(primary), "temperature": temperature, "messages": request_messages}
    use_tools = node == "intent_classification" and config("LLM_ENABLE_TOOL_CALLING", "0") == "1"
    if schema and not use_tools:
        payload["response_format"] = {"type": "json_schema", "json_schema": {"name": f"{node}_result", "strict": True, "schema": schema}}
    elif node == "intent_classification":
        payload["response_format"] = {"type": "json_object"}
    if use_tools:
        payload["tools"] = TOOL_DEFINITIONS
        payload["tool_choice"] = {"type": "function", "function": {"name": "agent_decision"}}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {config('LLM_API_KEY') or config('OPENAI_API_KEY')}"}
    retries = max(int(config("LLM_MAX_RETRIES", "2")), 0)
    for attempt in range(retries + 1):
        started = time.perf_counter()
        try:
            request = urllib.request.Request(_endpoint(), data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=float(config("LLM_TIMEOUT_SECONDS", "20"))) as response:
                body = json.loads(response.read().decode("utf-8"))
            record_model_call(trace_id=trace_id, node=node, model=payload["model"], prompt_version=prompt_version, started_at=started, usage=body.get("usage"), status="success", fallback=not primary)
            return body
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            if not retryable or attempt >= retries:
                record_model_call(trace_id=trace_id, node=node, model=payload["model"], prompt_version=prompt_version, started_at=started, usage=None, status="failed", error_type=f"http_{exc.code}", fallback=not primary)
                break
            retry_after = exc.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else min(2 ** attempt, 4)
            except ValueError:
                delay = min(2 ** attempt, 4)
            time.sleep(min(delay, 10))
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
            if attempt >= retries:
                record_model_call(trace_id=trace_id, node=node, model=payload["model"], prompt_version=prompt_version, started_at=started, usage=None, status="failed", error_type=type(exc).__name__, fallback=not primary)
                break
            time.sleep(min(2 ** attempt, 4))
    return None


def classify_intent(query: str, context: str = "", trace_id: str = "") -> dict[str, Any] | None:
    cache_query = f"{config('LLM_MODEL')}|{context}|{query}"
    cached = cache_get("intent", cache_query)
    if cached:
        return cached
    messages = [{"role": "user", "content": f"Conversation context: {context}\nUser query: {query}"}]
    body = _request(messages, node="intent_classification", trace_id=trace_id, schema=IntentResult.model_json_schema())
    fallback = False
    if not body and config("LLM_FALLBACK_MODEL"):
        body = _request(messages, node="intent_classification", trace_id=trace_id, schema=IntentResult.model_json_schema(), primary=False)
        fallback = bool(body)
    if not body:
        return None
    try:
        message = body["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        content = tool_calls[0]["function"]["arguments"] if tool_calls else message["content"]
        result = IntentResult.model_validate_json(content).model_dump()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        if not config("LLM_FALLBACK_MODEL"):
            return None
        body = _request(messages, node="intent_classification", trace_id=trace_id, schema=IntentResult.model_json_schema(), primary=False)
        if not body:
            return None
        try:
            message = body["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []
            content = tool_calls[0]["function"]["arguments"] if tool_calls else message["content"]
            result = IntentResult.model_validate_json(content).model_dump()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
    result["_model_fallback"] = fallback
    cache_set("intent", cache_query, result)
    return result


def extract_slots(query: str, trace_id: str = "") -> dict[str, Any] | None:
    messages = [{"role": "user", "content": query}]
    body = _request(messages, node="slot_extraction", trace_id=trace_id, schema=SlotResult.model_json_schema())
    if not body and config("LLM_FALLBACK_MODEL"):
        body = _request(messages, node="slot_extraction", trace_id=trace_id, schema=SlotResult.model_json_schema(), primary=False)
    if not body:
        return None
    try:
        return SlotResult.model_validate_json(body["choices"][0]["message"]["content"]).model_dump()["entities"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        if not config("LLM_FALLBACK_MODEL"):
            return None
        body = _request(messages, node="slot_extraction", trace_id=trace_id, schema=SlotResult.model_json_schema(), primary=False)
        if not body:
            return None
        try:
            return SlotResult.model_validate_json(body["choices"][0]["message"]["content"]).model_dump()["entities"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None


def generate_answer(query: str, context: str, trace_id: str = "") -> str | None:
    if not context:
        return None
    body = _request(
        [{"role": "user", "content": f"Question: {query}\n\nKnowledge context:\n{context}"}],
        node="answer_generation", trace_id=trace_id, temperature=0.1,
    )
    if not body and config("LLM_FALLBACK_MODEL"):
        body = _request(
            [{"role": "user", "content": f"Question: {query}\n\nKnowledge context:\n{context}"}],
            node="answer_generation", trace_id=trace_id, temperature=0.1, primary=False,
        )
    try:
        return body["choices"][0]["message"]["content"].strip() if body else None
    except (KeyError, TypeError, AttributeError):
        return None
