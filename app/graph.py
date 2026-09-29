from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from . import llm
from .agent_nodes import (
    classify_intent,
    extract_slots as extract_slots_node,
    generate_response,
    load_context,
    persist_result,
    retrieve_knowledge,
    retrieve_products as retrieve_products_node,
    validate_intent,
)
from .agent_state import AgentState

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
MODEL_CONFIDENCE_THRESHOLD = 0.65
RUN_SHOE = "\u8dd1\u978b"
HEADPHONE = "\u8033\u673a"
WATCH = "\u624b\u8868"
LIPSTICK = "\u53e3\u7ea2"
SUPPORTED_CATEGORIES = {RUN_SHOE, HEADPHONE, WATCH, LIPSTICK}


def load_products() -> list[dict[str, Any]]:
    return json.loads((DATA_DIR / "products.json").read_text(encoding="utf-8"))


def normalize_query(text: str) -> str:
    return text.lower().replace("\u4ee5\u5185", "\u4ee5\u4e0b").replace("\u4e0d\u8d85\u8fc7", "\u4ee5\u4e0b")


def empty_slots() -> dict[str, Any]:
    return {"category": None, "budget_max": None, "usage_scene": None, "brand_preference": None, "must_have": [], "avoid": []}


def extract_slots(text: str) -> dict[str, Any]:
    query = normalize_query(text)
    slots = empty_slots()
    category_map = {
        RUN_SHOE: [RUN_SHOE, "\u8dd1\u6b65\u978b", "\u8fd0\u52a8\u978b", "\u978b\u5b50", "\u978b"],
        HEADPHONE: [HEADPHONE, "\u964d\u566a", "\u84dd\u7259"],
        WATCH: [WATCH, "\u8155\u8868", "\u673a\u68b0\u8868"],
        LIPSTICK: [LIPSTICK, "\u5507\u818f"],
    }
    for category, keywords in category_map.items():
        if any(keyword in query for keyword in keywords):
            slots["category"] = category
            break
    budget_match = re.search(r"(\d{2,5})\s*(?:\u5143|\u5757|\u9884\u7b97|\u4ee5\u4e0b)?", query)
    if budget_match:
        slots["budget_max"] = int(budget_match.group(1))
    scenes = {
        "running": ["\u8dd1\u6b65", "\u6162\u8dd1", "\u8bad\u7ec3", "\u9a6c\u62c9\u677e"],
        "commute": ["\u901a\u52e4", "\u4e0a\u73ed", "\u65e5\u5e38"],
        "noise_cancel": ["\u964d\u566a", "\u5730\u94c1", "\u98de\u673a", "\u529e\u516c"],
        "business": ["\u5546\u52a1", "\u6b63\u5f0f", "\u4f1a\u8bae"],
    }
    for scene, keywords in scenes.items():
        if any(keyword in query for keyword in keywords):
            slots["usage_scene"] = scene
            break
    for brand in ["nike", "adidas", "asics", "hoka", "sony", "casio", "seiko", "apple", "garmin"]:
        if brand in query:
            slots["brand_preference"] = brand.title()
    feature_map = {
        "light": ["\u8f7b\u4fbf", "\u8f7b\u91cf", "\u8f7b\u4e00\u70b9"],
        "cushion": ["\u7f13\u9707", "\u8212\u9002"],
        "stable": ["\u7a33\u5b9a", "\u652f\u6491"],
        "battery": ["\u7eed\u822a", "\u7535\u6c60"],
        "noise_cancel": ["\u964d\u566a"],
        "durable": ["\u8010\u7528", "\u6297\u6454"],
    }
    for feature, keywords in feature_map.items():
        if any(keyword in query for keyword in keywords):
            slots["must_have"].append(feature)
    return slots


def normalize_category(value: Any) -> str | None:
    if not value:
        return None
    category = str(value).strip()
    aliases = {"\u978b": RUN_SHOE, "\u978b\u5b50": RUN_SHOE, "\u8fd0\u52a8\u978b": RUN_SHOE, "\u8dd1\u6b65\u978b": RUN_SHOE, "\u84dd\u7259\u8033\u673a": HEADPHONE, "\u964d\u566a\u8033\u673a": HEADPHONE, "\u8155\u8868": WATCH, "\u5507\u818f": LIPSTICK}
    return aliases.get(category, category)


