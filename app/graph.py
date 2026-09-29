from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import db, llm, rag, tools

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
        "跑鞋": ["跑鞋", "跑步鞋", "跑步的鞋", "跑步", "运动鞋", "鞋子"],
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
    feature_map = {"light": ["轻", "轻便", "轻量"], "cushion": ["缓震", "舒服", "舒适"], "stable": ["稳定", "支撑"], "battery": ["续航", "电池"], "noise_cancel": ["降噪"], "durable": ["耐用", "抗造"]}
    for feature, keywords in feature_map.items():
        if any(keyword in query for keyword in keywords):
            slots["must_have"].append(feature)
    return slots


def normalize_category(value: Any) -> str | None:
    if not value:
        return None
    category = str(value).strip()
    aliases = {
        "鞋": "跑鞋",
        "鞋子": "跑鞋",
        "运动鞋": "跑鞋",
        "跑步鞋": "跑鞋",
        "耳机": "耳机",
        "蓝牙耳机": "耳机",
        "降噪耳机": "耳机",
        "手表": "手表",
        "腕表": "手表",
        "口红": "口红",
    }
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
    previous_features = (previous or {}).get("must_have") or []
    current_features = current.get("must_have") or []
    merged["must_have"] = list(dict.fromkeys(previous_features + current_features))
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
        ranked = [value for value in pool.map(rank, perspectives)]
    merged: dict[int, dict[str, Any]] = {}
    for result in ranked:
        for item in result:
            merged[item["id"]] = max(merged.get(item["id"], item), item, key=lambda x: x["score"])
    return sorted(merged.values(), key=lambda item: item["score"], reverse=True), perspectives


def is_knowledge_query(text: str) -> bool:
    return any(keyword in text for keyword in ["退货", "退款", "换货", "售后", "发货", "物流", "快递", "保修", "订单取消", "怎么寄回", "多久"])


def is_recommendation_follow_up(text: str) -> bool:
    return any(keyword in text for keyword in ["还有", "再推荐", "换一个", "更便宜", "更贵", "太贵", "不喜欢", "类似", "这个", "那个", "同类"])


def is_price_query(text: str) -> bool:
    return any(keyword in text for keyword in ["有哪些价格", "什么价格", "价格有哪些", "多少钱", "价位", "价格范围"])


def is_greeting(text: str) -> bool:
    return text.strip() in {"你好", "您好", "嗨", "hello", "hi", "在吗"}


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


