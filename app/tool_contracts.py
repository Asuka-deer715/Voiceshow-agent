from __future__ import annotations

from typing import Any

from .schemas import ToolCall


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "agent_decision",
            "description": "Return the validated intent and extracted shopping entities.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "intent": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "entities": {"type": "object"},
                },
                "required": ["intent", "confidence", "entities"],
            },
        },
    }
]


def validate_tool_arguments(name: str, arguments: dict[str, Any]) -> ToolCall:
    if name != "agent_decision":
        raise ValueError(f"unsupported tool: {name}")
    return ToolCall(name="agent_decision", arguments=arguments)
