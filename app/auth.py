from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Any

from sqlalchemy import text

from .database import read_session, write_session


def _secret() -> bytes:
    return os.getenv("JWT_SECRET", "voiceshop-local-development-secret").encode()


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_raw, digest_raw = stored.split("$", 1)
        salt = base64.urlsafe_b64decode(salt_raw.encode())
        expected = base64.urlsafe_b64decode(digest_raw.encode())
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return hmac.compare_digest(actual, expected)


def _token(payload: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
    signature = hmac.new(_secret(), body, hashlib.sha256).digest()
    return f"{body.decode()}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def _decode(token: str) -> dict[str, Any] | None:
    try:
        body_raw, signature_raw = token.split(".", 1)
        body = body_raw.encode()
        expected = hmac.new(_secret(), body, hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(signature_raw + "=" * (-len(signature_raw) % 4))
        if not hmac.compare_digest(expected, supplied):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body_raw + "=" * (-len(body_raw) % 4)))
        return payload if int(payload.get("exp", 0)) > int(time.time()) else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def register(email: str, password: str, nickname: str = "") -> dict[str, Any]:
    email = email.strip().lower()
    nickname = nickname.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or not 8 <= len(password) <= 128 or len(nickname) > 40:
        raise ValueError("INVALID_SIGNUP")
    with write_session() as session:
        exists = session.execute(text("SELECT id FROM users WHERE email = :email"), {"email": email}).first()
        if exists:
            raise ValueError("EMAIL_EXISTS")
        result = session.execute(text("INSERT INTO users(email, password_hash, nickname, role) VALUES (:email, :password_hash, :nickname, 'user')"), {"email": email, "password_hash": _hash_password(password), "nickname": nickname or email.split("@")[0]})
        user_id = int(result.lastrowid)
    return issue_token(user_id, "user")


def login(email: str, password: str) -> dict[str, Any]:
    email = email.strip().lower()
    if not email or not 1 <= len(password) <= 128:
        raise PermissionError("INVALID_CREDENTIALS")
    with read_session() as session:
        row = session.execute(text("SELECT id, password_hash, role FROM users WHERE email = :email"), {"email": email}).mappings().first()
    if not row or not _verify_password(password, row["password_hash"]):
        raise PermissionError("INVALID_CREDENTIALS")
    return issue_token(int(row["id"]), row["role"] or "user")


def issue_token(user_id: int, role: str = "user") -> dict[str, Any]:
    return {"access_token": _token({"sub": user_id, "role": role, "exp": int(time.time()) + 86400}), "user_id": user_id, "role": role}


def current_user(authorization: str | None) -> dict[str, Any] | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    payload = _decode(authorization.split(" ", 1)[1].strip())
    if not payload:
        return None
    return {"id": int(payload["sub"]), "role": payload.get("role", "user")}