def slots_from_model(model_intent: dict[str, Any] | None) -> dict[str, Any]:
    entities = (model_intent or {}).get("entities") or {}
    slots = empty_slots()
    slots["category"] = normalize_category(entities.get("category"))
    budget = entities.get("budget_max")
    if budget not in (None, ""):
        try:
            slots["budget_max"] = int(budget)
        except (TypeError, ValueError):
            pass
    for key in ("usage_scene", "brand_preference"):
        if entities.get(key):
            slots[key] = entities[key]
    must_have = entities.get("must_have") or []
    slots["must_have"] = [must_have] if isinstance(must_have, str) else list(must_have)
    return slots


def unsupported_category(model_intent: dict[str, Any] | None) -> str | None:
    entities = (model_intent or {}).get("entities") or {}
    raw_category = entities.get("requested_category") or entities.get("category")
    if not raw_category:
        return None
    normalized = normalize_category(raw_category)
    return str(raw_category) if normalized not in SUPPORTED_CATEGORIES else None


def unsupported_category_from_text(text: str) -> str | None:
    for category in ["\u6c34\u679c", "\u4e66", "\u7535\u8111", "\u5bb6\u5177", "\u670d\u88c5"]:
        if category in text:
            return category
    return None


def select_intent(model_intent: dict[str, Any] | None, text: str) -> tuple[str, str, str | None]:
    if model_intent:
        try:
            confidence = float(model_intent.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0
        intent = model_intent.get("intent")
        if intent and confidence >= MODEL_CONFIDENCE_THRESHOLD:
            return str(intent), "llm", None
        return fallback_intent(text), "rules_fallback", "low_confidence"
    return fallback_intent(text), "rules_fallback", "model_unavailable"


def merge_slots(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = empty_slots()
    merged.update(previous or {})
    for key, value in current.items():
        if value not in (None, "", []):
            merged[key] = value
    merged["must_have"] = list(dict.fromkeys((previous or {}).get("must_have", []) + current.get("must_have", [])))
    return merged


def score_product(product: dict[str, Any], slots: dict[str, Any], perspective: str = "balanced") -> float:
    if slots.get("category") and product["category"] != slots["category"]:
        return 0.0
    score = 0.4
    if slots.get("budget_max"):
        if product["price"] <= slots["budget_max"]:
            score += 0.2
        elif product["price"] > slots["budget_max"] * 1.2:
            return 0.0
    if slots.get("usage_scene") in product.get("scene_tags", []):
        score += 0.15
    if slots.get("brand_preference") and product["brand"].lower() == slots["brand_preference"].lower():
        score += 0.1
    matched = set(slots.get("must_have", [])) & set(product.get("feature_tags", []))
    if slots.get("must_have") and not matched:
        return 0.0
    score += 0.15 * len(matched) / max(len(slots.get("must_have", [])), 1)
    if perspective == "budget" and slots.get("budget_max") and product["price"] <= slots["budget_max"]:
        score += 0.08
    if perspective == "preference" and matched:
        score += 0.08
    if product.get("stock", 0) > 0:
        score += 0.05
    return round(score, 4)


def retrieve_products(slots: dict[str, Any], products: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    if not slots.get("category"):
        return [], []
    perspectives = ["budget", "scene", "preference"]

    def rank(perspective: str) -> list[dict[str, Any]]:
        result = []
        for product in products:
            item = dict(product)
            item["score"] = score_product(product, slots, perspective)
            if item["score"] > 0:
                result.append(item)
        return sorted(result, key=lambda item: item["score"], reverse=True)

    with ThreadPoolExecutor(max_workers=3) as pool:
        ranked = list(pool.map(rank, perspectives))
    merged: dict[int, dict[str, Any]] = {}
    for result in ranked:
        for item in result:
            merged[item["id"]] = max(merged.get(item["id"], item), item, key=lambda value: value["score"])
    return sorted(merged.values(), key=lambda item: item["score"], reverse=True), perspectives


def is_knowledge_query(text: str) -> bool:
    return any(keyword in text for keyword in ["\u9000\u8d27", "\u9000\u6b3e", "\u6362\u8d27", "\u552e\u540e", "\u53d1\u8d27", "\u7269\u6d41", "\u5feb\u9012", "\u4fdd\u4fee", "\u8ba2\u5355\u53d6\u6d88", "\u5bc4\u56de", "\u591a\u4e45"])


def is_recommendation_follow_up(text: str) -> bool:
    return any(keyword in text for keyword in ["\u8fd8\u6709", "\u518d\u63a8\u8350", "\u6362\u4e00\u4e2a", "\u66f4\u4fbf\u5b9c", "\u66f4\u8d35", "\u592a\u8d35", "\u4e0d\u559c\u6b22", "\u7c7b\u4f3c", "\u8fd9\u4e2a", "\u90a3\u4e2a", "\u540c\u7c7b"])


def is_price_query(text: str) -> bool:
    return any(keyword in text for keyword in ["\u6709\u54ea\u4e9b\u4ef7\u683c", "\u4ec0\u4e48\u4ef7\u683c", "\u4ef7\u683c\u6709\u54ea\u4e9b", "\u591a\u5c11\u94b1", "\u4ef7\u4f4d", "\u4ef7\u683c\u8303\u56f4"])


def is_greeting(text: str) -> bool:
    return text.strip().lower() in {"\u4f60\u597d", "\u60a8\u597d", "\u55e8", "hello", "hi", "\u5728\u5417"}


def fallback_intent(text: str) -> str:
    if is_greeting(text):
        return "greeting"
    if any(keyword in text for keyword in ["\u8fc7\u5f80\u8ba2\u5355", "\u5386\u53f2\u8ba2\u5355", "\u4e0b\u5355\u5546\u54c1", "\u4e70\u8fc7\u4ec0\u4e48", "\u8d2d\u4e70\u8bb0\u5f55"]):
        return "order_history_query"
    if is_price_query(text):
        return "product_price_query"
    if any(keyword in text for keyword in ["\u4e0d\u60f3\u8981", "\u4e0d\u8981", "\u6362\u4e00\u79cd", "\u6392\u9664", "\u522b\u63a8\u8350"]):
        return "change_preference"
    if any(keyword in text for keyword in ["\u6709\u6ca1\u6709", "\u662f\u5426\u6709", "\u6709\u5417", "\u6709\u65e0"]):
        return "product_availability_query"
    if is_knowledge_query(text):
        return "knowledge_query"
    return "product_recommendation"


def _route_after_validation(state: AgentState) -> str:
    return "persist_result" if state.get("response") else "extract_slots"


def _route_after_slots(state: AgentState) -> str:
    if state["intent"] in {"knowledge_query", "after_sales_query", "logistics_query"}:
        return "retrieve_knowledge"
    if state["intent"] in {"product_recommendation", "product_compare", "product_availability_query", "product_detail_query", "product_price_query"}:
        return "retrieve_products"
    return "generate_response"


def build_agent_graph():
    builder = StateGraph(AgentState)
    builder.add_node("load_context", load_context)
    builder.add_node("classify_intent", classify_intent)
    builder.add_node("validate_intent", validate_intent)
    builder.add_node("extract_slots", extract_slots_node)
    builder.add_node("retrieve_products", retrieve_products_node)
    builder.add_node("retrieve_knowledge", retrieve_knowledge)
    builder.add_node("generate_response", generate_response)
    builder.add_node("persist_result", persist_result)
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "classify_intent")
    builder.add_edge("classify_intent", "validate_intent")
    builder.add_conditional_edges("validate_intent", _route_after_validation)
    builder.add_conditional_edges("extract_slots", _route_after_slots)
    builder.add_edge("retrieve_products", "generate_response")
    builder.add_edge("retrieve_knowledge", "generate_response")
    builder.add_edge("generate_response", "persist_result")
    builder.add_edge("persist_result", END)
    return builder.compile()


agent_graph = build_agent_graph()


def run_agent(user_input: str, session_id: str | None = None, user_id: int = 1) -> dict[str, Any]:
    state: AgentState = {
        "query": user_input,
        "session_id": session_id or str(uuid.uuid4()),
        "user_id": user_id,
        "trace_id": str(uuid.uuid4()),
        "trace": [],
        "llm_used": False,
        "status": "processing",
    }
    result = agent_graph.invoke(state)
    return {
        "trace_id": result["trace_id"],
        "session_id": result["session_id"],
        "status": result.get("status", "answered"),
        "slots": result.get("slots", {}),
        "response": result.get("response", ""),
        "recommendations": result.get("recommendations", []),
        "trace": result.get("trace", []),
        "llm_configured": llm.configured(),
        "llm_used": result.get("llm_used", False),
        "sources": result.get("sources", []),
    }
