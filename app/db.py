from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "voiceshop.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, nickname TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user_id INTEGER, slots_json TEXT NOT NULL DEFAULT '{}', phase TEXT NOT NULL DEFAULT 'INTENT', updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS profiles (user_id INTEGER PRIMARY KEY, profile_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS behaviors (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_id INTEGER, event TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, order_no TEXT UNIQUE, user_id INTEGER, session_id TEXT, product_id INTEGER, quantity INTEGER, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS faqs (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, answer TEXT, category TEXT);
        CREATE TABLE IF NOT EXISTS traces (id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT, session_id TEXT, payload_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        INSERT OR IGNORE INTO users(id, nickname) VALUES (1, 'Demo 用户');
        INSERT OR IGNORE INTO faqs(id, question, answer, category) VALUES (1, '怎么退货', '请在收货后七天内提交售后申请，商品需保持完好。', '售后');
        INSERT OR IGNORE INTO faqs(id, question, answer, category) VALUES (2, '多久发货', '现货商品通常会在一个工作日内发出。', '物流');
        """)


def get_session(session_id: str) -> dict[str, Any]:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO sessions(id, user_id) VALUES (?, 1)", (session_id,))
            return {"id": session_id, "user_id": 1, "slots": {}, "phase": "INTENT"}
        return {"id": row["id"], "user_id": row["user_id"], "slots": json.loads(row["slots_json"]), "phase": row["phase"]}


def save_session(session_id: str, slots: dict[str, Any], phase: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE sessions SET slots_json = ?, phase = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(slots, ensure_ascii=False), phase, session_id))


def append_message(session_id: str, role: str, content: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO messages(session_id, role, content) VALUES (?, ?, ?)", (session_id, role, content))
        conn.execute("UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))


def recent_messages(session_id: str, limit: int = 6) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?", (session_id, limit)).fetchall()
        return [dict(row) for row in reversed(rows)]


def list_sessions(user_id: int = 1) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("""
            SELECT sessions.id, sessions.phase, sessions.updated_at,
                   (SELECT content FROM messages WHERE session_id = sessions.id AND role = 'USER' ORDER BY id LIMIT 1) AS title,
                   (SELECT COUNT(*) FROM messages WHERE session_id = sessions.id) AS message_count
            FROM sessions
            WHERE sessions.user_id = ?
              AND EXISTS (SELECT 1 FROM messages WHERE session_id = sessions.id)
            ORDER BY datetime(sessions.updated_at) DESC
            LIMIT 50
        """, (user_id,)).fetchall()
        return [dict(row) for row in rows]


def list_messages(session_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
        return [dict(row) for row in rows]


def delete_session(session_id: str, user_id: int = 1) -> bool:
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
        if not exists:
            return False
        conn.execute("DELETE FROM traces WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
        return True


def save_trace(trace_id: str, session_id: str, trace: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO traces(trace_id, session_id, payload_json) VALUES (?, ?, ?)", (trace_id, session_id, json.dumps(trace, ensure_ascii=False)))


def record_behavior(user_id: int, product_id: int, event: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO behaviors(user_id, product_id, event) VALUES (?, ?, ?)", (user_id, product_id, event))


def create_order(user_id: int, session_id: str, product_id: int, quantity: int = 1) -> dict[str, Any]:
    order_no = "VS-" + uuid.uuid4().hex[:10].upper()
    with connect() as conn:
        conn.execute("INSERT INTO orders(order_no, user_id, session_id, product_id, quantity, status) VALUES (?, ?, ?, ?, ?, ?)", (order_no, user_id, session_id, product_id, quantity, "CREATED"))
    return {"order_no": order_no, "product_id": product_id, "quantity": quantity, "status": "CREATED"}


def list_orders(user_id: int = 1) -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()]


def delete_order(order_no: str, user_id: int = 1) -> bool:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM orders WHERE order_no = ? AND user_id = ?", (order_no, user_id))
        return cursor.rowcount > 0


def search_faq(query: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM faqs WHERE question LIKE ? OR answer LIKE ? LIMIT 5", (f"%{query}%", f"%{query}%")).fetchall()
        return [dict(row) for row in rows]
