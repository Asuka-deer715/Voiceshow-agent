from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

from .database import init_database, read_session, write_session
from . import db_monitor  # noqa: F401 - registers SQLAlchemy query listeners


def init_db() -> None:
    """Compatibility facade for process startup. Migrations run once, not per request."""
    init_database()


def get_session(session_id: str) -> dict[str, Any]:
    with read_session() as session:
        row = session.execute(text("SELECT * FROM sessions WHERE id = :id"), {"id": session_id}).mappings().first()
    if row:
        return {"id": row["id"], "user_id": row["user_id"], "slots": json.loads(row["slots_json"]), "phase": row["phase"]}
    with write_session() as session:
        session.execute(text("INSERT OR IGNORE INTO sessions(id, user_id) VALUES (:id, 1)"), {"id": session_id})
    return {"id": session_id, "user_id": 1, "slots": {}, "phase": "INTENT"}


def save_session(session_id: str, slots: dict[str, Any], phase: str) -> None:
    with write_session() as session:
        session.execute(text("UPDATE sessions SET slots_json = :slots, phase = :phase, updated_at = CURRENT_TIMESTAMP WHERE id = :id"), {"slots": json.dumps(slots, ensure_ascii=False), "phase": phase, "id": session_id})


def append_message(session_id: str, role: str, content: str) -> None:
    with write_session() as session:
        session.execute(text("INSERT INTO messages(session_id, role, content) VALUES (:session_id, :role, :content)"), {"session_id": session_id, "role": role, "content": content})
        session.execute(text("UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = :id"), {"id": session_id})


def recent_messages(session_id: str, limit: int = 6) -> list[dict[str, Any]]:
    with read_session() as session:
        rows = session.execute(text("SELECT role, content, created_at FROM messages WHERE session_id = :id ORDER BY id DESC LIMIT :limit"), {"id": session_id, "limit": limit}).mappings().all()
        return [dict(row) for row in reversed(rows)]


def list_sessions(user_id: int = 1) -> list[dict[str, Any]]:
    query = text("""
        SELECT sessions.id, sessions.phase, sessions.updated_at,
               (SELECT content FROM messages WHERE session_id = sessions.id AND role = 'USER' ORDER BY id LIMIT 1) AS title,
               (SELECT COUNT(*) FROM messages WHERE session_id = sessions.id) AS message_count
        FROM sessions
        WHERE sessions.user_id = :user_id
          AND EXISTS (SELECT 1 FROM messages WHERE session_id = sessions.id)
        ORDER BY datetime(sessions.updated_at) DESC LIMIT 50
    """)
    with read_session() as session:
        return [dict(row) for row in session.execute(query, {"user_id": user_id}).mappings().all()]


def list_messages(session_id: str) -> list[dict[str, Any]]:
    with read_session() as session:
        rows = session.execute(text("SELECT role, content, created_at FROM messages WHERE session_id = :id ORDER BY id"), {"id": session_id}).mappings().all()
        return [dict(row) for row in rows]


def delete_session(session_id: str, user_id: int = 1) -> bool:
    with write_session() as session:
        exists = session.execute(text("SELECT 1 FROM sessions WHERE id = :id AND user_id = :user_id"), {"id": session_id, "user_id": user_id}).first()
        if not exists:
            return False
        session.execute(text("DELETE FROM traces WHERE session_id = :id"), {"id": session_id})
        session.execute(text("DELETE FROM messages WHERE session_id = :id"), {"id": session_id})
        session.execute(text("DELETE FROM sessions WHERE id = :id AND user_id = :user_id"), {"id": session_id, "user_id": user_id})
        return True


def save_trace(trace_id: str, session_id: str, trace: list[dict[str, Any]]) -> None:
    with write_session() as session:
        session.execute(text("INSERT INTO traces(trace_id, session_id, payload_json) VALUES (:trace_id, :session_id, :payload)"), {"trace_id": trace_id, "session_id": session_id, "payload": json.dumps(trace, ensure_ascii=False)})


def record_model_call(record: dict[str, Any]) -> None:
    with write_session() as session:
        session.execute(text("""INSERT INTO model_calls(
            trace_id, node, model, prompt_version, latency_ms, input_tokens,
            output_tokens, total_tokens, estimated_cost, status, error_type, fallback
        ) VALUES (:trace_id, :node, :model, :prompt_version, :latency_ms, :input_tokens,
            :output_tokens, :total_tokens, :estimated_cost, :status, :error_type, :fallback)"""), record)


def record_behavior(user_id: int, product_id: int, event: str) -> None:
    with write_session() as session:
        session.execute(text("INSERT INTO behaviors(user_id, product_id, event) VALUES (:user_id, :product_id, :event)"), {"user_id": user_id, "product_id": product_id, "event": event})


def create_order(user_id: int, session_id: str, product_id: int, quantity: int = 1) -> dict[str, Any]:
    order_no = "VS-" + uuid.uuid4().hex[:10].upper()
    with write_session() as session:
        session.execute(text("INSERT INTO orders(order_no, user_id, session_id, product_id, quantity, status) VALUES (:order_no, :user_id, :session_id, :product_id, :quantity, 'CREATED')"), {"order_no": order_no, "user_id": user_id, "session_id": session_id, "product_id": product_id, "quantity": quantity})
        session.execute(text("INSERT INTO order_events(order_no, event) VALUES (:order_no, 'CREATED')"), {"order_no": order_no})
    return {"order_no": order_no, "product_id": product_id, "quantity": quantity, "status": "CREATED"}


def list_orders(user_id: int = 1) -> list[dict[str, Any]]:
    with read_session() as session:
        return [dict(row) for row in session.execute(text("SELECT * FROM orders WHERE user_id = :user_id ORDER BY id DESC"), {"user_id": user_id}).mappings().all()]


def delete_order(order_no: str, user_id: int = 1) -> bool:
    with write_session() as session:
        cursor = session.execute(text("DELETE FROM orders WHERE order_no = :order_no AND user_id = :user_id"), {"order_no": order_no, "user_id": user_id})
        return cursor.rowcount > 0


def search_faq(query: str) -> list[dict[str, Any]]:
    with read_session() as session:
        rows = session.execute(text("SELECT * FROM faqs WHERE question LIKE :query OR answer LIKE :query LIMIT 5"), {"query": f"%{query}%"}).mappings().all()
        return [dict(row) for row in rows]