def run_agent(user_input: str, session_id: str | None = None, user_id: int = 1) -> dict[str, Any]:
    db.init_db()
    session_id = session_id or str(uuid.uuid4())
    session = db.get_session(session_id)
    trace_id = str(uuid.uuid4())
    trace: list[dict[str, Any]] = [{"node": "session_load", "label": "加载会话状态", "session_id": session_id}]
    llm_used = False
    db.append_message(session_id, "USER", user_input)
    if is_greeting(user_input):
        response = "你好，我是 VoiceShop AI 导购。你可以告诉我想买什么、预算多少，或者直接询问商品价格、物流和售后规则。"
        trace.append({"node": "greeting", "label": "问候意图识别", "engine": "rules"})
        db.append_message(session_id, "ASSISTANT", response)
        trace.append({"node": "audit_persist", "label": "Trace 审计入库", "trace_id": trace_id})
        db.save_trace(trace_id, session_id, trace)
        return {"trace_id": trace_id, "session_id": session_id, "status": "clarify", "slots": session.get("slots", {}), "response": response, "recommendations": [], "trace": trace, "llm_configured": llm.configured(), "llm_used": False}
    if any(word in user_input for word in ["诈骗", "赌博", "色情"]):
        response = "抱歉，这类请求无法由购物助手处理。"
        trace.append({"node": "compliance_check", "label": "敏感词合规拦截", "status": "blocked"})
        db.append_message(session_id, "ASSISTANT", response)
        db.save_trace(trace_id, session_id, trace)
        return {"trace_id": trace_id, "session_id": session_id, "status": "blocked", "slots": session.get("slots", {}), "response": response, "recommendations": [], "trace": trace, "llm_configured": llm.configured(), "llm_used": False}
    history_context = db.recent_messages(session_id, 6)
    model_context = json.dumps({"phase": session.get("phase"), "slots": session.get("slots", {}), "recent_messages": history_context}, ensure_ascii=False)
    model_intent = llm.classify_intent(user_input, model_context) if llm.configured() else None
    intent, intent_engine, fallback_reason = select_intent(model_intent, user_input)
    model_slots = slots_from_model(model_intent) if intent_engine == "llm" else empty_slots()
    llm_used = bool(model_intent)
    trace.append({"node": "intent_classification", "label": "主要意图识别", "engine": intent_engine, "intent": intent, "confidence": (model_intent or {}).get("confidence"), "fallback_reason": fallback_reason})
    unknown_category = unsupported_category(model_intent) if intent_engine == "llm" else None
    if unknown_category and intent in {"product_recommendation", "product_availability_query", "product_compare", "product_detail_query"}:
        response = f"当前商品库暂不支持{unknown_category}，目前可以帮你挑选跑鞋、耳机、手表或口红。"
        trace.append({"node": "catalog_validation", "label": "商品类别校验", "category": unknown_category, "status": "unsupported"})
        db.append_message(session_id, "ASSISTANT", response)
        trace.append({"node": "audit_persist", "label": "Trace 审计入库", "trace_id": trace_id})
        db.save_trace(trace_id, session_id, trace)
        return {"trace_id": trace_id, "session_id": session_id, "status": "clarify", "slots": session.get("slots", {}), "response": response, "recommendations": [], "trace": trace, "llm_configured": llm.configured(), "llm_used": llm_used}
    if intent == "order_history_query":
        orders = tools.list_order_history(user_id)
        if orders:
            order_lines = "；".join(f"{order['order_no']}：{order['product_name']}，状态 {order['status']}" for order in orders[:5])
            response = f"你过往的下单商品如下：{order_lines}。"
        else:
            response = "目前还没有查询到你的历史订单。"
        trace.append({"node": "tool_call", "label": "调用历史订单工具", "tool": "list_order_history", "order_count": len(orders)})
        db.append_message(session_id, "ASSISTANT", response)
        trace.append({"node": "audit_persist", "label": "Trace 审计入库", "trace_id": trace_id})
        db.save_trace(trace_id, session_id, trace)
        return {"trace_id": trace_id, "session_id": session_id, "status": "answered", "slots": session.get("slots", {}), "response": response, "recommendations": [], "trace": trace, "llm_configured": llm.configured(), "llm_used": llm_used}
    if intent == "chitchat":
        response = "我可以陪你聊聊，也可以帮你查询商品、价格、订单和售后信息。"
        trace.append({"node": "chitchat_handler", "label": "闲聊回复", "engine": "rules"})
        db.append_message(session_id, "ASSISTANT", response)
        trace.append({"node": "audit_persist", "label": "Trace 审计入库", "trace_id": trace_id})
        db.save_trace(trace_id, session_id, trace)
        return {"trace_id": trace_id, "session_id": session_id, "status": "answered", "slots": session.get("slots", {}), "response": response, "recommendations": [], "trace": trace, "llm_configured": llm.configured(), "llm_used": llm_used}
    if intent == "product_availability_query":
        current_slots = merge_slots(extract_slots(user_input), model_slots)
        previous_slots = session.get("slots", {})
        category = current_slots.get("category") or previous_slots.get("category")
        budget_max = current_slots.get("budget_max") or previous_slots.get("budget_max")
        catalog = tools.search_products(category=category)
        if budget_max is not None:
            catalog = [item for item in catalog if item["price"] <= budget_max]
        trace.append({"node": "tool_call", "label": "调用商品目录工具", "tool": "search_products", "category": category, "result_count": len(catalog)})
        if catalog:
            names = "、".join(item["name"] for item in catalog[:5])
            if budget_max is not None:
                response = f"有符合 {budget_max} 元预算的{category or '商品'}：{names}。如果你告诉我使用场景，我可以继续帮你筛选。"
            else:
                response = f"目前商品库中有：{names}。如果你告诉我预算和使用场景，我可以继续帮你筛选。"
            status = "clarify"
        else:
            budget_text = f" {budget_max} 元以内" if budget_max is not None else ""
            response = f"当前商品库暂时没有{category or '符合条件的'}{budget_text}商品。你可以放宽预算，或者换一个商品类别。"
            status = "clarify"
        db.append_message(session_id, "ASSISTANT", response)
        trace.append({"node": "audit_persist", "label": "Trace 审计入库", "trace_id": trace_id})
        db.save_trace(trace_id, session_id, trace)
        return {"trace_id": trace_id, "session_id": session_id, "status": status, "slots": merge_slots(previous_slots, current_slots), "response": response, "recommendations": catalog[:5], "trace": trace, "llm_configured": llm.configured(), "llm_used": llm_used}
    emotion = "frustrated" if any(word in user_input for word in ["着急", "生气", "不满意", "太慢"]) else "neutral"
    trace.append({"node": "emotion_detect", "label": "情绪识别", "emotion": emotion})
    if intent in {"knowledge_query", "after_sales_query", "logistics_query"} or (intent == "unknown" and is_knowledge_query(user_input)):
        knowledge = tools.retrieve_knowledge(user_input)
        retrieved = knowledge["chunks"]
        trace.append({"node": "rag_retrieve", "label": "知识库语义召回", "chunks": [{"chunk_id": item["chunk_id"], "source": item["source"], "score": item["score"]} for item in retrieved]})
        context = rag.assemble_context(retrieved)
        llm_used = bool(retrieved and llm.configured())
        response = llm.generate_answer(user_input, context) if retrieved else None
        if not response and retrieved:
            response = f"根据 {retrieved[0]['source']}：{retrieved[0]['text']}"
            trace.append({"node": "rag_fallback", "label": "知识库证据兜底", "source": retrieved[0]["source"]})
        if not response:
            response = "暂时没有在售后知识库中找到匹配内容，建议转人工客服确认。"
            trace.append({"node": "knowledge_fallback", "label": "知识库无答案兜底"})
        db.save_session(session_id, session.get("slots", {}), "KNOWLEDGE")
        db.append_message(session_id, "ASSISTANT", response)
        trace.append({"node": "context_assembly", "label": "证据上下文组装", "source_count": len(retrieved)})
        trace.append({"node": "audit_persist", "label": "Trace 审计入库", "trace_id": trace_id})
        db.save_trace(trace_id, session_id, trace)
        return {"trace_id": trace_id, "session_id": session_id, "status": "answered", "slots": session.get("slots", {}), "response": response, "recommendations": [], "trace": trace, "llm_configured": llm.configured(), "llm_used": llm_used, "sources": [item["source"] for item in retrieved]}
    rule_slots = extract_slots(user_input)
    current = merge_slots(rule_slots, model_slots)
    trace.append({"node": "extract_slots", "label": "规则槽位抽取与模型实体合并", "slots": current, "engine": "rules_plus_llm_entities" if intent_engine == "llm" else "rules"})
    if intent == "change_preference":
        excluded_category = current.get("category") or session.get("slots", {}).get("category")
        updated_slots = empty_slots()
        if excluded_category:
            updated_slots["avoid"] = [excluded_category]
        response = "明白，我会排除当前偏好。你想换成哪一类商品？例如耳机、手表或口红。"
        trace.append({"node": "preference_update", "label": "否定偏好更新", "excluded_category": excluded_category})
        db.save_session(session_id, updated_slots, "CLARIFY")
        db.append_message(session_id, "ASSISTANT", response)
        trace.append({"node": "audit_persist", "label": "Trace 审计入库", "trace_id": trace_id})
        db.save_trace(trace_id, session_id, trace)
        return {"trace_id": trace_id, "session_id": session_id, "status": "clarify", "slots": updated_slots, "response": response, "recommendations": [], "trace": trace, "llm_configured": llm.configured(), "llm_used": llm_used}
    previous_slots = session.get("slots", {})
    previous_phase = session.get("phase", "INTENT")
    continuation = is_recommendation_follow_up(user_input)
    is_contextual_follow_up = continuation or is_price_query(user_input) or intent == "product_availability_query"
    starts_new_request = bool(rule_slots.get("category")) and not continuation and previous_phase == "RECOMMEND"
    unrelated_new_request = intent in {"product_recommendation", "product_compare", "product_detail_query"} and not any(current.get(key) for key in ["category", "budget_max", "usage_scene", "must_have"]) and not is_contextual_follow_up
    if starts_new_request or unrelated_new_request:
        merged = merge_slots({}, rule_slots if starts_new_request else current)
        trace.append({"node": "session_boundary", "label": "识别新的购物需求", "previous_phase": previous_phase})
    else:
        merged = merge_slots(previous_slots, current)
    needs_model_help = not merged.get("category")
    if needs_model_help and llm.configured():
        extracted_slots = llm.extract_slots(user_input)
        llm_used = llm_used or bool(extracted_slots)
        trace.append({"node": "llm_slot_fallback", "label": "大模型补充理解", "engine": "llm", "slot_extracted": bool(extracted_slots)})
        if extracted_slots:
            merged = merge_slots(merged, extracted_slots)
    if "休闲鞋" in user_input:
        merged["category"] = None
        response = "当前商品库暂未收录休闲鞋，现有鞋类主要是跑鞋。你可以选择跑鞋，或者告诉我是否需要补充其他鞋类。"
        phase = "CLARIFY"
        status = "clarify"
        trace.append({"node": "catalog_boundary", "label": "商品类别未收录", "category": "休闲鞋"})
        db.save_session(session_id, merged, phase)
        db.append_message(session_id, "ASSISTANT", response)
        trace.append({"node": "audit_persist", "label": "Trace 审计入库", "trace_id": trace_id})
        db.save_trace(trace_id, session_id, trace)
        return {"trace_id": trace_id, "session_id": session_id, "status": status, "slots": merged, "response": response, "recommendations": [], "trace": trace, "llm_configured": llm.configured(), "llm_used": llm_used}
    if is_price_query(user_input) and merged.get("category"):
        price_items = [item for item in load_products() if item["category"] == merged["category"]]
        prices = "、".join(f"{item['price']} 元" for item in sorted(price_items, key=lambda item: item["price"]))
        response = f"目前{merged['category']}商品的价格有：{prices}。你更倾向于哪个预算范围？我可以继续帮你筛选。"
        trace.append({"node": "price_range_lookup", "label": "商品价格范围查询", "category": merged["category"], "prices": [item["price"] for item in price_items]})
        db.save_session(session_id, merged, "CLARIFY")
        db.append_message(session_id, "ASSISTANT", response)
        trace.append({"node": "audit_persist", "label": "Trace 审计入库", "trace_id": trace_id})
        db.save_trace(trace_id, session_id, trace)
        return {"trace_id": trace_id, "session_id": session_id, "status": "clarify", "slots": merged, "response": response, "recommendations": [], "trace": trace, "llm_configured": llm.configured()}
    if not merged.get("category"):
        response = "你想买哪一类商品？比如跑鞋、耳机、手表或口红。"
        phase = "CLARIFY"
        status = "clarify"
    elif merged.get("budget_max") is None:
        response = "你大概准备多少预算？我可以按价格范围帮你筛选。"
        phase = "CLARIFY"
        status = "clarify"
    else:
        candidates, perspectives = retrieve_products(merged, load_products())
        trace.append({"node": "parallel_recommendation", "label": "并行推荐视角", "agents": perspectives})
        response = f"为你推荐 {candidates[0]['name']}，价格 {candidates[0]['price']} 元，符合当前预算和使用需求。" if candidates else "暂时没有完全匹配的商品，可以放宽预算或偏好。"
        phase = "RECOMMEND"
        status = "answered"
        trace.append({"node": "retrieve_products", "label": "商品召回与重排", "candidate_count": len(candidates)})
        trace.append({"node": "generate_recommendation", "label": "推荐解释生成", "top_ids": [item["id"] for item in candidates[:5]]})
    db.save_session(session_id, merged, phase)
    db.append_message(session_id, "ASSISTANT", response)
    trace.append({"node": "audit_persist", "label": "Trace 审计入库", "trace_id": trace_id})
    db.save_trace(trace_id, session_id, trace)
    return {"trace_id": trace_id, "session_id": session_id, "status": status, "slots": merged, "response": response, "recommendations": candidates[:5] if status == "answered" else [], "trace": trace, "llm_configured": llm.configured(), "llm_used": llm_used}
