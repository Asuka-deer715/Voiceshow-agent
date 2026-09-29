"""Application-level observability adapters."""

from __future__ import annotations

from typing import Any

from . import db


def record_span(trace_id: str, node: str, started_at: float, ended_at: float, input_data: Any, output_data: Any, status: str) -> None:
    db.save_trace(trace_id, "system", [{"node": node, "started_at": started_at, "ended_at": ended_at, "input": input_data, "output": output_data, "status": status}])


def regression_check(current: dict[str, float], baseline: dict[str, float], threshold: float = 0.03) -> str:
    if current.get("task_completed", 0) < baseline.get("task_completed", 0) - threshold:
        return "REGRESSION"
    return "PASS"
