from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from . import db, llm
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
SUPPORTED_CATEGORIES = {"跑鞋", "耳机", "手表", "口红"}


def load_products() -> list[dict[str, Any]]:
    return json.loads((DATA_DIR / "products.json").read_text(encoding="utf-8"))


def normalize_query(text: str) -> str:
    return text.lower().replace("以内", "以下").replace("不超过", "以下")


def empty_slots() -> dict[str, Any]:
    return {"category": None, "budget_max": None, "usage_scene": None, "brand_preference": None, "must_have": [], "avoid": []}


def extract_slots(text: str) -> dict[str, Any]:
    query = normalize_query(text)
    slots = empty_slots()
    category_map = {
        "跑鞋": ["跑鞋", "跑步鞋", "运动鞋", "鞋子"],
        "耳机": ["耳机", "降噪", "蓝牙"],
        "手表": ["手表", "腕表", "机械表"],
        "口红": ["口红", "唇膏"],
    }
    for category, keywords in category_map.items():
        if any(keyword in query for keyword in keywords):
            slots["category"] = category
            break
    budget_match = re.search(r"(\d{2,5})\s*(?:元|块|预算|以下)?", query)
    if budget_match:
        slots["budget_max"] = int(budget_match.group(1))
    scenes = {"running": ["跑步", "慢跑", "训练", "马拉松"], "commute": ["通勤", "上班", "日常"], "noise_cancel": ["降噪", "地铁", "飞机", "办公"], "business": ["商务", "正式", "会议"]}
    for scene, keywords in scenes.items():
        if any(keyword in query for keyword in keywords):
            slots["usage_scene"] = scene
            break
    for brand in ["nike", "adidas", "asics", "hoka", "sony", "casio", "seiko"]:
        if brand in query:
            slots["brand_preference"] = brand.title()
    feature_map = {"light": ["轻便", "轻量"], "cushion": ["缓震", "舒适"], "stable": ["稳定", "支撑"], "battery": ["续航", "电池"], "noise_cancel": ["降噪"], "durable": ["耐用", "抗摔"]}
    for feature, keywords in feature_map.items():
        if any(keyword in query for keyword in keywords):
            slots["must_have"].append(feature)
    return slots


def normalize_category(value: Any) -> str | None:
    if not value:
        return None
    category = str(value).strip()
    aliases = {"鞋": "跑鞋", "鞋子": "跑鞋", "运动鞋": "跑鞋", "跑步鞋": "跑鞋", "蓝牙耳机": "耳机", "降噪耳机": "耳机", "腕表": "手表", "唇膏": "口红"}
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
    for category in ("水果", "书", "电脑", "家具", "服装"):
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
    score += 0.15 * len(matched) / max(len(slots.get("must_have", [])), 1)
    if perspective == "budget" and slots.get("budget_max") and product["price"] <= slots["budget_max"]:
        score += 0.08
    if perspective == "preference" and matched:
        score += 0.08
    if product.get("stock", 0) > 0:
        score += 0.05
    return round(score, 4)


def retrieve_products(slots: dict[str, Any], products: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
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
    return any(keyword in text for keyword in ["退货", "退款", "换货", "售后", "发货", "物流", "快递", "保修", "订单取消", "寄回", "多久"])


def is_recommendation_follow_up(text: str) -> bool:
    return any(keyword in text for keyword in ["还有", "再推荐", "换一个", "更便宜", "更贵", "太贵", "不喜欢", "类似", "这个", "那个", "同类"])


def is_price_query(text: str) -> bool:
    return any(keyword in text for keyword in ["有哪些价格", "什么价格", "价格有哪些", "多少钱", "价位", "价格范围"])


def is_greeting(text: str) -> bool:
    return text.strip().lower() in {"你好", "您好", "嗨", "hello", "hi", "在吗"}


def fallback_intent(text: str) -> str:
    if is_greeting(text):
        return "greeting"
    if any(keyword in text for keyword in ["过往订单", "历史订单", "下单商品", "买过什么", "购买记录"]):
        return "order_history_query"
    if is_price_query(text):
        return "product_price_query"
    if any(keyword in text for keyword in ["不想要", "不要", "换一种", "排除", "别推荐"]):
        return "change_preference"
    if any(keyword in text for keyword in ["有没有", "是否有", "有吗", "有无"]):
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
