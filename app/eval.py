from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from . import llm
from .graph import run_agent


ROOT = Path(__file__).resolve().parents[1]


def f1(predicted: set[str], expected: set[str]) -> float:
    if not predicted and not expected:
        return 1.0
    if not predicted or not expected:
        return 0.0
    tp = len(predicted & expected)
    precision = tp / len(predicted)
    recall = tp / len(expected)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def slot_items(slots: dict) -> set[str]:
    result = set()
    for key in ["category", "budget_max", "usage_scene", "brand_preference"]:
        if slots.get(key) is not None:
            result.add(f"{key}={slots[key]}")
    for tag in slots.get("must_have", []):
        result.add(f"must_have={tag}")
    return result


def evaluate() -> dict:
    cases = json.loads((ROOT / "data" / "eval_cases.json").read_text(encoding="utf-8"))
    if os.getenv("EVAL_OFFLINE", "0") == "1":
        llm.configured = lambda: False
    slot_scores = []
    recall_hits = []
    clarification_hits = []
    category_purity = []
    response_checks = []
    reports = []

    for case in cases:
        session_id = f"eval-{case.get('id', uuid.uuid4().hex)}-{uuid.uuid4().hex[:8]}"
        queries = case.get("turns") or [case.get("input", "")]
        outputs = [run_agent(query, session_id) for query in queries]
        output = outputs[-1]
        slot_scores.append(f1(slot_items(output["slots"]), slot_items(case["expected_slots"])))
        top_ids = {item["id"] for item in output["recommendations"]}
        expected_ids = set(case.get("expected_product_ids", []))
        recall_hits.append(1.0 if expected_ids & top_ids else 0.0 if expected_ids else 1.0)
        clarification_hits.append(1.0 if output["status"] == case["expected_status"] else 0.0)
        if case.get("expected_category"):
            category_purity.append(1.0 if all(item.get("category") == case["expected_category"] for item in output["recommendations"]) else 0.0)
        if case.get("forbidden_categories"):
            category_purity.append(1.0 if not any(item.get("category") in case["forbidden_categories"] for item in output["recommendations"]) else 0.0)
        if case.get("expected_response_contains"):
            response_checks.append(1.0 if case["expected_response_contains"] in output["response"] else 0.0)
        response_check = None
        if case.get("expected_response_contains"):
            response_check = case["expected_response_contains"] in output["response"]
        reports.append({"id": case.get("id"), "status": output["status"], "top_ids": list(top_ids), "trace_nodes": [step.get("node") for step in output["trace"]], "response_check": response_check})

    report = {
        "total_cases": len(cases),
        "slot_f1": round(sum(slot_scores) / len(slot_scores), 4),
        "recall_at_5": round(sum(recall_hits) / len(recall_hits), 4),
        "clarification_accuracy": round(sum(clarification_hits) / len(clarification_hits), 4),
        "category_purity": round(sum(category_purity) / len(category_purity), 4) if category_purity else 1.0,
        "response_checks": round(sum(response_checks) / len(response_checks), 4) if response_checks else 1.0,
        "cases": reports,
    }
    return report


def main() -> None:
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
