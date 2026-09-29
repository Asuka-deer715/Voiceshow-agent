from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ALLOWED_INTENTS = {
    "product_recommendation", "product_compare", "product_price_query",
    "product_availability_query", "product_detail_query", "order_history_query",
    "order_detail_query", "logistics_query", "after_sales_query",
    "knowledge_query", "change_preference", "chitchat", "greeting", "unknown",
}


class IntentEntities(BaseModel):
    category: str | None = None
    requested_category: str | None = None
    budget_max: int | None = Field(default=None, ge=0)
    usage_scene: str | None = None
    brand_preference: str | None = None
    must_have: list[str] = Field(default_factory=list)
    excluded_category: str | None = None


class IntentResult(BaseModel):
    intent: str
    confidence: float = Field(ge=0, le=1)
    entities: IntentEntities = Field(default_factory=IntentEntities)

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, value: str) -> str:
        if value not in ALLOWED_INTENTS:
            return "unknown"
        return value


class SlotResult(BaseModel):
    entities: IntentEntities = Field(default_factory=IntentEntities)


class ToolCall(BaseModel):
    name: Literal["agent_decision", "search_products", "retrieve_knowledge", "list_order_history"]
    arguments: dict[str, Any] = Field(default_factory=dict)
