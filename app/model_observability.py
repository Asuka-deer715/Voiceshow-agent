from __future__ import annotations

import time
from typing import Any

from . import db


def record_model_call(
    *, trace_id: str, node: str, model: str, prompt_version: str,
    started_at: float, usage: dict[str, Any] | None, status: str,
    error_type: str | None = None, fallback: bool = False,
) -> None:
    usage = usage or {}
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    db.record_model_call({
        "trace_id": trace_id,
        "node": node,
        "model": model,
        "prompt_version": prompt_version,
        "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": estimate_cost(model, input_tokens, output_tokens),
        "status": status,
        "error_type": error_type,
        "fallback": int(fallback),
    })


def estimate_cost(model: str, input_tokens: Any, output_tokens: Any) -> float | None:
    if input_tokens is None or output_tokens is None:
        return None
    input_price = float(__import__("os").getenv("LLM_INPUT_PRICE_PER_MILLION", "0"))
    output_price = float(__import__("os").getenv("LLM_OUTPUT_PRICE_PER_MILLION", "0"))
    return round((input_tokens * input_price + output_tokens * output_price) / 1_000_000, 8)
