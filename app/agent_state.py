from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    query: str
    session_id: str
    user_id: int
    authenticated: bool
    trace_id: str
    session: dict[str, Any]
    history: list[dict[str, Any]]
    model_intent: dict[str, Any] | None
    intent: str
    intent_engine: str
    fallback_reason: str | None
    slots: dict[str, Any]
    retrieved: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    response: str | None
    sources: list[str]
    status: str
    phase: str
    llm_used: bool
    trace: list[dict[str, Any]]
    error: str | None
