from __future__ import annotations

import json
from typing import Any

from .agent_state import AgentState
from . import db, llm, rag, tools
from .security.guard import moderate_output, redact_pii, require_tool_permission, scan_input


def _trace(state: AgentState, node: str, **data: Any) -> list[dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, **data}]


def load_context(state: AgentState) -> AgentState:
    session_id = state["session_id"]
    risk = scan_input(state["query"])
    session = db.get_session(session_id, state.get("user_id", 1))
    db.append_message(session_id, "USER", redact_pii(state["query"]))
    history = db.recent_messages(session_id, 6)
    if risk.blocked:
        return {**state, "session": session, "history": history, "status": "blocked", "response": "抱歉，我不能执行绕过系统规则、读取其他用户数据或泄露内部提示词的请求。", "trace": _trace(state, "input_guard", reasons=list(risk.reasons), status="blocked")}
    return {**state, "session": session, "history": history, "query": redact_pii(state["query"]), "trace": _trace(state, "session_load", session_id=session_id)}


def classify_intent(state: AgentState) -> AgentState:
    from . import graph as logic

    query = state["query"]
    if logic.is_greeting(query):
        model_result = {"intent": "greeting", "confidence": 1.0, "entities": {}}
        engine, fallback_reason = "rules", None
    else:
        context = json.dumps({"phase": state["session"].get("phase"), "slots": state["session"].get("slots", {}), "recent_messages": state["history"]}, ensure_ascii=False)
        model_result = llm.classify_intent(query, context, state["trace_id"]) if llm.configured() else None
        intent, engine, fallback_reason = logic.select_intent(model_result, query)
        model_result = model_result or {"intent": intent, "confidence": 0.0, "entities": {}}
        model_result["intent"] = intent
        unsupported = logic.unsupported_category_from_text(query)
        if unsupported and not model_result.get("entities", {}).get("requested_category"):
            model_result.setdefault("entities", {})["requested_category"] = unsupported
    return {
        **state,
        "model_intent": model_result,
        "intent": model_result["intent"],
        "intent_engine": engine,
        "fallback_reason": fallback_reason,
        "llm_used": bool(engine == "llm"),
        "trace": _trace(state, "intent_classification", engine=engine, intent=model_result["intent"], confidence=model_result.get("confidence"), fallback_reason=fallback_reason),
    }


def validate_intent(state: AgentState) -> AgentState:
    from . import graph as logic

    unknown = logic.unsupported_category(state.get("model_intent"))
    if unknown and state["intent"] in {"product_recommendation", "product_availability_query", "product_compare", "product_detail_query"}:
        return {**state, "status": "clarify", "response": f"当前商品库暂不支持{unknown}，目前可以帮你挑选跑鞋、耳机、手表或口红。", "trace": _trace(state, "catalog_validation", category=unknown, status="unsupported")}
    return state


def extract_slots(state: AgentState) -> AgentState:
    from . import graph as logic

    if state["intent"] in {"knowledge_query", "after_sales_query", "logistics_query"}:
        return {**state, "slots": state["session"].get("slots", {}), "trace": _trace(state, "slot_extraction", status="not_required_for_knowledge")}
    model_slots = logic.slots_from_model(state.get("model_intent")) if state.get("intent_engine") == "llm" else logic.empty_slots()
    current = logic.merge_slots(logic.extract_slots(state["query"]), model_slots)
    previous = state["session"].get("slots", {})
    is_follow_up = logic.is_recommendation_follow_up(state["query"]) or logic.is_price_query(state["query"]) or state["intent"] == "product_availability_query"
    new_request = bool(current.get("category")) and state["session"].get("phase") == "RECOMMEND" and not is_follow_up
    merged = logic.merge_slots({}, current) if new_request else logic.merge_slots(previous, current)
    if not merged.get("category") and llm.configured():
        extra = llm.extract_slots(state["query"], state["trace_id"])
        if extra:
            merged = logic.merge_slots(merged, extra)
    return {**state, "slots": merged, "trace": _trace(state, "slot_extraction", engine="rules_plus_llm_entities", slots=merged)}


def retrieve_products(state: AgentState) -> AgentState:
    from . import graph as logic

    if not state["slots"].get("category"):
        return {**state, "recommendations": [], "trace": _trace(state, "retrieve_products", agents=[], candidate_count=0)}
    products, perspectives = logic.retrieve_products(state["slots"], logic.load_products())
    category = state["slots"].get("category")
    if category:
        products = [item for item in products if item.get("category") == category]
    return {**state, "recommendations": products[:5], "trace": _trace(state, "retrieve_products", agents=perspectives, candidate_count=len(products))}


