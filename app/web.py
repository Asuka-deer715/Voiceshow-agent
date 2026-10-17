from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db
from . import auth
from .eval import evaluate
from .graph import load_products, run_agent
from . import rag
from .security.guard import scan_input

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
EVAL_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eval")
EVAL_JOBS: dict[str, dict] = {}
EVAL_LOCK = threading.Lock()


class VoiceShopHandler(BaseHTTPRequestHandler):
    server_version = "VoiceShopAI/0.2"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/eval":
            user = self.require_user(role="admin")
            if not user:
                return
            self.send_json({"error": "use POST /api/eval to start an async evaluation"}, 405)
            return
        if path.startswith("/api/eval/"):
            user = self.require_user(role="admin")
            if not user:
                return
            job_id = path.rsplit("/", 1)[-1]
            with EVAL_LOCK:
                job = EVAL_JOBS.get(job_id)
            if not job:
                self.send_json({"error": "evaluation job not found"}, 404)
                return
            self.send_json(job)
            return
        if path == "/api/products":
            self.send_json({"products": load_products()})
            return
        if path == "/api/sessions":
            user = self.require_user()
            if not user:
                return
            self.send_json({"sessions": db.list_sessions(user["id"])})
            return
        if path.startswith("/api/sessions/"):
            user = self.require_user()
            if not user:
                return
            session_id = path.rsplit("/", 1)[-1]
            try:
                session = db.get_session(session_id, user["id"])
            except PermissionError:
                self.send_json({"error": "forbidden"}, 403)
                return
            self.send_json({"session": session, "messages": db.list_messages(session_id)})
            return
        if path.startswith("/api/products/"):
            product_id = int(path.rsplit("/", 1)[-1])
            item = next((product for product in load_products() if product["id"] == product_id), None)
            if not item:
                self.send_json({"error": "product not found"}, 404)
                return
            self.send_json({"product": item})
            return
        if path == "/api/orders":
            user = self.require_user()
            if not user:
                return
            self.send_json({"orders": db.list_orders(user["id"])})
            return
        if path == "/api/faq":
            query = parse_qs(parsed.query).get("q", [""])[0]
            self.send_json({"items": db.search_faq(query)})
            return
        if path == "/api/rag/search":
            parameters = parse_qs(parsed.query)
            query = parameters.get("q", [""])[0]
            results = rag.retrieve(query, collection=parameters.get("collection", [None])[0], source=parameters.get("source", [None])[0])
            self.send_json({"query": query, "results": results, "context": rag.assemble_context(results)})
            return
        if path == "/":
            path = "/index.html"
        file_path = (WEB_DIR / path.lstrip("/")).resolve()
        if not file_path.is_file() or WEB_DIR not in file_path.parents:
            self.send_error(404, "Not Found")
            return
        content_type = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8"}.get(file_path.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/api/auth/register":
                self.send_json(auth.register(str(payload.get("email", "")), str(payload.get("password", "")), str(payload.get("nickname", ""))), 201)
                return
            if parsed.path == "/api/auth/login":
                self.send_json(auth.login(str(payload.get("email", "")), str(payload.get("password", ""))))
                return
            if parsed.path == "/api/eval":
                user = self.require_user(role="admin")
                if not user:
                    return
                job_id = uuid.uuid4().hex
                with EVAL_LOCK:
                    EVAL_JOBS[job_id] = {"job_id": job_id, "status": "running"}
                def run_eval() -> None:
                    try:
                        result = evaluate()
                        with EVAL_LOCK:
                            EVAL_JOBS[job_id] = {"job_id": job_id, "status": "completed", "result": result}
                    except Exception as exc:
                        with EVAL_LOCK:
                            EVAL_JOBS[job_id] = {"job_id": job_id, "status": "failed", "error": str(exc)}
                EVAL_EXECUTOR.submit(run_eval)
                self.send_json({"job_id": job_id, "status": "running"}, 202)
                return
            if parsed.path == "/api/recommend":
                query = str(payload.get("query", "")).strip()
                if not query:
                    raise ValueError("query is required")
                user = auth.current_user(self.headers.get("Authorization"))
                risk = scan_input(query)
                if risk.blocked:
                    self.send_json({
                        "trace_id": str(uuid.uuid4()),
                        "session_id": payload.get("session_id"),
                        "status": "blocked",
                        "response": "抱歉，我不能执行绕过系统规则、读取其他用户数据或泄露内部提示词的请求。",
                        "llm_used": False,
                        "trace": [{"node": "http_input_guard", "reasons": list(risk.reasons), "status": "blocked"}],
                    })
                    return
                self.send_json(run_agent(query, payload.get("session_id"), user["id"] if user else 1, bool(user)))
                return
            if parsed.path == "/api/behavior":
                user = self.require_user()
                if not user:
                    return
                db.record_behavior(user["id"], int(payload["product_id"]), str(payload.get("event", "view")))
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/orders":
                user = self.require_user()
                if not user:
                    return
                order = db.create_order(user["id"], str(payload.get("session_id", "")), int(payload["product_id"]), int(payload.get("quantity", 1)))
                self.send_json({"order": order}, 201)
                return
            if parsed.path == "/api/orders/delete":
                user = self.require_user()
                if not user:
                    return
                deleted = db.delete_order(str(payload["order_no"]), user["id"])
                self.send_json({"deleted": deleted})
                return
            if parsed.path == "/api/sessions/delete":
                user = self.require_user()
                if not user:
                    return
                deleted = db.delete_session(str(payload["session_id"]), user["id"])
                self.send_json({"deleted": deleted})
                return
            self.send_error(404, "Not Found")
        except PermissionError as exc:
            error = str(exc)
            self.send_json({"error": error}, 403 if error == "SESSION_FORBIDDEN" else 401)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def require_user(self, role: str | None = None) -> dict | None:
        user = auth.current_user(self.headers.get("Authorization"))
        if not user:
            self.send_json({"error": "login_required"}, 401)
            return None
        if role and user.get("role") != role:
            self.send_json({"error": "forbidden"}, 403)
            return None
        return user

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    host, port = "127.0.0.1", int(os.getenv("PORT", "7860"))
    db.init_db()
    server = ThreadingHTTPServer((host, port), VoiceShopHandler)
    from .voice_ws import start_voice_server

    start_voice_server()
    print(f"VoiceShop AI web demo running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