def retrieve_knowledge(state: AgentState) -> AgentState:
    result = tools.retrieve_knowledge(state["query"])
    return {**state, "retrieved": result["chunks"], "sources": result["sources"], "trace": _trace(state, "rag_retrieve", chunks=[{"chunk_id": item["chunk_id"], "source": item["source"], "score": item["score"]} for item in result["chunks"]])}


def generate_response(state: AgentState) -> AgentState:
    from . import graph as logic

    intent = state["intent"]
    slots = state.get("slots", {})
    recommendations = state.get("recommendations", [])
    if state.get("response"):
        return {**state, "response": moderate_output(state["response"])}
    if intent in {"knowledge_query", "after_sales_query", "logistics_query"}:
        context = rag.assemble_context(state.get("retrieved", []))
        response = llm.generate_answer(state["query"], context, state["trace_id"]) if context else None
        if not response and state.get("retrieved"):
            response = f"根据 {state['retrieved'][0]['source']}：{state['retrieved'][0]['text']}"
        response = response or "暂时没有在知识库中找到匹配内容，建议转人工客服确认。"
        return {**state, "response": response, "status": "answered", "phase": "KNOWLEDGE", "trace": _trace(state, "answer_generation", source_count=len(state.get("retrieved", [])))}
    if intent == "greeting":
        response = "你好，我是 VoiceShop AI 导购。你可以告诉我想买什么、预算多少，也可以查询商品、订单和售后信息。"
        return {**state, "response": response, "status": "clarify", "phase": "INTENT", "trace": _trace(state, "greeting")}
    if intent == "order_history_query":
        require_tool_permission(state.get("user_id", 1), state.get("authenticated", False), "list_order_history")
        orders = tools.list_order_history(state["user_id"])
        response = "目前还没有查询到你的历史订单。" if not orders else "你过往的下单商品如下：" + "、".join(item["product_name"] for item in orders[:5])
        return {**state, "response": response, "status": "answered", "phase": "ORDER", "trace": _trace(state, "order_history_tool", order_count=len(orders))}
    if intent == "chitchat":
        return {**state, "response": "我可以陪你聊聊，也可以帮你查询商品、价格、订单和售后信息。", "status": "answered", "phase": "INTENT", "trace": _trace(state, "chitchat")}
    if intent == "change_preference":
        category = slots.get("category") or state["session"].get("slots", {}).get("category")
        updated = logic.empty_slots()
        if category:
            updated["avoid"] = [category]
        return {**state, "slots": updated, "response": "明白，我会排除当前偏好。你想换成哪一类商品？例如耳机、手表或口红。", "status": "clarify", "phase": "CLARIFY", "trace": _trace(state, "preference_update", excluded_category=category)}
    if logic.is_price_query(state["query"]) and slots.get("category"):
        items = [item for item in logic.load_products() if item["category"] == slots["category"]]
        prices = "、".join(f"{item['price']} 元" for item in sorted(items, key=lambda item: item["price"]))
        return {**state, "response": f"目前{slots['category']}商品的价格有：{prices}。你更倾向于哪个预算范围？", "status": "clarify", "phase": "CLARIFY", "trace": _trace(state, "price_range_lookup")}
    if not slots.get("category"):
        return {**state, "response": "你想买哪一类商品？比如跑鞋、耳机、手表或口红。", "status": "clarify", "phase": "CLARIFY", "trace": _trace(state, "clarify_category")}
    if slots.get("budget_max") is None:
        return {**state, "response": "你大概准备多少预算？我可以按价格范围帮你筛选。", "status": "clarify", "phase": "CLARIFY", "trace": _trace(state, "clarify_budget")}
    if recommendations:
        top = recommendations[0]
        response = f"为你推荐 {top['name']}，价格 {top['price']} 元，匹配你的预算和使用偏好。"
    else:
        response = "暂时没有完全匹配的商品，可以放宽预算或调整偏好。"
    return {**state, "response": moderate_output(response), "status": "answered", "phase": "RECOMMEND", "trace": _trace(state, "recommendation_generation", top_ids=[item["id"] for item in recommendations])}


def persist_result(state: AgentState) -> AgentState:
    session_id = state["session_id"]
    db.save_session(session_id, state.get("slots", {}), state.get("phase", "INTENT"))
    db.append_message(session_id, "ASSISTANT", state.get("response") or "")
    trace = _trace(state, "audit_persist", trace_id=state["trace_id"])
    db.save_trace(state["trace_id"], session_id, trace)
    return {**state, "trace": trace}
